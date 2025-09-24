from pathlib import Path
from datetime import datetime

UPLOAD_DIR = Path("uploads")
LOG_DIR = Path("file_logs")

UPLOAD_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


def secure_filename(filename: str) -> str:
    # Very simple example — you can improve
    return filename.replace(" ", "_")


def get_file_path(filename: str) -> Path:
    return UPLOAD_DIR / filename


def get_log_path(file_id: int) -> Path:
    return LOG_DIR / f"file_{file_id}.txt"


def append_log(file_id: int, message: str):
    """Append a new line into the log file for a given file/folder"""
    log_file = get_log_path(file_id)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")  
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

