"""
Campaign Sticker with Price (web-app version of batch_price_insert.py)

Places each uploaded image into a per-run uploaded template PSD's "image"
layer, fits it (no stretch, centered) inside a target box, then looks up
that image's filename in an uploaded CSV (columns: filename, price) and
updates the first text layer containing "Tk." with the new price. Saves a
JPG per image and zips the results.

REQUIRES: Windows, Adobe Photoshop installed and opened at least once,
and `pip install pywin32`. This will not run on macOS/Linux.
"""
import csv
from pathlib import Path

from .common import zip_folder, IMAGE_EXTENSIONS


def _load_price_map(csv_path: Path, log):
    """Read filename -> price from the uploaded CSV, skipping blank rows."""
    price_map = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            price = (row.get("price") or "").strip()
            if not filename or not price:
                continue
            price_map[filename] = price
    if not price_map:
        log("⚠️ No filename/price rows found in the CSV — check the header row is 'filename,price'.")
    return price_map


def _find_and_update_price(doc, new_price):
    """Find the first text layer containing 'Tk.' (top-level, or one level
    into a layer group), update the number after it, and return the
    top-level layer that holds it (so callers can keep it visible)."""
    formatted_price = new_price.replace(".", ",") if "." in new_price else new_price

    def try_layer(layer):
        if layer.Kind != 2:  # not a text layer
            return False
        try:
            current_text = layer.TextItem.Contents
        except Exception:
            return False
        if "Tk." not in current_text:
            return False
        layer.TextItem.Contents = current_text.split("Tk.")[0] + f"Tk. {formatted_price}"
        return True

    for layer in doc.Layers:
        if layer.Kind == 1:  # layer group
            for sub_layer in layer.Layers:
                if try_layer(sub_layer):
                    return layer  # top-level group that owns the price text
        elif try_layer(layer):
            return layer  # top-level text layer itself
    return None


def _apply_layer_visibility(doc, layers_to_keep, price_layer):
    """Hide every top-level layer except 'image', the price layer/group,
    and whatever the user chose to keep visible."""
    keep_lower = {name.strip().lower() for name in (layers_to_keep or []) if name.strip()}
    for layer in doc.Layers:
        if layer.Name.lower() == "image":
            layer.Visible = True
            continue
        if price_layer is not None and layer.Name == price_layer.Name:
            layer.Visible = True
            continue
        layer.Visible = layer.Name.lower() in keep_lower


def run(images, template_psd: Path, prices_csv: Path, output_dir: Path, log,
        layers_to_keep=None,
        target_width=980, target_height=735, target_x=50, target_y=325, jpeg_quality=12):
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 is not installed, or this is not running on Windows. "
            "This tool needs a real Photoshop installation. "
            "Run:  pip install pywin32   (Windows only)"
        )

    output_dir = Path(output_dir)
    result_dir = output_dir / "with_price"
    result_dir.mkdir(parents=True, exist_ok=True)
    template_psd = Path(template_psd)
    prices_csv = Path(prices_csv)

    if not template_psd.exists():
        raise FileNotFoundError(f"Template PSD not found: {template_psd}")
    if not prices_csv.exists():
        raise FileNotFoundError(f"Prices CSV not found: {prices_csv}")

    price_map = _load_price_map(prices_csv, log)

    try:
        psApp = win32com.client.Dispatch("Photoshop.Application")
    except Exception as e:
        raise RuntimeError(
            "Could not connect to Photoshop via COM. Make sure Adobe "
            f"Photoshop is installed and has been opened at least once.\n{e}"
        )

    psApp.DisplayDialogs = 3
    psApp.Preferences.RulerUnits = 1  # pixels

    files = [Path(p) for p in images if Path(p).suffix.lower() in IMAGE_EXTENSIONS]
    if not files:
        log("No images found to process.")
        return []

    ok_count = 0

    for file in files:
        price = price_map.get(file.name)
        if not price:
            log(f"⚠️ Price not found for {file.name}. Skipping.")
            continue

        output_path = result_dir / (file.stem + ".jpg")
        log(f"Processing: {file.name} with price: {price}")
        doc = None
        try:
            doc = psApp.Open(str(template_psd))

            for layer in doc.Layers:
                if layer.Name.lower() == "image":
                    layer.Delete()
                    break

            placed_file = psApp.Open(str(file))
            placed_layer = placed_file.ActiveLayer.Duplicate(doc, 2)
            placed_file.Close(2)
            placed_layer.Name = "image"
            doc.ActiveLayer = placed_layer

            # Proportional fit inside the target box, centered, no stretch.
            bounds = placed_layer.Bounds
            current_width = bounds[2] - bounds[0]
            current_height = bounds[3] - bounds[1]

            scale_ratio = min(target_width / current_width, target_height / current_height)
            scale_percent = scale_ratio * 100
            placed_layer.Resize(scale_percent, scale_percent)

            bounds = placed_layer.Bounds
            new_width = bounds[2] - bounds[0]
            new_height = bounds[3] - bounds[1]
            new_x = bounds[0]
            new_y = bounds[1]

            offset_x = target_x + (target_width - new_width) / 2 - new_x
            offset_y = target_y + (target_height - new_height) / 2 - new_y
            placed_layer.Translate(offset_x, offset_y)

            price_layer = _find_and_update_price(doc, price)
            if price_layer is None:
                log("⚠️ Could not find price text in the template (looking for 'Tk.' in text layers)")

            _apply_layer_visibility(doc, layers_to_keep, price_layer)

            jpg_options = win32com.client.Dispatch("Photoshop.JPEGSaveOptions")
            jpg_options.Quality = jpeg_quality
            doc.SaveAs(str(output_path), jpg_options, True)
            doc.Close(2)
            doc = None

            log(f"✔ Saved {output_path.name}")
            ok_count += 1
        except Exception as e:
            log(f"❌ Error processing {file.name}: {e}")
            if doc is not None:
                try:
                    doc.Close(2)
                except Exception:
                    pass

    log("")
    log(f"Done. {ok_count}/{len(files)} images processed. Zipping…")
    zip_path = output_dir / "campaign_sticker_price.zip"
    zip_folder(result_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
