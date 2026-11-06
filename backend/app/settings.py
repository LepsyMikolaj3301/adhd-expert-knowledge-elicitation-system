from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    # Migrations must not go through a connection pooler (Neon `-pooler` host). When set, alembic
    # uses this instead of database_url.
    database_url_unpooled: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # The model that files sentences that carry no citation (prompts/Expert_sentence_targets.v1.md).
    # The chip test found the 35b model no better at this and far slower to load.
    classifier_model: str = "qwen3.5:9b"
    # One reply can include loading the model.
    ollama_request_timeout: float = 600
    # The folder with prompts/ and config/. The images copy both next to backend/.
    project_root: Path = Path(__file__).resolve().parents[2]
    # S3 (MinIO locally). Set s3_endpoint_url to an empty string to target real AWS S3.
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str = "rag-app"
    s3_secret_access_key: str = "rag-app-secret"
    s3_region: str = "us-east-1"
    s3_bucket: str = "documents"
    # "production" switches on the synthetic-data guard at ingestion. Anything else stops the app
    # at startup: a typo here must not silently turn the guard off.
    environment: Literal["development", "production"] = "development"
    # HTTPS-only session cookie. Always on in production; this turns it on elsewhere too.
    cookie_secure: bool = False
    session_ttl_hours: int = 12
    # Collect answers and nothing else: no reviews, knowledge base or home feed, and no worker to
    # follow a submission up. Submitting still files the answers and queues the job, which then
    # waits in the database for a worker started later, on a copy of the data.
    answers_only: bool = False


settings = Settings()
