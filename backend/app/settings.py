from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    ollama_base_url: str = "http://localhost:11434"
    # S3 (MinIO locally). Set s3_endpoint_url to an empty string to target real AWS S3.
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str = "rag-app"
    s3_secret_access_key: str = "rag-app-secret"
    s3_region: str = "us-east-1"
    s3_bucket: str = "documents"


settings = Settings()
