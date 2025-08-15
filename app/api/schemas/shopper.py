from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Base schema for Due
class DueBase(BaseModel):
    amount: float
    description: Optional[str] = None

# Schema for creating a new due
class DueCreate(DueBase):
    shopper_id: str
    order_id: Optional[str] = None

# Schema for returning due information
class DueResponse(DueBase):
    id: str
    shopper_id: str
    order_id: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True

# Base schema for Shopper
class ShopperBase(BaseModel):
    customer_code: str
    name: str
    phone_number: Optional[str] = None
    address: Optional[str] = None

# Schema for creating a new shopper
class ShopperCreate(ShopperBase):
    pass

# Schema for returning shopper information
class ShopperResponse(ShopperBase):
    id: str
    created_at: datetime
    dues: List[DueResponse] = []

    class Config:
        orm_mode = True
