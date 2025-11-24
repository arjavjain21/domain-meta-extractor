from sqlalchemy import Column, Integer, Date, DateTime, Numeric, func
from datetime import datetime

from app.core.database import Base


class ExtractionStats(Base):
    __tablename__ = "extraction_stats"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    total_requests = Column(Integer, default=0)
    successful_extractions = Column(Integer, default=0)
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    average_extraction_time = Column(Numeric(5, 2))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        """Convert stats object to dictionary"""
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "totalRequests": self.total_requests,
            "successfulExtractions": self.successful_extractions,
            "cacheHits": self.cache_hits,
            "cacheMisses": self.cache_misses,
            "averageExtractionTime": float(self.average_extraction_time) if self.average_extraction_time else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None
        }