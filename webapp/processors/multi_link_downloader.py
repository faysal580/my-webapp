"""
Multi Link Image Downloader (web-app version of
"Single or Multiple Image Downloader / Multi Link / download_sortly_images.py")

Supports CSVs with several serial columns + several link columns per row
(e.g. "serial 1", "serial 2" ... + "Image Link 1", "Image Link 2" ...), as
well as the simple single serial + single link layout. Every image is
downloaded, fit onto a white square canvas, and saved as JPG. Returns a zip
with every downloaded image.
"""
import csv
import re
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image

from .common import zip_folder


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\/:*?"<>|]', "_", name.strip()) or "unnamed"


def detect_columns(fieldnames):
    """Find all 'serial'-style columns and all 'link/image'-style columns,
    in the order they appear in the CSV header."""
    serial_cols, link_cols = [], []
    for col in fieldnames:
        if not col:
            continue
        key = col.strip().lower().replace(" ", "")
        if "serial" in key:
            serial_cols.append(col)
        elif "link" in key or "image" in key:
            link_cols.append(col)
    return serial_cols, link_cols


def load_tasks(csv_path, log):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        log(f"Detected columns: {reader.fieldnames}")

        serial_cols, link_cols = detect_columns(reader.fieldnames)
        if not serial_cols or not link_cols:
            raise ValueError(
                "Could not find serial/link-style columns. Make sure your "
                "CSV has columns with 'serial' and 'link' (or 'image') in their names."
            )

        log(f"Serial columns: {serial_cols}")
        log(f"Link columns:   {link_cols}")

        # If there's more than one serial column, the first is the row's
        # base id and the rest are the per-image sub-ids.
        sub_serial_cols = serial_cols[1:] if len(serial_cols) > 1 else serial_cols

        tasks = []
        skipped = 0
        for row_index, row in enumerate(reader, start=1):
            for i, link_col in enumerate(link_cols):
                url = (row.get(link_col) or "").strip()
                if not url:
                    continue

                if i >= len(sub_serial_cols):
                    log(f"[Row {row_index}] No serial column available for '{link_col}' - skipping.")
                    skipped += 1
                    continue

                name = (row.get(sub_serial_cols[i]) or "").strip()
                if not name:
                    log(f"[Row {row_index}] Empty serial for '{link_col}' - skipping.")
                    skipped += 1
                    continue

                tasks.append((row_index, name, url))

        log(f"Total images to download: {len(tasks)} (skipped {skipped})")
        return tasks


def download_one(item, out_dir, target_size, jpeg_quality, timeout, stop_event=None, bg_color=(255, 255, 255)):
    row_index, name, url, filename = item
    filepath = out_dir / f"{filename}.jpg"

    if stop_event is not None and stop_event.is_set():
        return (False, filepath.name, f"[Row {row_index}] Skipped {name} (stopped by user)", 0)

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()

        img = Image.open(BytesIO(resp.content))
        img.load()

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, bg_color)
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        target_w, target_h = target_size
        scale = min(target_w / img.width, target_h / img.height)
        new_w, new_h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGB", target_size, bg_color)
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))
        img = canvas

        img.save(filepath, "JPEG", quality=jpeg_quality)
        size_bytes = filepath.stat().st_size if filepath.exists() else 0
        return (True, filepath.name, f"[Row {row_index}] Downloaded {name} -> {filepath.name}", size_bytes)
    except Exception as e:
        return (False, filepath.name, f"[Row {row_index}] ERROR for {name} ({url}): {e}", 0)


def parse_pasted_urls(urls_text):
    """Splits a textarea blob into a clean list of unique-order URLs."""
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
        canvas_size=1080, jpeg_quality=90, max_workers=10, timeout=30, make_zip=True,
        progress=None, stop_event=None):
    output_dir = Path(output_dir)
    images_dir = output_dir / "downloads"
    images_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_tasks(csv_file, log) if csv_file else []

    pasted_urls = parse_pasted_urls(urls_text)
    if pasted_urls:
        # If a CSV was also supplied, prefix the auto name so it can't
        # collide with a serial already used in the file.
        prefix = "pasted_" if tasks else ""
        start_row = (tasks[-1][0] if tasks else 0) + 1
        for j, url in enumerate(pasted_urls, start=1):
            tasks.append((start_row + j - 1, f"{prefix}{j}", url))
        log(f"Added {len(pasted_urls)} pasted URL(s).")

    if not tasks:
        raise ValueError("Please upload a CSV file or paste at least one image URL.")

    # Work out each task's final filename (from its name/serial), then drop
    # every task whose filename collides with another's — only names that
    # are unique across the whole batch get downloaded (no "_2", "_3" renaming).
    named_tasks = [(row_index, name, url, sanitize_filename(name)) for row_index, name, url in tasks]

    name_counts = {}
    for _, _, _, filename in named_tasks:
        name_counts[filename] = name_counts.get(filename, 0) + 1

    unique_tasks = [item for item in named_tasks if name_counts[item[3]] == 1]
    dropped = len(named_tasks) - len(unique_tasks)

    if dropped:
        for row_index, name, url, filename in named_tasks:
            if name_counts[filename] > 1:
                log(f"[Row {row_index}] Duplicate filename '{filename}' (same as {name_counts[filename] - 1} other row(s)) — skipping.")

    if not unique_tasks:
        raise ValueError("Every task's filename collided with another — nothing unique left to download.")

    log(f"Total images to download: {len(unique_tasks)} ({dropped} skipped for duplicate filename)")
    log(f"Starting parallel downloads with {max_workers} workers…")

    total = len(unique_tasks)
    success_count = 0
    failed_count = 0
    bytes_downloaded = 0

    def report(current_file=None):
        if progress:
            progress(total=total, success=success_count, failed=failed_count,
                      current_file=current_file, bytes=bytes_downloaded)

    report()

    target_size = (canvas_size, canvas_size)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_one, item, images_dir, target_size, jpeg_quality, timeout, stop_event): item
            for item in unique_tasks
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
    zip_path = output_dir / "multi_link_images.zip"
    zip_folder(images_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
