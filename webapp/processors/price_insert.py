"""
Custom positioned sticker / price insert (web-app version of batch_price_insert_updated.py)
Places each uploaded image into a template PSD's "image" layer, fits it
(no stretch) inside a target box, and keeps only the user-chosen overlay
layer (e.g. "sticker") visible on top — every other top-level layer in the
template is hidden. Saves a JPG per image.

REQUIRES: Windows, Adobe Photoshop installed and opened at least once,
and `pip install pywin32`. This will not run on macOS/Linux.
"""
import json
import os
from pathlib import Path

from .common import zip_folder, IMAGE_EXTENSIONS


def run(images, template_psd: Path, output_dir: Path, log,
        target_width=1080, target_height=826, target_x=0, target_y=254, jpeg_quality=12,
        sticker_layer="sticker"):
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 is not installed, or this is not running on Windows. "
            "This tool needs a real Photoshop installation. "
            "Run:  pip install pywin32   (Windows only)"
        )

    output_dir = Path(output_dir)
    result_dir = output_dir / "with_sticker"
    result_dir.mkdir(parents=True, exist_ok=True)
    template_psd = Path(template_psd)

    if not template_psd.exists():
        raise FileNotFoundError(f"Template PSD not found: {template_psd}")

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

    # The layer to keep on top of the placed image (chosen by the user in
    # the UI from the template's actual layer list). Empty/None means
    # "don't look for an overlay layer at all".
    sticker_layer_name = (sticker_layer or "").strip()
    if sticker_layer_name:
        sticker_lookup_js = f"findLayerByName({json.dumps(sticker_layer_name.lower())})"
        log(f"Overlay layer: \"{sticker_layer_name}\"")
    else:
        sticker_lookup_js = "null"
        log("No overlay layer selected — skipping overlay step.")

    for file in files:
        output_path = result_dir / (file.stem + ".jpg")
        log(f"Processing: {file.name}")
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

            psApp.DoJavaScript(f"""
            #target photoshop
            var doc = app.activeDocument;

            function findLayerByName(nameLower) {{
                for (var i = 0; i < doc.layers.length; i++) {{
                    if (doc.layers[i].name.toLowerCase() === nameLower) return doc.layers[i];
                }}
                return null;
            }}

            var layer = findLayerByName("image");
            if (!layer) throw new Error("Layer 'image' not found");

            var b = layer.bounds;
            var w = b[2].as("px") - b[0].as("px");
            var h = b[3].as("px") - b[1].as("px");

            var scaleW = {target_width} / w;
            var scaleH = {target_height} / h;
            var scale = Math.min(scaleW, scaleH) * 100;

            layer.resize(scale, scale, AnchorPosition.MIDDLECENTER);

            b = layer.bounds;
            var newW = b[2].as("px") - b[0].as("px");
            var newH = b[3].as("px") - b[1].as("px");

            var targetCenterX = {target_x} + ({target_width} / 2);
            var targetCenterY = {target_y} + ({target_height} / 2);

            var layerCenterX = b[0].as("px") + (newW / 2);
            var layerCenterY = b[1].as("px") + (newH / 2);

            layer.translate(targetCenterX - layerCenterX, targetCenterY - layerCenterY);

            var sticker = {sticker_lookup_js};

            // Keep only "image" and the one layer the user picked visible;
            // hide every other top-level layer (other sticker variants,
            // unused overlays, etc.) so just the chosen one shows up.
            for (var i = 0; i < doc.layers.length; i++) {{
                var lyr = doc.layers[i];
                if (lyr.name.toLowerCase() === "image") continue;
                lyr.visible = (sticker !== null && lyr === sticker);
            }}

            if (sticker) {{
                sticker.move(layer, ElementPlacement.PLACEBEFORE);
            }}
            """)

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
    zip_path = output_dir / "sticker_images.zip"
    zip_folder(result_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
