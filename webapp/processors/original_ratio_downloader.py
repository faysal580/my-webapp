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


def download_one(item, out_dir, jpeg_quality, timeout):
    row_index, url, stem = item
    filepath = out_dir / f"{stem}.jpg"

    if filepath.exists():
        return f"[Row {row_index}] '{stem}' already exists — skipped."

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()

        img = Image.open(BytesIO(resp.content))
        img.load()

        img = to_rgb(img)
        img.save(filepath, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)

        return f"[Row {row_index}] ✓ {stem}.jpg ({img.width}×{img.height})"
    except Exception as e:
        return f"[Row {row_index}] ERROR ({stem}): {e}"


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
        jpeg_quality=95, max_workers=10, timeout=30, make_zip=True):
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

    log(f"Total valid rows: {len(rows)}")
    log(f"Starting downloads with {max_workers} workers…")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_one, item, images_dir, jpeg_quality, timeout): item
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
    zip_path = output_dir / "original_name_ratio_images.zip"
    zip_folder(images_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
