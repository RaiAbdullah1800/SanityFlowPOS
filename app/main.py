# app/main.py
from fastapi import FastAPI
from app.db.db import engine
from app.db import models
from app.api.routes import auth, admin


# Create tables
models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="SanityFlow POS", version="1.0.0")

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)

@app.get("/")
def root():
    return {"message": "FastAPI with MySQL is live!"}
