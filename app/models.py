from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator

class ShortenRequest(BaseModel):
    url: HttpUrl
    custom_code: str | None = Field(default=None, min_length=3, max_length=32)
    ttl_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("custom_code")
    @classmethod
    def validate_custom_code(cls, value):
        if value is not None and not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("custom_code may contain only letters, numbers, '-' and '_'")
        return value

class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    original_url: str
    expires_at: datetime | None

class StatsResponse(BaseModel):
    short_code: str
    original_url: str
    click_count: int
    created_at: datetime
    expires_at: datetime | None
    is_active: bool

class DeleteResponse(BaseModel):
    short_code: str
    deleted: bool
