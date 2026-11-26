from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 环境变量优先于 .env，未设置的选项使用下面的默认值。
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    ocr_api_key: SecretStr
    ocr_base_url: str = (
        "https://ws-nzz9m16u7c5um2ek.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    ocr_model: str = "qwen3-vl-plus"
    # 限制每个 PDF 转换任务同时处理的页数。
    ocr_concurrency: int = Field(default=3, ge=1, le=16)
    ocr_dpi: int = Field(default=144, ge=72, le=300)
    ocr_timeout: float = Field(default=120, gt=0, le=600)
    ocr_retries: int = Field(default=2, ge=0, le=5)
    ocr_max_tokens: int = Field(default=4096, ge=256, le=32768)

    @field_validator("ocr_api_key")
    @classmethod
    def nonempty_key(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("OCR_API_KEY must not be empty")
        return value

    @field_validator("ocr_base_url")
    @classmethod
    def validate_url(cls, value):
        if not value.startswith("https://"):
            raise ValueError("OCR_BASE_URL must use HTTPS")
        return value.rstrip("/")
