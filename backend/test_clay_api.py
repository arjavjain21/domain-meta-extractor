#!/usr/bin/env python3
"""
Functional tests for Clay API endpoints
Tests the simple GET endpoints for domain metadata extraction
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any

BASE_URL = "http://127.0.0.1:8003"

async def test_single_domain():
    """Test GET /api/v1/domain/{domain}"""
    print("\n" + "="*60)
    print("TEST 1: Single Domain Lookup")
    print("="*60)

    test_cases = [
        ("google.com", "Valid domain"),
        ("example.com", "Simple domain"),
        ("https://github.com", "Domain with protocol"),
        ("invalid-domain", "Invalid domain should return 400")
    ]

    async with aiohttp.ClientSession() as session:
        for domain, description in test_cases:
            print(f"\n📝 Testing: {description}")
            print(f"   Domain: {domain}")

            try:
                async with session.get(f"{BASE_URL}/api/v1/domain/{domain}") as response:
                    status = response.status
                    data = await response.json()

                    if status == 200:
                        print(f"   ✅ Status: {status}")
                        print(f"   📊 Keys: {list(data.keys())}")
                        if 'meta_title' in data:
                            print(f"   🏷️  Title: {data.get('meta_title', 'N/A')[:50]}")
                        if 'extraction_time' in data:
                            print(f"   ⏱️  Time: {data.get('extraction_time', 'N/A'):.3f}s")
                    else:
                        print(f"   ⚠️  Status: {status}")
                        print(f"   📄 Detail: {data.get('detail', 'N/A')}")

            except Exception as e:
                print(f"   ❌ Error: {str(e)}")

    print("\n✅ Test 1 completed")

async def test_batch_domains():
    """Test GET /api/v1/batch?domains=..."""
    print("\n" + "="*60)
    print("TEST 2: Batch Domain Lookup")
    print("="*60)

    test_cases = [
        ("google.com,example.com", "Two valid domains"),
        ("google.com,invalid,example.com", "Mixed valid/invalid"),
        ("", "Empty should fail"),
    ]

    async with aiohttp.ClientSession() as session:
        for domains, description in test_cases:
            print(f"\n📝 Testing: {description}")
            print(f"   Domains: {domains if domains else '(empty)'}")

            try:
                async with session.get(f"{BASE_URL}/api/v1/batch", params={"domains": domains}) as response:
                    status = response.status
                    if response.status == 200:
                        data = await response.json()
                        print(f"   ✅ Status: {status}")
                        print(f"   📊 Total: {data.get('total_domains', 0)}")
                        print(f"   ✅ Successful: {data.get('successful_domains', 0)}")
                        print(f"   ❌ Failed: {data.get('failed_domains', 0)}")
                    else:
                        data = await response.json()
                        print(f"   ⚠️  Status: {status}")
                        print(f"   📄 Detail: {data.get('detail', 'N/A')}")

            except Exception as e:
                print(f"   ❌ Error: {str(e)}")

    print("\n✅ Test 2 completed")

async def test_cache_performance():
    """Test if caching works by making same request twice"""
    print("\n" + "="*60)
    print("TEST 3: Cache Performance")
    print("="*60)

    domain = "example.com"
    print(f"\n📝 Testing cache with domain: {domain}")

    async with aiohttp.ClientSession() as session:
        # First request
        print("\n1️⃣  First request (should hit web):")
        try:
            async with session.get(f"{BASE_URL}/api/v1/domain/{domain}") as response:
                data1 = await response.json()
                method1 = data1.get('extraction_method', 'unknown')
                time1 = data1.get('extraction_time', 0)
                print(f"   Method: {method1}")
                print(f"   Time: {time1:.3f}s")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            return

        # Wait a bit
        await asyncio.sleep(1)

        # Second request
        print("\n2️⃣  Second request (should hit cache):")
        try:
            async with session.get(f"{BASE_URL}/api/v1/domain/{domain}") as response:
                data2 = await response.json()
                method2 = data2.get('extraction_method', 'unknown')
                time2 = data2.get('extraction_time', 0)
                print(f"   Method: {method2}")
                print(f"   Time: {time2:.3f}s")

                if method1 != method2:
                    print(f"\n   ✅ Cache working! Method changed from {method1} to {method2}")
                    speedup = time1 / time2 if time2 > 0 else 0
                    print(f"   🚀 Speedup: {speedup:.1f}x faster")
                else:
                    print(f"\n   ⚠️  Same method both times - cache may not be working")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")

    print("\n✅ Test 3 completed")

async def test_response_structure():
    """Test response has all expected fields"""
    print("\n" + "="*60)
    print("TEST 4: Response Structure Validation")
    print("="*60)

    expected_fields = [
        'domain',
        'normalized_domain',
        'status_code',
        'meta_title',
        'meta_description',
        'extraction_method',
        'extraction_time'
    ]

    print(f"\n📝 Testing response structure for example.com")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{BASE_URL}/api/v1/domain/example.com") as response:
                data = await response.json()

                print("\n📋 Checking expected fields:")
                all_present = True
                for field in expected_fields:
                    present = field in data
                    status = "✅" if present else "❌"
                    print(f"   {status} {field}: {present}")
                    if not present:
                        all_present = False

                if all_present:
                    print("\n✅ All expected fields present!")
                else:
                    print("\n⚠️  Some fields missing")

                print("\n📊 Sample data:")
                for key, value in list(data.items())[:5]:
                    value_str = str(value)[:50] if value else "None"
                    print(f"   {key}: {value_str}")

        except Exception as e:
            print(f"   ❌ Error: {str(e)}")

    print("\n✅ Test 4 completed")

async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧪 CLAY API FUNCTIONAL TESTS")
    print("="*60)
    print(f"🌐 Base URL: {BASE_URL}")
    print(f"⏰ Started at: {asyncio.get_event_loop().time()}")

    try:
        await test_single_domain()
        await test_batch_domains()
        await test_cache_performance()
        await test_response_structure()

        print("\n" + "="*60)
        print("🎉 ALL TESTS COMPLETED")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Test suite failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
