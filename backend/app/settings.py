from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mwiewior/bielik:7b-instruct-v0.1.Q4_K_M.gguf"


settings = Settings()
