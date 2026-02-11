#!/usr/bin/env python3
"""
Script to update blog_posts.json with featured_image references
"""
import json
from pathlib import Path

# Path to blog_posts.json
blog_posts_path = Path("tracker/data/blog_posts.json")

# Read the current blog posts
with blog_posts_path.open(encoding="utf-8") as f:
    data = json.load(f)

# Add featured_image field to each post
for post in data["posts"]:
    slug = post["slug"]
    # Set the featured_image path using Django static template path
    post["featured_image"] = f"images/blog/{slug}.png"

# Write back to the file with proper formatting
with blog_posts_path.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"✓ Updated {len(data['posts'])} blog posts with featured_image references")
print("\nUpdated posts:")
for post in data["posts"]:
    print(f"  • {post['slug']}: {post['featured_image']}")
