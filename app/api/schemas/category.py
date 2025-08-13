from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional

class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    discount: float | None = Field(
        None,
        ge=0,
        le=100,
        description="Optional percentage discount (0-100) applied to all items in this category"
    )

class CategoryCreate(CategoryBase):
    pass

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    discount: Optional[float] = Field(None, ge=0, le=100)

class CategoryInDB(CategoryBase):
    id: str
    created_at: datetime

    class Config:
        orm_mode = True

class CategoryResponse(CategoryInDB):
    pass

class CategoryWithItems(CategoryInDB):
    items: List[dict] = []

    class Config:
        orm_mode = True
