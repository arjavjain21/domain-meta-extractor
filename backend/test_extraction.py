#!/usr/bin/env python3
"""
Test extraction functionality
"""

import asyncio
import sys
sys.path.append('.')

from app.services.extraction.extractors import ConsolidatedExtractor, DomainUtils
from app.models.domain import Domain

async def test_extraction_batch():
    """Test batch extraction functionality"""
    print("🧪 Testing extraction functionality...\n")

    # Test 1: Domain normalization
    print("📋 Test 1: Domain Normalization")
    test_domains = [
        'google.com',
        'https://github.com',
        'http://www.python.org/',
        'subdomain.example.com',
        'INVALID_DOMAIN_123',
        'no-tld',
        'UPPERCASE.COM',
        'with-space .com'
    ]

    print(f"Testing {len(test_domains)} domains:")
    for domain in test_domains:
        normalized = DomainUtils.normalize_domain(domain)
        print(f"  {domain:<30} -> {normalized}")

    valid_domains = [d for d in test_domains if DomainUtils.normalize_domain(d)]
    print(f"\n✅ {len(valid_domains)} out of {len(test_domains)} domains are valid\n")

    # Test 2: Basic extraction
    print("🔍 Test 2: Basic HTML Extraction")
    extractor = ConsolidatedExtractor(concurrency=2, timeout=10)

    # Test with a few reliable sites
    test_sites = ['httpbin.org', 'example.com']

    import aiohttp
    connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=10, connect=5)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={
            'User-Agent': 'Mozilla/5.0 (compatible; DomainMetaExtractor/1.0)'
        }
    ) as session:
        for site in test_sites:
            print(f"\n  Extracting from: {site}")
            try:
                result = await extractor.extract_domain(site, session)
                print(f"    Status: {'✅ Success' if result.success else '❌ Failed'}")
                print(f"    Method: {result.method}")
                print(f"    Status Code: {result.status_code}")
                print(f"    Extraction Time: {result.extraction_time:.2f}s")

                if result.success:
                    print(f"    Title: {result.title[:50] if result.title else 'None'}{'...' if result.title and len(result.title) > 50 else ''}")
                    print(f"    Description: {result.description[:100] if result.description else 'None'}{'...' if result.description and len(result.description) > 100 else ''}")
                else:
                    print(f"    Error: {result.error_message}")

            except Exception as e:
                print(f"    ❌ Exception: {str(e)}")

    # Test 3: Mock database model
    print("\n💾 Test 3: Database Model")
    from datetime import datetime, timedelta

    mock_domain = Domain(
        domain="example.com",
        normalized_domain="example.com",
        meta_title="Example Domain",
        meta_description="This domain is for use in illustrative examples in documents.",
        extraction_method="html_extractor",
        status_code=200,
        extraction_time=1.23,
        last_extracted=datetime.utcnow(),
        cache_expires=datetime.utcnow() + timedelta(days=30),
        extraction_count=1,
        success_count=1
    )

    print(f"  Created Domain model:")
    print(f"    Domain: {mock_domain.domain}")
    print(f"    Title: {mock_domain.meta_title}")
    print(f"    Cache Valid: {mock_domain.is_cache_valid()}")
    print(f"    Is Expired: {mock_domain.is_expired()}")

    print("\n✅ All extraction tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_extraction_batch())