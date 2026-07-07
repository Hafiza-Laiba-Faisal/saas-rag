"""Data models for table detection."""

from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import json

@dataclass
class BoundingBox:
    """Bounding box representation."""
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    
    @classmethod
    def from_list(cls, bbox_list: List[int]) -> 'BoundingBox':
        return cls(bbox_list[0], bbox_list[1], bbox_list[2], bbox_list[3])
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @property
    def width(self) -> int:
        return self.x_max - self.x_min
    
    @property
    def height(self) -> int:
        return self.y_max - self.y_min
    
    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class TableData:
    """Table data structure."""
    table_id: str
    bbox: BoundingBox
    html: str
    csv_rows: List[List[str]]
    page_number: Optional[int] = None
    confidence: float = 0.85
    quality_score: float = 1.0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.table_id,
            "bbox": self.bbox.to_dict(),
            "html": self.html,
            "rows": len(self.csv_rows),
            "columns": max((len(r) for r in self.csv_rows), default=0),
            "csv_preview": self.csv_rows[:2] if self.csv_rows else [],
            "page": self.page_number,
            "confidence": self.confidence,
            "quality": self.quality_score
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ExtractionResult:
    """Overall extraction result."""
    tables: List[TableData]
    total_detected: int
    processing_time_ms: float
    errors: List[str]
    
    def to_dict(self) -> Dict:
        return {
            "tables": [t.to_dict() for t in self.tables],
            "total": self.total_detected,
            "time_ms": self.processing_time_ms,
            "errors": self.errors
        }
