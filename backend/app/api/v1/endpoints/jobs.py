from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import uuid

from app.core.database import get_db
from app.schemas.job import JobCreate, JobResponse, JobStatus
from app.services.job_service import JobService
from app.services.extraction_service import ExtractionService

router = APIRouter()


@router.post("/upload", response_model=JobResponse)
async def upload_file(
    file: UploadFile = File(...),
    max_domains: Optional[int] = None,
    concurrency: Optional[int] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Upload CSV file for processing"""
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    job_service = JobService(db)
    extraction_service = ExtractionService(db)

    # Create job
    job = await job_service.create_job(
        file=file,
        max_domains=max_domains,
        concurrency=concurrency
    )

    # Start processing in background
    background_tasks.add_task(
        extraction_service.process_file,
        job_id=job.id
    )

    return JobResponse.from_job(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get job status and details"""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job_service = JobService(db)
    job = await job_service.get_job(job_uuid)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.from_job(job)


@router.get("/")
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List user jobs"""
    job_service = JobService(db)
    jobs = await job_service.list_jobs(limit=limit, offset=offset, status=status)

    return [JobResponse.from_job(job) for job in jobs]


@router.get("/{job_id}/download")
async def download_results(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Download processed results as CSV"""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job_service = JobService(db)
    job = await job_service.get_job(job_uuid)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != 'completed':
        raise HTTPException(status_code=400, detail="Job is not completed")

    if not job.result_file_path:
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(
        job.result_file_path,
        media_type='text/csv',
        filename=f"results_{job.original_filename}"
    )


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Cancel/delete a job"""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job_service = JobService(db)
    success = await job_service.delete_job(job_uuid)

    if not success:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"message": "Job deleted successfully"}