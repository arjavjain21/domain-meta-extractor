# Domain Meta Extractor - Backend

FastAPI backend for domain metadata extraction with intelligent caching.

## Features

- **Async Processing**: Fast concurrent domain extraction
- **30-Day Caching**: PostgreSQL + Redis for intelligent caching
- **Batch Processing**: Handle thousands of domains efficiently
- **Background Jobs**: Celery for reliable background processing
- **REST API**: Full API with OpenAPI documentation
- **Real-time Updates**: WebSocket support for job progress

## Tech Stack

- FastAPI (async Python web framework)
- PostgreSQL (primary storage with JSONB)
- Redis (caching & job queue)
- Celery (background processing)
- SQLAlchemy (async ORM)
- Alembic (database migrations)
- Pydantic (data validation)

## Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- PostgreSQL 14+
- Redis 7+

### Installation

1. **Clone and setup**:
```bash
git clone <repository>
cd domain-extractor/backend
```

2. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Setup environment variables**:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Database Setup

1. **Start PostgreSQL & Redis**:
```bash
docker-compose up -d postgres redis
```

2. **Run database migrations**:
```bash
cd backend
alembic upgrade head
```

### Running the Application

1. **Development mode**:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. **With Docker Compose**:
```bash
docker-compose up
```

3. **Start Celery worker**:
```bash
celery -A app.celery worker --loglevel=info --concurrency=4
```

## API Documentation

Once running, visit:
- API Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI Schema: http://localhost:8000/openapi.json

## Key Endpoints

### Jobs API
- `POST /api/v1/jobs/upload` - Upload CSV for processing
- `GET /api/v1/jobs/{job_id}` - Get job status
- `GET /api/v1/jobs/{job_id}/download` - Download results
- `GET /api/v1/jobs` - List jobs
- `DELETE /api/v1/jobs/{job_id}` - Delete job

### Domains API
- `GET /api/v1/domains/{domain}` - Get cached domain data
- `POST /api/v1/domains/extract` - Extract single domain
- `GET /api/v1/domains` - Search domains

### Stats API
- `GET /api/v1/stats` - Get system statistics
- `GET /api/v1/stats/daily` - Get daily statistics

## Configuration

Key environment variables:

```env
# Database
DATABASE_URL=postgresql+asyncpg://domain_user:temp12345@localhost:5432/domain_extractor

# Redis
REDIS_URL=redis://localhost:6379
CELERY_BROKER_URL=redis://localhost:6379

# Security
SECRET_KEY=your-secret-key-change-in-production

# Processing
DEFAULT_CONCURRENCY=25
MAX_CONCURRENCY=100
MAX_DOMAINS_PER_FILE=10000

# Cache
CACHE_EXPIRE_DAYS=30
REDIS_CACHE_EXPIRE_SECONDS=3600
```

## Testing

Run tests:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=app tests/
```

## Architecture

### Directory Structure
```
backend/
├── app/
│   ├── api/v1/          # API endpoints
│   ├── core/            # Core configuration
│   ├── models/          # Database models
│   ├── services/        # Business logic
│   ├── schemas/         # Pydantic models
│   └── main.py          # FastAPI application
├── alembic/             # Database migrations
├── tests/               # Test suite
└── requirements.txt     # Python dependencies
```

### Database Schema

- **domains**: Cached domain metadata
- **jobs**: Processing job tracking
- **job_domains**: Job-domain relationships
- **extraction_stats**: Daily statistics

### Processing Pipeline

1. Upload CSV → Create job
2. Cache check → Identify new/expired domains
3. Batch extraction → Concurrent processing
4. Database update → Cache results
5. Generate results → Download CSV

## Performance

- **Concurrent Processing**: 25-50 domains simultaneously
- **Cache Hit Rate**: 80-90% for repeat domains
- **Processing Time**: 2-5 minutes for 10K domains (with cache)
- **Memory Usage**: Optimized batch processing

## Monitoring

- Health check: `GET /health`
- Application metrics via logs
- Celery monitoring with Flower

## Deployment

Production deployment with Docker:

1. Set production environment variables
2. Update SSL certificates
3. Configure nginx reverse proxy
4. Scale workers as needed

```bash
docker-compose -f docker-compose.prod.yml up -d
```

## Security Features

- File type validation (CSV only)
- Size limits on uploads
- Rate limiting per IP
- Input sanitization
- SQL injection prevention via ORM