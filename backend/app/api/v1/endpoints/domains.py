from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.schemas.domain import DomainResponse, DomainExtractRequest
from app.services.domain_service import DomainService

router = APIRouter()


@router.get("/{domain}", response_model=DomainResponse)
async def get_domain(
    domain: str,
    db: AsyncSession = Depends(get_db)
):
    """Get cached domain data"""
    domain_service = DomainService(db)

    # Normalize domain
    normalized_domain = domain.lower().strip()

    # Get domain data from cache or database
    domain_data, from_cache = await domain_service.get_domain_data(normalized_domain)

    if not domain_data:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for domain: {domain}"
        )

    response = DomainResponse.from_domain(domain_data)
    response.fromCache = from_cache

    return response


@router.post("/extract", response_model=DomainResponse)
async def extract_domain(
    request: DomainExtractRequest,
    db: AsyncSession = Depends(get_db)
):
    """Extract domain metadata directly"""
    domain_service = DomainService(db)

    # Normalize domain
    normalized_domain = request.domain.lower().strip()

    # Extract domain data
    domain_data = await domain_service.extract_domain(normalized_domain)

    if not domain_data:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract data for domain: {request.domain}"
        )

    return DomainResponse.from_domain(domain_data)


@router.get("/")
async def search_domains(
    q: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """Search domains"""
    domain_service = DomainService(db)

    if q:
        domains = await domain_service.search_domains(q, limit=limit, offset=offset)
    else:
        domains = await domain_service.list_recent_domains(limit=limit, offset=offset)

    return [DomainResponse.from_domain(domain) for domain in domains]