import csv
from datetime import datetime
import io
import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
from typing import List
import shutil
import zipfile
from app import models
from app.database import get_db
from app.utils.log_utils import log_action
from app.auth.utils import get_current_user

router = APIRouter()

BASE_DIR = Path("uploads")
BASE_DIR.mkdir(exist_ok=True)


def list_directory(path: Path):
    """Recursively list all files and folders"""
    items = []
    for item in path.iterdir():
        if item.is_dir():
            items.append({
                "name": item.name,
                "type": "folder",
                "path": str(item.relative_to(BASE_DIR)),
                "children": list_directory(item)
            })
        else:
            items.append({
                "name": item.name,
                "type": "file",
                "path": str(item.relative_to(BASE_DIR))
            })
    return items


@router.get("/list")
def list_files():
    return list_directory(BASE_DIR)


@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    folder: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    folder_path = BASE_DIR / folder
    folder_path.mkdir(parents=True, exist_ok=True)

    for file in files:
        file_path = folder_path / file.filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if file.filename.lower().endswith(".zip"):
            extract_path = folder_path / file.filename.replace(".zip", "")
            extract_path.mkdir(exist_ok=True)
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)
            file_path.unlink()  

        log_action(db, current_user.id, "Upload", str(file_path.relative_to(BASE_DIR)))

    return {"message": "Files uploaded successfully"}


@router.post("/create-folder")
def create_folder(
    name: str = Form(...),
    folder: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    new_folder_path = BASE_DIR / folder / name
    new_folder_path.mkdir(parents=True, exist_ok=True)

    log_action(db, current_user.id, "Create Folder", str(new_folder_path.relative_to(BASE_DIR)))
    return {"message": f"Folder '{name}' created successfully"}


@router.post("/create-file")
def create_file(
    name: str = Form(...),
    folder: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_path = BASE_DIR / folder / name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.touch(exist_ok=True)

    log_action(db, current_user.id, "Create File", str(file_path.relative_to(BASE_DIR)))
    return {"message": f"File '{name}' created successfully"}


@router.get("/logs")
def get_logs(db: Session = Depends(get_db)):
    logs = db.query(models.ActionLog).order_by(models.ActionLog.timestamp.desc()).all()
    return [
        {
            "user": log.user.username if log.user else None,
            "action": log.action,
            "path": log.target_path,
            "timestamp": log.timestamp.isoformat()
        }
        for log in logs
    ]

@router.get("/download-logs")
def download_logs(db: Session = Depends(get_db)):
    logs = (
        db.query(models.ActionLog)
        .order_by(models.ActionLog.timestamp.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Username", "Action", "Path", "Timestamp"])

    for log in logs:
        writer.writerow([
            log.user.username if log.user else "Unknown",
            log.action,
            log.target_path,
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=action_logs.csv"},
    )
    
@router.delete("/delete")
def delete_item(
    path: str = Form(...),  
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    item_path = BASE_DIR / path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="File or folder not found")

    if item_path.is_dir():
        shutil.rmtree(item_path)
        action_type = "Delete Folder"
    else:
        item_path.unlink()
        action_type = "Delete File"

    log_action(db, current_user.id, action_type, str(item_path.relative_to(BASE_DIR)))
    return {"message": f"{action_type} '{path}' successfully"}

@router.post("/rename")
def rename_item(
    old_path: str = Form(...),  
    
    new_name: str = Form(...),  
    
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    item_path = BASE_DIR / old_path
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="File or folder not found")

    new_path = item_path.parent / new_name
    if new_path.exists():
        raise HTTPException(status_code=400, detail="A file/folder with the new name already exists")

    item_path.rename(new_path)

    action_type = "Rename Folder" if new_path.is_dir() else "Rename File"
    log_action(db, current_user.id, action_type, f"{old_path} -> {str(new_path.relative_to(BASE_DIR))}")

    return {"message": f"{action_type} '{old_path}' renamed to '{new_name}' successfully"}

import shutil

@router.post("/move")
def move_item(
    src_path: str = Form(...),  
    
    dest_folder: str = Form(...), 
    
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    source = BASE_DIR / src_path
    destination = BASE_DIR / dest_folder / source.name

    if not source.exists():
        raise HTTPException(status_code=404, detail="Source file/folder not found")
    if not (BASE_DIR / dest_folder).exists():
        raise HTTPException(status_code=404, detail="Destination folder not found")
    if destination.exists():
        raise HTTPException(status_code=400, detail="A file/folder with the same name exists in the destination")

    shutil.move(str(source), str(destination))

    action_type = "Move Folder" if destination.is_dir() else "Move File"
    log_action(db, current_user.id, action_type, f"{src_path} -> {dest_folder}/{source.name}")

    return {"message": f"{action_type} '{src_path}' moved to '{dest_folder}' successfully"}

@router.post("/copy")
def copy_item(
    src_path: str = Form(...),  
    
    dest_folder: str = Form(...),  
    
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    source = BASE_DIR / src_path
    destination = BASE_DIR / dest_folder / source.name

    if not source.exists():
        raise HTTPException(status_code=404, detail="Source file/folder not found")
    if not (BASE_DIR / dest_folder).exists():
        raise HTTPException(status_code=404, detail="Destination folder not found")
    if destination.exists():
        raise HTTPException(status_code=400, detail="A file/folder with the same name exists in the destination")

    if source.is_dir():
        shutil.copytree(str(source), str(destination))
        action_type = "Copy Folder"
    else:
        shutil.copy2(str(source), str(destination))
        action_type = "Copy File"

    log_action(db, current_user.id, action_type, f"{src_path} -> {dest_folder}/{source.name}")

    return {"message": f"{action_type} '{src_path}' copied to '{dest_folder}' successfully"}

@router.get("/download")
def download_file(
    path: str,  
    
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_path = BASE_DIR / path
    if not file_path.exists() or file_path.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    log_action(db, current_user.id, "Download File", path)
    return FileResponse(path=file_path, filename=file_path.name)

RECYCLE_BIN = BASE_DIR / ".recycle_bin"
RECYCLE_BIN.mkdir(exist_ok=True)

@router.post("/recycle")
def move_to_recyclebin(
    path: str,  
    
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    source = BASE_DIR / path
    if not source.exists():
        raise HTTPException(status_code=404, detail="File or folder not found")

    dest = RECYCLE_BIN / source.name
    if dest.exists():
        dest = RECYCLE_BIN / f"{source.stem}_{int(source.stat().st_mtime)}{source.suffix}"

    if source.is_dir():
        shutil.move(str(source), str(dest))
        action_type = "Recycle Folder"
    else:
        shutil.move(str(source), str(dest))
        action_type = "Recycle File"

    log_action(db, current_user.id, action_type, path)
    return {"message": f"{action_type} '{path}' moved to Recycle Bin"}


@router.get("/properties")
def file_properties(
    path: str,  # relative to BASE_DIR
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    target = BASE_DIR / path
    if not target.exists():
        raise HTTPException(status_code=404, detail="File or folder not found")

    stats = target.stat()
    properties = {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "type": "folder" if target.is_dir() else "file",
        "size_bytes": stats.st_size,
        "created_at": datetime.fromtimestamp(stats.st_ctime).isoformat(),
        "modified_at": datetime.fromtimestamp(stats.st_mtime).isoformat(),
        "is_readable": os.access(target, os.R_OK),
        "is_writable": os.access(target, os.W_OK),
    }

    log_action(db, current_user.id, "View Properties", path)
    return properties
