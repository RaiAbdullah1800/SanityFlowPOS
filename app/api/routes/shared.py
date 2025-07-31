from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.db.db import get_db
from app.db.models import Order, OrderItem
from app.api.schemas.order import OrderResponse
from app.core.security import validate_admin_or_cashier

router = APIRouter(prefix="/shared_role", tags=["Shared Admin-Cashier"])

@router.get("/sales", response_model=List[OrderResponse])
def get_sales_list(
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin_or_cashier)
):
    """
    Retrieve all sales (orders) without pagination
    Accessible to both admin and cashier roles
    """
    orders = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.item)
    ).all()
    
    response_items = []
    for order in orders:
        order_data = {
            "id": order.id,
            "transaction_id": order.transaction_id,
            "date": order.date,
            "amount": order.amount,
            "global_discount": order.global_discount,
            "details": order.details,
            "cashier_id": order.cashier_id,
            "items": []
        }
        for item in order.items:
            item_data = {
                "id": item.id,
                "item_id": item.item_id,
                "item_name": item.item.name,
                "size_label": item.size_label,
                "quantity": item.quantity,
                "price_at_purchase": item.price_at_purchase,
                "discount_applied": item.discount_applied
            }
            order_data["items"].append(item_data)
        response_items.append(OrderResponse(**order_data))
    
    return response_items
