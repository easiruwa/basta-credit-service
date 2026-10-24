from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class Status(StrEnum):
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class CreditRequest(BaseModel):
    user_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(...)
    amount: float = Field(gt=0)


class User(BaseModel):
    user_id: str
    status: Status = Status.PROCESSING
    created_at: float | None = None
    balance: float = 0.0


class Credit(BaseModel):
    id: str = Field(validation_alias="_id")
    user_id: str
    amount: float
    status: Status = Status.PROCESSING
    created_at: float | None = None


class CreditAccepted(BaseModel):
    task_id: str
    credit_id: str
    status: Status
