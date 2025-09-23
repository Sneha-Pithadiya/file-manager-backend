from fastapi import FastAPI
from app.database import engine, Base
from app.auth import routes as auth_routes
from app.users import routes as user_routes
from app.files import routes as file_routes

Base.metadata.create_all(bind=engine)

app = FastAPI(title="File Manager - Backend (User module)")

app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(user_routes.router, prefix="/users", tags=["users"])
app.include_router(file_routes.router, prefix="/files", tags=["files"])


@app.get("/", tags=["root"])
def root():
    return {"message": "File Manager backend — user module active"}
