from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.db.db import get_db
from app.db.models import Order, OrderItem, User
from app.core.security import validate_cashier

router = APIRouter(prefix="/cashier/dashboard", tags=["Cashier Dashboard"])

class DailySummaryResponse(BaseModel):
    total_sales_amount: float
    average_transaction_value: float
    items_sold_count: int

class DailySalesTrendItem(BaseModel):
    date: str
    total_sales: float
    transaction_count: int
    items_sold: int

class DailySalesTrendResponse(BaseModel):
    data: List[DailySalesTrendItem]

@router.get("/daily-summary", response_model=DailySummaryResponse)
def get_daily_summary(
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Get daily summary for the current day:
    - Total sales amount
    - Average transaction value
    - Items sold count
    """
    # Get today's date
    today = datetime.now().date()
    
    # Get orders for today
    today_orders = db.query(Order).filter(
        func.date(Order.date) == today
    ).all()
    
    # Calculate metrics
    total_sales_amount = sum(order.amount for order in today_orders)
    transaction_count = len(today_orders)
    average_transaction_value = total_sales_amount / transaction_count if transaction_count > 0 else 0
    
    # Calculate items sold count
    items_sold_count = 0
    for order in today_orders:
        items_sold_count += sum(item.quantity for item in order.items)
    
    return DailySummaryResponse(
        total_sales_amount=total_sales_amount,
        average_transaction_value=average_transaction_value,
        items_sold_count=items_sold_count
    )

@router.get("/daily-sales-trend", response_model=DailySalesTrendResponse)
def get_daily_sales_trend(
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Get daily sales trend for the last 7 days
    """
    # Get today's date and 6 days before (7 days total)
    today = datetime.now().date()
    start_date = today - timedelta(days=6)
    
    # Query to get sales data grouped by day for the last 7 days
    sales_data = db.query(
        func.date(Order.date).label('order_date'),
        func.sum(Order.amount).label('total_sales'),
        func.count(Order.id).label('transaction_count')
    ).filter(
        func.date(Order.date) >= start_date,
        func.date(Order.date) <= today
    ).group_by(
        func.date(Order.date)
    ).order_by(
        func.date(Order.date)
    ).all()
    
    # Get items sold count for each day
    items_sold_data = {}
    for i in range(7):
        day_date = start_date + timedelta(days=i)
        day_orders = db.query(Order).options(joinedload(Order.items)).filter(
            func.date(Order.date) == day_date
        ).all()
        
        items_count = 0
        for order in day_orders:
            items_count += sum(item.quantity for item in order.items)
        
        items_sold_data[day_date] = items_count
    
    # Format response
    trend_data = []
    for i in range(7):
        day_date = start_date + timedelta(days=i)
        day_str = day_date.strftime('%Y-%m-%d')
        
        # Find data for this day
        day_sales = next((data for data in sales_data if data.order_date == day_date), None)
        
        trend_data.append(DailySalesTrendItem(
            date=day_str,
            total_sales=float(day_sales.total_sales) if day_sales else 0.0,
            transaction_count=day_sales.transaction_count if day_sales else 0,
            items_sold=items_sold_data.get(day_date, 0)
        ))
    
    return DailySalesTrendResponse(data=trend_data)
