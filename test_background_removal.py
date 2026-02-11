#!/usr/bin/env python
"""
Quick test script for background removal functionality.

Run this after starting the Django dev server:
    python manage.py runserver

Then in another terminal:
    python test_background_removal.py
"""

import requests
from urllib.parse import quote

# Test with a sample Nintendo amiibo image
test_url = "https://assets.nintendo.com/image/upload/f_png/q_auto/amiibo/Kirby%20Air%20RIders/chef-kawasaki-and-hop-star-figure"

# API endpoint
api_url = f"http://localhost:8000/api/remove-bg/?url={quote(test_url, safe='')}"

print("🧪 Testing Background Removal API...")
print(f"   Test Image: {test_url}")
print(f"   API URL: {api_url}\n")

try:
    print("📥 Fetching processed image...")
    response = requests.get(api_url, timeout=30)

    if response.status_code == 200:
        # Save the result
        output_file = "test_output.png"
        with open(output_file, "wb") as f:
            f.write(response.content)

        print(f"✅ SUCCESS!")
        print(f"   Status: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('Content-Type')}")
        print(f"   Size: {len(response.content):,} bytes")
        print(f"   Saved to: {output_file}")
        print("\n💡 Open test_output.png to see the result!")

    else:
        print(f"❌ FAILED!")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")

except requests.RequestException as e:
    print(f"❌ ERROR: {e}")
    print("\n💡 Make sure the Django server is running:")
    print("   python manage.py runserver")
