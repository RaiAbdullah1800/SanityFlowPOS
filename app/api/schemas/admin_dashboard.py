from pydantic import BaseModel
from datetime import date
from typing import Optional

class RevenueByDateResponse(BaseModel):
    date: date
    total_revenue: float
    
    class Config:
        from_attributes = True

class TotalRevenueResponse(BaseModel):
    total_revenue: float
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    
    class Config:
        from_attributes = True

class SalesByCategoryResponse(BaseModel):
    category_name: str
    total_quantity: int
    total_revenue: float
    
    class Config:
        from_attributes = True

class PaymentMethodBreakdownResponse(BaseModel):
    payment_method: str
    transaction_count: int
    total_amount: float
    
    class Config:
        from_attributes = True

class LowStockItemResponse(BaseModel):
    item_name: str
    size_label: str
    current_stock: int
    
    class Config:
        from_attributes = True

class InventoryMovementResponse(BaseModel):
    item_name: str
    change_type: str  # 'sale', 'restock', 'correction'
    total_change: int
    
    class Config:
        from_attributes = True

class BestSellingItemResponse(BaseModel):
    item_name: str
    total_sold: int
    
    class Config:
        from_attributes = True

class StaffPerformanceResponse(BaseModel):
    staff_name: str
    transaction_count: int
    total_revenue: float
    
    class Config:
        from_attributes = True
