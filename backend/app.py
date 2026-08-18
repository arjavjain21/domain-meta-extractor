#!/usr/bin/env python3
"""
Domain Meta Extractor - Unified Enterprise Application
A single, cohesive system combining all features from fragmented versions
"""

import os
import re
import csv
import uuid
import asyncio
import logging
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import hashlib

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Numeric, ForeignKey, select, func, and_, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import aiofiles
import aiohttp
from bs4 import BeautifulSoup
import extruct
import tldextract
import numpy as np
from pydantic import BaseModel, validator
import redis.asyncio as redis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://domain_user:temp12345@localhost:5432/domain_extractor")
async_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Redis setup
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = None

# Shared HTTP session (pooled connections: one TLS handshake per host instead of per request)
http_session: aiohttp.ClientSession = None

# Realistic browser headers (UA-only gets lazy-bot-checked on some sites)
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}

# Usage counters (best-effort; never break a request over analytics)
async def bump_stat(*parts):
    try:
        r = await get_redis()
        key = "stats:metadata_api:" + datetime.utcnow().strftime("%Y%m%d") + ":" + ":".join(parts)
        await r.incr(key)
        await r.expire(key, 86400 * 90)  # 90-day retention
    except Exception:
        pass

# Templates setup
templates = Jinja2Templates(directory="templates")

# ==============
# MODELS
# ==============

class Job(Base):
    __tablename__ = "jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(20), default="pending")
    total_domains = Column(Integer)
    processed_domains = Column(Integer, default=0)
    successful_domains = Column(Integer, default=0)
    failed_domains = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    domain_column = Column(String(100))
    original_filename = Column(String(255))
    error_message = Column(Text)

class Domain(Base):
    __tablename__ = "domains"
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    normalized_domain = Column(String(255), unique=False, nullable=True)
    meta_title = Column(Text)
    meta_description = Column(Text)
    meta_keywords = Column(Text)
    h1_tag = Column(Text)
    first_paragraph = Column(Text)
    status_code = Column(Integer)
    extraction_method = Column(String(50))
    extraction_time = Column(Numeric(8, 2))
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_extracted = Column(DateTime, default=datetime.utcnow)
    cache_expires = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))
    status = Column(String(20), default="pending")
    extraction_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)

class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    content_type = Column(String(100))
    status = Column(String(20), default="uploaded")
    domain_column = Column(String(100))
    total_domains = Column(Integer)
    total_rows = Column(Integer)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ==============
# PYDANTIC MODELS
# ==============

class FileUploadResponse(BaseModel):
    success: bool
    file_id: str
    message: str
    total_domains: Optional[int] = None
    total_rows: Optional[int] = None
    job_id: Optional[str] = None

class DomainValidation(BaseModel):
    domain: str

    @validator('domain')
    def validate_domain(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Domain cannot be empty')
        return v.strip()

class ProcessRequest(BaseModel):
    job_id: str
    domains: List[DomainValidation]

# ==============
# FASTAPI APP
# ==============

app = FastAPI(
    title="Domain Meta Extractor - Enterprise",
    description="Professional domain metadata extraction with intelligent caching",
    version="4.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============
# UTILITIES
# ==============

def normalize_domain(domain: str) -> str:
    """
    Normalize domain name to lowercase without protocol or www

    Handles:
    - https://example.com → example.com
    - http://www.example.com → example.com
    - https://example.com/path → example.com
    - www.example.com → example.com
    - example.com/ → example.com
    - example.com:8080 → example.com
    """
    try:
        from urllib.parse import urlparse

        # Strip whitespace
        domain = domain.strip()

        # If it looks like a URL, parse it properly
        if '://' in domain or '/' in domain:
            parsed = urlparse(domain if '://' in domain else f'http://{domain}')
            domain = parsed.netloc or parsed.path
        else:
            # Remove any path after first slash
            domain = domain.split('/')[0]

        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]

        # Convert to lowercase
        domain = domain.lower()

        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove trailing slash
        domain = domain.rstrip('/')

        return domain

    except Exception:
        # If parsing fails, do basic cleanup
        domain = domain.strip().lower()
        domain = domain.split('://')[-1]  # Remove protocol
        domain = domain.split('/')[0]  # Remove path
        if domain.startswith('www.'):
            domain = domain[4:]
        domain = domain.rstrip('/')
        return domain

def is_valid_domain(domain: str) -> bool:
    """Check if domain is valid"""
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    return bool(re.match(pattern, domain))

async def get_redis():
    """Get Redis connection"""
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(REDIS_URL)
    return redis_client

async def get_http_session() -> aiohttp.ClientSession:
    """Get shared pooled HTTP session (created lazily, reused across requests)"""
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=BROWSER_HEADERS,
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=10, ttl_dns_cache=300),
        )
    return http_session

async def get_db():
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# ==============
# SERVICES
# ==============

async def _fetch_and_parse(url: str, timeout: aiohttp.ClientTimeout, verify_ssl: bool = True):
    """Fetch URL and parse metadata. Returns (data, status_code): data is a parsed
    dict on HTTP 200, else None. Raises on connection/timeout errors (caller falls back)."""
    session = await get_http_session()
    async with session.get(url, timeout=timeout, allow_redirects=True, ssl=verify_ssl) as response:
        status_code = response.status
        if status_code != 200:
            return None, status_code
        html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')

        data = {
            "status_code": status_code,
            "meta_title": soup.title.string.strip() if soup.title and soup.title.string else None,
            "meta_description": None,
            "meta_keywords": None,
            "h1_tag": None,
            "first_paragraph": None
        }

        desc_meta = soup.find('meta', attrs={'name': 'description'})
        if desc_meta:
            data["meta_description"] = desc_meta.get('content', '').strip()

        keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta:
            data["meta_keywords"] = keywords_meta.get('content', '').strip()

        h1_tag = soup.find('h1')
        if h1_tag:
            data["h1_tag"] = h1_tag.get_text().strip()

        p_tag = soup.find('p')
        if p_tag:
            data["first_paragraph"] = p_tag.get_text().strip()[:200]

        return data, status_code

def _last_error_text(pending_error: Optional[str]) -> str:
    return pending_error or "All extraction methods failed"

NEGATIVE_TTL = 86400  # 24h negative cache

async def extract_metadata(domain: str) -> Dict[str, Any]:
    """Extract metadata from a domain.

    Strategy (failure-path fallbacks only — successful domains behave exactly as before):
      1. https://{apex}        (20s: connect 5s)  — primary, unchanged behavior
      2. https://www.{apex}    (14s)               — recovers SSL name-mismatch + some dead apex DNS
      3. http://{apex}         (12s)               — recovers https-only timeouts / no-TLS sites
      4. https://{apex} no-verify (10s)            — recovers self-signed / broken-cert sites

    Caching:
      - Success: Redis domain:{n} 30d (unchanged, same response shape)
      - Failure: Redis failed:domain:{n} 24h — same error response shape, skips re-scraping
    """
    start_time = time.time()
    normalized = normalize_domain(domain)

    try:
        redis = await get_redis()

        # --- Positive cache (unchanged key + shape) ---
        cache_key = f"domain:{normalized}"
        cached_data = await redis.get(cache_key)
        if cached_data:
            data = json.loads(cached_data)
            await bump_stat("cache_hit")
            return {
                "domain": domain,
                "normalized_domain": normalized,
                **data,
                "extraction_method": "redis_cache",
                "extraction_time": time.time() - start_time
            }

        # --- Negative cache (new): dead/blocked domains skip re-scraping for 24h ---
        neg_key = f"failed:domain:{normalized}"
        neg_cached = await redis.get(neg_key)
        if neg_cached:
            data = json.loads(neg_cached)
            await bump_stat("negative_cache_hit")
            return {
                "domain": domain,
                "normalized_domain": normalized,
                **data,
                "extraction_method": data.get("extraction_method", "error") + "_cached",
                "extraction_time": time.time() - start_time
            }

        await bump_stat("request")

        # --- Attempt chain ---
        attempts = [
            (f"https://{normalized}", aiohttp.ClientTimeout(total=20, connect=5), True, "web_extraction"),
            (f"https://www.{normalized}", aiohttp.ClientTimeout(total=14, connect=5), True, "web_extraction_www"),
            (f"http://{normalized}", aiohttp.ClientTimeout(total=12, connect=5), True, "web_extraction_http"),
            (f"https://{normalized}", aiohttp.ClientTimeout(total=10, connect=5), False, "web_extraction_noverify"),
        ]

        last_error = None
        last_status = None

        for url, timeout, verify, method in attempts:
            try:
                data, status = await _fetch_and_parse(url, timeout, verify)
                if data is not None:
                    # Success: cache 30d under the SAME key/shape as before
                    await redis.setex(cache_key, 2592000, json.dumps({
                        "status_code": data["status_code"],
                        "meta_title": data["meta_title"],
                        "meta_description": data["meta_description"],
                        "meta_keywords": data["meta_keywords"],
                        "h1_tag": data["h1_tag"],
                        "first_paragraph": data["first_paragraph"]
                    }))
                    data["extraction_method"] = method
                    data["extraction_time"] = time.time() - start_time
                    await bump_stat("success", method)
                    return {
                        "domain": domain,
                        "normalized_domain": normalized,
                        **data
                    }
                # Non-200 response — try next method, but remember the status
                last_error = f"HTTP {status}"
                last_status = status
            except Exception as e:
                last_error = str(e)
                continue

        # --- All attempts failed: negative-cache the error response (same shape as old failures) ---
        if last_status is not None:
            error_result = {
                "domain": domain,
                "normalized_domain": normalized,
                "status_code": last_status,
                "error_message": f"HTTP {last_status}",
                "extraction_method": "http_error",
                "extraction_time": time.time() - start_time
            }
        else:
            error_result = {
                "domain": domain,
                "normalized_domain": normalized,
                "error_message": _last_error_text(last_error),
                "extraction_method": "error",
                "extraction_time": time.time() - start_time
            }
        try:
            await redis.setex(neg_key, NEGATIVE_TTL, json.dumps({
                "error_message": error_result["error_message"],
                "extraction_method": error_result["extraction_method"],
                "status_code": error_result.get("status_code"),
            }))
        except Exception:
            pass
        await bump_stat("failure")
        logger.warning(f"Extraction failed for {domain}: {error_result['error_message'][:120]}")
        return error_result

    except Exception as e:
        logger.error(f"Error extracting metadata for {domain}: {str(e)}")
        return {
            "domain": domain,
            "normalized_domain": normalized,
            "error_message": str(e),
            "extraction_method": "error",
            "extraction_time": time.time() - start_time
        }

async def process_domains(job_id: str, domains: List[str], domain_column: str):
    """Process a list of domains"""
    async with AsyncSessionLocal() as db:
        try:
            # Update job status
            job = await db.get(Job, job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return

            job.status = "processing"
            job.started_at = datetime.utcnow()
            await db.commit()

            # Process domains
            for i, domain_data in enumerate(domains):
                try:
                    domain = domain_data.domain if hasattr(domain_data, 'domain') else domain_data
                    domain = normalize_domain(domain)

                    if not is_valid_domain(domain):
                        job.failed_domains += 1
                        continue

                    # Check if domain exists and is not expired
                    existing_domain = await db.execute(
                        select(Domain).where(
                            and_(
                                Domain.normalized_domain == domain,
                                Domain.cache_expires > datetime.utcnow()
                            )
                        )
                    )
                    existing = existing_domain.scalar_one_or_none()

                    if existing:
                        job.successful_domains += 1
                    else:
                        # Extract metadata
                        metadata = await extract_metadata(domain)

                        # Create or update domain record
                        domain_record = Domain(
                            domain=domain,
                            normalized_domain=domain,
                            meta_title=metadata.get('meta_title'),
                            meta_description=metadata.get('meta_description'),
                            meta_keywords=metadata.get('meta_keywords'),
                            h1_tag=metadata.get('h1_tag'),
                            first_paragraph=metadata.get('first_paragraph'),
                            status_code=metadata.get('status_code'),
                            extraction_method=metadata.get('extraction_method'),
                            extraction_time=metadata.get('extraction_time'),
                            error_message=metadata.get('error_message'),
                            last_extracted=datetime.utcnow(),
                            cache_expires=datetime.utcnow() + timedelta(days=30),
                            status="completed" if metadata.get('meta_title') else "failed",
                            extraction_count=1,
                            success_count=1 if metadata.get('meta_title') else 0
                        )

                        db.add(domain_record)
                        job.successful_domains += 1

                    job.processed_domains += 1

                    # Update progress every 10 domains
                    if i % 10 == 0:
                        await db.commit()

                except Exception as e:
                    logger.error(f"Error processing domain {domain}: {str(e)}")
                    job.failed_domains += 1
                    job.processed_domains += 1

            # Complete job
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            await db.commit()

            logger.info(f"Job {job_id} completed: {job.successful_domains} successful, {job.failed_domains} failed")

        except Exception as e:
            logger.error(f"Error processing job {job_id}: {str(e)}")
            if job:
                job.status = "failed"
                job.error_message = str(e)
                await db.commit()

# ==============
# API ROUTES
# ==============

@app.post("/upload", response_model=FileUploadResponse)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    domain_column: str = Form(...)
):
    """Upload CSV file and create job"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    try:
        # Create uploads directory
        upload_dir = Path("uploads")
        upload_dir.mkdir(exist_ok=True)

        # Generate unique filename
        file_id = str(uuid.uuid4())
        file_extension = Path(file.filename).suffix
        stored_filename = f"{file_id}{file_extension}"
        file_path = upload_dir / stored_filename

        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        # Parse CSV to count domains
        domains = []
        total_rows = 0

        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            csv_reader = csv.DictReader(content.splitlines())

            for row in csv_reader:
                total_rows += 1
                if domain_column in row and row[domain_column]:
                    domain = normalize_domain(row[domain_column])
                    if domain and is_valid_domain(domain):
                        domains.append(domain)

        if not domains:
            raise HTTPException(status_code=400, detail="No valid domains found in the specified column")

        # Create job
        job = Job(
            id=file_id,
            status="pending",
            total_domains=len(domains),
            domain_column=domain_column,
            original_filename=file.filename
        )

        async with AsyncSessionLocal() as db:
            db.add(job)

            # Create file record
            uploaded_file = UploadedFile(
                id=file_id,
                filename=stored_filename,
                original_filename=file.filename,
                file_path=str(file_path),
                file_size=len(content),
                content_type=file.content_type,
                domain_column=domain_column,
                total_domains=len(domains),
                total_rows=total_rows,
                job_id=job_id
            )
            db.add(uploaded_file)
            await db.commit()

        # Start background processing
        background_tasks.add_task(process_domains, file_id, domains, domain_column)

        return FileUploadResponse(
            success=True,
            file_id=file_id,
            message=f"Successfully uploaded {file.filename} with {len(domains)} domains",
            total_domains=len(domains),
            total_rows=total_rows,
            job_id=file_id
        )

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status"""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "job_id": str(job.id),
            "status": job.status,
            "total_domains": job.total_domains,
            "processed_domains": job.processed_domains,
            "successful_domains": job.successful_domains,
            "failed_domains": job.failed_domains,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "domain_column": job.domain_column,
            "original_filename": job.original_filename,
            "error_message": job.error_message
        }

@app.get("/jobs")
async def list_jobs():
    """List all jobs"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job).order_by(Job.created_at.desc())
        )
        jobs = result.scalars().all()

        return {
            "jobs": [
                {
                    "id": str(job.id),
                    "status": job.status,
                    "total_domains": job.total_domains,
                    "processed_domains": job.processed_domains,
                    "successful_domains": job.successful_domains,
                    "failed_domains": job.failed_domains,
                    "created_at": job.created_at.isoformat(),
                    "original_filename": job.original_filename
                }
                for job in jobs
            ]
        }

@app.get("/download/{job_id}")
async def download_results(job_id: str):
    """Download results as CSV"""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != "completed":
            raise HTTPException(status_code=400, detail="Job not completed")

        # Get domains with successful extraction
        result = await db.execute(
            select(Domain).where(Domain.status == "completed")
        )
        domains = result.scalars().all()

        # Create CSV content
        output = []
        output.append([
            "domain", "normalized_domain", "meta_title", "meta_description",
            "meta_keywords", "h1_tag", "first_paragraph", "status_code",
            "extraction_method", "last_extracted"
        ])

        for domain in domains:
            output.append([
                domain.domain,
                domain.normalized_domain,
                domain.meta_title or "",
                domain.meta_description or "",
                domain.meta_keywords or "",
                domain.h1_tag or "",
                domain.first_paragraph or "",
                domain.status_code or "",
                domain.extraction_method or "",
                domain.last_extracted.isoformat() if domain.last_extracted else ""
            ])

        # Generate CSV content
        csv_content = "\n".join([",".join([f'"{field}"' for field in row]) for row in output])

        filename = f"domain_results_{job_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "4.0.0"
    }

# ==============
# CLAY API ENDPOINTS
# ==============

@app.get("/api/v1/domain")
async def get_domain_metadata(domain: str):
    """
    Get comprehensive metadata for a single domain.
    Perfect for integration with Clay or other external tools.

    Args:
        domain: The domain name to analyze (e.g., "google.com", "https://example.com")

    Returns:
        JSON object with all extracted metadata including:
        - domain: Original input domain
        - normalized_domain: Cleaned domain name
        - status_code: HTTP response code
        - meta_title: Page title
        - meta_description: Meta description tag
        - meta_keywords: Meta keywords tag
        - h1_tag: First H1 heading
        - first_paragraph: First 200 chars of content
        - extraction_method: How data was obtained (cache/web/error)
        - extraction_time: Time taken in seconds

    Example:
        GET /api/v1/domain?domain=google.com
        GET /api/v1/domain?domain=https://example.com
    """
    try:
        # Normalize and validate domain
        normalized = normalize_domain(domain)

        if not is_valid_domain(normalized):
            await bump_stat("invalid_domain")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid domain format: {domain}"
            )

        # Extract metadata
        result = await extract_metadata(normalized)

        return JSONResponse(
            status_code=200,
            content=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_domain_metadata for {domain}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.get("/api/v1/batch", response_model=Dict[str, Any])
async def batch_domain_metadata(domains: str):
    """
    Get metadata for multiple domains in one request.
    Domains should be comma-separated.

    Args:
        domains: Comma-separated list of domains (e.g., "google.com,example.com,test.org")

    Returns:
        JSON object with:
        - success: Boolean indicating overall status
        - total_domains: Number of domains requested
        - results: Array of domain metadata objects
        - errors: Array of any errors encountered

    Example:
        GET /api/v1/batch?domains=google.com,example.com,test.org
    """
    try:
        # Parse domains
        domain_list = [d.strip() for d in domains.split(',') if d.strip()]

        if not domain_list:
            raise HTTPException(
                status_code=400,
                detail="No domains provided"
            )

        if len(domain_list) > 50:
            raise HTTPException(
                status_code=400,
                detail="Maximum 50 domains per batch request"
            )

        # Process domains concurrently
        results = []
        errors = []

        for domain in domain_list:
            try:
                normalized = normalize_domain(domain)
                if is_valid_domain(normalized):
                    result = await extract_metadata(normalized)
                    results.append(result)
                else:
                    await bump_stat("invalid_domain")
                    errors.append({
                        "domain": domain,
                        "error": "Invalid domain format"
                    })
            except Exception as e:
                errors.append({
                    "domain": domain,
                    "error": str(e)
                })

        return {
            "success": True,
            "total_domains": len(domain_list),
            "successful_domains": len(results),
            "failed_domains": len(errors),
            "results": results,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch_domain_metadata: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# ==============
# WEB INTERFACE ROUTES
# ==============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with upload form"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "page_title": "Domain Meta Extractor - Enterprise"
    })

@app.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    """Files management page"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UploadedFile, Job)
            .outerjoin(Job, UploadedFile.job_id == Job.id)
            .order_by(UploadedFile.created_at.desc())
        )
        files_data = result.all()

        files = []
        for file_row, job_row in files_data:
            if job_row:
                if job_row.status == 'completed':
                    if job_row.successful_domains > 0:
                        status_text = f"✅ {job_row.successful_domains} extracted"
                        status_class = "success"
                    else:
                        status_text = f"❌ {job_row.failed_domains} failed"
                        status_class = "error"
                elif job_row.status == 'processing':
                    status_text = f"🔄 {job_row.processed_domains or 0}/{job_row.total_domains or 0}"
                    status_class = "processing"
                elif job_row.status == 'failed':
                    status_text = f"❌ Extraction failed"
                    status_class = "error"
                else:
                    status_text = f"⏳ Pending"
                    status_class = "pending"
            else:
                status_text = f"📂 Uploaded"
                status_class = "pending"

            files.append({
                'id': str(file_row.id),
                'filename': file_row.filename,
                'original_filename': file_row.original_filename,
                'file_size': file_row.file_size,
                'total_rows': file_row.total_rows,
                'domain_column': file_row.domain_column,
                'status_text': status_text,
                'status_class': status_class,
                'job_id': str(file_row.job_id) if file_row.job_id else None,
                'uploaded_at': file_row.created_at.isoformat(),
            })

        return templates.TemplateResponse("files.html", {
            "request": request,
            "files": files,
            "page_title": "File Management - Domain Meta Extractor"
        })

@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    """Job queue monitoring page"""
    return templates.TemplateResponse("queue.html", {
        "request": request,
        "page_title": "Job Queue - Domain Meta Extractor"
    })

# ==============
# MAIN EXECUTION
# ==============

if __name__ == "__main__":
    # Create tables
    async def create_tables():
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())

    # Run server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info"
    )