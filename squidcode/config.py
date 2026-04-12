from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ICAP server
    icap_host: str = "0.0.0.0"
    icap_port: int = 1344

    # SSE server
    sse_host: str = "0.0.0.0"
    sse_port: int = 8080

    # LLM
    llm_api_key: str = "sk-placeholder"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3

    # Rewrite
    rewrite_style: str = "clarity"
    batch_size: int = 5

    # Semantic cache
    cache_similarity_threshold: float = 0.85
    cache_ttl_hours: int = 24
    cache_persist_dir: str = "./cache_db"

    # RAG
    rag_data_dir: str = "./data"

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"

    # Logging
    log_level: str = "INFO"

    @property
    def sse_origin(self) -> str:
        return f"http://{self.sse_host}:{self.sse_port}"


settings = Settings()
