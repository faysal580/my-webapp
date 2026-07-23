"""
Original Name & Ratio Image Downloader (web-app version of
"Single or Multiple Image Downloader / Original Name & Ratio / download_images.py")

Reads an uploaded CSV with a link/url column, downloads every image and
saves it as JPG using its ORIGINAL filename (taken from the URL) and its
ORIGINAL aspect ratio — no cropping, no square canvas, no renaming. Returns
a zip with every downloaded image.
"""
import csv
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image

from .common import zip_folder


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\/:*?"<>|]', "_", name.strip()) or "unnamed"


def clean_url(raw: str):
    """Strip trailing junk (inline CSS, query noise) from a URL and return a
    clean https:// URL, or None if the URL looks invalid."""
    raw = re.split(r'\s*style\s*=', raw, maxsplit=1)[0].strip()
    if not raw.lower().startswith("http"):
        return None
    parsed = urlparse(raw)
    if not parsed.netloc:
        return None
    return parsed._replace(query="", fragment="").geturl()


def filename_from_url(url: str, row_index: int) -> str:
    """Extract the image stem from the URL path, falling back to
    image_row<N> if nothing useful is found."""
    try:
        path = unquote(urlparse(url).path)
        stem = Path(path).stem
        if stem:
            return sanitize_filename(stem)
    except Exception:
        pass
    return f"image_row{row_index}"


def load_rows(csv_path, log):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        reader = csv.DictReader(f, dialect=dialect)

        url_col = None
        for col in (reader.fieldnames or []):
            if col and re.search(r'link|url', col.strip(), re.IGNORECASE):
                url_col = col
                break

        if not url_col:
            raise ValueError("Could not find a column named 'links' or 'url' in your CSV.")

        log(f"Using URL column: '{url_col}'")

        rows = []
        skipped = 0
        for i, row in enumerate(reader, start=2):  # start=2, row 1 is header
            raw_url = str(row.get(url_col, "")).strip()
            url = clean_url(raw_url)
            if not url:
                log(f"[Row {i}] Skipping invalid URL: {raw_url[:80]}")
                skipped += 1
                continue
            stem = filename_from_url(url, i)
            rows.append((i, url, stem))

        log(f"Valid rows: {len(rows)}   Skipped: {skipped}")
        return rows


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def download_one(item, out_dir, jpeg_quality, timeout, stop_event=None):
    row_index, url, stem = item
    filepath = out_dir / f"{stem}.jpg"

    if stop_event is not None and stop_event.is_set():
        return (False, filepath.name, f"[Row {row_index}] Skipped '{stem}' (stopped by user)", 0)

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()

        img = Image.open(BytesIO(resp.content))
        img.load()

        img = to_rgb(img)
        img.save(filepath, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)

        size_bytes = filepath.stat().st_size if filepath.exists() else 0
        return (True, filepath.name, f"[Row {row_index}] ✓ {stem}.jpg ({img.width}×{img.height})", size_bytes)
    except Exception as e:
        return (False, filepath.name, f"[Row {row_index}] ERROR ({stem}): {e}", 0)


def parse_pasted_urls(urls_text):
    """Splits a textarea blob into a clean list of raw URL strings."""
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


def run(output_dir: Path, log, csv_file: Path = None, urls_text: str = None,
        jpeg_quality=95, max_workers=10, timeout=30, make_zip=True,
        progress=None, stop_event=None):
    output_dir = Path(output_dir)
    images_dir = output_dir / "downloads"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(csv_file, log) if csv_file else []

    pasted_urls = parse_pasted_urls(urls_text)
    if pasted_urls:
        next_row = (rows[-1][0] if rows else 1) + 1
        added, skipped = 0, 0
        for raw in pasted_urls:
            url = clean_url(raw)
            if not url:
                log(f"Skipping invalid pasted URL: {raw[:80]}")
                skipped += 1
                continue
            stem = filename_from_url(url, next_row)
            rows.append((next_row, url, stem))
            next_row += 1
            added += 1
        log(f"Added {added} pasted URL(s) (skipped {skipped}).")

    if not rows:
        raise ValueError("Please upload a CSV file or paste at least one image URL.")

    # Drop every row whose filename (its original-name stem) collides with
    # another row's — only names that are unique across the whole batch get
    # downloaded (no "_2", "_3" renaming).
    name_counts = {}
    for _, _, stem in rows:
        name_counts[stem] = name_counts.get(stem, 0) + 1

    unique_rows = [item for item in rows if name_counts[item[2]] == 1]
    dropped = len(rows) - len(unique_rows)

    if dropped:
        for row_index, _, stem in rows:
            if name_counts[stem] > 1:
                log(f"[Row {row_index}] Duplicate filename '{stem}' (same as {name_counts[stem] - 1} other row(s)) — skipping.")

    if not unique_rows:
        raise ValueError("Every row's filename collided with another — nothing unique left to download.")

    log(f"Total valid rows to download: {len(unique_rows)} ({dropped} skipped for duplicate filename)")
    log(f"Starting parallel downloads with {max_workers} workers…")

    total = len(unique_rows)
    success_count = 0
    failed_count = 0
    bytes_downloaded = 0

    def report(current_file=None):
        if progress:
            progress(total=total, success=success_count, failed=failed_count,
                      current_file=current_file, bytes=bytes_downloaded)

    report()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_one, item, images_dir, jpeg_quality, timeout, stop_event): item
            for item in unique_rows
        }
        for future in as_completed(futures):
            ok, filename, message, size_bytes = future.result()
            if ok:
                success_count += 1
                bytes_downloaded += size_bytes
            else:
                failed_count += 1
            log(message)
            report(current_file=filename)

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
    zip_path = output_dir / "original_name_ratio_images.zip"
    zip_folder(images_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
