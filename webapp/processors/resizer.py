"""
Bulk image resizer (web-app version of resize_images.py)
Pads every uploaded image to a square white canvas, resizes it to the
requested dimensions, and saves it as a size-capped JPG.
"""
from pathlib import Path

from PIL import Image

from .common import zip_folder, save_with_max_size, IMAGE_EXTENSIONS


def run(images, output_dir: Path, log,
        width=1080, height=1080, max_filesize_kb=940, make_zip=True):
    output_dir = Path(output_dir)
    result_dir = output_dir / "resized"
    result_dir.mkdir(parents=True, exist_ok=True)

    max_filesize = max_filesize_kb * 1024
    ok_count, fail_count = 0, 0
    saved_paths = []

    for path in images:
        path = Path(path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            log(f"Skipping non-image file: {path.name}")
            continue
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            max_side = max(w, h)
            square_bg = Image.new("RGB", (max_side, max_side), (255, 255, 255))
            offset = ((max_side - w) // 2, (max_side - h) // 2)
            square_bg.paste(img, offset)
            final_img = square_bg.resize((width, height), Image.Resampling.LANCZOS)

            output_path = result_dir / (path.stem + ".jpg")
            fitted, quality = save_with_max_size(final_img, output_path, max_filesize)
            if fitted:
                log(f"✅ Saved {output_path.name} under {max_filesize_kb}KB (quality {quality})")
                ok_count += 1
            else:
                log(f"⚠️ Could not keep {output_path.name} under {max_filesize_kb}KB (used min quality)")
                ok_count += 1
            saved_paths.append(output_path)
        except Exception as e:
            log(f"❌ Error processing {path.name}: {e}")
            fail_count += 1

    log("")

    if not make_zip:
        log(f"Done. {ok_count} resized, {fail_count} failed.")
        # Downloads are served straight from output_dir, so move the
        # individual files up out of the "resized" subfolder.
        final_paths = []
        for p in sorted(saved_paths):
            dest = output_dir / p.name
            p.replace(dest)
            final_paths.append(dest)
        return final_paths

    log(f"Done. {ok_count} resized, {fail_count} failed. Zipping…")
    zip_path = output_dir / "resized_images.zip"
    zip_folder(result_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
