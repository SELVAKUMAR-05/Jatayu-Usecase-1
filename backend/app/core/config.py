"""
Core configuration for OrderFlow Sentinel
"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self):
        self.APP_NAME = os.getenv("APP_NAME", "OrderFlow Sentinel")
        self.ENV = os.getenv("ENV", "local")
        self.DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orderflow.db")
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.USE_LLM = os.getenv("USE_LLM", "false").lower() == "true"
        self.JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
        self.SLA_DEFAULT_MS = int(os.getenv("SLA_DEFAULT_MS", "30000"))
        self.AUTO_HEAL_LOW_RISK = os.getenv("AUTO_HEAL_LOW_RISK", "true").lower() == "true"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
