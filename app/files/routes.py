import os
import shutil
import threading
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
from sqlalchemy.orm import joinedload
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time


from app.schemas import CopyRequest

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}

class FileCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    model_config = {"from_attributes": True}

def sync_uploads_with_db(db: Session, base_path: Path = UPLOAD_DIR, parent_id: Optional[int] = None):
    """
    Recursively sync the filesystem with the database.
    """
    base_path.mkdir(parents=True, exist_ok=True)
    for entry in base_path.iterdir():
        existing = db.query(models.FileModel).filter_by(filename=entry.name, parent_id=parent_id).first()
        if not existing:
            last = db.query(models.FileModel).order_by(models.FileModel.id.desc()).first()
            next_id = (last.id + 1) if last else 1

            new_file = models.FileModel(
                id=next_id,
                filename=entry.name,
                original_name=entry.name,
                path=str(entry.resolve()),
                is_folder=entry.is_dir(),
                parent_id=parent_id,
                uploaded_at=datetime.now(),
                uploaded_by_id=None,
                size=entry.stat().st_size if entry.is_file() else 0,
                is_star=False,
            )
            db.add(new_file)
            db.commit()
            db.refresh(new_file)

        if entry.is_dir():
            folder_in_db = db.query(models.FileModel).filter_by(filename=entry.name, parent_id=parent_id).first()
            sync_uploads_with_db(db, entry, folder_in_db.id)

class UploadsEventHandler(FileSystemEventHandler):
    def __init__(self, db_factory):
        self.db_factory = db_factory

    def on_created(self, event):
        if not event.is_directory or event.is_directory():  
            db = self.db_factory()
            sync_uploads_with_db(db)
            db.close()

def start_watcher(db_factory):
    event_handler = UploadsEventHandler(db_factory)
    observer = Observer()
    observer.schedule(event_handler, str(UPLOAD_DIR), recursive=True)
    observer.start()

    def run():
        try:
            while True:
                time.sleep(0.01)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    threading.Thread(target=run, daemon=True).start()

def get_full_path(file: models.FileModel) -> str:
    parts = []
    current = file
    while current:
        parts.insert(0, current.filename)
        current = current.parent
    return str(UPLOAD_DIR / Path(*parts))

def get_folder_full_path(folder: models.FileModel):
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
   
    existing = db.query(models.FileModel).filter(
        models.FileModel.filename == folder.name,
        models.FileModel.parent_id == folder.parent_id,
        models.FileModel.is_folder == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Folder already exists")

   
    if folder.parent_id:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == folder.parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        parent_path = get_folder_full_path(parent_folder)
    else:
        parent_path = UPLOAD_DIR

    new_folder_path = parent_path / folder.name
    new_folder_path.mkdir(parents=True, exist_ok=True)

    new_folder = models.FileModel(
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

@router.post("/createfile")
def create_file(
    file: FileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
   
    existing = db.query(models.FileModel).filter(
        models.FileModel.filename == file.name,
        models.FileModel.parent_id == file.parent_id,
        models.FileModel.is_folder == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="file already exists")

   
    if file.parent_id:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == file.parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        parent_path = get_folder_full_path(parent_folder)
    else:
        parent_path = UPLOAD_DIR

    new_file_path = parent_path / file.name
    new_file_path.touch( exist_ok=True)

    new_file = models.FileModel(
        filename=file.name,
        original_name=file.name,
        uploaded_by_id=current_user.id,
        is_folder=False,
        parent_id=file.parent_id
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    utils.append_log(new_file.id, f"{current_user.username} created folder in {parent_path}")
    log = models.FileLog(
        user_id = current_user.id,
        file_id = new_file.id,
        action = "Create"
        
        
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return {
        "id": new_file.id,
        "name": new_file.filename,
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
        items = db.query(models.FileModel).filter(models.FileModel.parent_id == None).all()
    else:
        items = db.query(models.FileModel).filter(models.FileModel.parent_id == folder_id).all()

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
):
    saved_items = []

    if parent_id:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        
        if not parent_folder.path:
            parent_folder.path = str(UPLOAD_DIR / parent_folder.filename)
            Path(parent_folder.path).mkdir(parents=True, exist_ok=True)
            db.commit()

        upload_path = Path(parent_folder.path)
    else:
        upload_path = UPLOAD_DIR

    upload_path.mkdir(parents=True, exist_ok=True)

    for file in uploaded_file:
        file_path = upload_path / file.filename
        with open(file_path, "wb") as f:
            f.write(await file.read())

        size_bytes = file_path.stat().st_size

        file_db = models.FileModel(
            filename=file.filename,
            original_name=file.filename,
            path=str(file_path.resolve()),
            uploaded_by_id=None,
            is_folder=False,
            parent_id=parent_id,
            size=size_bytes,
            is_star=False,
        )
        db.add(file_db)
        db.commit()
        db.refresh(file_db)

        saved_items.append({
            "id": file_db.id,
            "name": file.filename,
            "type": "file",
            "size": size_bytes,
            "parent_id": parent_id
        })

    return {"uploaded": saved_items}

@router.get("/")
def get_files(folder_id: Optional[int] = None, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
    query = db.query(models.FileModel)
    if folder_id is not None:
        query = query.filter(models.FileModel.parent_id == folder_id)
    else:
        query = query.filter(models.FileModel.parent_id == None)

    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()

    data = [
        {
            "id": f.id,
            "original_name": f.original_name,
            "filename": f.filename,
            "is_folder": f.is_folder,
            "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
            "uploaded_at": f.uploaded_at,
            "size": f.size,
        }
        for f in items
    ]

    return {
        "data": data,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/log/{file_id}", summary="Get logs for a file/folder")
def get_file_log(file_id: int):
    log_file = utils.get_log_path(file_id)
    if not log_file.exists():
        raise HTTPException(404, "No logs")
    return {"file_id": file_id, "logs": log_file.read_text().splitlines()}

@router.get("/properties")
def file_os_properties(file_id: int, db: Session = Depends(get_db)):
    file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file:
        return {"error": "File not found"}

    full_path = get_full_path(file)
    path = Path(full_path)  
    if not path.exists():
        return {"error": "File not found"}

    stats = path.stat()
    file_type = "folder" if path.is_dir() else (path.suffix[1:] if path.suffix else "unknown")
    file_size_mb = stats.st_size / 1024 / 1024
    import datetime

    return {
        "name": path.name,
        "type": file_type,
        "size": file_size_mb,
        "created_at": datetime.datetime.fromtimestamp(stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        "modified_at": datetime.datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "accessed_at": datetime.datetime.fromtimestamp(stats.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
        "absolute_path": str(path.resolve()),
        "is_readable": os.access(path, os.R_OK),
        "is_writable": os.access(path, os.W_OK),
        "is_executable": os.access(path, os.X_OK)
    }

    
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
    file_db = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
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
    file_db = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "File/Folder not found")
    utils.append_log(file_db.id,f"{current_user.username} delete file {file_db.filename} at {datetime.now()}")

    move_to_recycle_bin_db(file_db, current_user, db)

    db.commit()

    return {"deleted_file_id": file_id, "status": "moved to recycle bin (DB only)"}

def generate_unique_filename(filename: str, existing_files: set) -> str:
    name, ext = os.path.splitext(filename)
    counter = 1
    new_name = filename
    while new_name in existing_files:
        new_name = f"{name}_copy{counter}{ext}"
        counter += 1
    return new_name


def recursive_copy(file_db, dest_folder_id, db: Session):
    if dest_folder_id:
        dest_folder = db.query(models.FileModel).filter(models.FileModel.id == dest_folder_id).first()
        dest_path = utils.get_folder_full_path(dest_folder)
    else:
        dest_path = UPLOAD_DIR

    os.makedirs(dest_path, exist_ok=True)

    existing_files = {f.name for f in os.scandir(dest_path)}
    new_filename = generate_unique_filename(file_db.filename, existing_files)

    new_file = models.FileModel(
        filename=new_filename,
        original_name=file_db.original_name,
        is_folder=file_db.is_folder,
        parent_id=dest_folder_id,
        uploaded_by_id=file_db.uploaded_by_id
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    if file_db.is_folder:
        folder_path = dest_path / new_file.filename
        os.makedirs(folder_path, exist_ok=True)
        for child in file_db.children:
            recursive_copy(child, new_file.id, db)
    else:
        src_path = utils.UPLOAD_DIR / file_db.filename
        dest_file_path = dest_path / new_file.filename
        if not src_path.exists():
            raise HTTPException(404, f"Source file {file_db.filename} not found")
        shutil.copy2(src_path, dest_file_path)

    utils.append_log(new_file.id, f"Copied from {file_db.filename}")
    return new_file

def copy_file_or_folder(src: models.FileModel, dest_folder: models.FileModel, db: Session, current_user: models.User):
    src_path = UPLOAD_DIR / src.filename
    dest_path = UPLOAD_DIR / dest_folder.filename / src.filename if dest_folder else UPLOAD_DIR / src.filename

    if src.is_folder:
        shutil.copytree(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)

    new_file = models.FileModel(
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
def copy_files(
    request: CopyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    dest_folder = None
    if request.destination_folder_id:
        dest_folder = db.query(models.FileModel).filter(
            models.FileModel.id == request.destination_folder_id,
            models.FileModel.is_folder == True
        ).first()
        if not dest_folder:
            raise HTTPException(404, "Destination folder not found")

    copied_files = []

    for file_id in request.file_ids:
        src_file = db.query(models.FileModel).options(joinedload(models.FileModel.children)).filter(
            models.FileModel.id == file_id
        ).first()
        if not src_file:
            continue
        
        try:
            new_file = recursive_copy(src_file, dest_folder.id if dest_folder else None, db)
            copied_files.append({
                "id": new_file.id,
                "name": new_file.filename,
                "type": "folder" if new_file.is_folder else "file"
            })
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to copy {src_file.filename}: {str(e)}")

    return {"copied_files": copied_files}

@router.post("/move")
def move_files(
    request: CopyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    dest_folder = None
    if request.destination_folder_id and request.destination_folder_id != 0:
        dest_folder = db.query(models.FileModel).filter(
            models.FileModel.id == request.destination_folder_id,
            models.FileModel.is_folder == True
        ).first()
        if not dest_folder:
            raise HTTPException(404, "Destination folder not found")


    moved_files = []

    for file_id in request.file_ids:
        src_file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
        if not src_file:
            continue

        src_path = utils.UPLOAD_DIR / src_file.filename
        if dest_folder:
            dest_path = utils.get_folder_full_path(dest_folder) / src_file.filename
        else:
            dest_path = utils.UPLOAD_DIR / src_file.filename


        if not src_path.exists():
            raise HTTPException(404, f"Source '{src_file.filename}' not found on disk")

        try:
            os.makedirs(dest_path.parent, exist_ok=True)

            if src_file.is_folder and dest_path.resolve().is_relative_to(src_path.resolve()):
                raise HTTPException(400, "Cannot move a folder into its own subfolder")

            existing_files = {f.name for f in os.scandir(dest_path.parent)}
            if dest_path.name in existing_files:
                base, ext = os.path.splitext(dest_path.name)
                counter = 1
                while f"{base}_copy{counter}{ext}" in existing_files:
                    counter += 1
                dest_path = dest_path.parent / f"{base}_copy{counter}{ext}"

            shutil.move(str(src_path), str(dest_path))

            src_file.parent_id = dest_folder.id if dest_folder else None
            src_file.filename = os.path.relpath(dest_path, utils.UPLOAD_DIR)
            db.commit()

            utils.append_log(src_file.id, f"{current_user.username} moved '{src_file.original_name}'")

            moved_files.append({
                "id": src_file.id,
                "name": src_file.original_name,
                "type": "folder" if src_file.is_folder else "file"
            })

        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to move '{src_file.filename}': {str(e)}")

    return {"moved_files": moved_files}

@router.put("/rename")
def rename_file_or_folder(file_id: int, new_name: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)):
    file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File/folder not found")

    old_path = os.path.join(UPLOAD_DIR, file.filename)
    new_path = os.path.join(UPLOAD_DIR, new_name)

    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail=f"File not found: {old_path}")

    try:
        os.rename(old_path, new_path)
        old_name = file.original_name
        file.original_name = new_name
        db.commit()
        utils.append_log(file.id,f"{current_user.username} Renamed file '{old_name}' with '{new_name}'")
        db.refresh(file)
        return {"message": f"Renamed '{old_name}' to '{new_name}'"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.put("/star")
def star_file_or_folder(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()

    if not file:
        raise HTTPException(status_code=404, detail="File/folder not found")

    try:
        file.is_star = not file.is_star

        db.add(file)
        db.commit()
        db.refresh(file)

        utils.append_log(file.id, f"{current_user.username} toggled star for '{file.filename}'")
        return {
            "id": file.id,
            "is_star": file.is_star,
            "filename": file.filename,
            "message": f"File {'starred' if file.is_star else 'unstarred'} successfully"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
