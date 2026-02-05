# Demo Page for Google AdSense

## Overview

A publicly accessible demo page has been created to allow Google AdSense crawlers to access meaningful content without requiring OAuth authentication. This solves the problem where the main app is behind authentication.

## What Was Created

### 1. Demo Page (`/demo/`)
- **URL**: https://goozamiibo.com/demo/
- **Template**: `tracker/templates/tracker/demo.html`
- **View**: `DemoView` in `tracker/views.py`

### 2. Key Features

#### Publicly Accessible
- No authentication required
- Crawlable by Google bots
- Includes Google AdSense tags

#### Purely Client-Side
- No backend API calls to Google Sheets
- All data loaded from static JSON file
- "Collected" state stored in browser localStorage
- No database interactions

#### Full UI/UX Replication
- Same design as the authenticated app
- All filtering and search features work
- Dark mode toggle
- Type filters
- Collection tracking (local only)

### 3. Data Source

The demo loads Amiibo data from the existing API endpoint:
```
/api/amiibo/
```

This reuses the `AmiiboDatabaseView` which:
- Fetches from remote API first (amiiboapi.com)
- Falls back to local `tracker/amiibo_database.json` if remote unavailable
- No duplicate files needed - single source of truth

### 4. Entry Points

Two ways to access the demo:

1. **From Landing Page**: "View Demo" button on homepage (index.html)
2. **Direct URL**: `/demo/`

### 5. Banner

The demo includes a prominent banner at the top:
> "This is a demo version with sample data. Sign in with Google to track your own collection!"

This clearly indicates it's a demo and provides a call-to-action to convert visitors.

## Technical Details

### Client-Side Storage

The demo uses browser localStorage to persist:
- Collected items: `amiibo_demo_collected`
- Dark mode preference: `amiibo_demo_dark_mode`
- Type filter preferences: `amiibo_demo_type_filters`

### Minimal Backend Dependencies

**No Authentication Required:**
- Does NOT require OAuth/login
- Does NOT require authentication cookies
- Does NOT make any API requests to Google Sheets

**Only Backend Call:**
- Fetches Amiibo catalog from `/api/amiibo/` (public endpoint)
- This is a read-only operation with no authentication

**Client-Side State:**
- Does NOT call `/toggle/` endpoint
- Does NOT call `/toggle-dark-mode/` endpoint
- Does NOT call `/toggle-type-filter/` endpoint
- All user interactions stored in localStorage

### SEO & AdSense Friendly

- Includes `<meta name="description">` for SEO
- Google AdSense script tag included
- Meaningful HTML content for crawlers
- No authentication barriers

## Files Modified/Created

### Created
- `tracker/templates/tracker/demo.html` - Demo page template
- `DEMO_PAGE_README.md` - This documentation

### Modified
- `tracker/views.py` - Added `DemoView` class
- `tracker/urls.py` - Added `/demo/` route and imported `DemoView`
- `tracker/templates/tracker/index.html` - Added "View Demo" button

## Testing

To test the demo page locally:

```bash
source env/bin/activate
python manage.py runserver
```

Then visit: http://localhost:8000/demo/

## Deployment Notes

When deploying to production:

1. **Static Files**: Ensure `python manage.py collectstatic` is run
2. **WhiteNoise**: Already configured to serve static files in production
3. **No Additional Config**: No environment variables or settings changes needed

## Google AdSense Verification

The demo page should now be accessible to Google AdSense crawlers for:
- Content verification
- Ad placement approval
- Site quality assessment

Since it's not behind OAuth, crawlers can freely access and evaluate the content.

## User Flow

```
Visitor lands on homepage
    ↓
Clicks "View Demo" button
    ↓
Views fully functional demo with sample data
    ↓
Clicks "Sign in with Google" in banner
    ↓
Returns to homepage → OAuth flow → Full app
```

## Future Enhancements (Optional)

- Add analytics tracking to measure demo engagement
- Add more prominent CTAs to convert demo users
- Create a "Sign up" button within the demo interface
- Add a tooltip explaining "This is demo data" on first visit
