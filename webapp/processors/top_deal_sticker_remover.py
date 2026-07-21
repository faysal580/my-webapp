"""
Top Deal Sticker Remover (web-app version of the standalone
photoshop_batch_crop.py script bundled with "free crop.psd")

Crops away the region of each uploaded image that contains the "Top Deal"
sticker, then places the remaining crop into a bundled square template
("free crop.psd"), scales it to fit the canvas, centers it, and saves a
JPG under a max file size. The template ships with the app, so you only
need to upload images — no per-run template upload needed.

REQUIRES: Windows, Adobe Photoshop installed and opened at least once,
and `pip install pywin32`. This will not run on macOS/Linux.
"""
import os
from pathlib import Path

from .common import zip_folder, IMAGE_EXTENSIONS

# Bundled template — lives at webapp/assets/top_deal_sticker_remover/free_crop.psd
TEMPLATE_PSD = Path(__file__).parent.parent / "assets" / "top_deal_sticker_remover" / "free_crop.psd"


def run(images, output_dir: Path, log,
        x=168, y=325, w=742, h=735, max_filesize_kb=950):
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 is not installed, or this is not running on Windows. "
            "This tool needs a real Photoshop installation. "
            "Run:  pip install pywin32   (Windows only)"
        )

    output_dir = Path(output_dir)
    result_dir = output_dir / "cropped"
    result_dir.mkdir(parents=True, exist_ok=True)

    if not TEMPLATE_PSD.exists():
        raise FileNotFoundError(
            f"Bundled template PSD not found: {TEMPLATE_PSD}. "
            "Make sure 'free_crop.psd' is present under webapp/assets/top_deal_sticker_remover/."
        )

    try:
        psApp = win32com.client.Dispatch("Photoshop.Application")
    except Exception as e:
        raise RuntimeError(
            "Could not connect to Photoshop via COM. Make sure Adobe "
            f"Photoshop is installed and has been opened at least once.\n{e}"
        )

    psApp.Visible = True
    psPixels = 1
    psApp.Preferences.RulerUnits = psPixels

    files = [Path(p) for p in images if Path(p).suffix.lower() in IMAGE_EXTENSIONS]
    if not files:
        log("No images found to process.")
        return []

    ok_count = 0

    for file in files:
        output_path = result_dir / (file.stem + ".jpg")
        log(f"Processing: {file.name}")
        try:
            doc = psApp.Open(str(file))
            crop_rect = [x, y, x + w, y + h]
            doc.Crop(crop_rect)

            template_doc = psApp.Open(str(TEMPLATE_PSD))
            psApp.ActiveDocument = doc
            doc.ActiveLayer.Duplicate(template_doc)
            doc.Close(2)

            layer = template_doc.ActiveLayer
            bounds = layer.Bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]

            canvas_size = template_doc.Width
            scale = min(canvas_size / width, canvas_size / height) * 100
            layer.Resize(scale, scale)

            bounds = layer.Bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            moveX = (canvas_size / 2) - (bounds[0] + width / 2)
            moveY = (canvas_size / 2) - (bounds[1] + height / 2)
            layer.Translate(moveX, moveY)

            quality = 12
            filesize_kb = None
            while quality > 0:
                options = win32com.client.Dispatch("Photoshop.JPEGSaveOptions")
                options.Quality = quality
                template_doc.SaveAs(str(output_path), options, True)
                filesize_kb = os.path.getsize(output_path) / 1024
                if filesize_kb <= max_filesize_kb:
                    break
                quality -= 1

            template_doc.Close(2)
            log(f"✔ Saved {output_path.name} ({filesize_kb:.1f} KB) at quality {quality}")
            ok_count += 1
        except Exception as e:
            log(f"❌ Error processing {file.name}: {e}")

    log("")
    log(f"Done. {ok_count}/{len(files)} images processed. Zipping…")
    zip_path = output_dir / "cropped_images.zip"
    zip_folder(result_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
