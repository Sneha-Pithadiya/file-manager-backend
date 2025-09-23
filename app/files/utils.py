import os
from pathlib import Path
from fastapi import HTTPException

UPLOAD_DIR = Path("uploads")
LOG_DIR = Path("file_logs")
UPLOAD_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

def secure_filename(filename: str) -> str:
    return "".join(c for c in filename if c.isalnum() or c in (" ", ".", "_")).rstrip()

def get_file_path(filename: str) -> Path:
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return file_path

def get_log_path(file_id: int) -> Path:
    return LOG_DIR / f"file_{file_id}.txt"
