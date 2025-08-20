from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class OrderItemHistory(BaseModel):
    id: str
    item_name: str
    size_label: Optional[str] = None
    quantity: int
    price_at_purchase: float
    discount_applied: Optional[float] = None

    class Config:
        orm_mode = True


class OrderHistory(BaseModel):
    id: str
    transaction_id: str
    date: datetime
    amount: float
    details: Optional[str] = None
    items: List[OrderItemHistory] = []

    class Config:
        orm_mode = True


class DueHistory(BaseModel):
    id: str
    amount: float
    description: Optional[str] = None
    created_at: datetime
    order_id: Optional[str] = None

    class Config:
        orm_mode = True


class CustomerHistoryResponse(BaseModel):
    customer_code: str
    name: str
    phone_number: Optional[str] = None
    address: Optional[str] = None
    orders: List[OrderHistory] = []
    dues: List[DueHistory] = []
    total_due: float

    class Config:
        orm_mode = True
