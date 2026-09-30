from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')
    node_id: str = 'node-1'
    port: int = 9001
    data_dir: str = '/data'
    demo_mode: bool = True
    quorumvault_internal_token: str = 'local-demo-internal-token-change-me'

    @property
    def internal_token(self) -> str:
        return self.quorumvault_internal_token


settings = Settings()
