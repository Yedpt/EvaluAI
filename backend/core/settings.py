"""
Application settings using Pydantic Settings.

This module provides centralized configuration management with:
- Type-safe settings with IDE autocomplete
- Automatic loading from .env file
- Sensible defaults for all values
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from enum import Enum


class AIProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings have sensible defaults but can be overridden
    via environment variables or .env file.
    """

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    APP_TITLE: str = "Evaluador RAG API"
    APP_DESCRIPTION: str = "Automated GitHub Repository Grading with RAG"
    APP_VERSION: str = "1.0.0"

    # Route Configuration - Rubrics
    RUBRICS_ROUTE_PREFIX: str = "/rubrics"
    RUBRICS_TAG: str = "Rubrics"

    # Route Configuration - Evaluations
    EVALUATIONS_ROUTE_PREFIX: str = "/evaluations"
    EVALUATIONS_TAG: str = "Evaluations"

    # Route Configuration - System
    HEALTH_CHECK_PATH: str = "/health"
    ROOT_PATH: str = "/"

    # Route Configuration - Briefings
    BRIEFING_UPLOAD_ENDPOINT: str = "/briefings"

    # Evaluation Status Constants
    EVALUATION_STATUS_PENDING: str = "pending"
    EVALUATION_STATUS_PROCESSING: str = "processing"
    EVALUATION_STATUS_COMPLETED: str = "completed"
    EVALUATION_STATUS_FAILED: str = "failed"

    # RAG / Vector Store Configuration. To be obtained from environment
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    GEMINI_MODEL_VERTEX: str = "gemini-2.5-flash"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = ""
    GEMINI_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    GEMINI_EMBEDDING_MODEL_VERTEX: str = "text-embedding-005"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    VERTEX_ENABLED: bool = False
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "europe-west1"
    GOOGLE_APPLICATION_CREDENTIALS_JSON: str = ""

    # Abuse protection for server-default provider
    ENABLE_DEFAULT_PROVIDER_COOLDOWN: bool = True
    DEFAULT_PROVIDER_COOLDOWN_SECONDS: int = 900
    ENABLE_EVALUATION_RATE_LIMIT: bool = True
    EVALUATION_RATE_LIMIT_MAX_REQUESTS: int = 5
    EVALUATION_RATE_LIMIT_WINDOW_SECONDS: int = 600
    

    # GitLoader Configuration
    CODE_SUFFIXES: list = [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".rb", ".go", ".php", ".mjs"]
    TEXT_SUFFIXES: list = [".md", ".txt", ".rst", ".html", ".css", ".sh", ".bat", ".ps1"]
    CONFIG_SUFFIXES: list = [".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env.example", ".sql"]
    SPECIAL_FILES: set = {"Dockerfile", "Makefile", "Procfile", "Gemfile", ".gitignore", ".dockerignore"}
    IGNORE_DIRS: set = {".git", "node_modules", "__pycache__", ".venv", "venv",
                        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"}
    IGNORE_FILES: set = {"package-lock.json", "yarn.lock", "poetry.lock", 
                         "Pipfile.lock", "composer.lock", "pnpm-lock.yaml", ".DS_Store"}
    MAX_FILE_SIZE: int = 50_000  # ~50KB

    # RAG Context Limits
    RAG_MAX_CHUNKS: int = 8
    RAG_MAX_CHUNK_CHARS: int = 1200
    
    # File upload path
    FILE_UPLOAD_PATH: str = "/tmp/briefings"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"  # Ignore extra environment variables
    )

    @model_validator(mode="after")
    def validate_ai_configuration(self):
        """Validate required settings with Vertex-aware conditions."""
        missing = []

        # Always required for non-Gemini providers
        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not self.OPENAI_MODEL:
            missing.append("OPENAI_MODEL")
        if not self.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        if not self.GROQ_MODEL:
            missing.append("GROQ_MODEL")

        # Gemini requirements depend on the selected server mode
        if self.VERTEX_ENABLED:
            if not self.GCP_PROJECT_ID:
                missing.append("GCP_PROJECT_ID")
            if not self.GCP_LOCATION:
                missing.append("GCP_LOCATION")
            if not self.GEMINI_MODEL_VERTEX:
                missing.append("GEMINI_MODEL_VERTEX")
            if not self.GEMINI_EMBEDDING_MODEL_VERTEX:
                missing.append("GEMINI_EMBEDDING_MODEL_VERTEX")
        else:
            if not self.GEMINI_API_KEY:
                missing.append("GEMINI_API_KEY")
            if not self.GEMINI_MODEL:
                missing.append("GEMINI_MODEL")
            if not self.GEMINI_EMBEDDING_MODEL:
                missing.append("GEMINI_EMBEDDING_MODEL")

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        return self
    

# Global settings instance
settings = Settings()


def get_api_key(provider: AIProvider) -> str:
    """Get API key for the specified provider."""
    if provider == AIProvider.OPENAI:
        return settings.OPENAI_API_KEY
    elif provider == AIProvider.GEMINI:
        return settings.GEMINI_API_KEY
    elif provider == AIProvider.GROQ:
        return settings.GROQ_API_KEY
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
    
def get_model(provider: AIProvider) -> str:
    """Get model for the specified provider."""
    if provider == AIProvider.OPENAI:
        return settings.OPENAI_MODEL
    elif provider == AIProvider.GEMINI:
        return settings.GEMINI_MODEL_VERTEX if settings.VERTEX_ENABLED else settings.GEMINI_MODEL
    elif provider == AIProvider.GROQ:
        return settings.GROQ_MODEL
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
