from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class OrderItemCreate(BaseModel):
    item_id: str
    size_label: str
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    details: Optional[str] = None
    customer_code: Optional[str] = None
    is_paid: bool = True

class OrderItemResponse(BaseModel):
    id: str
    item_id: str
    item_name: str
    size_label: str
    quantity: int
    price_at_purchase: float
    discount_applied: Optional[float] = None

class OrderResponse(BaseModel):
    id: str
    transaction_id: str
    date: datetime
    amount: float
    details: Optional[str]
    cashier_id: str
    shopper_id: Optional[str] = None
    items: List[OrderItemResponse]
    has_been_returned: Optional[bool] = False

class PaginatedSalesResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    skip: int
    limit: int
