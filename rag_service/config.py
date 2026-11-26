"""检索服务配置：读取 .env，并允许 embedding 显式配置或复用 OCR 凭据。"""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CorsSettings(BaseSettings):
    """单独读取跨域配置，构建中间件无需加载数据库或模型密钥。"""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix="CORS_"
    )
    origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )


class Settings(BaseSettings):
    """从环境变量和 .env 加载服务配置，SecretStr 避免意外显示密钥。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "postgres"
    postgres_user: str = "postgres"
    postgres_password: SecretStr
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    ocr_api_key: SecretStr | None = None
    ocr_base_url: str = (
        "https://ws-nzz9m16u7c5um2ek.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    request_timeout: float = Field(default=30, gt=0)
    concurrency: int = Field(default=8, ge=1, le=64)
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "kaogong_service_v1"
    asset_root: Path = Path("output/rag_assets")
    local_review: bool = False

    @model_validator(mode="after")
    def fallback(self):
        """缺少 embedding 专用凭据时复用 OCR 配置；密钥缺失立即报错。"""
        self.embedding_api_key = self.embedding_api_key or self.ocr_api_key
        self.embedding_base_url = self.embedding_base_url or self.ocr_base_url
        if not self.embedding_api_key:
            raise ValueError("EMBEDDING_API_KEY or OCR_API_KEY required")
        return self

    @property
    def conninfo(self):
        """通过驱动安全构造连接串，避免密码中特殊字符破坏连接参数。"""
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            connect_timeout=10,
        )
