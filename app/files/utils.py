from pathlib import Path
from datetime import datetime

from app import models

UPLOAD_DIR = Path("uploads")
LOG_DIR = Path("file_logs")

UPLOAD_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


def secure_filename(filename: str) -> str:
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
        
def get_folder_full_path(folder: models.FileModel):
    """Return the full path on disk for a folder object."""
    parts = [folder.filename]
    parent = folder.parent
    while parent:
        parts.insert(0, parent.filename)
        parent = parent.parent
    return UPLOAD_DIR.joinpath(*parts)

