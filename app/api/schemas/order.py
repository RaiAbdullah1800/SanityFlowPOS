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
    category_name: str

    class Config:
        orm_mode = True

class ShopperInfo(BaseModel):
    """Basic shopper information for order responses"""
    id: str
    customer_code: str
    name: str
    phone_number: Optional[str] = None
    address: Optional[str] = None

    class Config:
        orm_mode = True

class BalanceSummary(BaseModel):
    """Summary of customer's balances"""
    dues_balance: float = 0.0
    advance_balance: float = 0.0

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
    shopper: Optional[ShopperInfo] = None
    balance_summary: Optional[BalanceSummary] = None

class PaginatedSalesResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    skip: int
    limit: int
