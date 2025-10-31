from fastapi import FastAPI
from app.database import SessionLocal, engine, Base
from app.auth import routes as auth_routes
from app.users import routes as user_routes
from app.files import routes as file_routes
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="File Manager - Backend (User module)")
origins = [
    "http://localhost:5173",  
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)
@app.on_event("startup")
def startup_event():
    file_routes.start_watcher(SessionLocal)
    db = SessionLocal()
    file_routes.sync_uploads_with_db(db)
    db.close()

app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(user_routes.router, prefix="/users", tags=["users"])
app.include_router(file_routes.router, prefix="/files", tags=["files"])


@app.get("/", tags=["root"])
def root():
    return {"message": "File Manager backend — user module active"}
