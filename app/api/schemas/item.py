from pydantic import BaseModel, HttpUrl, conint, validator, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

class ItemSizeBase(BaseModel):
    size_label: str = Field(..., min_length=1, max_length=20)
    price: float = Field(..., gt=0)
    discount: Optional[float] = Field(None, ge=0, le=100, description="Local discount percentage (0-100)")
    stock: conint(ge=0) = 0

class ItemSizeCreate(ItemSizeBase):
    pass

class ItemSizeUpdate(ItemSizeBase):
    id: Optional[str] = None 
    size_label: Optional[str] = Field(None, min_length=1, max_length=20)
    price: Optional[float] = Field(None, gt=0)
    discount: Optional[float] = Field(None, ge=0, le=100, description="Local discount percentage (0-100)")
    stock: Optional[conint(ge=0)] = None
    correction_reason: Optional[str] = None

    @validator('correction_reason')
    def validate_correction_reason(cls, v, values):
        if 'stock' in values and values['stock'] is not None and not v:
            raise ValueError('correction_reason is required when updating stock')
        return v

class ItemSizeResponse(ItemSizeBase):
    id: str
    item_id: str
    created_at: datetime

    class Config:
        orm_mode = True

class ItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category_id: Optional[str] = Field(None, min_length=36, max_length=36)

class ItemCreate(ItemBase):
    sizes: List[ItemSizeCreate] = Field(..., min_items=1)

    class Config:
        json_encoders = {
            List[ItemSizeCreate]: lambda v: [size.dict() for size in v]
        }

class ItemUpdate(ItemBase):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category_id: Optional[str] = Field(None, min_length=36, max_length=36)
    sizes: List[ItemSizeUpdate] = Field(default_factory=list)
    sizes_to_delete: List[str] = Field(default_factory=list)

class ItemResponse(ItemBase):
    id: str
    image_url: Optional[str]
    created_at: datetime
    sizes: List[ItemSizeResponse]
    category: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True
        json_encoders = {
            'datetime': lambda v: v.isoformat() if v else None
        }

    @classmethod
    def from_orm(cls, obj):
        # Custom from_orm to handle the category relationship
        item_dict = super().from_orm(obj).dict()
        if hasattr(obj, 'category_obj') and obj.category_obj:
            item_dict['category'] = {
                'id': obj.category_obj.id,
                'name': obj.category_obj.name,
                'discount': getattr(obj.category_obj, 'discount', None)
            }
        return cls(**item_dict)

class ItemListResponse(BaseModel):
    id: str
    name: str
    image_url: Optional[str] = None
    category: Optional[Dict[str, Any]] = None
    sizes: List[Dict[str, Any]]

    class Config:
        orm_mode = True
        json_encoders = {
            'datetime': lambda v: v.isoformat() if v else None
        }

class NewItemListResponse(BaseModel):
    id: str
    name: str
    category: Optional[Dict[str, Any]] = None
    sizes: List[Dict[str, Any]]

class RestockRequest(BaseModel):
    item_id: str
    size_label: str
    quantity: conint(gt=0)
    description: Optional[str]

class DateRangeFilter(BaseModel):
    start_date: Optional[datetime]
    end_date: Optional[datetime]
