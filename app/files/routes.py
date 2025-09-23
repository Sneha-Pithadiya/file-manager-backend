from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.auth.utils import get_current_user
from app import models
from app.files import utils

router = APIRouter()


@router.post("/upload", summary="Upload a file")
async def upload_file(
    uploaded_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    filename = utils.secure_filename(uploaded_file.filename)
    file_path = utils.UPLOAD_DIR / filename

    with open(file_path, "wb") as f:
        f.write(await uploaded_file.read())

    file_db = models.File(filename=filename, original_name=uploaded_file.filename, uploaded_by_id=current_user.id)
    db.add(file_db)
    db.commit()
    db.refresh(file_db)

    log_entry = models.FileLog(file_id=file_db.id, user_id=current_user.id, action="upload")
    db.add(log_entry)
    db.commit()

    log_file = utils.get_log_path(file_db.id)
    with open(log_file, "a") as f:
        f.write(f"{current_user.username} uploaded at {file_db.uploaded_at}\n")

    return {"file_id": file_db.id, "filename": filename, "uploaded_by": current_user.username}


@router.get("/download/{file_id}", summary="Download a file")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_db = db.query(models.File).filter(models.File.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "File not found")

    download_log = models.DownloadLog(file_id=file_id, user_id=current_user.id)
    db.add(download_log)
    db.commit()

    log_entry = models.FileLog(file_id=file_id, user_id=current_user.id, action="download")
    db.add(log_entry)
    db.commit()

    log_file = utils.get_log_path(file_id)
    with open(log_file, "a") as f:
        f.write(f"{current_user.username} downloaded at {download_log.downloaded_at}\n")

    file_path = utils.get_file_path(file_db.filename)
    return FileResponse(path=file_path, filename=file_db.original_name)


@router.get("/log/{file_id}", summary="Get log of a file")
def get_file_log(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    logs = db.query(models.FileLog).filter(models.FileLog.file_id == file_id).all()
    result = []
    for l in logs:
        result.append({
            "user": l.user.username,
            "action": l.action,
            "timestamp": l.timestamp
        })
    return {"file_id": file_id, "logs": result}


@router.get("/log/{file_id}/download", summary="Download log file as text")
def download_file_log(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    log_file = utils.get_log_path(file_id)
    if not log_file.exists():
        raise HTTPException(404, "Log file not found")
    return FileResponse(path=log_file, filename=f"file_{file_id}_log.txt")
