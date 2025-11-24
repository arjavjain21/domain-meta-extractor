"""
Domain meta extractors adapted from standalone script for web application.
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urlparse
from lxml import html, etree
import re
from dataclasses import dataclass

from app.core.config import settings


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
        """Convert to dictionary."""
        return {
            'domain': self.domain,
            'title': self.title,
            'description': self.description,
            'method': self.method,
            'status_code': self.status_code,
            'extraction_time': self.extraction_time,
            'error_message': self.error_message,
            'success': self.success
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

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.min_title_length = self.config.get('min_title_length', 3)
        self.max_title_length = self.config.get('max_title_length', 200)
        self.min_description_length = self.config.get('min_description_length', 10)
        self.max_description_length = self.config.get('max_description_length', 500)
        self.max_content_length = self.config.get('max_content_length', 1048576)

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

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.timeout = self.config.get('timeout', 30)
        self.follow_redirects = self.config.get('follow_redirects', True)
        self.max_redirects = self.config.get('max_redirects', 10)

    async def extract(self, domain: str, session: aiohttp.ClientSession, **kwargs) -> ExtractionResult:
        """Extract meta information using HTML parsing."""
        start_time = asyncio.get_event_loop().time()

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
    """Consolidated extractor for web application."""

    def __init__(self, concurrency: int = None, timeout: int = None, max_retries: int = None):
        self.concurrency = concurrency or settings.DEFAULT_CONCURRENCY
        self.timeout = timeout or 30
        self.max_retries = max_retries or 2

        config = {
            'timeout': self.timeout,
            'follow_redirects': True,
            'max_redirects': 5,
            'min_title_length': 3,
            'max_title_length': 200,
            'min_description_length': 10,
            'max_description_length': 500,
            'max_content_length': 1048576,
        }

        self.html_extractor = HTMLExtractor(config)

    async def extract_domain(self, domain: str, session: aiohttp.ClientSession) -> ExtractionResult:
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

            attempts = self.max_retries + 1
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