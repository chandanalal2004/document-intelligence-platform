"""
Pydantic schemas for request bodies and dashboard list responses.
(The full processing-result schema lives in schemas/extraction.py.)
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"


class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_validation_status: Optional[str] = None
    processed_at: str

    class Config:
        from_attributes = True


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
