"""
Lightweight persistent job-history log used to power the dashboard's
real usage stats (tasks completed, files processed, top tools, recent
activity, weekly trend).

Stored as a plain JSON-lines file on local disk — one line per finished
job. This is intentionally simple (no DB needed for a single-user local
console). Note: on hosts with ephemeral disks (e.g. a Render free-tier
web service), this file resets on redeploy, same as the in-memory JOBS
dict already did — it's durable across ordinary restarts/requests, just
not across a redeploy that wipes the disk.
"""
import json
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "data" / "job_history.jsonl"
_LOCK = threading.Lock()

# Rough, clearly-labeled estimate of manual effort a single automated job
# replaces (used only for the "Time Saved" stat). Adjust freely.
MINUTES_SAVED_PER_JOB = 6


def record_job(tool_id, tool_name, stage, status, output_bytes=0, file_count=0):
    """Append one finished-job record. status: 'done' or 'error'."""
    entry = {
        "ts": time.time(),
        "tool_id": tool_id,
        "tool_name": tool_name,
        "stage": stage,
        "status": status,
        "output_bytes": output_bytes,
        "file_count": file_count,
    }
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def load_all():
    if not HISTORY_FILE.exists():
        return []
    out = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _time_ago(ts):
    delta = max(0, time.time() - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def get_dashboard_stats(recent_limit=5, top_n=4, chart_days=7):
    entries = load_all()
    done = [e for e in entries if e["status"] == "done"]
    errored = [e for e in entries if e["status"] == "error"]

    total_jobs = len(entries)
    total_done = len(done)
    total_bytes = sum(e.get("output_bytes", 0) for e in done)
    total_gb = total_bytes / (1024 ** 3)
    success_rate = (total_done / total_jobs * 100) if total_jobs else None
    time_saved_hours = (total_done * MINUTES_SAVED_PER_JOB) / 60

    # Recent activity — newest first.
    recent = sorted(entries, key=lambda e: e["ts"], reverse=True)[:recent_limit]
    recent_activity = [
        {
            "name": e["tool_name"],
            "meta": f"{'Completed' if e['status'] == 'done' else 'Failed'} \u00b7 {_time_ago(e['ts'])}",
            "stage": e["stage"],
            "status": e["status"],
        }
        for e in recent
    ]

    # Top tools used (by completed-job count).
    counts = {}
    for e in done:
        key = (e["tool_id"], e["tool_name"], e.get("stage", ""))
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    max_count = ranked[0][1] if ranked else 1
    top_tools = [
        {"tool_id": k[0], "name": k[1], "stage": k[2], "count": v, "pct": max(6, round(v / max_count * 100))}
        for k, v in ranked
    ]

    # Weekly trend — last `chart_days` calendar days, oldest first.
    now = time.localtime()
    today = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
    buckets = []
    for i in range(chart_days - 1, -1, -1):
        day_start = today - i * 86400
        day_end = day_start + 86400
        label = time.strftime("%a", time.localtime(day_start))
        day_done = [e for e in done if day_start <= e["ts"] < day_end]
        tasks = len(day_done)
        gb = sum(e.get("output_bytes", 0) for e in day_done) / (1024 ** 3)
        buckets.append({"label": label, "tasks": tasks, "gb": round(gb, 2)})

    return {
        "total_jobs": total_jobs,
        "total_done": total_done,
        "total_errored": len(errored),
        "total_gb": total_gb,
        "success_rate": success_rate,
        "time_saved_hours": time_saved_hours,
        "recent_activity": recent_activity,
        "top_tools": top_tools,
        "weekly": buckets,
    }
