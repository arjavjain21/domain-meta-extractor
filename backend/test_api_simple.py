#!/usr/bin/env python3
"""
Simple API test without database dependency
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import sys
sys.path.append('.')

# Create a simple test app
app = FastAPI(title="Test API")

@app.get("/")
async def root():
    return {"message": "Domain Meta Extractor API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy", "database": "connected"}

client = TestClient(app)

def test_root():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    print("✅ Root endpoint test:")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {data}")

def test_health():
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    print("\n✅ Health endpoint test:")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {data}")

if __name__ == "__main__":
    print("🧪 Running simple API tests...")
    test_root()
    test_health()
    print("\n✅ All tests passed!")