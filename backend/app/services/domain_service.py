from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, update
from typing import Optional, Tuple, List
import asyncio
import aiohttp
from datetime import datetime, timedelta

from app.models.domain import Domain
from app.services.extraction.extractors import ConsolidatedExtractor, DomainUtils


class DomainService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_domain_data(self, domain: str) -> Tuple[Optional[Domain], bool]:
        """Get domain data from cache or database"""
        normalized_domain = DomainUtils.normalize_domain(domain)

        if not normalized_domain:
            return None, False

        # Check database for cached data
        stmt = select(Domain).where(Domain.normalized_domain == normalized_domain)
        result = await self.db.execute(stmt)
        domain_obj = result.scalar_one_or_none()

        if domain_obj and domain_obj.is_cache_valid():
            return domain_obj, True

        return domain_obj, False

    async def extract_domain(self, domain: str, concurrency: int = 10) -> Optional[Domain]:
        """Extract domain metadata using real extraction logic"""
        start_time = asyncio.get_event_loop().time()
        normalized_domain = DomainUtils.normalize_domain(domain)

        if not normalized_domain:
            return None

        # Check if domain exists
        stmt = select(Domain).where(Domain.normalized_domain == normalized_domain)
        result = await self.db.execute(stmt)
        existing_domain = result.scalar_one_or_none()

        # Create extractor with optimized settings
        extractor = ConsolidatedExtractor(concurrency=concurrency)

        # Create aiohttp session
        connector = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=concurrency,
            ttl_dns_cache=300,
            use_dns_cache=True
        )

        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        ) as session:
            # Extract using real extractor
            extraction_result = await extractor.extract_domain(normalized_domain, session)

        if extraction_result.success:
            if existing_domain:
                # Update existing domain
                existing_domain.meta_title = extraction_result.title
                existing_domain.meta_description = extraction_result.description
                existing_domain.extraction_method = extraction_result.method
                existing_domain.status_code = extraction_result.status_code
                existing_domain.extraction_time = extraction_result.extraction_time
                existing_domain.error_message = None
                existing_domain.last_extracted = datetime.utcnow()
                existing_domain.refresh_cache_expiry()
                existing_domain.extraction_count += 1
                existing_domain.success_count += 1

                await self.db.commit()
                await self.db.refresh(existing_domain)
                return existing_domain
            else:
                # Create new domain
                new_domain = Domain(
                    domain=domain,
                    normalized_domain=normalized_domain,
                    meta_title=extraction_result.title,
                    meta_description=extraction_result.description,
                    extraction_method=extraction_result.method,
                    status_code=extraction_result.status_code,
                    extraction_time=extraction_result.extraction_time,
                    error_message=None,
                    last_extracted=datetime.utcnow(),
                    cache_expires=datetime.utcnow() + timedelta(days=30),
                    extraction_count=1,
                    success_count=1
                )

                self.db.add(new_domain)
                await self.db.commit()
                await self.db.refresh(new_domain)
                return new_domain
        else:
            # Handle extraction failure
            if existing_domain:
                # Update existing domain with error
                existing_domain.error_message = extraction_result.error_message
                existing_domain.last_extracted = datetime.utcnow()
                existing_domain.extraction_count += 1
                # Don't refresh cache on failure
                await self.db.commit()
                await self.db.refresh(existing_domain)
                return existing_domain
            else:
                # Create domain with error info
                new_domain = Domain(
                    domain=domain,
                    normalized_domain=normalized_domain,
                    meta_title=None,
                    meta_description=None,
                    extraction_method=extraction_result.method,
                    status_code=extraction_result.status_code,
                    extraction_time=extraction_result.extraction_time,
                    error_message=extraction_result.error_message,
                    last_extracted=datetime.utcnow(),
                    cache_expires=datetime.utcnow() + timedelta(days=1),  # Shorter cache for failures
                    extraction_count=1,
                    success_count=0
                )

                self.db.add(new_domain)
                await self.db.commit()
                await self.db.refresh(new_domain)
                return new_domain

    async def extract_domains_batch(self, domains: List[str], concurrency: int = 25) -> List[Domain]:
        """Extract multiple domains in batch"""
        # Normalize and filter valid domains
        normalized_domains = []
        for domain in domains:
            normalized = DomainUtils.normalize_domain(domain)
            if normalized:
                normalized_domains.append((domain, normalized))

        # Check cache first
        cached_domains = {}
        to_extract = []

        for original, normalized in normalized_domains:
            stmt = select(Domain).where(Domain.normalized_domain == normalized)
            result = await self.db.execute(stmt)
            domain_obj = result.scalar_one_or_none()

            if domain_obj and domain_obj.is_cache_valid():
                cached_domains[normalized] = domain_obj
            else:
                to_extract.append((original, normalized))

        # Extract uncached domains
        extractor = ConsolidatedExtractor(concurrency=concurrency)

        connector = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=concurrency,
            ttl_dns_cache=300,
            use_dns_cache=True
        )

        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        ) as session:
            # Create extraction tasks
            tasks = []
            for original, normalized in to_extract:
                task = extractor.extract_domain(normalized, session)
                tasks.append((original, task))

            # Execute tasks concurrently
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

            # Process results
            extracted_domains = []
            for (original, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    # Handle exception
                    error_domain = Domain(
                        domain=original,
                        normalized_domain=DomainUtils.normalize_domain(original),
                        meta_title=None,
                        meta_description=None,
                        extraction_method="exception",
                        status_code=0,
                        extraction_time=0,
                        error_message=str(result),
                        last_extracted=datetime.utcnow(),
                        cache_expires=datetime.utcnow() + timedelta(days=1),
                        extraction_count=1,
                        success_count=0
                    )
                    self.db.add(error_domain)
                    extracted_domains.append(error_domain)
                elif result.success:
                    # Create successful domain
                    success_domain = Domain(
                        domain=original,
                        normalized_domain=DomainUtils.normalize_domain(original),
                        meta_title=result.title,
                        meta_description=result.description,
                        extraction_method=result.method,
                        status_code=result.status_code,
                        extraction_time=result.extraction_time,
                        error_message=None,
                        last_extracted=datetime.utcnow(),
                        cache_expires=datetime.utcnow() + timedelta(days=30),
                        extraction_count=1,
                        success_count=1
                    )
                    self.db.add(success_domain)
                    extracted_domains.append(success_domain)
                else:
                    # Create failed domain
                    failed_domain = Domain(
                        domain=original,
                        normalized_domain=DomainUtils.normalize_domain(original),
                        meta_title=None,
                        meta_description=None,
                        extraction_method=result.method,
                        status_code=result.status_code,
                        extraction_time=result.extraction_time,
                        error_message=result.error_message,
                        last_extracted=datetime.utcnow(),
                        cache_expires=datetime.utcnow() + timedelta(days=1),
                        extraction_count=1,
                        success_count=0
                    )
                    self.db.add(failed_domain)
                    extracted_domains.append(failed_domain)

        # Commit all new domains
        if extracted_domains:
            await self.db.commit()
            for domain in extracted_domains:
                await self.db.refresh(domain)

        # Combine cached and extracted domains
        all_domains = list(cached_domains.values()) + extracted_domains

        return all_domains

    async def search_domains(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Domain]:
        """Search domains by name or metadata"""
        stmt = (
            select(Domain)
            .where(
                or_(
                    Domain.domain.ilike(f"%{query}%"),
                    Domain.normalized_domain.ilike(f"%{query}%"),
                    Domain.meta_title.ilike(f"%{query}%"),
                    Domain.meta_description.ilike(f"%{query}%")
                )
            )
            .order_by(Domain.last_extracted.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_recent_domains(
        self,
        limit: int = 20,
        offset: int = 0
    ) -> List[Domain]:
        """List recently extracted domains"""
        stmt = (
            select(Domain)
            .order_by(Domain.last_extracted.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(stmt)
        return result.scalars().all()