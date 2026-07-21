"""Small shared helpers used by every processor module."""
import zipfile
from pathlib import Path

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif")


def zip_folder(folder: Path, zip_path: Path):
    """Zip every file inside `folder` (not the zip itself) into `zip_path`."""
    folder = Path(folder)
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.resolve() != zip_path.resolve():
                zf.write(f, arcname=f.name)
    return zip_path


def save_with_max_size(img, output_path, max_filesize, min_quality=20, start_quality=95, step=5):
    """Save a PIL image as JPEG, stepping quality down until it fits under max_filesize bytes."""
    quality = start_quality
    while quality >= min_quality:
        img.save(output_path, "JPEG", quality=quality, optimize=True)
        if output_path.stat().st_size <= max_filesize:
            return True, quality
        quality -= step
    return False, quality
