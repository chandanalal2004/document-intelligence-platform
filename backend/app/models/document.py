"""
ORM model for a processed document. We store the full structured result
(as JSON text) alongside a few indexed columns used by the dashboard/list
and by GET-by-name lookups.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id = Column(String, primary_key=True, default=_uuid)
    document_name = Column(String, index=True, nullable=False)
    document_type = Column(String, nullable=False)
    processing_status = Column(String, nullable=False)  # PASS | FAILED
    overall_validation_status = Column(String, nullable=True)  # PASS | FAIL | NOT_APPLICABLE
    page_count = Column(Integer, nullable=True)
    ocr_used = Column(Integer, default=0)  # 0/1 boolean (portable across DBs)
    result_json = Column(Text, nullable=False)  # full structured response, JSON-encoded
    processing_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
