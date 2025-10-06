import os
import shutil
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.utils import get_current_user
from app import models
from app.files import utils
from pydantic import BaseModel

from app.schemas import CopyRequest

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)



class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}



def get_folder_full_path(folder: models.File):
    """Return the full path on disk for a folder object."""
    parts = [folder.filename]
    parent = folder.parent
    while parent:
        parts.insert(0, parent.filename)
        parent = parent.parent
    return UPLOAD_DIR.joinpath(*parts)



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

   
    if folder.parent_id:
        parent_folder = db.query(models.File).filter(models.File.id == folder.parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        parent_path = get_folder_full_path(parent_folder)
    else:
        parent_path = UPLOAD_DIR

    new_folder_path = parent_path / folder.name
    new_folder_path.mkdir(parents=True, exist_ok=True)

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

    utils.append_log(new_folder.id, f"{current_user.username} created folder in {parent_path}")
    log = models.FileLog(
        user_id = current_user.id,
        file_id = new_folder.id,
        action = "Create"
        
        
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return {
        "id": new_folder.id,
        "name": new_folder.filename,
        "type": "folder",
        "uploaded_by": current_user.username
    }



@router.get("/folder/{folder_id}", summary="Get contents of a folder")
def get_folder_contents(
    folder_id: int = 0,  
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if folder_id == 0:
        items = db.query(models.File).filter(models.File.parent_id == None).all()
    else:
        items = db.query(models.File).filter(models.File.parent_id == folder_id).all()

    result = []
    for f in items:
        result.append({
    "id": f.id,
    "name": f.filename,
    "original_name": f.original_name,
    "is_folder": f.is_folder,        
    "type": "folder" if f.is_folder else "file",
    "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
    "uploaded_at": f.uploaded_at
})

    return result


@router.post("/upload")
async def upload_file_or_folder(
    uploaded_file: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    parent_id: int = Form(None),
    current_user: models.User = Depends(get_current_user)
):
    saved_items = []

   
    if parent_id:
        parent_folder = db.query(models.File).filter(models.File.id == parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        upload_path = get_folder_full_path(parent_folder)
    else:
        upload_path = UPLOAD_DIR

    for file in uploaded_file:
        filename = utils.secure_filename(file.filename)
        file_path = upload_path / filename

        with open(file_path, "wb") as f:
            f.write(await file.read())

        is_folder = filename.lower().endswith(".zip")
        display_name = filename.replace(".zip", "") if is_folder else filename

        file_db = models.File(
            filename=filename,
            original_name=file.filename,
            uploaded_by_id=current_user.id,
            is_folder=is_folder,
            parent_id=parent_id
        )
        db.add(file_db)
        db.commit()
        db.refresh(file_db)

        utils.append_log(file_db.id, f"{current_user.username} uploaded file")

        saved_items.append({
            "id": file_db.id,
            "name": display_name,
            "type": "folder" if is_folder else "file",
            "uploaded_by": current_user.username,
            "parent_id": parent_id
        })

    return {"uploaded": saved_items}


@router.get("/")
def get_files(folder_id: Optional[int] = None, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
    query = db.query(models.File)
    if folder_id is not None:
        query = query.filter(models.File.parent_id == folder_id)
    else:
        query = query.filter(models.File.parent_id == None)

    total = query.count()
    items = query.offset((page-1)*limit).limit(limit).all()

    data = [
        {
            "id": f.id,
            "original_name": f.original_name,
            "filename": f.filename,
            "is_folder": f.is_folder,
            "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
            "uploaded_at": f.uploaded_at
        }
        for f in items
    ]
    return {
        "data": data,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

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

@router.get("/download/{file_id}", summary="Download a file or folder")
def download_file_or_folder(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    file_db = db.query(models.File).filter(models.File.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "Not found")

    file_path = utils.get_folder_full_path(file_db) if file_db.is_folder else utils.UPLOAD_DIR / file_db.filename

    if file_db.is_folder:
        zip_path = utils.UPLOAD_DIR / f"{file_db.id}_{file_db.filename}.zip"
        shutil.make_archive(str(zip_path).replace(".zip", ""), 'zip', str(file_path))
        send_path = zip_path
        send_name = f"{file_db.original_name}.zip"
    else:
        send_path = file_path
        send_name = file_db.original_name

    file_log = models.DownloadLog(
        file_id=file_db.id,
        user_id=current_user.id,
    )
    db.add(file_log)
    db.commit()
    db.refresh(file_log)
    utils.append_log(file_id, f"{current_user.username} downloaded at {datetime.now()}")

    return FileResponse(path=send_path, filename=send_name)

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

def recursive_copy(file_db, dest_folder_id, db: Session):
    """
    Copy a file or folder (with all nested contents) to destination folder.
    Returns list of new file DB objects.
    """
    new_file = models.File(
        filename=file_db.filename,
        original_name=file_db.original_name,
        is_folder=file_db.is_folder,
        parent_id=dest_folder_id,
        uploaded_by_id=file_db.uploaded_by_id
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    if file_db.is_folder:
        src_path = utils.get_folder_full_path(file_db)
        dest_path = utils.get_folder_full_path(new_file)
        shutil.copytree(src_path, dest_path)
        
        for child in file_db.children:
            recursive_copy(child, new_file.id, db)
    else:
        src_path = utils.UPLOAD_DIR / file_db.filename
        dest_path = utils.UPLOAD_DIR / new_file.filename
        shutil.copy2(src_path, dest_path)

    utils.append_log(new_file.id, f"{file_db.uploaded_by.username} copied {file_db.filename}")

    return new_file

def copy_file_or_folder(src: models.File, dest_folder: models.File, db: Session, current_user: models.User):
    src_path = UPLOAD_DIR / src.filename
    dest_path = UPLOAD_DIR / dest_folder.filename / src.filename if dest_folder else UPLOAD_DIR / src.filename

    if src.is_folder:
        shutil.copytree(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)

    new_file = models.File(
        filename=src.filename,
        original_name=src.original_name,
        uploaded_by_id=current_user.id,
        is_folder=src.is_folder,
        parent_id=dest_folder.id if dest_folder else None,
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)
    return new_file

@router.post("/copy")
@router.post("/copy")
def copy_files(
    request: CopyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    dest_folder = None
    if request.destination_folder_id:
        dest_folder = db.query(models.File).filter(
            models.File.id == request.destination_folder_id,
            models.File.is_folder==True
        ).first()
        if not dest_folder:
            raise HTTPException(404, "Destination folder not found")

    copied_files = []
    for file_id in request.file_ids:
        src_file = db.query(models.File).filter(models.File.id == file_id).first()
        if not src_file:
            continue
        new_file = copy_file_or_folder(src_file, dest_folder, db, current_user)
        copied_files.append({
            "id": new_file.id, 
            "name": new_file.filename, 
            "type": "folder" if new_file.is_folder else "file"
        })

    return {"copied_files": copied_files}