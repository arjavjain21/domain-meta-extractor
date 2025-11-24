from pydantic import BaseModel, Field
from typing import Optional


class DomainExtractRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=255)


class DomainResponse(BaseModel):
    id: Optional[int] = None
    domain: str
    normalized_domain: str
    metaTitle: Optional[str] = None
    metaDescription: Optional[str] = None
    extractionMethod: Optional[str] = None
    statusCode: Optional[int] = None
    extractionTime: Optional[float] = None
    errorMessage: Optional[str] = None
    lastExtracted: Optional[str] = None
    fromCache: bool = False

    @classmethod
    def from_domain(cls, domain) -> "DomainResponse":
        return cls(
            id=domain.id,
            domain=domain.domain,
            normalized_domain=domain.normalized_domain,
            metaTitle=domain.meta_title,
            metaDescription=domain.meta_description,
            extractionMethod=domain.extraction_method,
            statusCode=domain.status_code,
            extractionTime=float(domain.extraction_time) if domain.extraction_time else None,
            errorMessage=domain.error_message,
            lastExtracted=domain.last_extracted.isoformat() if domain.last_extracted else None,
            fromCache=domain.is_cache_valid()
        )