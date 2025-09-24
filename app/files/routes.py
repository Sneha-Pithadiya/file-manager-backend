import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.utils import get_current_user
from app import models
from app.files import utils

router = APIRouter()


@router.post("/upload", summary="Upload a file or folder (ZIP)")
async def upload_file_or_folder(
    uploaded_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    filename = utils.secure_filename(uploaded_file.filename)
    file_path = utils.UPLOAD_DIR / filename

    # Save uploaded file
    with open(file_path, "wb") as f:
        f.write(await uploaded_file.read())

    # Detect if it is a ZIP folder
    is_folder = filename.lower().endswith(".zip")
    extract_dir_name = None

    if is_folder:
        # Extract ZIP into a folder
        extract_dir_name = filename.replace(".zip", "")
        extract_dir = utils.UPLOAD_DIR / extract_dir_name
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

    # Save to DB
    file_db = models.File(
        filename=filename,
        original_name=uploaded_file.filename,
        uploaded_by_id=current_user.id,
        is_folder=is_folder
    )
    db.add(file_db)
    db.commit()
    db.refresh(file_db)

    utils.append_log(file_db.id, f"{current_user.username} uploaded {'folder' if is_folder else 'file'} at {file_db.uploaded_at}")

    return {
        "id": file_db.id,
        "name": extract_dir_name if is_folder else filename,
        "type": "folder" if is_folder else "file",
        "uploaded_by": current_user.username
    }
@router.get("/download/{file_id}", summary="Download a file or folder")
def download_file_or_folder(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    file_db = db.query(models.File).filter(models.File.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "Not found")

    file_path = utils.UPLOAD_DIR / file_db.filename

    if file_db.is_folder:
        extract_dir = utils.UPLOAD_DIR / file_db.filename.replace(".zip", "")
        zip_path = utils.UPLOAD_DIR / f"{file_db.id}_folder.zip"
        shutil.make_archive(str(zip_path).replace(".zip", ""), "zip", extract_dir)
        send_path = zip_path
        send_name = file_db.original_name
    else:
        send_path = file_path
        send_name = file_db.original_name

    utils.append_log(file_id, f"{current_user.username} downloaded at {datetime.utcnow()}")

    return FileResponse(path=send_path, filename=send_name)


@router.get("/log/{file_id}", summary="Get logs for a file/folder")
def get_file_log(file_id: int):
    log_file = utils.get_log_path(file_id)
    if not log_file.exists():
        raise HTTPException(404, "No logs")
    return {"file_id": file_id, "logs": log_file.read_text().splitlines()}


@router.get("/log/{file_id}/download", summary="Download logs as text")
def download_file_log(file_id: int):
    log_file = utils.get_log_path(file_id)
    if not log_file.exists():
        raise HTTPException(404, "Log file not found")
    return FileResponse(path=log_file, filename=f"file_{file_id}_log.txt")

@router.get("/", summary="Get all files and folders")
def get_all_files(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    files = db.query(models.File).all()
    result = []
    for f in files:
        result.append({
            "id": f.id,
            "filename": f.filename,
            "original_name": f.original_name,
            "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
            "uploaded_at": f.uploaded_at,
            "is_folder": f.is_folder
        })
    return result