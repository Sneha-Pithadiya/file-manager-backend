import os
import shutil
from typing import Any, Dict, List
import zipfile
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, FastAPI, Form, Query, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.utils import get_current_user
from app import models
from app.files import utils
from pydantic import BaseModel
from typing import Optional
router = APIRouter()
app = FastAPI()

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

    model_config = {
        "from_attributes": True
    }

@app.on_event("startup")
def create_home_folder():
    db: Session = next(get_db())
    home = db.query(models.File).filter(models.File.original_name == "Home", models.File.is_folder == True).first()
    if not home:
        home_folder = models.File(
            filename="Home",
            original_name="Home",
            is_folder=True,
            parent_id=None,
            uploaded_by_id=1  
        )
        db.add(home_folder)
        db.commit()

@router.post("/folder")
def create_folder(
    folder: FolderCreate,  
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    existing = db.query(models.File).filter(
        models.File.filename == folder.name,
        models.File.parent_id == folder.parent_id,
        models.File.is_folder == True
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Folder already exists")

    new_folder = models.File(
        filename=folder.name,
        original_name=folder.name,
        uploaded_by_id=current_user.id,
        is_folder=True,
        parent_id=folder.parent_id
    )
    db.add(new_folder)
    db.commit()
    db.refresh(new_folder)

    utils.append_log(
        new_folder.id,
        f"{current_user.username} created folder"
    )

    return {
        "id": new_folder.id,
        "name": new_folder.filename,
        "type": "folder",
        "uploaded_by": current_user.username
    }

@router.get("/folder/{folder_id}", summary="Get contents of a folder" )
def get_folder_contents(
    folder_id: Optional[int] = None,  
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    items = db.query(models.File).filter(
        models.File.parent_id == folder_id
    ).all()

    result = []
    for f in items:
        result.append({
            "id": f.id,
            "name": f.filename,
            "type": "folder" if f.is_folder else "file",
            "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
            "uploaded_at": f.uploaded_at
        })
    return result


@router.post("/upload", summary="Upload files or folders")
async def upload_file_or_folder(
    uploaded_file: List[UploadFile] = File(...),  
    db: Session = Depends(get_db),
    parent_id: int = Form(None),  
    current_user: models.User = Depends(get_current_user),
):
    if parent_id is None:
        home_folder = db.query(models.File).filter(models.File.original_name == "Home", models.File.is_folder == True).first()
        if home_folder:
            parent_id = home_folder.id

    saved_items = []
    for file in uploaded_file:
        filename = utils.secure_filename(file.filename)
        file_path = utils.UPLOAD_DIR / filename

        with open(file_path, "wb") as f:
            f.write(await file.read())

        is_folder = filename.lower().endswith(".zip")
        display_name = filename.replace(".zip", "") if is_folder else filename

        file_db = models.File(
            filename=filename,
            original_name=file.filename,
            uploaded_by_id=current_user.id,
            is_folder=is_folder,
            parent_id=parent_id,
        )
        db.add(file_db)
        db.commit()
        db.refresh(file_db)

        file_log = models.FileLog(
            file_id=file_db.id,
            action="Uploaded",
            user_id=current_user.id,
        )
        db.add(file_log)
        db.commit()
        db.refresh(file_log)

        saved_items.append({
            "id": file_db.id,
            "name": display_name,
            "type": "folder" if is_folder else "file",
            "uploaded_by": current_user.username,
            "parent_id": parent_id
        })

    return {"uploaded": saved_items}

def move_to_recycle_bin_db(file_db, current_user, db: Session):
    """
    Recursively move a file/folder and all nested children into RecycleBin (DB only).
    """
    for child in file_db.children:
        move_to_recycle_bin_db(child, current_user, db)

    recycle_item = models.RecycleBin(
        filename=file_db.filename,
        original_name=file_db.original_name,
        deleted_by_id=current_user.id,
        is_folder=file_db.is_folder,
        parent_id=file_db.parent_id
    )
    db.add(recycle_item)

    log_path = utils.get_log_path(file_db.id)
    if log_path.exists():
        removed_log_path = log_path.parent / f"removed_log_file_{file_db.id}.txt"
        shutil.move(log_path, removed_log_path)

    db.delete(file_db)

@router.delete("/delete/{file_id}", summary="Delete a file or folder (DB only)")
def delete_file_or_folder_db(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_db = db.query(models.File).filter(models.File.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "File/Folder not found")

    move_to_recycle_bin_db(file_db, current_user, db)

    db.commit()

    return {"deleted_file_id": file_id, "status": "moved to recycle bin (DB only)"}

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
    
    file_log = models.DownloadLog(
            file_id = file_db.id,
           
            user_id = current_user.id,
            
        )
    db.add(file_log)
    db.commit()
    db.refresh(file_log)    
    utils.append_log(file_id, f"{current_user.username} downloaded at {datetime.now()}")

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


@router.get("/")
def get_files(
    folder: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get files:
    - folder=None → root/home
    - folder=<id> → files inside that folder
    Paginated response
    """
    query = db.query(models.File)

    if folder is None:
        query = query.filter(models.File.parent_id == None)
    else:
        query = query.filter(models.File.parent_id == folder)

    total = query.count()
    files = query.offset((page - 1) * limit).limit(limit).all()

    return {
        "data": [
            {
                "id": f.id,
                "filename": f.filename,
                "original_name": f.original_name,
                "is_folder": f.is_folder,
                "uploaded_by": f.uploaded_by.username if f.uploaded_by else None
            }
            for f in files
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit  
    }
def get_bin_recursive(file: models.RecycleBin) -> dict:
    """
    Recursively retrieve a file/folder and its children from Recycle Bin.
    """
    return {
        "id": file.id,
        "filename": file.filename,
        "original_name": file.original_name,
        "is_folder": file.is_folder,
        "deleted_by": file.deleted_by.username if file.deleted_by else None,
        "deleted_at": file.delete_at if hasattr(file, "delete_at") else None,
        "children": [get_bin_recursive(child) for child in file.children]  
    }

@router.get("/bin/recursive", summary="Get all Recycle Bin files/folders recursively")
def get_bin_files_recursive(db: Session = Depends(get_db),
                            current_user: models.User = Depends(get_current_user)) -> List[dict]:
    """
    Retrieve all files and folders from Recycle Bin recursively
    starting from top-level items (parent_id=None).
    """
    try:
        top_level_items = db.query(models.RecycleBin).filter(models.RecycleBin.parent_id == None).all()
        return [get_bin_recursive(item) for item in top_level_items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))