"""
Serial Wise Image (web-app version of
"Single or Multiple Image Downloader / Single Link / download_sortly_images.py")

Reads an uploaded CSV with one serial column + one link column, downloads
every image, fits it onto a white square canvas, and saves it as a
high-quality JPG. Returns a zip with every downloaded image.
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
        for i, row in enumerate(reader, start=1):
            serial = str(row.get(serial_col, "")).strip()
            url = str(row.get(url_col, "")).strip()
            if not serial or not url:
                log(f"[Row {i}] Missing serial or link — skipping.")
                continue
            rows.append((i, serial, url))

        log(f"Total valid rows to download: {len(rows)}")
        return rows


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


def download_one(item, out_dir, canvas_size, jpeg_quality, timeout):
    row_index, serial, url = item
    filename = sanitize_filename(serial)
    filepath = out_dir / f"{filename}.jpg"

    if filepath.exists():
        return f"[Row {row_index}] {serial} already exists, skipping."

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        img.load()
        final_img = fit_on_square_canvas(img, canvas_size)
        final_img.save(filepath, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)
        return f"[Row {row_index}] Downloaded {serial} -> {filepath.name}"
    except Exception as e:
        return f"[Row {row_index}] ERROR for {serial}: {e}"


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
        canvas_size=1080, jpeg_quality=95, max_workers=10, timeout=30, make_zip=True):
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

    log(f"Total valid rows to download: {len(rows)}")
    log(f"Starting parallel downloads with {max_workers} workers…")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_one, item, images_dir, canvas_size, jpeg_quality, timeout): item
            for item in rows
        }
        for future in as_completed(futures):
            log(future.result())

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
    zip_path = output_dir / "single_link_images.zip"
    zip_folder(images_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
