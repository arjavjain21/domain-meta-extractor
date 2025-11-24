from sqlalchemy import Column, Integer, String, Text, DateTime, Numeric, ForeignKey, func, UUID, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import uuid

from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    status = Column(String(20), default='pending', index=True)  # pending, running, completed, failed
    total_domains = Column(Integer)
    processed_domains = Column(Integer, default=0)
    successful_domains = Column(Integer, default=0)
    failed_domains = Column(Integer, default=0)
    original_filename = Column(String(255))
    file_path = Column(String(500))
    result_file_path = Column(String(500))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(String(100))  # IP address or user identifier
    config = Column(JSONB)  # Processing configuration

    # Relationships
    job_domains = relationship("JobDomain", back_populates="job", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index('idx_jobs_status', 'status'),
        Index('idx_jobs_created_at', 'created_at'),
    )

    def start_job(self) -> None:
        """Mark job as started"""
        self.status = 'running'
        self.started_at = datetime.utcnow()

    def complete_job(self) -> None:
        """Mark job as completed"""
        self.status = 'completed'
        self.completed_at = datetime.utcnow()

    def fail_job(self, error_message: str) -> None:
        """Mark job as failed"""
        self.status = 'failed'
        self.completed_at = datetime.utcnow()
        self.error_message = error_message

    def update_progress(self, successful: int = 0, failed: int = 0) -> None:
        """Update job progress"""
        self.processed_domains += successful + failed
        self.successful_domains += successful
        self.failed_domains += failed

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage"""
        if self.total_domains == 0:
            return 0.0
        return (self.processed_domains / self.total_domains) * 100

    @property
    def estimated_time_remaining(self) -> float:
        """Estimate time remaining in seconds"""
        if self.status != 'running' or self.processed_domains == 0 or not self.started_at:
            return None

        elapsed_time = (datetime.utcnow() - self.started_at).total_seconds()
        avg_time_per_domain = elapsed_time / self.processed_domains
        remaining_domains = self.total_domains - self.processed_domains

        return avg_time_per_domain * remaining_domains

    def to_dict(self) -> dict:
        """Convert job object to dictionary"""
        return {
            "id": str(self.id),
            "status": self.status,
            "progress": {
                "total": self.total_domains,
                "processed": self.processed_domains,
                "successful": self.successful_domains,
                "failed": self.failed_domains,
                "percentage": round(self.progress_percentage, 2)
            },
            "original_filename": self.original_filename,
            "estimatedTimeRemaining": self.estimated_time_remaining,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "errorMessage": self.error_message,
            "config": self.config
        }


class JobDomain(Base):
    __tablename__ = "job_domains"

    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    original_row_index = Column(Integer)
    status = Column(String(20), default='pending', index=True)  # pending, processing, completed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    job = relationship("Job", back_populates="job_domains")
    domain = relationship("Domain", back_populates="job_domains")

    # Index for performance
    __table_args__ = (
        Index('idx_job_domains_status', 'status'),
    )