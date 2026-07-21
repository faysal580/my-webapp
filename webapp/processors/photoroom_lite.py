"""
Photoroom Lite — AI background remover (web-app version of batch_processor.py)

Removes the background from each uploaded image with an AI model (rembg /
isnet-general-use), cleans up faint shadow pixels and small noise, tight-
crops around the subject, fits it onto a white square canvas, and saves a
high quality JPG.

Pure Python — no Photoshop needed, works on Windows/macOS/Linux. Needs
extra packages: rembg, scipy, numpy (see requirements.txt). The AI model
(~170 MB) is downloaded automatically the first time this tool runs, so
that first run needs an internet connection and takes noticeably longer.
"""
import threading
from io import BytesIO
from pathlib import Path

from .common import zip_folder, IMAGE_EXTENSIONS

BACKGROUND_COLOR = (255, 255, 255)

# The AI model is large and slow to load, so we load it once and reuse it
# across every job/file instead of reloading per run.
_session = None
_session_lock = threading.Lock()


def _get_session(log):
    global _session
    with _session_lock:
        if _session is None:
            from rembg import new_session
            log("Loading AI model (first run downloads it, ~170 MB)…")
            _session = new_session("isnet-general-use")
            log("AI model loaded.")
    return _session


def _process_image(image_path: Path, output_path: Path, session,
                    canvas_width, canvas_height, fit_ratio, jpeg_quality):
    import numpy as np
    from PIL import Image
    from rembg import remove
    from scipy import ndimage

    with open(image_path, "rb") as f:
        input_bytes = f.read()

    output_bytes = remove(input_bytes, session=session)
    subject = Image.open(BytesIO(output_bytes)).convert("RGBA")

    # Remove weak shadow pixels
    alpha = np.array(subject.getchannel("A"))
    alpha[alpha < 30] = 0
    subject.putalpha(Image.fromarray(alpha))

    # Remove small noise (connected components smaller than 0.5% of the
    # total foreground) — larger detached parts (e.g. plug pins) are kept.
    alpha = np.array(subject.getchannel("A"))
    binary = alpha > 15
    labeled, num_features = ndimage.label(binary)
    if num_features > 1:
        component_sizes = ndimage.sum(binary, labeled, range(1, num_features + 1))
        total_fg = binary.sum()
        min_size = total_fg * 0.005
        for label_idx, size in enumerate(component_sizes, start=1):
            if size < min_size:
                alpha[labeled == label_idx] = 0
        subject.putalpha(Image.fromarray(alpha))

    # Tight crop around subject
    alpha = np.array(subject.getchannel("A"))
    coords = np.argwhere(alpha > 15)
    if len(coords) == 0:
        return False

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    subject = subject.crop((x_min, y_min, x_max + 1, y_max + 1))

    # Resize while maintaining aspect ratio
    sw, sh = subject.size
    available_w = canvas_width * fit_ratio
    available_h = canvas_height * fit_ratio
    scale = min(available_w / sw, available_h / sh)
    new_w = max(1, int(sw * scale))
    new_h = max(1, int(sh * scale))
    subject = subject.resize((new_w, new_h), Image.LANCZOS)

    # Center on a white canvas
    canvas = Image.new("RGB", (canvas_width, canvas_height), BACKGROUND_COLOR)
    x = (canvas_width - new_w) // 2
    y = (canvas_height - new_h) // 2
    canvas.paste(subject, (x, y), subject)

    canvas.save(output_path, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)
    return True


def run(images, output_dir: Path, log,
        canvas_width=1080, canvas_height=1080, fit_percent=92, jpeg_quality=100):
    log("Starting up…")
    try:
        log("Importing numpy…")
        import numpy  # noqa: F401
        log("Importing rembg (this loads onnxruntime, can take a while on first run)…")
        from rembg import remove, new_session  # noqa: F401
        log("Importing scipy…")
        from scipy import ndimage  # noqa: F401
        log("Packages loaded.")
    except ImportError as e:
        raise RuntimeError(
            "Missing packages for Photoroom Lite. Run:\n"
            "  pip install \"rembg[cpu]\" scipy numpy\n"
            f"Underlying error: {e}"
        )
    except Exception as e:
        if "onnxruntime" in str(e).lower():
            raise RuntimeError(
                "rembg is installed but has no onnxruntime backend. Run:\n"
                "  pip install \"rembg[cpu]\"   # or rembg[gpu] for NVIDIA/CUDA\n"
                f"Underlying error: {e}"
            )
        raise

    output_dir = Path(output_dir)
    result_dir = output_dir / "cutouts"
    result_dir.mkdir(parents=True, exist_ok=True)

    files = [Path(p) for p in images if Path(p).suffix.lower() in IMAGE_EXTENSIONS]
    if not files:
        log("No images found to process.")
        return []

    fit_ratio = max(1, min(100, fit_percent)) / 100
    session = _get_session(log)

    ok_count = 0
    for file in files:
        output_path = result_dir / (file.stem + ".jpg")
        log(f"Processing: {file.name}")
        try:
            saved = _process_image(
                file, output_path, session,
                canvas_width, canvas_height, fit_ratio, jpeg_quality,
            )
            if saved:
                log(f"✔ Saved {output_path.name}")
                ok_count += 1
            else:
                log(f"⚠ Skipped {file.name} (no subject detected)")
        except Exception as e:
            log(f"❌ Error processing {file.name}: {e}")

    log("")
    log(f"Done. {ok_count}/{len(files)} images processed. Zipping…")
    zip_path = output_dir / "cutout_images.zip"
    zip_folder(result_dir, zip_path)
    log(f"Saved -> {zip_path.name}")
    return [zip_path]
