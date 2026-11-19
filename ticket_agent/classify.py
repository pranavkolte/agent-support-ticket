from dataclasses import dataclass

from .llm import LlmResponse
from .prompts import (
    ALWAYS_HUMAN_TOPICS,
    CATEGORIES,
    CLASSIFICATION_OUTPUT_SCHEMA,
    LANGUAGES,
    PRIORITIES,
    build_classification_system_prompt,
    build_ticket_user_message,
)


class InvalidModelOutput(Exception):
    pass


@dataclass
class Classification:
    language: str
    category: str
    priority: str
    reason: str
    always_human_topic: str
    is_spam: bool
    faq_ids: list[str]
    answer_fully_in_faq: bool
    draft_reply: str | None
    handoff_note: str
    confidence: float


def require_value_in_choices(data: dict, field: str, choices: list[str]) -> str:
    if data.get(field) not in choices:
        raise InvalidModelOutput(f"{field}={data.get(field)!r} is not one of {choices}")
    return data[field]


def require_text(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidModelOutput(f"{field} is missing or empty")
    return value.strip()


def parse_classification(data: dict) -> Classification:
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise InvalidModelOutput(f"confidence={confidence!r} is not a number between 0 and 1")
    faq_ids = data.get("faq_ids")
    if not isinstance(faq_ids, list) or not all(isinstance(faq_id, str) for faq_id in faq_ids):
        raise InvalidModelOutput("faq_ids must be a list of strings")
    draft_reply = data.get("draft_reply")
    return Classification(
        language=require_value_in_choices(data, "language", LANGUAGES),
        category=require_value_in_choices(data, "category", CATEGORIES),
        priority=require_value_in_choices(data, "priority", PRIORITIES),
        reason=require_text(data, "reason"),
        always_human_topic=require_value_in_choices(data, "always_human_topic", ALWAYS_HUMAN_TOPICS),
        is_spam=bool(data.get("is_spam")),
        faq_ids=faq_ids,
        answer_fully_in_faq=bool(data.get("answer_fully_in_faq")),
        draft_reply=draft_reply.strip() if isinstance(draft_reply, str) and draft_reply.strip() else None,
        handoff_note=require_text(data, "handoff_note"),
        confidence=float(confidence),
    )


def classify_ticket_with_model(backend, faq_text: str, ticket: dict) -> tuple[Classification, LlmResponse]:
    response = backend.ask_for_structured_answer(
        purpose="classify",
        system_prompt=build_classification_system_prompt(faq_text),
        user_message=build_ticket_user_message(ticket),
        output_schema=CLASSIFICATION_OUTPUT_SCHEMA,
    )
    return parse_classification(response.data), response
