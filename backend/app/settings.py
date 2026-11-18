from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    ollama_base_url: str = "http://localhost:11434"
    # The models run on another machine (the owner's PC, reached over Tailscale): before a request
    # queues a job, ask that machine and answer 503 `compute_unavailable` if it isn't ready.
    require_compute: bool = False
    # The model that files sentences that carry no citation (prompts/Expert_sentence_targets.v1.md).
    # The chip test found the 35b model no better at this and far slower to load.
    classifier_model: str = "qwen3.5:9b"
    # One reply can include loading the model.
    ollama_request_timeout: float = 600
    # The grammar checker (a self-hosted LanguageTool server, see docker-compose.yml). It is
    # rule-based: the same text and server version always give the same corrections.
    languagetool_url: str = "http://localhost:8010"
    languagetool_language: str = "en-US"
    languagetool_timeout: float = 60
    # The model that turns fragments into full sentences (prompts/Answer_enhance.v2.md). Empty
    # switches the enhancement off: the answers are then only proofread.
    enhance_model: str = "qwen3.5:9b"
    # The folder with prompts/ and config/. The images copy both next to backend/.
    project_root: Path = Path(__file__).resolve().parents[2]
    # "production" forces the HTTPS-only session cookie. Anything else stops the app at startup:
    # a typo here must not silently turn that off.
    environment: Literal["development", "production"] = "development"
    # HTTPS-only session cookie. Always on in production; this turns it on elsewhere too.
    cookie_secure: bool = False
    session_ttl_hours: int = 12


settings = Settings()
