from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class Status(str, Enum):
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class CreditRequest(BaseModel):
    user_id: str
    amount: float = Field(gt=0)

class User(BaseModel):
    user_id: str
    status: Status = Status.PROCESSING
    created_at: Optional[float] = None
    balance: float = 0.0


class Credit(BaseModel):
    id: str = Field(validation_alias="_id") 
    user_id: str
    amount: float
    status: Status = Status.PROCESSING
    created_at: Optional[float] = None