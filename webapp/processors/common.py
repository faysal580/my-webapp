"""Small shared helpers used by every processor module."""
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif")

_thread_local = threading.local()


def get_pooled_session(pool_size: int) -> requests.Session:
    """One pooled, keep-alive requests.Session per worker thread, sized to
    the thread pool so connections are reused instead of every download
    paying a fresh TCP/TLS handshake — the single biggest speed win for a
    batch of many small image requests. Also retries transient 5xx errors."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session


def run_parallel_downloads(items, worker_fn, max_workers, log, progress=None, stop_event=None):
    """Runs worker_fn(item, stop_event) for every item in a thread pool,
    logging each result and reporting live totals/bytes/current-file via
    `progress` (see app.py's job progress callback) as they complete.

    worker_fn must return a 4-tuple: (ok: bool, filename: str,
    log_message: str, size_bytes: int).

    Returns (success_count, failed_count, bytes_downloaded).
    """
    total = len(items)
    counts = {"success": 0, "failed": 0, "bytes": 0}

    def report(current_file=None):
        if progress:
            progress(total=total, success=counts["success"], failed=counts["failed"],
                      current_file=current_file, bytes=counts["bytes"])

    report()
    if not items:
        return 0, 0, 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker_fn, item, stop_event): item for item in items}
        for future in as_completed(futures):
            ok, filename, message, size_bytes = future.result()
            if ok:
                counts["success"] += 1
                counts["bytes"] += size_bytes
            else:
                counts["failed"] += 1
            log(message)
            report(current_file=filename)

    return counts["success"], counts["failed"], counts["bytes"]


def zip_folder(folder: Path, zip_path: Path, log=None, compression=zipfile.ZIP_STORED):
    """Zip every file inside `folder` (not the zip itself) into `zip_path`.

    Defaults to ZIP_STORED (no compression) instead of ZIP_DEFLATED: the
    files here are almost always JPEGs/PNGs that are already compressed,
    so re-running DEFLATE over them barely shrinks the archive but costs a
    lot of CPU time — for a batch of a few hundred/thousand images that
    difference is the "zipping takes forever" slowdown. Pass
    compression=zipfile.ZIP_DEFLATED to opt back into compression for
    genuinely compressible content (e.g. an already-uncompressed BMP).

    If `log` is given, it's called every ~50 files (or 5%, whichever is
    larger) so long batches still show visible progress instead of the UI
    looking frozen while the zip is being written.
    """
    folder = Path(folder)
    zip_path = Path(zip_path)
    files = [f for f in sorted(folder.rglob("*")) if f.is_file() and f.resolve() != zip_path.resolve()]
    total = len(files)
    step = max(50, total // 20) if total else 1

    with zipfile.ZipFile(zip_path, "w", compression) as zf:
        for i, f in enumerate(files, start=1):
            zf.write(f, arcname=f.name)
            if log and (i % step == 0 or i == total):
                log(f"Zipping… {i}/{total}")
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
