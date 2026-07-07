"""
app/config.py

应用配置，从环境变量读取，提供合理默认值。
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 服务
    host: str = "0.0.0.0"
    port: int = 8080

    # 目录
    backend_root: Path = Path(__file__).parent.parent   # backend/

    @property
    def parsers_root(self) -> Path:
        return self.backend_root / "parsers"

    @property
    def plugins_root(self) -> Path:
        return self.backend_root / "plugins"

    model_config = SettingsConfigDict(
        env_prefix="GDM_",          # 环境变量前缀，如 GDM_PORT=9000
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
