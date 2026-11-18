import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "gemini-3.1-flash-lite"


@dataclass(frozen=True)
class Settings:
    helpdesk_url: str | None
    helpdesk_key: str | None
    candidate_email: str | None
    candidate_name: str | None
    llm_backend: str
    model: str
    anthropic_api_key: str | None
    groq_api_key: str | None


def read_required_environment_variable(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing environment variable {name}. See .env.example.")
    return value


def read_optional_environment_variable(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def load_settings_from_environment(require_helpdesk_access: bool = True) -> Settings:
    load_dotenv()
    read_helpdesk_value = (
        read_required_environment_variable
        if require_helpdesk_access
        else read_optional_environment_variable
    )
    return Settings(
        helpdesk_url=read_helpdesk_value("HELPDESK_URL"),
        helpdesk_key=read_helpdesk_value("HELPDESK_KEY"),
        candidate_email=read_helpdesk_value("CANDIDATE_EMAIL"),
        candidate_name=read_optional_environment_variable("CANDIDATE_NAME"),
        llm_backend=os.environ.get("LLM_BACKEND", "anthropic").strip(),
        model=os.environ.get("MODEL", DEFAULT_MODEL).strip(),
        anthropic_api_key=read_optional_environment_variable("ANTHROPIC_API_KEY"),
        groq_api_key=read_optional_environment_variable("GROQ_API_KEY"),
    )
