# Clay API Quick Start Guide

## 🚀 Quick Start

### Single Domain Lookup
```bash
curl "https://metadata.eagleinfoservice.com/api/v1/domain?domain=example.com"
```

### Batch Domain Lookup
```bash
curl "https://metadata.eagleinfoservice.com/api/v1/batch?domains=google.com,example.com"
```

---

## 📊 Response Example

```json
{
  "domain": "example.com",
  "normalized_domain": "example.com",
  "status_code": 200,
  "meta_title": "Example Domain",
  "meta_description": null,
  "meta_keywords": null,
  "h1_tag": "Example Domain",
  "first_paragraph": "This domain is for use in documentation...",
  "extraction_method": "redis_cache",
  "extraction_time": 0.001
}
```

---

## 🔗 Clay Integration

### 1. Add HTTP Enrichment
- **Method:** GET
- **URL:** `https://metadata.eagleinfoservice.com/api/v1/domain?domain={{YourDomainColumn}}`

### 2. Map Fields
- `meta_title` → Domain Title
- `meta_description` → Description
- `h1_tag` → Main Heading
- `status_code` → HTTP Status
- `first_paragraph` → Content Preview

### 3. Run Enrichment
Apply to rows with domains and watch data populate!

---

## ✨ Key Features

- ✅ Simple GET requests (no auth required)
- ✅ 30-day caching (instant repeat requests)
- ✅ Batch up to 50 domains
- ✅ Graceful error handling
- ✅ Sub-second average response time

---

## 📖 Full Documentation

See [CLAY_API_DOCUMENTATION.md](./CLAY_API_DOCUMENTATION.md) for complete guide including:
- All endpoints and parameters
- Error handling
- Clay formula examples
- Best practices
- Troubleshooting

---

## 🧪 Test the API

```bash
# Test single domain
curl "https://metadata.eagleinfoservice.com/api/v1/domain?domain=example.com" | jq

# Test batch
curl "https://metadata.eagleinfoservice.com/api/v1/batch?domains=google.com,example.com,github.com" | jq

# Test health
curl "https://metadata.eagleinfoservice.com/health" | jq
```

---

## 🎯 Use Cases

1. **Lead Enrichment** - Add website metadata to company leads
2. **SEO Analysis** - Check meta descriptions and titles
3. **Content Categorization** - Categorize by H1 headings
4. **Website Health** - Verify domains are accessible (status_code)
5. **Competitor Research** - Extract competitor page data

---

## ⚡ Response Times

- **Cached domains:** < 0.01s
- **New domains:** 1-3s
- **Batch (50 domains):** 5-15s

---

## 🛠️ Service Status

- **URL:** https://metadata.eagleinfoservice.com
- **Status:** Running
- **Health Check:** https://metadata.eagleinfoservice.com/health
- **Version:** v1.0

---

## 📝 Notes

- No authentication required
- 30-day cache on all successful extractions
- Graceful handling of rate limits (429) and errors (5xx)
- Works with Clay HTTP enrichment
- Can be called from any tool that supports HTTP requests

---

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| Empty meta_description | Use `first_paragraph` or `h1_tag` instead |
| status_code = 429 | Target site is rate limiting, try again later |
| status_code = 5xx | Target site has server issues |
| extraction_method = "error" | Domain doesn't exist or DNS failure |
| Slow first request | Normal! Subsequent requests will be cached and fast |

---

Made with ❤️ for Clay users
