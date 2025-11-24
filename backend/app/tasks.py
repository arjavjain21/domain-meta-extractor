from celery import current_app
from app.celery import celery_app
from app.services.extraction_service import ExtractionService
from app.core.database import AsyncSessionLocal


@celery_app.task(bind=True)
def process_domains_task(self, job_id: str):
    """Process domains for a job"""
    import asyncio

    async def process():
        async with AsyncSessionLocal() as db:
            extraction_service = ExtractionService(db)
            await extraction_service.process_file(job_id)

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process())
    finally:
        loop.close()


@celery_app.task(bind=True)
def extract_domain_task(self, domain: str):
    """Extract a single domain"""
    import asyncio

    async def extract():
        async with AsyncSessionLocal() as db:
            from app.services.domain_service import DomainService
            domain_service = DomainService(db)
            result = await domain_service.extract_domain(domain)
            return result.to_dict() if result else None

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(extract())
        return result
    finally:
        loop.close()