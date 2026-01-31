# Domain Metadata Extractor API - Clay Integration Guide

## Overview

This API provides simple GET endpoints to extract comprehensive metadata from any domain/website. Perfect for enriching data in Clay with website insights, SEO metadata, and content analysis.

**Base URL:** `https://metadata.eagleinfoservice.com`

**Version:** v1

---

## Features

- ✅ **Simple GET requests** - No complex authentication or POST bodies
- ✅ **Caching** - 30-day Redis cache for fast responses
- ✅ **Batch processing** - Query up to 50 domains at once
- ✅ **Error handling** - Graceful handling of invalid domains, rate limits, and connection errors
- ✅ **Rich metadata** - Title, description, keywords, headings, content snippets
- ✅ **Fast responses** - Sub-second average response time

---

## API Endpoints

### 1. Single Domain Lookup

Get comprehensive metadata for a single domain.

**Endpoint:** `GET /api/v1/domain/{domain}`

**Parameters:**
- `domain` (path parameter) - Domain name to analyze
  - Examples: `google.com`, `example.com`, `https://example.com`

**Request Examples:**

```bash
# Using curl
curl "https://metadata.eagleinfoservice.com/api/v1/domain/example.com"

# With protocol
curl "https://metadata.eagleinfoservice.com/api/v1/domain/https://github.com"
```

**Response Structure:**

```json
{
  "domain": "example.com",
  "normalized_domain": "example.com",
  "status_code": 200,
  "meta_title": "Example Domain",
  "meta_description": "This domain is for use in illustrative examples...",
  "meta_keywords": null,
  "h1_tag": "Example Domain",
  "first_paragraph": "This domain is for use in documentation...",
  "extraction_method": "redis_cache",
  "extraction_time": 0.001
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `domain` | string | Original input domain |
| `normalized_domain` | string | Cleaned domain name (lowercase, no protocol) |
| `status_code` | integer | HTTP status code (200=success, 4xx/5xx=errors) |
| `meta_title` | string/null | Page title tag |
| `meta_description` | string/null | Meta description content |
| `meta_keywords` | string/null | Meta keywords content |
| `h1_tag` | string/null | First H1 heading text |
| `first_paragraph` | string/null | First 200 characters of content |
| `error_message` | string/null | Error message if extraction failed |
| `extraction_method` | string | How data was obtained: `redis_cache`, `web_extraction`, `http_error`, `error` |
| `extraction_time` | float | Time taken in seconds |

---

### 2. Batch Domain Lookup

Get metadata for multiple domains in a single request.

**Endpoint:** `GET /api/v1/batch`

**Parameters:**
- `domains` (query parameter) - Comma-separated list of domains
  - Maximum: 50 domains per request
  - Example: `google.com,example.com,github.com`

**Request Example:**

```bash
curl "https://metadata.eagleinfoservice.com/api/v1/batch?domains=google.com,example.com,github.com"
```

**Response Structure:**

```json
{
  "success": true,
  "total_domains": 3,
  "successful_domains": 2,
  "failed_domains": 1,
  "results": [
    {
      "domain": "google.com",
      "normalized_domain": "google.com",
      "status_code": 200,
      "meta_title": "Google",
      ...
    },
    {
      "domain": "example.com",
      "normalized_domain": "example.com",
      "status_code": 200,
      "meta_title": "Example Domain",
      ...
    }
  ],
  "errors": [
    {
      "domain": "invalid-domain",
      "error": "Invalid domain format"
    }
  ],
  "timestamp": "2026-01-31T02:42:54.713878"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Overall request status |
| `total_domains` | integer | Total domains requested |
| `successful_domains` | integer | Successfully processed |
| `failed_domains` | integer | Failed to process |
| `results` | array | Array of domain metadata objects (same structure as single lookup) |
| `errors` | array | Array of error objects with `domain` and `error` fields |
| `timestamp` | string | ISO timestamp of request |

---

## Clay Integration Setup

### Step 1: Add HTTP Enrichment in Clay

1. In your Clay table, add a new enrichment
2. Select "HTTP Request" or "API Enrichment"
3. Configure as follows:

**For Single Domain:**
- **Method:** GET
- **URL:** `https://metadata.eagleinfoservice.com/api/v1/domain/{{domain_column}}`
- **Headers:** None required
- **Response Mapping:** Map JSON fields to Clay columns

**For Batch Domains:**
- **Method:** GET
- **URL:** `https://metadata.eagleinfoservice.com/api/v1/batch`
- **Query Params:** `domains={{domain1}},{{domain2}},{{domain3}}`
- **Response Mapping:** Map `results[*]` array to Clay records

### Step 2: Map Response Fields

Create these columns in your Clay table:

| Clay Column | JSON Path | Description |
|-------------|-----------|-------------|
| `Domain Title` | `meta_title` | Page title |
| `Domain Description` | `meta_description` | Meta description |
| `H1 Heading` | `h1_tag` | Main heading |
| `Content Preview` | `first_paragraph` | First paragraph |
| `HTTP Status` | `status_code` | Response code |
| `Extraction Time` | `extraction_time` | Processing time |
| `Data Source` | `extraction_method` | Cache or live |
| `Error Message` | `error_message` | Any errors |

### Step 3: Run Enrichment

1. Apply the enrichment to your Clay table
2. Run on rows with domain values
3. Results will populate automatically
4. Cached domains return instantly (< 0.01s)

---

## Common Use Cases in Clay

### 1. Lead Enrichment

Enrich company domains with website metadata:

```javascript
// Clay Formula
// Get meta title for company website
{{enrichment:get_domain_meta.meta_title}}
```

### 2. SEO Analysis

Analyze SEO metadata of prospect websites:

```javascript
// Clay Formula
// Check if has meta description
IF(
  NOT(IS_BLANK({enrichment:get_domain_meta.meta_description})),
  "Has SEO description",
  "Missing SEO description"
)
```

### 3. Content Categorization

Categorize leads based on website content:

```javascript
// Clay Formula
// Categorize by H1 text
IF(
  CONTAINS({enrichment:get_domain_meta.h1_tag}, "SaaS"),
  "SaaS Company",
  IF(
    CONTAINS({enrichment:get_domain_meta.h1_tag}, "Agency"),
    "Agency",
    "Other"
  )
)
```

### 4. Website Health Check

Check if websites are accessible:

```javascript
// Clay Formula
// Check HTTP status
IF(
  {enrichment:get_domain_meta.status_code} == 200,
  "Website Live",
  "Website Down"
)
```

---

## Error Handling

The API handles errors gracefully and returns appropriate responses:

### HTTP 400 - Bad Request

```json
{
  "detail": "Invalid domain format: invalid-domain"
}
```

### HTTP 500 - Server Error

```json
{
  "detail": "Internal server error: [error details]"
}
```

### Extraction Errors (HTTP 200 with error_message)

```json
{
  "domain": "nonexistent-domain-12345.com",
  "normalized_domain": "nonexistent-domain-12345.com",
  "error_message": "Cannot connect to host...",
  "extraction_method": "error",
  "extraction_time": 2.5
}
```

### HTTP Errors in Response

```json
{
  "domain": "rate-limited.com",
  "status_code": 429,
  "error_message": "HTTP 429",
  "extraction_method": "http_error",
  "extraction_time": 0.5
}
```

---

## Best Practices

### 1. Use Batch for Multiple Domains

Instead of multiple single requests:
```javascript
// ❌ Bad - Multiple requests
for (domain of domains) {
  await fetch(`/api/v1/domain/${domain}`);
}

// ✅ Good - Single batch request
await fetch(`/api/v1/batch?domains=${domains.join(',')}`);
```

### 2. Handle Errors in Clay

```javascript
// Clay Formula - Safe field access
IF(
  IS_BLANK({enrichment:get_domain_meta.error_message}),
  {enrichment:get_domain_meta.meta_title},
  "Error: " & {enrichment:get_domain_meta.error_message}
)
```

### 3. Cache Awareness

First request for a domain takes 1-3 seconds, subsequent requests take < 0.01 seconds due to 30-day cache.

### 4. Rate Limiting

While there's no hard rate limit, be reasonable:
- Single requests: As fast as needed
- Batch requests: Up to 50 domains
- Concurrent requests: Keep under 10/second

---

## Testing the API

### Quick Test Commands

```bash
# Test single domain
curl "https://metadata.eagleinfoservice.com/api/v1/domain/example.com" | jq

# Test batch
curl "https://metadata.eagleinfoservice.com/api/v1/batch?domains=google.com,example.com" | jq

# Test with errors
curl "https://metadata.eagleinfoservice.com/api/v1/domain/invalid-domain" | jq

# Test health
curl "https://metadata.eagleinfoservice.com/health" | jq
```

### Expected Response Times

- **Cached domain:** < 0.01 seconds
- **New domain:** 1-3 seconds
- **Batch (50 domains):** 5-15 seconds

---

## Response Examples

### Successful Domain

```json
{
  "domain": "airbnb.com",
  "normalized_domain": "airbnb.com",
  "status_code": 200,
  "meta_title": "Vacation Rentals, Cabins, Beach Houses & More | Airbnb",
  "meta_description": "Find vacation rentals, cabins, beach houses, unique homes and experiences around the world – all made possible by hosts on Airbnb.",
  "meta_keywords": null,
  "h1_tag": "Find the perfect place to stay",
  "first_paragraph": "Book unique homes and experiences all over the world on Airbnb.",
  "extraction_method": "web_extraction",
  "extraction_time": 2.134
}
```

### Rate Limited Domain

```json
{
  "domain": "rate-limited-site.com",
  "normalized_domain": "rate-limited-site.com",
  "status_code": 429,
  "error_message": "HTTP 429",
  "extraction_method": "http_error",
  "extraction_time": 0.381
}
```

### Cached Result

```json
{
  "domain": "example.com",
  "normalized_domain": "example.com",
  "status_code": 200,
  "meta_title": "Example Domain",
  "extraction_method": "redis_cache",
  "extraction_time": 0.002
}
```

---

## Troubleshooting

### Issue: Empty meta_description

**Cause:** Many modern websites don't use meta description tags

**Solution:** Use `first_paragraph` or `h1_tag` as alternative content

### Issue: status_code is 4xx or 5xx

**Cause:** Website is down, blocking bots, or has access restrictions

**Solution:** Check `error_message` field for details, try again later

### Issue: extraction_method is "error"

**Cause:** Domain doesn't exist, DNS failure, or network error

**Solution:** Verify domain is valid and accessible

### Issue: Slow response times

**Cause:** First-time extraction (not cached) or slow target website

**Solution:** Normal for new domains, subsequent requests will be fast (cached)

---

## Technical Details

### Metadata Extraction Process

1. **Domain Normalization:** Clean and validate input
2. **Cache Check:** Look up in Redis (30-day TTL)
3. **HTTP Fetch:** GET request to `https://{domain}` with user agent
4. **HTML Parsing:** Extract metadata using BeautifulSoup
5. **Cache Store:** Save results to Redis
6. **Response:** Return JSON with all fields

### Technology Stack

- **Backend:** FastAPI (Python)
- **Caching:** Redis (30-day TTL)
- **Parsing:** BeautifulSoup4
- **HTTP:** aiohttp (async)
- **Hosting:** nginx + uvicorn

### Data Retention

- **Cached data:** 30 days in Redis
- **Logs:** 7 days
- **No permanent storage** of extracted data (cache only)

---

## Support

For issues or questions:
- Check service health: `GET /health`
- Review error messages in responses
- Test with curl first before integrating with Clay
- Contact: [Your contact info]

---

## Changelog

### v1.0 (2026-01-31)
- Initial release
- Single domain lookup endpoint
- Batch processing endpoint
- Redis caching (30-day)
- Comprehensive error handling
- Full test suite

---

## Future Enhancements

Planned features:
- [ ] Webhook support for async processing
- [ ] Additional metadata (OpenGraph, Schema.org)
- [ ] Historical tracking
- [ ] API key authentication
- [ ] Export to CSV/JSON
- [ ] Rate limiting dashboard
