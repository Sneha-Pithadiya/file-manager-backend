from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from app import models, schemas
from app.database import get_db
from app.auth import utils

router = APIRouter()


@router.post("/register", response_model=schemas.UserOut, summary="Register a new user")
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = utils.get_user_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")
    hashed = utils.get_password_hash(user_in.password)
    user = models.User(username=user_in.username, full_name=user_in.full_name, hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token, summary="Login to get access token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = utils.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = utils.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}
