from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class OrderItemCreate(BaseModel):
    item_id: str
    size_label: str
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    global_discount: Optional[float] = 0.0
    details: Optional[str] = None

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
    global_discount: float
    details: Optional[str]
    cashier_id: str
    items: List[OrderItemResponse]
    has_been_returned: Optional[bool] = False

class PaginatedSalesResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    skip: int
    limit: int
