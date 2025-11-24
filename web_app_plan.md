# Web Application Plan: Domain Meta Extractor with Database Caching

## 🎯 **Overview**
Transform the standalone script into a scalable web application with intelligent 30-day caching, built for Ubuntu VPS at OVH.

## 🏗️ **Technical Architecture**

### **Core Technology Stack**
- **Backend**: FastAPI (async Python) - High performance, auto-docs
- **Database**: PostgreSQL - Primary storage with JSONB
- **Cache**: Redis - In-memory caching & job queue
- **Queue**: Celery - Background processing
- **Frontend**: Vue.js 3 + TypeScript - Modern reactive UI
- **Deployment**: Docker + Nginx - Production-ready

### **Smart Caching System**
- **30-day cache window** for domain metadata
- **Cache-first lookup**: Redis → PostgreSQL → Fresh extraction
- **Intelligent upserts**: Update existing, insert new
- **Performance boost**: 80-90% cache hit rate for repeat domains

## 📊 **Database Schema Design**

### **Core Tables**

```sql
-- Domains table with caching metadata
CREATE TABLE domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) UNIQUE NOT NULL,
    normalized_domain VARCHAR(255) UNIQUE NOT NULL,
    meta_title VARCHAR(500),
    meta_description TEXT,
    extraction_method VARCHAR(50),
    status_code INTEGER,
    extraction_time DECIMAL(5,2),
    error_message TEXT,
    last_extracted TIMESTAMP WITH TIME ZONE,
    cache_expires TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    extraction_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0
);

-- Jobs table for tracking processing batches
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) DEFAULT 'pending', -- pending, running, completed, failed
    total_domains INTEGER,
    processed_domains INTEGER DEFAULT 0,
    successful_domains INTEGER DEFAULT 0,
    failed_domains INTEGER DEFAULT 0,
    original_filename VARCHAR(255),
    file_path VARCHAR(500),
    result_file_path VARCHAR(500),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(100), -- IP address or user identifier
    config JSONB -- Processing configuration
);

-- Job domains relationship
CREATE TABLE job_domains (
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    domain_id INTEGER REFERENCES domains(id) ON DELETE CASCADE,
    original_row_index INTEGER,
    status VARCHAR(20) DEFAULT 'pending', -- pending, processing, completed, failed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (job_id, domain_id)
);

-- Extraction statistics for analytics
CREATE TABLE extraction_stats (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    total_requests INTEGER DEFAULT 0,
    successful_extractions INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    cache_misses INTEGER DEFAULT 0,
    average_extraction_time DECIMAL(5,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### **Indexes for Performance**
```sql
CREATE INDEX idx_domains_normalized_domain ON domains(normalized_domain);
CREATE INDEX idx_domains_cache_expires ON domains(cache_expires);
CREATE INDEX idx_domains_last_extracted ON domains(last_extracted);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at);
CREATE INDEX idx_job_domains_status ON job_domains(status);
```

## 🚀 **Processing Pipeline**

### **Smart Workflow**
1. **Upload CSV** → Analyze domains
2. **Cache Check** → Identify existing data (<30 days)
3. **Batch Processing** → Extract only new/expired domains
4. **Database Upsert** → Update existing, insert new
5. **Results Generation** → Merge cached + fresh data

### **Performance Benefits**
- **80% reduction** in processing time for repeat domains
- **Concurrent processing** with configurable worker pools
- **Real-time progress** via WebSocket updates
- **Resilient processing** survives server restarts

## 🌐 **API Design**

### **REST Endpoints**

```python
# Main API endpoints
POST /api/v1/upload          # Upload CSV file
GET  /api/v1/jobs/{job_id}   # Get job status
GET  /api/v1/jobs/{job_id}/download # Download results
GET  /api/v1/jobs            # List user jobs
DELETE /api/v1/jobs/{job_id} # Cancel/delete job

POST /api/v1/extract         # Direct domain extraction
GET  /api/v1/domains/{domain} # Get cached domain data
GET  /api/v1/stats           # System statistics

WebSocket /ws/jobs/{job_id}  # Real-time progress updates
```

### **Request/Response Formats**

```typescript
// Upload request
interface UploadRequest {
  file: File;
  config: {
    maxDomains?: number;
    concurrency?: number;
    timeout?: number;
    maxRetries?: number;
  };
}

// Job response
interface JobResponse {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: {
    total: number;
    processed: number;
    successful: number;
    failed: number;
    percentage: number;
  };
  estimatedTimeRemaining?: number;
  createdAt: string;
  config: ProcessingConfig;
}

// Domain extraction result
interface DomainResult {
  domain: string;
  metaTitle: string;
  metaDescription: string;
  extractionMethod: string;
  statusCode: number;
  extractionTime: number;
  fromCache: boolean;
  errorMessage?: string;
}
```

## 🖥️ **Web Interface Features**

### **User Experience**
- **Drag & drop CSV upload** with file validation
- **Instant preview** showing domain analysis
- **Real-time progress bar** with percentage and ETA
- **Results table** with sorting and filtering
- **Download enhanced CSV** with metadata columns

### **Progress Tracking**
- **WebSocket updates** for real-time status
- **Job persistence** survives browser refresh
- **Email notifications** (optional) for completion
- **Job history** with result access

## 🛠️ **Implementation Phases**

### **Phase 1: Foundation (2 weeks)**
1. **Set up project structure**
   ```
   domain-extractor/
   ├── backend/
   │   ├── app/
   │   │   ├── api/
   │   │   ├── core/
   │   │   ├── models/
   │   │   └── services/
   │   ├── tests/
   │   ├── requirements.txt
   │   └── Dockerfile
   ├── frontend/
   │   ├── src/
   │   ├── public/
   │   └── package.json
   └── docker-compose.yml
   ```

2. **Database models and migrations**
   - SQLAlchemy models based on schema
   - Alembic migrations setup
   - Database indexes and constraints

3. **Core API structure**
   - FastAPI application setup
   - Database connection and session management
   - Basic health check endpoints

4. **Adapt existing extraction logic**
   - Refactor extractors to work with database models
   - Implement caching layer
   - Add error handling and logging

### **Phase 2: Background Processing (2 weeks)**

1. **Celery integration**
   - Task definitions and queue setup
   - Worker configuration and monitoring
   - Error handling and retry logic

2. **File processing pipeline**
   - CSV upload and validation
   - Domain normalization and deduplication
   - Batch processing with cache checking

3. **Progress tracking**
   - WebSocket implementation
   - Real-time progress broadcasting
   - Job state management

4. **Cache management**
   - Redis integration for fast lookup
   - Cache expiration and cleanup
   - Cache hit/miss analytics

### **Phase 3: Frontend & UI (1-2 weeks)**

1. **Vue.js application setup**
   - Vite build configuration
   - Router and state management
   - Component library integration

2. **Core UI components**
   - File upload with drag & drop
   - Progress tracking interface
   - Results display and export

3. **WebSocket integration**
   - Real-time progress updates
   - Connection management
   - Error handling

4. **Responsive design**
   - Mobile-friendly interface
   - Accessibility features
   - Performance optimization

### **Phase 4: Production Deployment (1 week)**

1. **Production configuration**
   - Environment variables management
   - Security hardening
   - SSL certificate setup

2. **Monitoring and logging**
   - Application metrics
   - Error tracking
   - Performance monitoring

3. **Scaling considerations**
   - Horizontal worker scaling
   - Database connection pooling
   - Load balancing

## 🐳 **Deployment Architecture**

### **Docker Compose Configuration**

```yaml
version: '3.8'
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/ssl
    depends_on:
      - api
      - frontend

  api:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/domain_extractor
      - REDIS_URL=redis://redis:6379
      - CELERY_BROKER_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis
    volumes:
      - ./uploads:/app/uploads
      - ./results:/app/results

  worker:
    build: ./backend
    command: celery -A app.celery worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/domain_extractor
      - REDIS_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis
    volumes:
      - ./uploads:/app/uploads
      - ./results:/app/results

  postgres:
    image: postgres:14
    environment:
      - POSTGRES_DB=domain_extractor
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  frontend:
    build: ./frontend
    environment:
      - VUE_APP_API_URL=http://localhost/api

volumes:
  postgres_data:
  redis_data:
```

### **Nginx Configuration**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }

    # WebSocket proxy
    location /ws/ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # File upload limits
    client_max_body_size 100M;
}
```

## ⚡ **Performance Considerations**

### **Caching Strategy**
```python
# Cache-first approach
async def get_domain_data(domain: str) -> Optional[DomainResult]:
    # Check Redis cache first (fastest)
    cached_data = await redis.get(f"domain:{domain}")
    if cached_data:
        return DomainResult.from_json(cached_data), True

    # Check database cache
    db_domain = await session.get(Domain, normalized_domain)
    if db_domain and not db_domain.is_expired():
        # Refresh Redis cache
        await redis.setex(f"domain:{domain}", 3600, db_domain.to_json())
        return DomainResult.from_db(db_domain), True

    return None, False
```

### **Batch Processing Optimization**
```python
# Intelligent batching
async def process_domains_batch(domains: List[str], batch_size: int = 100):
    # Group domains by cache status
    cached_domains, fresh_domains = await separate_cached_domains(domains)

    # Process fresh domains in batches
    for i in range(0, len(fresh_domains), batch_size):
        batch = fresh_domains[i:i + batch_size]
        results = await process_concurrent(batch)
        await cache_results(results)

        # Update progress
        await update_job_progress(len(batch))
```

## 🔧 **Resource Requirements for OVH VPS**

### **Minimum Specs**
- **CPU**: 2-4 cores
- **RAM**: 4-8 GB
- **Storage**: 50 GB SSD
- **OS**: Ubuntu 20.04+

### **Expected Performance**
- **Concurrent processing**: 25-50 domains
- **Cache hit rate**: 80-90% after initial runs
- **Processing time**: 2-5 minutes for 10K domains (with cache)
- **Users supported**: 50-100 concurrent

## 🔒 **Security & Reliability**

### **Security Features**
- **File validation** (CSV only, size limits)
- **Rate limiting** per IP
- **Input sanitization**
- **SSL certificates**
- **Database connection security**

### **Reliability Features**
- **Job persistence** survives restarts
- **Error recovery** with retry logic
- **Circuit breaker** pattern for external failures
- **Comprehensive logging** and monitoring

### **Error Handling & Resilience**

#### **Retry Logic**
```python
# Exponential backoff retry
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
)
async def extract_with_retry(domain: str) -> ExtractionResult:
    # Extraction logic
```

#### **Circuit Breaker Pattern**
```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure = 0
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
```

## 🚀 **Getting Started**

### **Prerequisites on Ubuntu VPS**
```bash
# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Install additional dependencies
apt update
apt install -y python3-pip nginx certbot
```

### **Installation Steps**
1. Clone the repository
2. Configure environment variables
3. Set up SSL certificates
4. Run with Docker Compose
5. Configure monitoring

This comprehensive plan provides a production-ready solution that will dramatically improve processing speed through intelligent caching while providing a professional web interface for domain extraction needs.