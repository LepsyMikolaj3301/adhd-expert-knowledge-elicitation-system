from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    ollama_base_url: str = "http://localhost:11434"
    graphdb_url: str = "http://localhost:7200"
    graphdb_repository: str = "adhd-knowledge"


settings = Settings()
