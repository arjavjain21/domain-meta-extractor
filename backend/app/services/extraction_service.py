from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
import uuid
import os
import pandas as pd
from datetime import datetime

from app.models.job import Job
from app.models.domain import Domain
from app.models.job import JobDomain
from app.services.job_service import JobService
from app.services.domain_service import DomainService
from app.core.config import settings


class ExtractionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.job_service = JobService(db)
        self.domain_service = DomainService(db)

    async def process_file(self, job_id: uuid.UUID):
        """Process uploaded file and extract metadata"""
        try:
            # Get job
            job = await self.job_service.get_job(job_id)
            if not job:
                return

            # Start job
            job.start_job()
            await self.job_service.update_job(job)

            # Read CSV file
            df = pd.read_csv(job.file_path)
            
            # Normalize column names to lowercase (matching job_service.py)
            df.columns = df.columns.str.lower()
            
            # Find domain column (could be 'domain', 'email', 'website', 'url', etc.)
            domain_col = None
            for col in df.columns:
                if any(k in col.lower() for k in ['domain', 'email', 'website', 'url', 'address']):
                    domain_col = col
                    break
            
            if not domain_col:
                # Try to use 'domain' column, or first column as fallback
                if 'domain' in df.columns:
                    domain_col = 'domain'
                else:
                    domain_col = df.columns[0]
            
            # Extract unique domains for processing
            domains = df[domain_col].dropna().unique().tolist()

            # Get concurrency from job config
            concurrency = job.config.get('concurrency', settings.DEFAULT_CONCURRENCY) if job.config else settings.DEFAULT_CONCURRENCY
            concurrency = min(concurrency, settings.MAX_CONCURRENCY)

            # Process domains in batches for better memory management
            batch_size = min(500, len(domains))  # Process in batches of 500
            all_results = []

            for i in range(0, len(domains), batch_size):
                batch_domains = domains[i:i + batch_size]

                # Extract batch using optimized service
                batch_results = await self.domain_service.extract_domains_batch(
                    batch_domains,
                    concurrency=concurrency
                )

                all_results.extend(batch_results)

                # Update job progress
                successful_in_batch = sum(1 for r in batch_results if r.meta_title)
                failed_in_batch = len(batch_results) - successful_in_batch

                job.update_progress(successful=successful_in_batch, failed=failed_in_batch)
                await self.job_service.update_job(job)

            # Create job-domain relationships
            await self._create_job_domain_relationships(job, domains, all_results)

            # Generate results file (pass domain_col to ensure correct column is used)
            result_file_path = await self._generate_results_file(job, df, all_results, domain_col)

            # Complete job
            job.result_file_path = result_file_path
            job.complete_job()
            await self.job_service.update_job(job)

            # Update extraction stats
            await self._update_stats(job)

        except Exception as e:
            # Fail job
            job = await self.job_service.get_job(job_id)
            if job:
                job.fail_job(str(e))
                await self.job_service.update_job(job)

    async def _create_job_domain_relationships(self, job: Job, original_domains: List[str], extracted_domains: List[Domain]):
        """Create relationships between job and domains"""
        # Create mapping of normalized domain to domain object
        domain_map = {d.normalized_domain: d for d in extracted_domains}

        # Create job-domain relationships
        for index, original_domain in enumerate(original_domains):
            from app.services.extraction.extractors import DomainUtils
            normalized = DomainUtils.normalize_domain(original_domain)

            if normalized and normalized in domain_map:
                job_domain = JobDomain(
                    job_id=job.id,
                    domain_id=domain_map[normalized].id,
                    original_row_index=index,
                    status='completed' if domain_map[normalized].meta_title else 'failed'
                )
                self.db.add(job_domain)

        await self.db.commit()

    async def _update_stats(self, job: Job):
        """Update extraction statistics"""
        from app.services.stats_service import StatsService
        from datetime import date

        stats_service = StatsService(self.db)

        # Calculate stats for this job
        cache_hits = 0  # We could track this more precisely if needed
        cache_misses = job.successful_domains
        average_time = None  # We could aggregate this from domains if needed

        # Record today's stats
        await stats_service.record_stats(
            date=date.today(),
            total_requests=job.total_domains,
            successful_extractions=job.successful_domains,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            average_extraction_time=average_time
        )

    async def _generate_results_file(
        self,
        job: Job,
        original_df: pd.DataFrame,
        extracted_domains: List[Domain],
        domain_col: str = 'domain'
    ) -> str:
        """Generate results CSV file - ensures ALL rows from original CSV are included"""
        # Create mapping of normalized domain to domain object
        domain_map = {d.normalized_domain: d for d in extracted_domains}

        # Create results dataframe matching original order
        results = []
        
        from app.services.extraction.extractors import DomainUtils

        for _, row in original_df.iterrows():
            # Get original domain value from the correct column
            original_domain = str(row.get(domain_col, '')).strip() if domain_col in row else ''
            
            # If domain column is missing or empty, still include the row
            if not original_domain:
                result = {
                    'domain': '',
                    'meta_title': '',
                    'meta_description': '',
                    'extraction_method': 'missing_domain',
                    'status_code': None,
                    'extraction_time': None,
                    'from_cache': False,
                    'error_message': 'Domain column missing or empty'
                }
                results.append(result)
                continue

            # Normalize domain to find in our results
            normalized = DomainUtils.normalize_domain(original_domain)

            if normalized and normalized in domain_map:
                domain_data = domain_map[normalized]
                result = {
                    'domain': domain_data.domain,
                    'meta_title': domain_data.meta_title or '',
                    'meta_description': domain_data.meta_description or '',
                    'extraction_method': domain_data.extraction_method,
                    'status_code': domain_data.status_code,
                    'extraction_time': domain_data.extraction_time,
                    'from_cache': domain_data.is_cache_valid(),
                    'error_message': domain_data.error_message or ''
                }
            else:
                # Domain was in original CSV but not successfully processed
                # Still include it in results with error info
                result = {
                    'domain': original_domain,
                    'meta_title': '',
                    'meta_description': '',
                    'extraction_method': 'not_processed' if normalized else 'invalid_domain',
                    'status_code': None,
                    'extraction_time': None,
                    'from_cache': False,
                    'error_message': 'Domain not processed or invalid' if normalized else 'Domain failed normalization'
                }

            results.append(result)

        # Convert to DataFrame
        results_df = pd.DataFrame(results)

        # Ensure results directory exists
        os.makedirs(settings.RESULTS_DIR, exist_ok=True)

        # Generate output filename
        base_name = os.path.splitext(job.original_filename)[0]
        output_filename = f"{base_name}_results_{uuid.uuid4().hex[:8]}.csv"
        output_path = os.path.join(settings.RESULTS_DIR, output_filename)

        # Save results with all columns
        results_df.to_csv(output_path, index=False)

        return output_path