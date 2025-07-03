from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.db import engine
from app.db import models
from app.api.routes import auth, admin

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SanityFlow POS", version="1.0.0")

# 🚨 Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 👈 Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)

@app.get("/")
def root():
    return {"message": "FastAPI with MySQL is live!"}
