"""
Original Name & 1080px Downloader (web-app version of
"Single or Multiple Image Downloader / Original Name & 1080px / download_sortly_images.py")

Reads an uploaded CSV with a serial + link column (or pasted URLs), downloads
every image, fits it onto a white 1080px (default) square canvas, and saves
it using the image's ORIGINAL filename (taken from the URL) — not the
serial. If two or more rows would produce the same filename, ALL of those
rows are skipped (no renaming/suffixing) — only rows whose filename is
unique across the whole batch get downloaded. Each file is also kept under
a configurable size limit by automatically lowering JPEG quality until it
fits. Returns a zip with every downloaded image.
"""
import csv
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote

from PIL import Image

from .common import zip_folder, get_pooled_session, run_parallel_downloads


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\/:*?"<>|]', "_", name.strip()) or "unnamed"


def original_name_from_url(url: str) -> str:
    """Extract the original image filename (without extension) from a URL."""
    path = urlparse(url).path
    name = unquote(Path(path).name)
    name = Path(name).stem
    return sanitize_filename(name) if name else "unnamed"


def find_column(fieldnames, keyword):
    keyword = keyword.lower()
    for col in fieldnames:
        if col and keyword in col.strip().lower().replace(" ", ""):
            return col
    return None


def load_rows(csv_path, log):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        reader = csv.DictReader(f, dialect=dialect)

        log(f"Detected columns: {reader.fieldnames}")

        serial_col = find_column(reader.fieldnames, "serial")
        url_col = find_column(reader.fieldnames, "link")

        if not serial_col or not url_col:
            raise ValueError(
                "Could not find columns for SERIAL or LINKS. Make sure your "
                "CSV has header names like: serial,links"
            )

        log(f"Using serial column: {serial_col}")
        log(f"Using links column:  {url_col}")

        rows = []
        seen_urls = {}
        duplicate_count = 0
        for i, row in enumerate(reader, start=1):
            serial = str(row.get(serial_col, "")).strip()
            url = str(row.get(url_col, "")).strip()
            if not serial or not url:
                log(f"[Row {i}] Missing serial or link — skipping.")
                continue
            if url in seen_urls:
                duplicate_count += 1
                first_row, first_serial = seen_urls[url]
                log(f"[Row {i}] Duplicate URL (same as row {first_row}, {first_serial}) — skipping.")
                continue
            seen_urls[url] = (i, serial)
            rows.append((i, serial, url))

        log(f"Rows from CSV: {len(rows)} ({duplicate_count} duplicate URL(s) skipped)")
        return rows


def parse_pasted_urls(urls_text):
    """Splits a textarea blob into a clean list of URLs."""
    if not urls_text:
        return []
    lines = re.split(r"[\r\n]+", urls_text)
    urls = []
    for line in lines:
        for piece in re.split(r"[,\s]+", line.strip()):
            piece = piece.strip()
            if piece:
                urls.append(piece)
    return urls


def flatten_to_white(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def fit_on_square_canvas(img: Image.Image, size: int) -> Image.Image:
    img = flatten_to_white(img)
    w, h = img.size
    scale = size / max(w, h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    offset = ((size - new_w) // 2, (size - new_h) // 2)
    canvas.paste(resized, offset)
    return canvas


def save_jpeg_under_limit(img: Image.Image, filepath: Path, max_bytes: int, min_quality=40, start_quality=95):
    """Save img as JPEG, lowering quality via binary search until it fits
    under max_bytes, without going below min_quality."""
    def encode(quality):
        buf = BytesIO()
        img.save(buf, "JPEG", quality=quality, subsampling=0, optimize=False)
        return buf.getvalue()

    data = encode(start_quality)
    if len(data) <= max_bytes:
        filepath.write_bytes(data)
        return

    low, high = min_quality, start_quality
    best = None
    while low <= high:
        mid = (low + high) // 2
        data = encode(mid)
        if len(data) <= max_bytes:
            best = data
            low = mid + 1
        else:
            high = mid - 1

    filepath.write_bytes(best if best is not None else encode(min_quality))


def download_one(item, out_dir, canvas_size, jpeg_quality, max_bytes, timeout, max_workers, stop_event=None):
    row_index, serial, url, base_name = item
    filepath = out_dir / f"{base_name}.jpg"

    if stop_event is not None and stop_event.is_set():
        return (False, filepath.name, f"[Row {row_index}] Skipped {serial} (stopped by user)", 0)

    try:
        session = get_pooled_session(max_workers)
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        img.load()
        final_img = fit_on_square_canvas(img, canvas_size)
        save_jpeg_under_limit(final_img, filepath, max_bytes, start_quality=jpeg_quality)
        size_bytes = filepath.stat().st_size if filepath.exists() else 0
        return (True, filepath.name, f"[Row {row_index}] Downloaded {serial} -> {filepath.name}", size_bytes)
    except Exception as e:
        return (False, filepath.name, f"[Row {row_index}] ERROR for {serial}: {e}", 0)


def run(output_dir: Path, log, csv_file: Path = None, urls_text: str = None,
        canvas_size=1080, jpeg_quality=95, max_filesize_kb=1200, max_workers=24, timeout=20,
        make_zip=True, progress=None, stop_event=None):
    output_dir = Path(output_dir)
    images_dir = output_dir / "downloads"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(csv_file, log) if csv_file else []

    pasted_urls = parse_pasted_urls(urls_text)
    if pasted_urls:
        # If a CSV was also supplied, prefix the auto serial so it can't
        # collide with a serial already used in the file.
        prefix = "pasted_" if rows else ""
        start_row = (rows[-1][0] if rows else 0) + 1
        for j, url in enumerate(pasted_urls, start=1):
            rows.append((start_row + j - 1, f"{prefix}{j}", url))
        log(f"Added {len(pasted_urls)} pasted URL(s).")

    if not rows:
        raise ValueError("Please upload a CSV file or paste at least one image URL.")

    # Work out each row's original filename, then drop every row whose name
    # collides with another row's — only names that are unique across the
    # whole batch get downloaded (no "_2", "_3" renaming).
    named_rows = [(row_index, serial, url, original_name_from_url(url)) for row_index, serial, url in rows]

    name_counts = {}
    for _, _, _, base_name in named_rows:
        name_counts[base_name] = name_counts.get(base_name, 0) + 1

    unique_rows = [item for item in named_rows if name_counts[item[3]] == 1]
    dropped = len(named_rows) - len(unique_rows)

    if dropped:
        for row_index, serial, url, base_name in named_rows:
            if name_counts[base_name] > 1:
                log(f"[Row {row_index}] Duplicate filename '{base_name}' (same as {name_counts[base_name] - 1} other row(s)) — skipping.")

    if not unique_rows:
        raise ValueError("Every row's filename collided with another — nothing unique left to download.")

    log(f"Total valid rows to download: {len(unique_rows)} ({dropped} skipped for duplicate filename)")
    log(f"Starting parallel downloads with {max_workers} workers…")

    max_bytes = int(max_filesize_kb * 1024)
    total = len(unique_rows)

    success_count, failed_count, _bytes = run_parallel_downloads(
        unique_rows,
        lambda item, stop_evt: download_one(item, images_dir, canvas_size, jpeg_quality, max_bytes, timeout, max_workers, stop_evt),
        max_workers, log, progress, stop_event,
    )

    if stop_event is not None and stop_event.is_set():
        log(f"Stopped early: {success_count} downloaded, {failed_count} failed/skipped, "
            f"{total - success_count - failed_count} not started.")

    if not make_zip:
        log("All downloads done!")
        final_paths = []
        for p in sorted(images_dir.glob("*")):
            if p.is_file():
                dest = output_dir / p.name
                p.replace(dest)
                final_paths.append(dest)
        return final_paths

    log("All downloads done! Zipping…")
    zip_path = output_dir / "original_name_1080_images.zip"
    zip_folder(images_dir, zip_path, log=log)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
