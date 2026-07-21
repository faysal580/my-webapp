"""
Local Tools Dashboard
======================
A small local Flask app that gives every .py automation script a proper
web page: upload files, click Run, watch the log, download the result.

Run:
    pip install -r requirements.txt
    python app.py
Then open:
    http://localhost:5000
"""
import os
import shutil
import tempfile
import threading
import traceback
import uuid
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_file, abort
)
from werkzeug.utils import secure_filename

from processors import (
    scraper, resizer, price_insert,
    single_link_downloader, multi_link_downloader, original_ratio_downloader,
    original_name_1080,
    daraz_scraper, top_deal_sticker_remover, photoroom_lite,
    campaign_sticker_price,
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "jobs"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB uploads

# ──────────────────────────────────────────────────────────────────────────
# Tool registry — add a new tool here and it shows up on the landing page.
# field types: "file" (single upload), "files" (multiple upload), "number"
# ──────────────────────────────────────────────────────────────────────────
ICONS = {
    "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.3" y1="15.3" x2="20.5" y2="20.5"/></svg>',
    "download": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="3" x2="12" y2="14.5"/><polyline points="7.5 10.5 12 15 16.5 10.5"/><line x1="4" y1="20" x2="20" y2="20"/></svg>',
    "expand": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 9 4 4 9 4"/><polyline points="15 4 20 4 20 9"/><polyline points="20 15 20 20 15 20"/><polyline points="9 20 4 20 4 15"/></svg>',
    "tag": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11.5V5a2 2 0 0 1 2-2h6.5L21 11.5a2 2 0 0 1 0 2.8L14.3 21a2 2 0 0 1-2.8 0L3 12.3Z"/><circle cx="8" cy="8" r="1.4"/></svg>',
    "folder": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6.5a1.5 1.5 0 0 1 1.5-1.5H9l2 2.2h8a1.5 1.5 0 0 1 1.5 1.5V17.5A1.5 1.5 0 0 1 19 19H4.5A1.5 1.5 0 0 1 3 17.5Z"/></svg>',
    "eraser": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18.5 13.5 9 4 3.5 9.5a2 2 0 0 0 0 2.8L9.7 18.5H20"/><path d="M12.5 8 6 14.5"/></svg>',
    "wand": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20 15 9"/><path d="M15 9 18 6"/><path d="M11 4v2.2"/><path d="M4.5 8.5h2.2"/><path d="M17 2v2.2"/><path d="M20.5 5.5h2.2"/><path d="M18.5 15.5v2.2"/><path d="M22 18.7h-2.2"/></svg>',
}

TOOLS = {
    "scraper": {
        "name": "Product Image Scraper",
        "description": "Upload an .xlsx file (with product URLs), or paste URLs directly — visits every link and extracts image links into a new .xlsx.",
        "stage": "SCRAPE",
        "icon": ICONS["search"],
        "fields": [
            {"key": "xlsx_file", "type": "file", "label": "Catalog Excel file (.xlsx)", "accept": ".xlsx", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste product URLs directly (one per line)",
             "placeholder": "https://example.com/product-1\nhttps://example.com/product-2", "required": False},
        ],
        "require_one_of": ["xlsx_file", "urls_text"],
        "module": scraper,
    },
    "daraz_scraper": {
        "name": "Product Image Scraper (Daraz 100%)",
        "description": "Upload an .xlsx file (with product URLs), or paste URLs directly — visits every link, including Daraz.com, Rokomari.com, Inest.com and Pickaboo.com, and extracts image links into a new .xlsx.",
        "stage": "SCRAPE",
        "icon": ICONS["search"],
        "fields": [
            {"key": "xlsx_file", "type": "file", "label": "Catalog Excel file (.xlsx)", "accept": ".xlsx", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste product URLs directly (one per line)",
             "placeholder": "https://example.com/product-1\nhttps://example.com/product-2", "required": False},
        ],
        "require_one_of": ["xlsx_file", "urls_text"],
        "module": daraz_scraper,
    },
    "single_link_downloader": {
        "name": "Serial Wise Image",
        "description": "Upload a .csv file (with serial + link columns), or paste URLs directly — downloads each image, fits it onto a white square canvas, and zips the results.",
        "stage": "DOWNLOAD",
        "icon": ICONS["download"],
        "fields": [
            {"key": "csv_file", "type": "file", "label": "CSV file (serial, link)", "accept": ".csv", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste image URLs directly (one per line)",
             "placeholder": "https://example.com/image-1.jpg\nhttps://example.com/image-2.jpg", "required": False},
            {"key": "canvas_size", "type": "number", "label": "Canvas size (px)", "default": 1080},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-100)", "default": 95},
            {"key": "max_workers", "type": "number", "label": "Parallel downloads", "default": 10},
            {"key": "make_zip", "type": "checkbox", "label": "Zip the output files", "default": True,
             "hint": "Uncheck to skip zipping — files will auto-download individually instead."},
        ],
        "require_one_of": ["csv_file", "urls_text"],
        "module": single_link_downloader,
    },
    "original_name_1080": {
        "name": "Original Name & 1080px Downloader",
        "description": "Upload a .csv file (with serial + link columns), or paste URLs directly — downloads each image using its ORIGINAL filename, fits it onto a white 1080px square canvas, skips any rows whose filename duplicates another row's, and keeps every file under your size limit.",
        "stage": "DOWNLOAD",
        "icon": ICONS["download"],
        "fields": [
            {"key": "csv_file", "type": "file", "label": "CSV file (serial, link)", "accept": ".csv", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste product URLs directly (one per line)",
             "placeholder": "https://example.com/product-1.jpg\nhttps://example.com/product-2.jpg", "required": False},
            {"key": "canvas_size", "type": "number", "label": "Canvas size (px)", "default": 1080},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-100)", "default": 95},
            {"key": "max_filesize_kb", "type": "number", "label": "Max file size (KB)", "default": 1200},
            {"key": "max_workers", "type": "number", "label": "Parallel downloads", "default": 10},
            {"key": "make_zip", "type": "checkbox", "label": "Zip the output files", "default": True,
             "hint": "Uncheck to skip zipping — files will auto-download individually instead."},
        ],
        "require_one_of": ["csv_file", "urls_text"],
        "module": original_name_1080,
    },
    "multi_link_downloader": {
        "name": "Multi Link Image Downloader",
        "description": "Upload a .csv file with multiple serial + multiple link columns (e.g. serial 1/2/3 + Image Link 1/2/3), or paste URLs directly — downloads every image, fits it onto a square canvas, and zips the results.",
        "stage": "DOWNLOAD",
        "icon": ICONS["download"],
        "fields": [
            {"key": "csv_file", "type": "file", "label": "CSV file (multi serial + multi link columns)", "accept": ".csv", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste image URLs directly (one per line)",
             "placeholder": "https://example.com/image-1.jpg\nhttps://example.com/image-2.jpg", "required": False},
            {"key": "canvas_size", "type": "number", "label": "Canvas size (px)", "default": 1080},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-100)", "default": 90},
            {"key": "max_workers", "type": "number", "label": "Parallel downloads", "default": 10},
            {"key": "make_zip", "type": "checkbox", "label": "Zip the output files", "default": True,
             "hint": "Uncheck to skip zipping — files will auto-download individually instead."},
        ],
        "require_one_of": ["csv_file", "urls_text"],
        "module": multi_link_downloader,
    },
    "original_ratio_downloader": {
        "name": "Original Name & Ratio Downloader",
        "description": "Upload a .csv file (with a link/url column), or paste URLs directly — downloads each image as a JPG keeping its original filename and aspect ratio (no cropping or resizing), then zips the results.",
        "stage": "DOWNLOAD",
        "icon": ICONS["download"],
        "fields": [
            {"key": "csv_file", "type": "file", "label": "CSV file (link/url column)", "accept": ".csv", "required": False},
            {"key": "urls_text", "type": "textarea", "label": "Or paste image URLs directly (one per line)",
             "placeholder": "https://example.com/image-1.jpg\nhttps://example.com/image-2.jpg", "required": False},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-100)", "default": 95},
            {"key": "max_workers", "type": "number", "label": "Parallel downloads", "default": 10},
            {"key": "make_zip", "type": "checkbox", "label": "Zip the output files", "default": True,
             "hint": "Uncheck to skip zipping — files will auto-download individually instead."},
        ],
        "require_one_of": ["csv_file", "urls_text"],
        "module": original_ratio_downloader,
    },
    "resizer": {
        "name": "Bulk Image Resizer",
        "description": "Upload multiple images — resizes all of them onto a square canvas, keeps every file under the size limit, and zips the results.",
        "stage": "RESIZE",
        "icon": ICONS["expand"],
        "fields": [
            {"key": "images", "type": "files", "label": "Images", "accept": "image/*", "required": True},
            {"key": "width", "type": "number", "label": "Width (px)", "default": 1080},
            {"key": "height", "type": "number", "label": "Height (px)", "default": 1080},
            {"key": "max_filesize_kb", "type": "number", "label": "Max file size (KB)", "default": 940},
            {"key": "make_zip", "type": "checkbox", "label": "Zip the output files", "default": True,
             "hint": "Uncheck to skip zipping — files will auto-download individually instead."},
        ],
        "module": resizer,
    },
    "price_insert": {
        "name": "Custom Positioned Sticker / Price Insert",
        "description": "Upload your images plus a template PSD (an 'image' layer, and an optional overlay/sticker layer) — fits each image into the target box and places it in the template.",
        "stage": "TAG",
        "icon": ICONS["tag"],
        "windows_only": True,
        "fields": [
            {"key": "images", "type": "files", "label": "Images", "accept": "image/*", "required": True},
            {"key": "template_psd", "type": "file", "label": "Template PSD file", "accept": ".psd", "required": True},
            # Populated live from the uploaded template's actual layers (see
            # /tool/<tool_id>/psd-layers below) — always reflects whatever
            # layers exist in the template right now, including new ones.
            {"key": "sticker_layer", "type": "layer_select", "label": "Overlay / sticker layer to use",
             "source_field": "template_psd", "default": "sticker", "required": False},
            {"key": "target_width", "type": "number", "label": "Target box width", "default": 1080},
            {"key": "target_height", "type": "number", "label": "Target box height", "default": 826},
            {"key": "target_x", "type": "number", "label": "Target box X", "default": 0},
            {"key": "target_y", "type": "number", "label": "Target box Y", "default": 254},
        ],
        "module": price_insert,
    },
    "campaign_sticker_price": {
        "name": "Campaign Sticker with Price",
        "description": "Upload your images, a campaign template PSD (with an 'image' layer and a price text layer containing 'Tk.'), and a CSV (filename, price) — fits each image into the template and updates the price automatically.",
        "stage": "TAG",
        "icon": ICONS["tag"],
        "windows_only": True,
        "fields": [
            {"key": "images", "type": "files", "label": "Images", "accept": "image/*", "required": True},
            {"key": "template_psd", "type": "file", "label": "Campaign template PSD", "accept": ".psd", "required": True},
            {"key": "prices_csv", "type": "file", "label": "Prices CSV (filename, price)", "accept": ".csv", "required": True},
            {"key": "target_width", "type": "number", "label": "Target box width", "default": 980},
            {"key": "target_height", "type": "number", "label": "Target box height", "default": 735},
            {"key": "target_x", "type": "number", "label": "Target box X", "default": 50},
            {"key": "target_y", "type": "number", "label": "Target box Y", "default": 325},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-12)", "default": 12},
        ],
        "module": campaign_sticker_price,
    },
    "top_deal_sticker_remover": {
        "name": "Top Deal Sticker Remover",
        "description": "Upload your images — crops away the 'Top Deal' sticker area and places the rest into a bundled square template. No template upload needed.",
        "stage": "CROP",
        "icon": ICONS["eraser"],
        "windows_only": True,
        "fields": [
            {"key": "images", "type": "files", "label": "Images", "accept": "image/*", "required": True},
            {"key": "x", "type": "number", "label": "Crop X", "default": 168},
            {"key": "y", "type": "number", "label": "Crop Y", "default": 325},
            {"key": "w", "type": "number", "label": "Crop Width", "default": 742},
            {"key": "h", "type": "number", "label": "Crop Height", "default": 735},
            {"key": "max_filesize_kb", "type": "number", "label": "Max file size (KB)", "default": 950},
        ],
        "module": top_deal_sticker_remover,
    },
    "photoroom_lite": {
        "name": "Photoroom Lite",
        "description": "Upload your images — an AI model removes the background, cleans up shadows/noise, tight-crops the subject, and centers it on a white square canvas.",
        "stage": "CUTOUT",
        "icon": ICONS["wand"],
        "fields": [
            {"key": "images", "type": "files", "label": "Images", "accept": "image/*", "required": True},
            {"key": "canvas_width", "type": "number", "label": "Canvas width (px)", "default": 1080},
            {"key": "canvas_height", "type": "number", "label": "Canvas height (px)", "default": 1080},
            {"key": "fit_percent", "type": "number", "label": "Product fit (% of canvas)", "default": 92},
            {"key": "jpeg_quality", "type": "number", "label": "JPEG quality (1-100)", "default": 100},
        ],
        "module": photoroom_lite,
    },
}

# ──────────────────────────────────────────────────────────────────────────
# Tool groups — bundles a few related tools behind one "folder" card on the
# landing page. Add a group here and list the tool ids that belong in it;
# those tools will be hidden from the top-level grid and shown inside the
# folder page instead.
# ──────────────────────────────────────────────────────────────────────────
TOOL_GROUPS = {
    "single_or_multi_downloader": {
        "name": "Single or Multiple Image Downloader",
        "description": "Four modes for downloading images from links — a single column, original name at 1080px, multiple columns, or keeping the original name and aspect ratio.",
        "stage": "DOWNLOAD",
        "icon": ICONS["folder"],
        "tool_ids": ["single_link_downloader", "original_name_1080", "multi_link_downloader", "original_ratio_downloader"],
    },
}

# ──────────────────────────────────────────────────────────────────────────
# In-memory job manager (single local user, so a plain dict + lock is enough)
# ──────────────────────────────────────────────────────────────────────────
JOBS = {}
JOBS_LOCK = threading.Lock()


def new_job(tool_id):
    job_id = uuid.uuid4().hex[:12]
    job_dir = DATA_DIR / job_id
    (job_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(parents=True, exist_ok=True)
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "tool_id": tool_id,
            "status": "queued",   # queued -> running -> done | error
            "logs": [],
            "files": [],          # output filenames (relative to output dir)
            "error": None,
            "dir": job_dir,
            "auto_download": False,
        }
    return job_id


def log_to_job(job_id, message):
    with JOBS_LOCK:
        if job_id in JOBS:
            for line in str(message).splitlines() or [""]:
                JOBS[job_id]["logs"].append(line)


def run_job(job_id, tool_id, form_kwargs):
    job = JOBS[job_id]
    job_dir = job["dir"]
    output_dir = job_dir / "output"
    tool = TOOLS[tool_id]
    module = tool["module"]

    with JOBS_LOCK:
        job["status"] = "running"

    def log(msg):
        log_to_job(job_id, msg)

    try:
        result_files = module.run(output_dir=output_dir, log=log, **form_kwargs)
        rel_names = [Path(f).name for f in (result_files or [])]
        with JOBS_LOCK:
            job["files"] = rel_names
            job["status"] = "done"
        log("")
        log("✅ Finished.")
    except Exception as e:
        log("")
        log(f"❌ Error: {e}")
        log(traceback.format_exc())
        with JOBS_LOCK:
            job["status"] = "error"
            job["error"] = str(e)


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    grouped_ids = set()
    for group in TOOL_GROUPS.values():
        grouped_ids.update(group["tool_ids"])

    seen_groups = set()
    display_items = []
    for tool_id, tool in TOOLS.items():
        if tool_id in grouped_ids:
            group_id = next(gid for gid, g in TOOL_GROUPS.items() if tool_id in g["tool_ids"])
            if group_id in seen_groups:
                continue
            seen_groups.add(group_id)
            display_items.append({"kind": "group", "id": group_id, "item": TOOL_GROUPS[group_id]})
        else:
            display_items.append({"kind": "tool", "id": tool_id, "item": tool})

    return render_template("index.html", display_items=display_items)


@app.route("/folder/<group_id>")
def folder_page(group_id):
    group = TOOL_GROUPS.get(group_id)
    if not group:
        abort(404)
    sub_tools = {tid: TOOLS[tid] for tid in group["tool_ids"] if tid in TOOLS}
    return render_template("folder.html", group=group, group_id=group_id, tools=sub_tools)


@app.route("/tool/<tool_id>")
def tool_page(tool_id):
    tool = TOOLS.get(tool_id)
    if not tool:
        abort(404)
    return render_template("tool.html", tool_id=tool_id, tool=tool)


@app.route("/tool/<tool_id>/psd-layers", methods=["POST"])
def tool_psd_layers(tool_id):
    """Reads a just-uploaded (not yet saved to a job) template PSD and
    returns its top-level layer names, so the UI can show a live picker
    instead of a hardcoded layer name. Works without Photoshop installed
    (uses the psd-tools library), so it also works for previewing on
    non-Windows machines."""
    tool = TOOLS.get(tool_id)
    if not tool:
        abort(404)

    f = request.files.get("template_psd")
    if not f or not f.filename:
        return jsonify({"error": "No template file uploaded."}), 400

    try:
        from psd_tools import PSDImage
    except ImportError:
        return jsonify({
            "error": "psd-tools is not installed on the server. Run: pip install psd-tools"
        }), 500

    suffix = Path(secure_filename(f.filename)).suffix or ".psd"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            f.save(tmp)
            tmp_path = tmp.name

        psd = PSDImage.open(tmp_path)
        layers = [layer.name for layer in psd if layer.name]
        return jsonify({"layers": layers})
    except Exception as e:
        return jsonify({"error": f"Could not read layers from this PSD: {e}"}), 400
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.route("/tool/<tool_id>/run", methods=["POST"])
def tool_run(tool_id):
    tool = TOOLS.get(tool_id)
    if not tool:
        abort(404)

    job_id = new_job(tool_id)
    job_dir = JOBS[job_id]["dir"]
    upload_dir = job_dir / "uploads"

    kwargs = {}
    for field in tool["fields"]:
        key = field["key"]
        ftype = field["type"]

        if ftype == "file":
            f = request.files.get(key)
            if not f or not f.filename:
                if field.get("required"):
                    shutil.rmtree(job_dir, ignore_errors=True)
                    with JOBS_LOCK:
                        del JOBS[job_id]
                    return f"Field '{field['label']}' is required.", 400
                continue
            filename = secure_filename(f.filename)
            save_path = upload_dir / filename
            f.save(save_path)
            kwargs[key] = save_path

        elif ftype == "files":
            files = request.files.getlist(key)
            files = [f for f in files if f and f.filename]
            if not files:
                if field.get("required"):
                    shutil.rmtree(job_dir, ignore_errors=True)
                    with JOBS_LOCK:
                        del JOBS[job_id]
                    return f"Field '{field['label']}' is required.", 400
                continue
            saved_paths = []
            sub_dir = upload_dir / key
            sub_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                filename = secure_filename(f.filename)
                save_path = sub_dir / filename
                f.save(save_path)
                saved_paths.append(save_path)
            kwargs[key] = saved_paths

        elif ftype == "number":
            raw = request.form.get(key)
            default = field.get("default")
            try:
                kwargs[key] = int(raw) if raw not in (None, "") else default
            except ValueError:
                kwargs[key] = default

        elif ftype == "layer_select":
            raw = request.form.get(key)
            default = field.get("default", "")
            value = raw.strip() if raw and raw.strip() else default
            if field.get("required") and not value:
                shutil.rmtree(job_dir, ignore_errors=True)
                with JOBS_LOCK:
                    del JOBS[job_id]
                return f"Field '{field['label']}' is required.", 400
            kwargs[key] = value

        elif ftype == "textarea":
            kwargs[key] = (request.form.get(key) or "").strip()

        elif ftype == "checkbox":
            # Unchecked checkboxes aren't submitted at all by the browser.
            kwargs[key] = request.form.get(key) is not None

    # Some tools accept more than one way to supply input (e.g. an uploaded
    # file OR pasted text) — at least one of that group must be present.
    require_one_of = tool.get("require_one_of")
    if require_one_of and not any(kwargs.get(k) for k in require_one_of):
        shutil.rmtree(job_dir, ignore_errors=True)
        with JOBS_LOCK:
            del JOBS[job_id]
        labels = " / ".join(
            f["label"] for f in tool["fields"] if f["key"] in require_one_of
        )
        return f"Please provide at least one of: {labels}.", 400

    # If this tool has a zip toggle and the user unchecked it, the job's
    # output files should be auto-downloaded as soon as they're ready
    # instead of waiting for the user to click each link.
    with JOBS_LOCK:
        JOBS[job_id]["auto_download"] = ("make_zip" in kwargs) and (not kwargs["make_zip"])

    thread = threading.Thread(target=run_job, args=(job_id, tool_id, kwargs), daemon=True)
    thread.start()

    return redirect(url_for("job_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_page(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    tool = TOOLS[job["tool_id"]]
    return render_template("job.html", job_id=job_id, tool=tool, tool_id=job["tool_id"])


@app.route("/job/<job_id>/status")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    with JOBS_LOCK:
        return jsonify({
            "status": job["status"],
            "logs": job["logs"],
            "files": job["files"],
            "error": job["error"],
            "auto_download": job.get("auto_download", False),
        })


@app.route("/job/<job_id>/download/<path:filename>")
def job_download(job_id, filename):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    file_path = job["dir"] / "output" / filename
    if not file_path.exists():
        abort(404)
    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    # host="0.0.0.0" makes the server reachable from other devices on the
    # same wifi/LAN network, not just this machine. debug is turned off
    # because Flask's debug mode exposes an interactive code console that
    # is dangerous to leave open on a network-accessible server.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
