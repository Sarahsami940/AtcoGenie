"""
AtcoGenie AI Engine — LLM Factory

Abstracts the creation of LLM instances (OpenAI vs Google Gemini).
Handles provider selection and configuration from environment settings.
"""

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_llm(settings: Settings, streaming: bool = True):
    """
    Returns a configured LangChain Chat model instance.
    Defaults to Gemini as requested, but supports OpenAI fallback.
    """
    provider = settings.llm_provider.lower()

    if provider == "google":
        if not settings.google_api_key:
            logger.error("google_api_key_missing")
            raise ValueError("GOOGLE_API_KEY is not set in environment")

        logger.info("llm_factory_init", provider="google", model=settings.google_model)
        return ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key,
            temperature=0,
            streaming=streaming,
        )

    elif provider == "openai":
        if not settings.openai_api_key:
            logger.error("openai_api_key_missing")
            raise ValueError("OPENAI_API_KEY is not set in environment")

        logger.info("llm_factory_init", provider="openai", model=settings.openai_model)
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
            streaming=streaming,
        )

    else:
        logger.error("invalid_llm_provider", provider=provider)
        raise ValueError(f"Unsupported LLM provider: {provider}")
