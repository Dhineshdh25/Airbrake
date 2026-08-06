#!/usr/bin/env python3
"""
Test script for Jira API endpoints in the Python backend.
Run this after starting the Python Flask server.
"""

import requests
import sys

BASE_URL = "http://localhost:3001"
HEADERS = {
    "Authorization": "Bearer dev-token-developer",
    "X-Device-ID": "test-device-123",
    "Accept": "application/json",
}


def test_endpoint(name, method, url, expected_status=200, **kwargs):
    """Test an API endpoint and print results."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")
    print(f"Method: {method}")
    print(f"URL: {url}")
    
    try:
        if method == "GET":
            response = requests.get(url, headers=HEADERS, timeout=10, **kwargs)
        elif method == "POST":
            response = requests.post(url, headers=HEADERS, timeout=10, **kwargs)
        else:
            print(f"❌ Unsupported method: {method}")
            return False
        
        print(f"Status Code: {response.status_code}")
        
        # Parse JSON response
        try:
            data = response.json()
            print(f"Response:")
            import json
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Response text: {response.text[:500]}")
        
        # Check if status matches expected
        if response.status_code == expected_status:
            print(f"✅ PASS - Status code matches expected {expected_status}")
            return True
        elif response.status_code == 401 and "jira" in url.lower():
            print(f"⚠️  EXPECTED - Jira not connected (401 Unauthorized)")
            return True
        else:
            print(f"❌ FAIL - Expected {expected_status}, got {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ FAIL - Could not connect to {BASE_URL}")
        print(f"Make sure the Python backend is running:")
        print(f"  cd backend-python")
        print(f"  python -c \"from app import app; app.run(port=3001, debug=True)\"")
        return False
    except Exception as e:
        print(f"❌ FAIL - Error: {e}")
        return False


def main():
    """Run all tests."""
    print("="*60)
    print("Jira API Test Suite - Python Backend")
    print("="*60)
    
    results = []
    
    # Test 1: Check Jira status
    results.append(test_endpoint(
        "GET /api/jira/status",
        "GET",
        f"{BASE_URL}/api/jira/status",
        expected_status=200
    ))
    
    # Test 2: Check if search endpoint exists (will fail with 401 if not connected)
    results.append(test_endpoint(
        "GET /api/jira/search",
        "GET",
        f"{BASE_URL}/api/jira/search?jql=ORDER BY updated DESC&maxResults=10",
        expected_status=401  # Expected to fail with 401 if Jira not connected
    ))
    
    # Test 3: Test search without JQL parameter (should return 400)
    results.append(test_endpoint(
        "GET /api/jira/search (no JQL)",
        "GET",
        f"{BASE_URL}/api/jira/search",
        expected_status=400
    ))
    
    # Test 4: Check tickets endpoint (database query)
    results.append(test_endpoint(
        "GET /api/jira/tickets",
        "GET",
        f"{BASE_URL}/api/jira/tickets",
        expected_status=200
    ))
    
    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
