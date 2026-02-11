# Background Removal Feature

This document describes the automatic background removal feature for amiibo images.

## Overview

The app uses the `rembg` library to automatically remove backgrounds from amiibo images scraped from Nintendo's website. This provides clean, transparent PNG images for display.

### Features

- 🎯 **Smart Processing** - Only processes `is_upcoming=true` amiibos (newly scraped from Nintendo)
- 🤖 **Optimized Model** - Uses `u2net_human_seg` optimized for figures/characters
- ✨ **White Fringe Removal** - Automatically removes white halos around edges
- ⚡ **Fast Caching** - Results cached for 1 hour (configurable)
- 🔒 **Secure** - Domain whitelist prevents abuse

## How It Works

### API Endpoint

The background removal is handled by an on-demand API endpoint:

```
GET /api/remove-bg/?url=<image_url>
```

**Parameters:**
- `url` (required): The URL of the image to process

**Returns:**
- PNG image with transparent background
- Content-Type: `image/png`

**Caching:**
- Results are cached for 1 hour (3600 seconds)
- Cache key is based on MD5 hash of the image URL

**Security:**
- Only processes images from allowed domains:
  - `www.nintendo.com`
  - `assets.nintendo.com`
  - `raw.githubusercontent.com`
  - `amiiboapi.org`

### Template Usage

Use the custom template filter in Django templates:

```django
{% load amiibo_filters %}

<!-- Smart image handling: -->
<!-- - Upcoming amiibos (is_upcoming=True) → Background removed via API -->
<!-- - Official amiibos → Original image (already has transparent background) -->
<img src="{{ amiibo|amiibo_image }}" alt="{{ amiibo.name }}">

<!-- Force original image (no background removal) -->
<img src="{{ amiibo|amiibo_image_original }}" alt="{{ amiibo.name }}">
```

**Note:** Background removal is **only applied to upcoming amiibos** (`is_upcoming=True`) that are newly scraped from Nintendo's website. Official AmiiboAPI images already have transparent backgrounds and don't need processing.

### JavaScript Usage

In JavaScript code, construct the API URL manually:

```javascript
const processedImageUrl = `/api/remove-bg/?url=${encodeURIComponent(amiibo.image)}`;
img.src = processedImageUrl;
```

## Performance Considerations

1. **First Request**: The first time an image is requested, it will be downloaded, processed, and cached. This may take 1-3 seconds.

2. **Subsequent Requests**: Cached images are served instantly from memory.

3. **Session Reuse**: The ML model is loaded once at startup and reused for all requests, improving performance.

## Configuration

### Adjust Cache Duration

Edit `tracker/views_image.py`:

```python
# Cache for 1 hour (default)
cache.set(cache_key, png_bytes, timeout=3600)

# Cache for 1 day
cache.set(cache_key, png_bytes, timeout=86400)
```

### Change ML Model

The app uses `u2net_human_seg` which is optimized for figures and characters (perfect for amiibos!).

To change the model, edit `tracker/views_image.py`:

```python
# Current (optimized for amiibo figures) ✅
_session = new_session("u2net_human_seg")

# Other options:
_session = new_session("u2net")              # Balanced, general purpose
_session = new_session("isnet-general-use")  # Higher quality, slower
_session = new_session("u2netp")             # Faster, lower quality
_session = new_session("silueta")            # Lightweight, very fast
```

### Adjust White Fringe Removal

The app automatically removes white halos/fringes around edges after background removal.

To adjust the sensitivity, edit the `remove_bg()` function in `tracker/views_image.py`:

```python
# Default (removes pixels with RGB > 240)
output_img = remove_white_fringe(output_img, threshold=240)

# More aggressive (removes more white pixels)
output_img = remove_white_fringe(output_img, threshold=230)

# Less aggressive (only removes very white pixels)
output_img = remove_white_fringe(output_img, threshold=250)

# Disable fringe removal (comment out the line)
# output_img = remove_white_fringe(output_img)
```

### Add Allowed Domains

Edit `tracker/views_image.py`:

```python
ALLOWED_DOMAINS = {
    "www.nintendo.com",
    "assets.nintendo.com",
    "your-domain.com",  # Add your domain
}
```

### Disable Background Removal

To use original images without processing, use the `amiibo_image_original` filter:

```django
<img src="{{ amiibo|amiibo_image_original }}" alt="{{ amiibo.name }}">
```

## Dependencies

Required packages (already added to `requirements.txt`):

```
rembg==2.0.61
Pillow==11.1.0
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Download the ML model (first run will auto-download):
```bash
python manage.py shell
>>> from rembg import new_session
>>> new_session()  # Downloads model on first run
```

## Troubleshooting

### Images Not Processing

1. Check that the domain is in `ALLOWED_DOMAINS`
2. Verify the image URL is accessible
3. Check Django logs for error messages

### Slow Performance

1. Ensure the ML model is loaded once at startup (check `_session` in `views_image.py`)
2. Verify caching is working (check cache backend configuration)
3. Consider increasing cache timeout for longer storage

### Memory Usage

The rembg ML model uses approximately 300-400MB of RAM. If memory is constrained:

1. Use a different rembg model (smaller but less accurate)
2. Disable background removal for some image types
3. Reduce cache timeout to free memory faster

## Cloud Run Deployment

### Memory Requirements

**Important:** Cloud Run requires **2Gi (2048 MiB)** of memory for this application due to the rembg ML model running with 2 workers.

The deployment is configured in `.github/workflows/build.yml`:

```yaml
gcloud run services update "$SERVICE_NAME" \
  --memory 2Gi \
  --timeout 300
```

**Why 2Gi?**
- Rembg model per worker: ~300-400 MiB × 2 workers = ~600-800 MiB
- Django + gunicorn: ~100-200 MiB
- Request processing overhead: ~100-200 MiB
- **Total:** ~800-1200 MiB (2Gi provides safe headroom)

### Startup Optimization

To avoid Cloud Run startup timeouts, the rembg model is **pre-downloaded during Docker build**:

**In Dockerfile:**
```dockerfile
# Pre-download rembg model to avoid startup timeout in Cloud Run
RUN python -c "from rembg import new_session; new_session('u2net_human_seg')"
```

This ensures:
- Model is cached in the Docker image
- Container starts quickly (no download needed)
- First request is fast (model already loaded)

### Gunicorn Configuration

**In `scripts/entrypoint.sh`:**
```bash
exec gunicorn amiibo_tracker.wsgi:application \
    --bind 0.0.0.0:8080 \
    --timeout 120 \
    --workers 2 \
    --worker-class gthread \
    --threads 2
```

**Configuration breakdown:**
- **Workers: 2** - Balances concurrency with memory usage (each worker loads the model independently)
- **Worker class: gthread** - Efficient for I/O-bound operations (image processing, HTTP requests)
- **Threads: 2 per worker** - Allows 4 total concurrent requests (2 workers × 2 threads)
- **Timeout: 120s** - Sufficient for background removal operations (typically 1-3s)

### Monitoring

Check Cloud Run logs for memory issues:
```bash
gcloud logging read "resource.type=cloud_run_revision AND severity>=WARNING" --limit 50
```

If you see "Memory limit exceeded" errors:
1. Increase memory: `--memory 2Gi`
2. Reduce workers: `--workers 1`
3. Use lighter model: `u2netp` or `silueta`
