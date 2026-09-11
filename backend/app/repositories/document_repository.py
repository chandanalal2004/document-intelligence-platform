"""
Data-access layer for ProcessedDocument. Keeps SQLAlchemy queries out of
the service/business-logic layer.
"""
import json
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.document import ProcessedDocument


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_result(
        self,
        *,
        document_name: str,
        document_type: str,
        processing_status: str,
        overall_validation_status: Optional[str],
        page_count: Optional[int],
        ocr_used: bool,
        result: dict,
        processing_time_ms: Optional[int],
    ) -> ProcessedDocument:
        record = ProcessedDocument(
            document_name=document_name,
            document_type=document_type,
            processing_status=processing_status,
            overall_validation_status=overall_validation_status,
            page_count=page_count,
            ocr_used=1 if ocr_used else 0,
            result_json=json.dumps(result),
            processing_time_ms=processing_time_ms,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_latest_by_name(self, document_name: str) -> Optional[ProcessedDocument]:
        return (
            self.db.query(ProcessedDocument)
            .filter(ProcessedDocument.document_name == document_name)
            .order_by(desc(ProcessedDocument.created_at))
            .first()
        )

    def list_all(self, limit: int = 200) -> List[ProcessedDocument]:
        return (
            self.db.query(ProcessedDocument)
            .order_by(desc(ProcessedDocument.created_at))
            .limit(limit)
            .all()
        )
