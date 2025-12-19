from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from app import models, schemas
from app.database import get_db
from app.auth import utils

router = APIRouter()

# register
@router.post("/register", response_model=schemas.UserOut)
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = utils.get_user_by_username(db, user_in.username)
    if existing:
        raise HTTPException(400, "Username already registered")
        
    hashed = utils.get_password_hash(user_in.password)
    
    user = models.User(
        username=user_in.username,
        full_name=user_in.full_name,
        hashed_password=hashed
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# login
@router.post("/login", response_model=schemas.Token)
def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = utils.get_user_by_username(db, username)
    if not user or not utils.verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    access_token = utils.create_access_token(
        data={"sub": user.username, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout",response_model=schemas.Token)
def logout(user_in: schemas.UserOut, db: Session = Depends(get_db)):
    response = RedirectResponse(url="/auth/register")
    return response