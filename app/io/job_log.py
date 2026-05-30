from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict

from app.config import CONFIG_DIR

JOB_LOG_FILE = os.path.join(CONFIG_DIR, "job_log.json")
MAX_ENTRIES = 500


@dataclass
class LogEntry:
    timestamp: str
    project_file: str
    move_count: int
    duration_seconds: float
    status: str          # "finished" | "stopped" | "error"
    error_message: str = ""


def load_log() -> list[LogEntry]:
    if not os.path.exists(JOB_LOG_FILE):
        return []
    try:
        with open(JOB_LOG_FILE) as f:
            data = json.load(f)
        return [LogEntry(**e) for e in data]
    except Exception:
        return []


def append_entry(entry: LogEntry):
    entries = load_log()
    entries.insert(0, entry)
    entries = entries[:MAX_ENTRIES]
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(JOB_LOG_FILE, "w") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)


def clear_log():
    if os.path.exists(JOB_LOG_FILE):
        os.remove(JOB_LOG_FILE)
