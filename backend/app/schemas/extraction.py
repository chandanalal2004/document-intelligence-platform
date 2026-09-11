"""
Pydantic schemas describing the mandatory structured JSON response
(see Case Study section 5.2). These are used both to validate what the
LLM extraction returns and to shape the final API response.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FileValidation(BaseModel):
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: Optional[int] = None
    status: str  # PASS | FAILED
    reason: Optional[str] = None  # populated when status == FAILED


class Evidence(BaseModel):
    source_text: Optional[str] = None
    page_number: Optional[int] = None


class ExtractedField(BaseModel):
    value: Any = None
    confidence: Optional[float] = None  # OPTIONAL
    page_number: Optional[int] = None
    evidence: Optional[Evidence] = None


class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ValidationCheck(BaseModel):
    name: str
    formula: str
    operands: Dict[str, Any] = Field(default_factory=dict)
    calculated_value: Optional[float] = None
    reported_value: Optional[float] = None
    variance: Optional[float] = None
    status: str  # PASS | FAIL | NOT_APPLICABLE
    period: Optional[str] = None  # which year/period this check applies to


class ValidationResult(BaseModel):
    checks: List[ValidationCheck] = Field(default_factory=list)
    overall_status: str = "NOT_APPLICABLE"  # PASS | FAIL | NOT_APPLICABLE
    issues: List[str] = Field(default_factory=list)


class ProcessingMetadata(BaseModel):
    ocr_used: bool = False
    processed_at: str
    processing_time_ms: int


class ProcessedDocumentResponse(BaseModel):
    document_name: str
    document_type: str
    processing_status: str  # PASS | FAILED
    overall_confidence: Optional[float] = None  # OPTIONAL
    file_validation: FileValidation
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult
    processing_metadata: ProcessingMetadata
