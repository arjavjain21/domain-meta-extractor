from sqlalchemy import Column, Integer, String, Text, DateTime, Numeric, Boolean, func, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta
import uuid

from app.core.database import Base


class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    normalized_domain = Column(String(255), unique=True, nullable=False, index=True)
    meta_title = Column(String(500))
    meta_description = Column(Text)
    extraction_method = Column(String(50))
    status_code = Column(Integer)
    extraction_time = Column(Numeric(5, 2))
    error_message = Column(Text)
    last_extracted = Column(DateTime(timezone=True))
    cache_expires = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    extraction_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)

    # Relationships
    job_domains = relationship("JobDomain", back_populates="domain")

    # Indexes for performance
    __table_args__ = (
        Index('idx_domains_normalized_domain', 'normalized_domain'),
        Index('idx_domains_cache_expires', 'cache_expires'),
        Index('idx_domains_last_extracted', 'last_extracted'),
    )

    def is_expired(self) -> bool:
        """Check if cached data is expired (30 days)"""
        if not self.cache_expires:
            return True
        return datetime.utcnow() > self.cache_expires

    def is_cache_valid(self) -> bool:
        """Check if cached data is still valid"""
        if not self.last_extracted or not self.meta_title:
            return False
        return not self.is_expired()

    def refresh_cache_expiry(self) -> None:
        """Refresh cache expiry to 30 days from now"""
        self.cache_expires = datetime.utcnow() + timedelta(days=30)

    def to_dict(self) -> dict:
        """Convert domain object to dictionary"""
        return {
            "id": self.id,
            "domain": self.domain,
            "normalized_domain": self.normalized_domain,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "extraction_method": self.extraction_method,
            "status_code": self.status_code,
            "extraction_time": float(self.extraction_time) if self.extraction_time else None,
            "error_message": self.error_message,
            "last_extracted": self.last_extracted.isoformat() if self.last_extracted else None,
            "cache_expires": self.cache_expires.isoformat() if self.cache_expires else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "extraction_count": self.extraction_count,
            "success_count": self.success_count,
            "from_cache": self.is_cache_valid()
        }