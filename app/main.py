# app/main.py
from fastapi import FastAPI
from app.db.db import engine
from app.db import models
from app.api.routes import auth


# Create tables
models.Base.metadata.create_all(bind=engine)
app = FastAPI()
app.include_router(auth.router)

@app.get("/")
def root():
    return {"message": "FastAPI with MySQL is live!"}
