#!/usr/bin/env python3
"""
Standalone Domain Meta Extractor
Optimized script that extracts meta information from domain names by processing unique domains first.
"""

import asyncio
import aiohttp
import pandas as pd
import time
from datetime import datetime
import argparse
import sys
import os
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List, Set
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin
from lxml import html, etree
from bs4 import BeautifulSoup
import re
import json
from tqdm import tqdm
import signal

# Configure logging
def setup_logging(log_file: str = None):
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file) if log_file else logging.NullHandler(),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

@dataclass
class ExtractionResult:
    """Result of a meta extraction attempt."""
    domain: str
    title: Optional[str] = None
    description: Optional[str] = None
    method: str = "unknown"
    status_code: Optional[int] = None
    extraction_time: Optional[float] = None
    error_message: Optional[str] = None
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV output."""
        return {
            'meta_title': self.title or '',
            'meta_description': self.description or '',
            'extraction_method': self.method,
            'status_code': self.status_code or 0,
            'extraction_time': self.extraction_time or 0,
            'error_message': self.error_message or ''
        }


class DomainUtils:
    """Utility class for domain operations."""

    @staticmethod
    def normalize_domain(domain: str) -> Optional[str]:
        """Normalize a domain name."""
        if not domain:
            return None

        try:
            domain = str(domain).strip()
            if domain.startswith(('http://', 'https://')):
                parsed = urlparse(domain)
                domain = parsed.netloc
            else:
                parsed = urlparse(f'http://{domain}')
                domain = parsed.netloc

            domain = domain.lower()
            domain = domain.split(':')[0]
            domain = domain.rstrip('.')

            if DomainUtils.is_valid_domain(domain):
                return domain
            else:
                return None

        except Exception:
            return None

    @staticmethod
    def is_valid_domain(domain: str) -> bool:
        """Validate if a domain name is properly formatted."""
        if not domain:
            return False

        domain_pattern = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'
        )

        if not domain_pattern.match(domain):
            return False

        parts = domain.split('.')
        if len(parts) < 2 or len(parts[-1]) < 2:
            return False

        if len(domain) > 253:
            return False

        for part in parts:
            if len(part) > 63 or part.startswith('-') or part.endswith('-'):
                return False

        return True


class BaseExtractor:
    """Base class for all meta extractors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.min_title_length = config.get('extraction', {}).get('min_title_length', 3)
        self.max_title_length = config.get('extraction', {}).get('max_title_length', 200)
        self.min_description_length = config.get('extraction', {}).get('min_description_length', 10)
        self.max_description_length = config.get('extraction', {}).get('max_description_length', 500)
        self.max_content_length = config.get('extraction', {}).get('max_content_length', 1048576)

    def validate_title(self, title: str) -> bool:
        """Validate if a title meets quality criteria."""
        if not title:
            return False

        title = title.strip()
        length = len(title)

        return (self.min_title_length <= length <= self.max_title_length and
                not title.isdigit() and
                not title.isspace())

    def validate_description(self, description: str) -> bool:
        """Validate if a description meets quality criteria."""
        if not description:
            return False

        description = description.strip()
        length = len(description)

        return (self.min_description_length <= length <= self.max_description_length and
                not description.isdigit() and
                not description.isspace())

    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""

        text = ' '.join(text.split())
        unwanted_patterns = ['\n', '\r', '\t']
        for pattern in unwanted_patterns:
            text = text.replace(pattern, ' ')

        while '  ' in text:
            text = text.replace('  ', ' ')

        return text.strip()

    def create_success_result(self, domain: str, title: str, description: str,
                            method: str, extraction_time: float,
                            status_code: int = 200) -> ExtractionResult:
        """Create a successful extraction result."""
        return ExtractionResult(
            domain=domain,
            title=self.clean_text(title) if title else None,
            description=self.clean_text(description) if description else None,
            method=method,
            status_code=status_code,
            extraction_time=extraction_time,
            success=True
        )

    def create_error_result(self, domain: str, error_message: str,
                          method: str, extraction_time: float,
                          status_code: Optional[int] = None) -> ExtractionResult:
        """Create an error extraction result."""
        return ExtractionResult(
            domain=domain,
            method=method,
            status_code=status_code,
            extraction_time=extraction_time,
            error_message=error_message,
            success=False
        )


class HTMLExtractor(BaseExtractor):
    """Fast HTML-based meta extractor using lxml."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('performance', {}).get('timeout', 30)
        self.follow_redirects = config.get('advanced', {}).get('follow_redirects', True)
        self.max_redirects = config.get('advanced', {}).get('max_redirects', 10)

    async def extract(self, domain: str, **kwargs) -> ExtractionResult:
        """Extract meta information using HTML parsing."""
        start_time = asyncio.get_event_loop().time()
        session = kwargs.get('session')

        try:
            url = f'https://{domain.strip()}'

            async with session.get(
                url,
                allow_redirects=self.follow_redirects,
                max_redirects=self.max_redirects
            ) as response:
                status_code = response.status
                content_type = response.headers.get('content-type', '').lower()

                if not self._is_valid_response(response.status, content_type):
                    return self.create_error_result(
                        domain=domain,
                        error_message=f"Invalid response: {response.status} {content_type}",
                        method="html_extractor",
                        extraction_time=asyncio.get_event_loop().time() - start_time,
                        status_code=response.status
                    )

                content = await self._read_content_safely(response)
                if not content:
                    return self.create_error_result(
                        domain=domain,
                        error_message="No content received",
                        method="html_extractor",
                        extraction_time=asyncio.get_event_loop().time() - start_time,
                        status_code=response.status
                    )

                title, description = self._extract_from_html(content, url)
                extraction_time = asyncio.get_event_loop().time() - start_time

                if title or description:
                    return self.create_success_result(
                        domain=domain,
                        title=title,
                        description=description,
                        method="html_extractor",
                        extraction_time=extraction_time,
                        status_code=status_code
                    )
                else:
                    return self.create_error_result(
                        domain=domain,
                        error_message="No meta information found in HTML",
                        method="html_extractor",
                        extraction_time=extraction_time,
                        status_code=status_code
                    )

        except Exception as e:
            return self.create_error_result(
                domain=domain,
                error_message=f"HTML extraction error: {str(e)}",
                method="html_extractor",
                extraction_time=asyncio.get_event_loop().time() - start_time
            )

    def _is_valid_response(self, status_code: int, content_type: str) -> bool:
        """Check if the response is valid for HTML parsing."""
        if status_code >= 400:
            return False

        html_types = ['text/html', 'text/xhtml', 'application/xhtml+xml']
        return any(html_type in content_type for html_type in html_types)

    async def _read_content_safely(self, response: aiohttp.ClientResponse) -> Optional[str]:
        """Safely read response content with size limits."""
        try:
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_content_length:
                return None

            content = await response.text()
            if len(content.encode('utf-8')) > self.max_content_length:
                return None

            return content

        except Exception:
            return None

    def _extract_from_html(self, content: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract title and description from HTML content."""
        try:
            tree = html.fromstring(content)
            title = self._extract_title(tree)
            description = self._extract_description(tree)
            return title, description

        except etree.ParserError:
            return self._extract_from_partial_html(content)
        except Exception:
            return None, None

    def _extract_title(self, tree) -> Optional[str]:
        """Extract title from HTML tree with multiple fallbacks."""
        # Primary: title tag
        title_elem = tree.find('.//title')
        if title_elem is not None and title_elem.text:
            title = title_elem.text.strip()
            if self.validate_title(title):
                return title

        # Secondary: h1 tag
        h1_elem = tree.find('.//h1')
        if h1_elem is not None and h1_elem.text:
            title = h1_elem.text.strip()
            if self.validate_title(title):
                return title

        # Tertiary: meta property og:title
        og_title = tree.xpath('.//meta[@property="og:title"]/@content')
        if og_title and og_title[0]:
            title = og_title[0].strip()
            if self.validate_title(title):
                return title

        return None

    def _extract_description(self, tree) -> Optional[str]:
        """Extract description from HTML tree with multiple fallbacks."""
        # Primary: meta name description
        meta_desc = tree.xpath('.//meta[@name="description"]/@content')
        if meta_desc and meta_desc[0]:
            desc = meta_desc[0].strip()
            if self.validate_description(desc):
                return desc

        # Secondary: meta property og:description
        og_desc = tree.xpath('.//meta[@property="og:description"]/@content')
        if og_desc and og_desc[0]:
            desc = og_desc[0].strip()
            if self.validate_description(desc):
                return desc

        return None

    def _extract_from_partial_html(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract from potentially malformed HTML using regex fallbacks."""
        title = None
        description = None

        # Extract title using regex
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = self.clean_text(title_match.group(1))
            if not self.validate_title(title):
                title = None

        # Extract description using regex
        desc_patterns = [
            r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
            r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
            r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
        ]

        for pattern in desc_patterns:
            desc_match = re.search(pattern, content, re.IGNORECASE)
            if desc_match:
                desc = self.clean_text(desc_match.group(1))
                if self.validate_description(desc):
                    description = desc
                    break

        return title, description


class ConsolidatedExtractor:
    """Consolidated extractor for standalone script."""

    def __init__(self, concurrency: int = 10, timeout: int = 30, max_retries: int = 2):
        self.config = self.get_default_config(concurrency, timeout, max_retries)
        self.concurrency = max(1, int(concurrency))
        self.html_extractor = HTMLExtractor(self.config)

    def get_default_config(self, concurrency: int, timeout: int, max_retries: int):
        """Get default configuration."""
        return {
            'performance': {
                'timeout': timeout,
                'max_retries': max_retries,
                'concurrency': concurrency
            },
            'extraction': {
                'max_content_length': 1048576,
                'min_title_length': 3,
                'max_title_length': 200,
                'min_description_length': 10,
                'max_description_length': 500
            },
            'advanced': {
                'follow_redirects': True,
                'max_redirects': 5,
            }
        }

    async def extract_domain(self, domain: str, session) -> ExtractionResult:
        """Extract meta information from a single domain."""
        start_time = time.time()

        try:
            normalized_domain = DomainUtils.normalize_domain(domain)
            if not normalized_domain:
                return ExtractionResult(
                    domain=domain,
                    method="invalid_domain",
                    extraction_time=0,
                    error_message='Invalid domain format',
                    success=False
                )

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br'
            }

            max_retries = max(0, int(self.config.get('performance', {}).get('max_retries', 0)))
            attempts = max_retries + 1
            last_error_message: Optional[str] = None
            last_status_code: Optional[int] = None

            for attempt in range(attempts):
                try:
                    result = await self.html_extractor.extract(normalized_domain, session=session, headers=headers)

                    if result.success:
                        extraction_time = time.time() - start_time
                        return ExtractionResult(
                            domain=domain,
                            title=result.title,
                            description=result.description,
                            method=result.method,
                            status_code=result.status_code,
                            extraction_time=extraction_time,
                            success=True
                        )

                    last_error_message = result.error_message or last_error_message
                    last_status_code = result.status_code or last_status_code

                except Exception as exc:
                    last_error_message = str(exc)

                if attempt < attempts - 1:
                    await asyncio.sleep(0.1)  # Brief pause between retries

            extraction_time = time.time() - start_time
            return ExtractionResult(
                domain=domain,
                method="none",
                status_code=last_status_code or 0,
                extraction_time=extraction_time,
                error_message=last_error_message or 'All extraction methods failed',
                success=False
            )

        except Exception as e:
            extraction_time = time.time() - start_time
            return ExtractionResult(
                domain=domain,
                method="exception",
                status_code=0,
                extraction_time=extraction_time,
                error_message=str(e),
                success=False
            )

    async def process_domains(self, domains: List[str]) -> Dict[str, ExtractionResult]:
        """Process a list of unique domains."""
        performance_config = self.config.get('performance', {})
        concurrency = max(1, int(performance_config.get('concurrency', self.concurrency)))

        connector = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=concurrency,
            ttl_dns_cache=300,
            use_dns_cache=True
        )

        timeout = aiohttp.ClientTimeout(
            total=performance_config.get('timeout', 30)
        )

        semaphore = asyncio.Semaphore(concurrency)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'User-Agent': 'DomainMetaExtractor/1.0'}
        ) as session:

            async def bounded_extract(domain: str):
                async with semaphore:
                    return await self.extract_domain(domain, session)

            results = {}
            tasks = [asyncio.create_task(bounded_extract(domain)) for domain in domains]

            for task in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Processing domains"):
                result = await task
                results[result.domain] = result

            return results


class CSVProcessor:
    """Handle CSV input and output processing."""

    def __init__(self, input_file: str, output_file: str, log_file: str = None):
        self.input_file = input_file
        self.output_file = output_file
        self.log_file = log_file
        self.logger = setup_logging(log_file)

    def detect_domain_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect the domain column in the DataFrame."""
        possible_columns = ['domain', 'website', 'url', 'site', 'domains', 'websites', 'urls']

        for col in possible_columns:
            if col in df.columns:
                return col

        # Fallback: check if any column contains domain-like data
        for col in df.columns:
            sample_values = df[col].dropna().head(10).astype(str)
            if sample_values.str.contains(r'\.', regex=True).any():
                return col

        return None

    def load_and_analyze_csv(self) -> Tuple[pd.DataFrame, str, int, int]:
        """Load CSV and analyze unique domains."""
        try:
            df = pd.read_csv(self.input_file)
            self.logger.info(f"Loaded CSV with {len(df)} rows and {len(df.columns)} columns")

            # Remove completely blank rows
            original_length = len(df)
            df = df.dropna(how='all')
            if len(df) < original_length:
                self.logger.info(f"Removed {original_length - len(df)} completely blank rows")

            domain_column = self.detect_domain_column(df)
            if not domain_column:
                raise ValueError("Could not detect domain column. Expected columns: domain, website, url, site")

            self.logger.info(f"Detected domain column: '{domain_column}'")

            # Extract domains and count unique ones
            domains = df[domain_column].dropna().astype(str)
            unique_domains = set()
            valid_domains = []

            for domain in domains:
                normalized = DomainUtils.normalize_domain(domain)
                if normalized:
                    unique_domains.add(normalized)
                    valid_domains.append(normalized)

            total_domains = len(domains)
            unique_count = len(unique_domains)

            self.logger.info(f"Total domains: {total_domains}")
            self.logger.info(f"Unique valid domains: {unique_count}")

            return df, domain_column, total_domains, unique_count

        except Exception as e:
            self.logger.error(f"Error loading CSV: {str(e)}")
            raise

    def map_results_to_dataframe(self, df: pd.DataFrame, domain_column: str,
                                results: Dict[str, ExtractionResult]) -> pd.DataFrame:
        """Map extraction results back to the original DataFrame."""
        # Create metadata columns
        metadata_columns = ['meta_title', 'meta_description', 'extraction_method',
                          'status_code', 'extraction_time', 'error_message']

        for col in metadata_columns:
            df[col] = ''

        # Map results
        for idx, row in df.iterrows():
            domain_value = str(row[domain_column]) if pd.notna(row[domain_column]) else ''
            normalized_domain = DomainUtils.normalize_domain(domain_value)

            if normalized_domain and normalized_domain in results:
                result = results[normalized_domain]
                result_dict = result.to_dict()

                for col in metadata_columns:
                    df.at[idx, col] = result_dict.get(col, '')

        return df

    def save_results(self, df: pd.DataFrame):
        """Save results to CSV."""
        try:
            df.to_csv(self.output_file, index=False)
            self.logger.info(f"Results saved to: {self.output_file}")
        except Exception as e:
            self.logger.error(f"Error saving results: {str(e)}")
            raise


class DomainExtractorCLI:
    """Command-line interface for the domain extractor."""

    def __init__(self):
        self.setup_signal_handlers()

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            print("\n\n⚠️  Process interrupted by user. Exiting gracefully...")
            sys.exit(1)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def parse_arguments(self):
        """Parse command-line arguments."""
        parser = argparse.ArgumentParser(
            description="Extract meta information from domain names in CSV files.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  python domain_extractor_standalone.py input.csv output.csv
  python domain_extractor_standalone.py input.csv output.csv --concurrency 5 --timeout 15
  python domain_extractor_standalone.py input.csv output.csv --log errors.log
            """
        )

        parser.add_argument('input_file', help='Input CSV file containing domains')
        parser.add_argument('output_file', help='Output CSV file with metadata')
        parser.add_argument('--concurrency', type=int, default=10,
                          help='Number of concurrent requests (default: 10)')
        parser.add_argument('--timeout', type=int, default=30,
                          help='Request timeout in seconds (default: 30)')
        parser.add_argument('--max-retries', type=int, default=2,
                          help='Maximum retries per domain (default: 2)')
        parser.add_argument('--log', help='Log file path for debugging errors')

        return parser.parse_args()

    def run(self):
        """Run the domain extraction process."""
        args = self.parse_arguments()

        # Validate input file
        if not os.path.exists(args.input_file):
            print(f"❌ Error: Input file '{args.input_file}' does not exist.")
            sys.exit(1)

        # Setup logging
        log_file = args.log or f"domain_extractor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        try:
            print("🔍 Domain Meta Extractor - Standalone Edition")
            print("=" * 50)

            # Initialize processor
            processor = CSVProcessor(args.input_file, args.output_file, log_file)

            # Load and analyze CSV
            print(f"📁 Loading and analyzing: {args.input_file}")
            df, domain_column, total_domains, unique_count = processor.load_and_analyze_csv()

            print(f"📊 Analysis Results:")
            print(f"   • Total rows in CSV: {len(df)}")
            print(f"   • Domain column: '{domain_column}'")
            print(f"   • Total domains found: {total_domains}")
            print(f"   • Unique valid domains: {unique_count}")

            if unique_count == 0:
                print("❌ No valid domains found in the CSV file.")
                sys.exit(1)

            # Extract unique domains
            unique_domains = set()
            domains_to_process = []

            for domain in df[domain_column].dropna().astype(str):
                normalized = DomainUtils.normalize_domain(domain)
                if normalized and normalized not in unique_domains:
                    unique_domains.add(normalized)
                    domains_to_process.append(normalized)

            print(f"\n🚀 Starting extraction of {len(domains_to_process)} unique domains...")
            print(f"⚙️  Configuration: concurrency={args.concurrency}, timeout={args.timeout}s, retries={args.max_retries}")

            # Process unique domains
            start_time = time.time()
            extractor = ConsolidatedExtractor(args.concurrency, args.timeout, args.max_retries)
            results = asyncio.run(extractor.process_domains(domains_to_process))
            processing_time = time.time() - start_time

            # Calculate statistics
            successful = sum(1 for r in results.values() if r.success)
            success_rate = (successful / len(results)) * 100 if results else 0

            print(f"\n✅ Extraction completed in {processing_time:.1f} seconds")
            print(f"📈 Results Summary:")
            print(f"   • Successful extractions: {successful}/{len(results)} ({success_rate:.1f}%)")
            print(f"   • Failed extractions: {len(results) - successful}")
            print(f"   • Average time per domain: {processing_time/len(results):.2f}s")

            # Map results back to original DataFrame
            print(f"\n📝 Mapping results back to original CSV...")
            result_df = processor.map_results_to_dataframe(df, domain_column, results)

            # Save results
            processor.save_results(result_df)

            print(f"\n🎉 All done! Results saved to: {args.output_file}")
            print(f"📋 Log file: {log_file}")

            # Log summary
            logger.info(f"Processing summary: {successful}/{len(results)} domains successful, {success_rate:.1f}% success rate")

        except KeyboardInterrupt:
            print("\n\n⚠️  Process interrupted by user.")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            if log_file:
                logger.error(f"Fatal error: {str(e)}")
            sys.exit(1)


def main():
    """Main entry point."""
    cli = DomainExtractorCLI()
    cli.run()


if __name__ == "__main__":
    main()