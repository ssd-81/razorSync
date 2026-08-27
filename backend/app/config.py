from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    APP_NAME: str = "RazorSync"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite:///./razorSync.db"
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    WEBHOOK_BASE_URL: str = ""
    MERCHANT_ID: str = "merchant_default"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    SIMULATION_DEFAULT_CUSTOMERS: int = 500
    SIMULATION_SEEDS: str = "42,137,256"
    SIMULATION_DURATION_DAYS: int = 7
    SIMULATE_RAZORPAY_FAILURE: bool = False

    # v3: Async ingestion queue (Option B - Redis Stream)
    REDIS_URL: str = ""  # e.g. redis://localhost:6379/0 ; empty => in-memory fallback for tests
    REDIS_STREAM: str = "razor:inbox"
    REDIS_CONSUMER_GROUP: str = "reasoning"
    REDIS_CONSUMER_NAME: str = "worker-1"

    # v3: LLM free cloud (provider-agnostic OpenAI-compatible)
    LLM_PROVIDER: str = ""  # groq | together | openrouter | huggingface | ollama
    LLM_ENDPOINT: str = ""  # e.g. https://api.groq.com/openai/v1/chat/completions
    LLM_MODEL: str = ""  # e.g. llama-3.1-8b-instant
    LLM_API_KEY: str = ""
    LLM_TIMEOUT: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def simulation_seeds_list(self) -> List[int]:
        return [int(s.strip()) for s in self.SIMULATION_SEEDS.split(",") if s.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_ENDPOINT and self.LLM_MODEL)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.REDIS_URL)


settings = Settings()
