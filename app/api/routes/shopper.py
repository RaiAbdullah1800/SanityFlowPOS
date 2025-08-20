from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db import models
from app.api.schemas import shopper as shopper_schemas
from app.api.schemas import customer_history as history_schemas
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


@router.get("/{customer_code}/history", response_model=history_schemas.CustomerHistoryResponse)
def get_customer_history(customer_code: str, db: Session = Depends(get_db)):
    db_shopper = db.query(models.Shopper).filter(models.Shopper.customer_code == customer_code).first()
    if not db_shopper:
        raise HTTPException(status_code=404, detail="Shopper not found")

    # Get all orders for this shopper
    orders = db.query(models.Order).filter(models.Order.shopper_id == db_shopper.id).all()
    
    # Get all dues for this shopper
    dues = db.query(models.Due).filter(models.Due.shopper_id == db_shopper.id).all()
    
    # Calculate total due (sum of all dues)
    total_due = sum(due.amount for due in dues)
    
    # Format orders with items
    formatted_orders = []
    for order in orders:
        order_items = []
        for item in order.items:
            order_items.append(history_schemas.OrderItemHistory(
                id=item.id,
                item_name=item.item.name if item.item else "Unknown Item",
                size_label=item.size_label,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
                discount_applied=item.discount_applied
            ))
        
        formatted_orders.append(history_schemas.OrderHistory(
            id=order.id,
            transaction_id=order.transaction_id,
            date=order.date,
            amount=order.amount,
            details=order.details,
            items=order_items
        ))
    
    # Format dues
    formatted_dues = [
        history_schemas.DueHistory(
            id=due.id,
            amount=due.amount,
            description=due.description,
            created_at=due.created_at,
            order_id=due.order_id
        )
        for due in dues
    ]
    
    return history_schemas.CustomerHistoryResponse(
        customer_code=db_shopper.customer_code,
        name=db_shopper.name,
        phone_number=db_shopper.phone_number,
        address=db_shopper.address,
        orders=formatted_orders,
        dues=formatted_dues,
        total_due=total_due
    )
