from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from fastapi import UploadFile
from typing import List, Optional
import uuid
import os
import aiofiles
import pandas as pd
from datetime import datetime

from app.models.job import Job, JobDomain
from app.models.domain import Domain
from app.schemas.job import JobCreate, JobConfig
from app.core.config import settings


class JobService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_job(
        self,
        file: UploadFile,
        max_domains: Optional[int] = None,
        concurrency: Optional[int] = None,
        created_by: Optional[str] = None
    ) -> Job:
        """Create a new job from uploaded file"""

        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        # Read and validate CSV
        try:
            df = pd.read_csv(file_path)
            if 'domain' not in df.columns.str.lower():
                # Clean up file on error
                os.remove(file_path)
                raise ValueError("CSV must contain a 'domain' column")

            # Normalize column names
            df.columns = df.columns.str.lower()
            domains = df['domain'].dropna().unique().tolist()

            # Apply limits
            if max_domains:
                domains = domains[:max_domains]
            if len(domains) > settings.MAX_DOMAINS_PER_FILE:
                domains = domains[:settings.MAX_DOMAINS_PER_FILE]

        except Exception as e:
            # Clean up file on error
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e

        # Create job record
        job_config = JobConfig(
            max_domains=max_domains,
            concurrency=concurrency or settings.DEFAULT_CONCURRENCY,
            timeout=30,
            max_retries=3
        )

        job = Job(
            original_filename=file.filename,
            file_path=file_path,
            total_domains=len(domains),
            config=job_config.dict(),
            created_by=created_by
        )

        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        return job

    async def get_job(self, job_id: uuid.UUID) -> Optional[Job]:
        """Get job by ID"""
        stmt = select(Job).where(Job.id == job_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_job(self, job: Job) -> Job:
        """Update job"""
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None
    ) -> List[Job]:
        """List jobs with optional filtering"""
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)

        if status:
            stmt = stmt.where(Job.status == status)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def delete_job(self, job_id: uuid.UUID) -> bool:
        """Delete a job"""
        # Get job first to clean up files
        job = await self.get_job(job_id)
        if not job:
            return False

        # Delete files
        if job.file_path and os.path.exists(job.file_path):
            os.remove(job.file_path)
        if job.result_file_path and os.path.exists(job.result_file_path):
            os.remove(job.result_file_path)

        # Delete job (cascade will handle job_domains)
        stmt = delete(Job).where(Job.id == job_id)
        await self.db.execute(stmt)
        await self.db.commit()

        return True