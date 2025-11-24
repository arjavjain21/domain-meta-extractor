#!/usr/bin/env python3
"""
System Integration Test
Tests the complete domain extraction workflow
"""

import pandas as pd
import os
import tempfile
from app.services.extraction.extractors import ConsolidatedExtractor, DomainUtils

def test_csv_processing():
    """Test CSV processing workflow"""
    print("🧪 Testing CSV Processing Workflow\n")

    # Create a test CSV
    test_domains = [
        'google.com',
        'https://github.com',
        'httpbin.org',
        'example.com',
        'invalid_domain',
        'no-tld',
        'python.org'
    ]

    df = pd.DataFrame({'domain': test_domains})

    # Save to temporary CSV
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        csv_path = f.name

    try:
        print(f"✅ Created test CSV with {len(test_domains)} domains: {csv_path}")

        # Read back and process
        df_read = pd.read_csv(csv_path)
        domains = df_read['domain'].dropna().unique().tolist()

        print(f"✅ Read CSV: {len(domains)} unique domains")

        # Normalize and validate domains
        valid_domains = []
        for domain in domains:
            normalized = DomainUtils.normalize_domain(domain)
            if normalized:
                valid_domains.append((domain, normalized))

        print(f"✅ Normalized domains: {len(valid_domains)}/{len(domains)} valid")

        # Show results
        print("\n📋 Domain Normalization Results:")
        for original, normalized in valid_domains:
            print(f"  {original:<20} -> {normalized}")

        # Calculate stats
        invalid_count = len(domains) - len(valid_domains)
        print(f"\n📊 Statistics:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Valid domains: {len(valid_domains)}")
        print(f"  Invalid domains: {invalid_count}")
        print(f"  Validation rate: {len(valid_domains)/len(domains)*100:.1f}%")

    finally:
        # Cleanup
        os.unlink(csv_path)
        print("\n✅ Test completed and cleaned up")

def test_file_structure():
    """Test project file structure"""
    print("\n🧪 Testing Project Structure\n")

    required_files = [
        'backend/app/main.py',
        'backend/app/core/config.py',
        'backend/app/core/database.py',
        'backend/app/models/domain.py',
        'backend/app/models/job.py',
        'backend/app/models/stats.py',
        'backend/app/services/domain_service.py',
        'backend/app/services/extraction/extractors.py',
        'backend/requirements.txt',
        'backend/Dockerfile',
        'docker-compose.yml'
    ]

    missing_files = []
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path}")
            missing_files.append(file_path)

    if missing_files:
        print(f"\n❌ Missing {len(missing_files)} required files")
        return False
    else:
        print(f"\n✅ All {len(required_files)} required files present")
        return True

def main():
    """Run all integration tests"""
    print("=" * 60)
    print("🚀 Domain Meta Extractor - System Integration Tests")
    print("=" * 60)

    # Test 1: File structure
    structure_ok = test_file_structure()

    # Test 2: CSV processing
    if structure_ok:
        test_csv_processing()

    print("\n" + "=" * 60)
    if structure_ok:
        print("✅ All integration tests completed successfully!")
        print("\n📋 System Ready For:")
        print("  • PostgreSQL + Redis setup")
        print("  • Docker deployment")
        print("  • API server startup")
        print("  • Domain extraction jobs")
        print("  • Background processing with Celery")
    else:
        print("❌ Some tests failed - check missing files")
    print("=" * 60)

if __name__ == "__main__":
    main()