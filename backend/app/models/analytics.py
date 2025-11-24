"""
Analytics models for Phase 3
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, BigInteger, ForeignKey, Date, ARRAY
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import enum

Base = declarative_base()


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


# SQLAlchemy Models
class RequestMetric(Base):
    """Model for tracking API request metrics"""
    __tablename__ = "request_metrics"
    __table_args__ = {"schema": "analytics"}

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time = Column(Float, nullable=False)  # in milliseconds
    user_id = Column(String(255))
    user_agent = Column(Text)
    ip_address = Column(INET)
    request_size = Column(BigInteger)
    response_size = Column(BigInteger)
    cache_hit = Column(Boolean, default=False)
    error_message = Column(Text)


class ExtractionMetric(Base):
    """Model for tracking domain extraction metrics"""
    __tablename__ = "extraction_metrics"
    __table_args__ = {"schema": "analytics"}

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    job_id = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    extraction_time = Column(Float)  # in seconds
    cache_hit = Column(Boolean, default=False)
    extraction_method = Column(String(100))
    status_code = Column(Integer)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    concurrent_tasks = Column(Integer)
    worker_id = Column(String(255))


class SystemMetric(Base):
    """Model for system performance metrics"""
    __tablename__ = "system_metrics"
    __table_args__ = {"schema": "analytics"}

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    cpu_usage = Column(Float)  # percentage
    memory_usage = Column(Float)  # percentage
    disk_usage = Column(Float)  # percentage
    active_connections = Column(Integer, default=0)
    queue_length = Column(Integer, default=0)
    workers_active = Column(Integer, default=0)
    workers_total = Column(Integer, default=0)
    redis_memory_usage = Column(BigInteger)  # in bytes
    redis_connected_clients = Column(Integer)
    database_connections = Column(Integer)
    database_size = Column(BigInteger)  # in bytes


class DomainStat(Base):
    """Model for daily domain statistics"""
    __tablename__ = "domain_stats"
    __table_args__ = {"schema": "analytics"}

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    date = Column(Date, nullable=False)
    total_domains_extracted = Column(Integer, default=0)
    successful_extractions = Column(Integer, default=0)
    failed_extractions = Column(Integer, default=0)
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    avg_extraction_time = Column(Float)
    unique_domains = Column(Integer, default=0)
    top_domains = Column(JSONB)  # top 10 domains by frequency
    error_types = Column(JSONB)  # error types and counts


class UserActivity(Base):
    """Model for tracking user activity"""
    __tablename__ = "user_activity"
    __table_args__ = {"schema": "analytics"}

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    user_id = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(String(255))
    metadata = Column(JSONB)
    ip_address = Column(INET)
    user_agent = Column(Text)


class Alert(Base):
    """Model for system alerts"""
    __tablename__ = "alerts"
    __table_args__ = {"schema": "analytics"}

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    severity = Column(String(20), nullable=False)
    alert_type = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSONB)
    status = Column(String(20), default="active")
    acknowledged_by = Column(String(255))
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_by = Column(String(255))
    tags = Column(ARRAY(String))


# Pydantic Models for API serialization
class RequestMetricCreate(BaseModel):
    endpoint: str
    method: str
    status_code: int
    response_time: float
    user_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    request_size: Optional[int] = None
    response_size: Optional[int] = None
    cache_hit: bool = False
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class RequestMetricResponse(BaseModel):
    id: int
    timestamp: datetime
    endpoint: str
    method: str
    status_code: int
    response_time: float
    user_id: Optional[str]
    cache_hit: bool
    error_message: Optional[str]

    class Config:
        from_attributes = True


class ExtractionMetricCreate(BaseModel):
    job_id: str
    domain: str
    status: str
    extraction_time: Optional[float] = None
    cache_hit: bool = False
    extraction_method: Optional[str] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    concurrent_tasks: Optional[int] = None
    worker_id: Optional[str] = None

    class Config:
        from_attributes = True


class ExtractionMetricResponse(BaseModel):
    id: int
    timestamp: datetime
    job_id: str
    domain: str
    status: str
    extraction_time: Optional[float]
    cache_hit: bool
    extraction_method: Optional[str]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class SystemMetricCreate(BaseModel):
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    disk_usage: Optional[float] = None
    active_connections: int = 0
    queue_length: int = 0
    workers_active: int = 0
    workers_total: int = 0
    redis_memory_usage: Optional[int] = None
    redis_connected_clients: Optional[int] = None
    database_connections: Optional[int] = None
    database_size: Optional[int] = None

    class Config:
        from_attributes = True


class SystemMetricResponse(BaseModel):
    id: int
    timestamp: datetime
    cpu_usage: Optional[float]
    memory_usage: Optional[float]
    disk_usage: Optional[float]
    active_connections: int
    queue_length: int
    workers_active: int
    workers_total: int

    class Config:
        from_attributes = True


class AlertCreate(BaseModel):
    severity: AlertSeverity
    alert_type: str
    message: str
    details: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None

    class Config:
        from_attributes = True


class AlertResponse(BaseModel):
    id: int
    created_at: datetime
    resolved_at: Optional[datetime]
    severity: AlertSeverity
    alert_type: str
    message: str
    details: Optional[Dict[str, Any]]
    status: AlertStatus
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]
    resolved_by: Optional[str]
    tags: Optional[List[str]]

    class Config:
        from_attributes = True


class AlertUpdate(BaseModel):
    status: Optional[AlertStatus] = None
    acknowledged_by: Optional[str] = None
    resolved_by: Optional[str] = None

    class Config:
        from_attributes = True


class UserActivityCreate(BaseModel):
    user_id: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    class Config:
        from_attributes = True


class UserActivityResponse(BaseModel):
    id: int
    timestamp: datetime
    user_id: str
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]

    class Config:
        from_attributes = True


# Analytics response models
class HourlyStats(BaseModel):
    hour: datetime
    total_extractions: int
    successful: int
    failed: int
    avg_extraction_time: Optional[float]
    cache_hits: int
    cache_misses: int

    class Config:
        from_attributes = True


class DailyStats(BaseModel):
    date: datetime
    unique_domains: int
    total_extractions: int
    successful: int
    avg_extraction_time: Optional[float]

    class Config:
        from_attributes = True


class OverviewStats(BaseModel):
    total_domains_extracted: int = Field(default=0, description="Total number of domains extracted")
    successful_extractions: int = Field(default=0, description="Number of successful extractions")
    failed_extractions: int = Field(default=0, description="Number of failed extractions")
    cache_hit_rate: float = Field(default=0.0, description="Cache hit rate percentage")
    avg_extraction_time: float = Field(default=0.0, description="Average extraction time in seconds")
    active_jobs: int = Field(default=0, description="Number of currently active jobs")
    queue_length: int = Field(default=0, description="Number of items in queue")
    system_health: str = Field(default="healthy", description="Overall system health status")


class PerformanceMetrics(BaseModel):
    timestamp: datetime
    avg_response_time: float
    p95_response_time: float
    requests_per_second: float
    error_rate: float
    cpu_usage: Optional[float]
    memory_usage: Optional[float]


class TopDomains(BaseModel):
    domain: str
    extraction_count: int
    success_rate: float
    avg_extraction_time: float


class ErrorAnalysis(BaseModel):
    error_type: str
    count: int
    percentage: float
    trend: str  # 'increasing', 'decreasing', 'stable'


class TrendData(BaseModel):
    timestamp: datetime
    value: float
    metric: str


class AnalyticsQuery(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    metric: Optional[str] = None
    aggregation: Optional[str] = Field(default="hour", regex="^(minute|hour|day|week|month)$")
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = Field(default=100, le=1000)
    offset: Optional[int] = Field(default=0, ge=0)