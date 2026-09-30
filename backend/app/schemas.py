import re
from pydantic import BaseModel, Field, field_validator
EMAIL_RE=re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    @field_validator('email')
    @classmethod
    def validate_email(cls,value:str)->str:
        value=value.strip().lower()
        if not EMAIL_RE.fullmatch(value): raise ValueError('invalid email address')
        return value
class LoginRequest(RegisterRequest):
    password: str = Field(min_length=1, max_length=128)
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
class ChunkDescriptor(BaseModel):
    index: int = Field(ge=0)
    hash: str = Field(min_length=64, max_length=64)
    size: int = Field(ge=0)
    @field_validator('hash')
    @classmethod
    def hex_hash(cls, value: str) -> str:
        value=value.lower()
        if any(c not in '0123456789abcdef' for c in value): raise ValueError('hash must be lowercase SHA-256 hex')
        return value
class UploadSessionCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    expected_size: int = Field(ge=0)
    content_type: str | None = None
    chunks: list[ChunkDescriptor]
class SnapshotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
class DemoCorruptRequest(BaseModel):
    chunk_hash: str
    node_id: str
class DemoNodeRequest(BaseModel):
    node_id: str
