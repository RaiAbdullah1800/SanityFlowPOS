from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# Import existing schemas
from .order import OrderItemCreate, OrderItemResponse


class PaymentBreakdown(BaseModel):
    """Details of how a payment is allocated"""
    order_payment: float = Field(..., description="Amount paid toward current order")
    dues_payment: float = Field(..., description="Amount paid toward previous dues")
    advance_payment: float = Field(0.0, description="Amount paid as advance for future purchases")
    credit_used: float = Field(0.0, description="Amount of advance credit used for this order")
    remaining_dues: float = Field(..., description="Remaining dues balance after payment")
    remaining_order_balance: float = Field(..., description="Remaining order balance after payment")
    remaining_credit: float = Field(0.0, description="Remaining advance credit after this transaction")


class EnhancedOrderCreate(BaseModel):
    """Enhanced order creation with payment handling"""
    items: List[OrderItemCreate]
    details: Optional[str] = None
    customer_code: Optional[str] = None
    is_paid: bool = True
    payment_amount: Optional[float] = None
    payment_breakdown: Optional[PaymentBreakdown] = None


class CashierInfo(BaseModel):
    """Basic cashier information"""
    id: str
    username: str

    class Config:
        orm_mode = True


class ShopperInfo(BaseModel):
    """Basic shopper information"""
    id: str
    customer_code: str
    name: str
    phone_number: Optional[str] = None
    address: Optional[str] = None

    class Config:
        orm_mode = True


class EnhancedOrderResponse(BaseModel):
    """Enhanced order response with payment details"""
    id: str
    transaction_id: str
    date: datetime
    amount: float
    details: Optional[str]
    cashier_id: str
    shopper_id: Optional[str] = None
    items: List[OrderItemResponse]
    is_paid: bool
    payment_amount: Optional[float] = None
    payment_breakdown: Optional[PaymentBreakdown] = None
    remaining_dues: Optional[float] = None
    remaining_order_balance: Optional[float] = None
    cashier: Optional[CashierInfo] = None
    shopper: Optional[ShopperInfo] = None

    class Config:
        orm_mode = True
