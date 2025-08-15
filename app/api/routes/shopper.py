from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db import models
from app.api.schemas import shopper as shopper_schemas
from app.db.db import get_db
from sqlalchemy import func

router = APIRouter()

@router.post("/", response_model=shopper_schemas.ShopperResponse, status_code=status.HTTP_201_CREATED)
def create_shopper(shopper: shopper_schemas.ShopperCreate, db: Session = Depends(get_db)):
    db_shopper = db.query(models.Shopper).filter(models.Shopper.customer_code == shopper.customer_code).first()
    if db_shopper:
        raise HTTPException(status_code=400, detail="Shopper with this customer code already exists")
    
    new_shopper = models.Shopper(**shopper.dict())
    db.add(new_shopper)
    db.commit()
    db.refresh(new_shopper)
    return new_shopper

@router.get("/", response_model=List[shopper_schemas.ShopperResponse])
def get_all_shoppers(db: Session = Depends(get_db)):
    shoppers = db.query(models.Shopper).all()
    return shoppers

@router.get("/{customer_code}", response_model=shopper_schemas.ShopperResponse)
def get_shopper_by_code(customer_code: str, db: Session = Depends(get_db)):
    db_shopper = db.query(models.Shopper).filter(models.Shopper.customer_code == customer_code).first()
    if not db_shopper:
        raise HTTPException(status_code=404, detail="Shopper not found")
    return db_shopper

@router.post("/{customer_code}/transactions", response_model=shopper_schemas.DueResponse, status_code=status.HTTP_201_CREATED)
def add_due_or_payment(customer_code: str, due: shopper_schemas.DueBase, db: Session = Depends(get_db)):
    db_shopper = db.query(models.Shopper).filter(models.Shopper.customer_code == customer_code).first()
    if not db_shopper:
        raise HTTPException(status_code=404, detail="Shopper not found")

    new_due = models.Due(
        **due.dict(),
        shopper_id=db_shopper.id
    )
    db.add(new_due)
    db.commit()
    db.refresh(new_due)
    return new_due
