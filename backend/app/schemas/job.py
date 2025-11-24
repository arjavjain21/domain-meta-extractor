from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class JobConfig(BaseModel):
    max_domains: Optional[int] = None
    concurrency: Optional[int] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None


class JobCreate(BaseModel):
    original_filename: str
    file_path: str
    total_domains: int
    config: Optional[JobConfig] = None
    created_by: Optional[str] = None


class JobProgress(BaseModel):
    total: int
    processed: int
    successful: int
    failed: int
    percentage: float = Field(..., ge=0, le=100)


class JobResponse(BaseModel):
    id: str
    status: str
    progress: JobProgress
    original_filename: Optional[str] = None
    estimatedTimeRemaining: Optional[float] = None
    createdAt: Optional[str] = None
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None
    errorMessage: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

    @classmethod
    def from_job(cls, job) -> "JobResponse":
        return cls(
            id=str(job.id),
            status=job.status,
            progress=JobProgress(
                total=job.total_domains or 0,
                processed=job.processed_domains,
                successful=job.successful_domains,
                failed=job.failed_domains,
                percentage=round(job.progress_percentage, 2)
            ),
            original_filename=job.original_filename,
            estimatedTimeRemaining=job.estimated_time_remaining,
            createdAt=job.created_at.isoformat() if job.created_at else None,
            startedAt=job.started_at.isoformat() if job.started_at else None,
            completedAt=job.completed_at.isoformat() if job.completed_at else None,
            errorMessage=job.error_message,
            config=job.config
        )


class JobStatus(BaseModel):
    id: str
    status: str
    progress: JobProgress