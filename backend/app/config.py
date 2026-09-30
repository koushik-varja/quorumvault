from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://quorumvault:quorumvault@postgres:5432/quorumvault'
    redis_url: str = 'redis://redis:6379/0'
    jwt_secret: str = 'replace-me'
    jwt_algorithm: str = 'HS256'
    access_token_minutes: int = 120
    demo_mode: bool = True
    chunk_size_bytes: int = 4 * 1024 * 1024
    replication_factor: int = 3
    heartbeat_interval_seconds: int = 5
    heartbeat_timeout_seconds: int = 15
    repair_interval_seconds: int = 8
    integrity_interval_seconds: int = 0
    max_upload_bytes: int = 1024 * 1024 * 1024
    storage_node_urls: str = 'http://storage-node-1:9001,http://storage-node-2:9002,http://storage-node-3:9003,http://storage-node-4:9004'
    cors_origins: str = 'http://localhost:5173,http://localhost:8080'
    demo_admin_email: str = 'admin@quorumvault.local'
    demo_admin_password: str = 'QuorumVaultDemo!23'
    quorumvault_internal_token: str = 'local-demo-internal-token-change-me'
    storage_connect_timeout_seconds: float = 2.0
    storage_read_timeout_seconds: float = 8.0
    storage_write_timeout_seconds: float = 8.0
    storage_pool_timeout_seconds: float = 2.0
    storage_max_connections: int = 32
    storage_max_keepalive_connections: int = 16

    @property
    def internal_token(self) -> str:
        return self.quorumvault_internal_token

    @property
    def node_urls(self) -> list[str]:
        return [u.strip() for u in self.storage_node_urls.split(',') if u.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [u.strip() for u in self.cors_origins.split(',') if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
