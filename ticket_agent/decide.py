from dataclasses import asdict, dataclass

from langdetect import DetectorFactory, LangDetectException, detect

from .classify import Classification, InvalidModelOutput, classify_ticket_with_model
from .faq import split_faq_into_entries
from .guards import (
    build_ticket_text,
    contains_prompt_injection_attempt,
    find_always_human_topic_in_text,
    is_ticket_empty,
)
from .llm import LlmUnavailable
from .redaction import redact_payment_details
from .verify import check_reply_draft

DetectorFactory.seed = 0

CONFIDENCE_THRESHOLD = 0.8
PRIORITY_FLOOR_BY_TOPIC = {
    "security": "P1",
    "legal": "P1",
    "refund": "P2",
    "cancellation": "P2",
    "contract": "P2",
    "churn_threat": "P2",
}


@dataclass
class Decision:
    ticket_id: str
    language: str
    category: str
    priority: str
    reason: str
    action: str
    draft_reply: str | None
    handoff_note: str | None
    confidence: float | None
    faq_ids: list[str]
    rule_triggered: str | None
    verifier_result: str
    english_translation: str | None
    input_tokens: int
    output_tokens: int

    def build_request_body(self) -> dict:
        body = {
            "language": self.language,
            "category": self.category,
            "priority": self.priority,
            "reason": self.reason,
        }
        if self.confidence is not None:
            body["confidence"] = self.confidence
        if self.action == "reply":
            body["draft_reply"] = self.draft_reply
        if self.action == "handoff":
            body["handoff_note"] = self.handoff_note
        return body

    def to_state_dict(self) -> dict:
        return asdict(self)


def raise_priority_to_floor(priority: str, floor: str | None) -> str:
    if floor is None:
        return priority
    return min(priority, floor)


def guess_supported_language(text: str) -> str:
    try:
        detected = detect(text)
    except LangDetectException:
        return "nl"
    return detected if detected in ("nl", "en", "de") else "nl"


def build_decision(ticket_id: str, classification: Classification, action: str, **overrides) -> Decision:
    priority_floor = PRIORITY_FLOOR_BY_TOPIC.get(overrides.get("rule_triggered") or "")
    decision = Decision(
        ticket_id=ticket_id,
        language=classification.language,
        category=classification.category,
        priority=raise_priority_to_floor(classification.priority, priority_floor),
        reason=redact_payment_details(classification.reason),
        action=action,
        draft_reply=redact_payment_details(classification.draft_reply) if action == "reply" else None,
        handoff_note=redact_payment_details(classification.handoff_note) if action == "handoff" else None,
        confidence=classification.confidence,
        faq_ids=classification.faq_ids if action == "reply" else [],
        rule_triggered=None,
        verifier_result="not_needed",
        english_translation=None,
        input_tokens=0,
        output_tokens=0,
    )
    for name, value in overrides.items():
        setattr(decision, name, value)
    return decision


def build_decision_for_empty_ticket(ticket: dict) -> Decision:
    return Decision(
        ticket_id=ticket["id"],
        language="nl",
        category="other",
        priority="P4",
        reason="Ticket has no subject and no body, so there is nothing to answer.",
        action="close",
        draft_reply=None,
        handoff_note=None,
        confidence=1.0,
        faq_ids=[],
        rule_triggered="empty_ticket",
        verifier_result="not_needed",
        english_translation=None,
        input_tokens=0,
        output_tokens=0,
    )


def build_fallback_handoff_decision(ticket: dict, failure_description: str) -> Decision:
    return Decision(
        ticket_id=ticket["id"],
        language=guess_supported_language(build_ticket_text(ticket)),
        category="other",
        priority="P3",
        reason="Automatic classification failed, so a human should read this ticket.",
        action="handoff",
        draft_reply=None,
        handoff_note=redact_payment_details(
            f"Automatic triage failed ({failure_description}). Please read the original ticket and handle it manually."
        ),
        confidence=0.0,
        faq_ids=[],
        rule_triggered="classification_failed",
        verifier_result="not_needed",
        english_translation=None,
        input_tokens=0,
        output_tokens=0,
    )


def find_reason_to_hand_off(classification: Classification, ticket_text: str, faq_entries: dict[str, str]) -> str | None:
    topic = classification.always_human_topic
    if topic == "none":
        topic = find_always_human_topic_in_text(ticket_text) or "none"
    if topic != "none":
        return topic
    if contains_prompt_injection_attempt(ticket_text):
        return "prompt_injection_suspected"
    if not classification.answer_fully_in_faq or not classification.draft_reply:
        return "answer_not_fully_in_faq"
    if not classification.faq_ids or any(faq_id not in faq_entries for faq_id in classification.faq_ids):
        return "no_valid_faq_citation"
    if classification.confidence < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return None


def decide_ticket(ticket: dict, backend, faq_text: str) -> Decision:
    if is_ticket_empty(ticket):
        return build_decision_for_empty_ticket(ticket)
    try:
        classification, model_response = classify_ticket_with_model(backend, faq_text, ticket)
    except (LlmUnavailable, InvalidModelOutput) as error:
        return build_fallback_handoff_decision(ticket, type(error).__name__)
    usage = {"input_tokens": model_response.input_tokens, "output_tokens": model_response.output_tokens}
    ticket_text = build_ticket_text(ticket)

    faq_entries = split_faq_into_entries(faq_text)
    looks_like_sensitive_topic = (
        classification.always_human_topic != "none" or find_always_human_topic_in_text(ticket_text) is not None
    )
    if classification.is_spam and not looks_like_sensitive_topic:
        return build_decision(ticket["id"], classification, "close", rule_triggered="spam", **usage)

    reason_to_hand_off = find_reason_to_hand_off(classification, ticket_text, faq_entries)
    if reason_to_hand_off:
        return build_decision(ticket["id"], classification, "handoff", rule_triggered=reason_to_hand_off, **usage)

    reply_check = check_reply_draft(backend, ticket, classification, faq_text, faq_entries)
    usage["input_tokens"] += reply_check.input_tokens
    usage["output_tokens"] += reply_check.output_tokens
    if not reply_check.passed:
        return build_decision(
            ticket["id"],
            classification,
            "handoff",
            rule_triggered="reply_failed_verification",
            verifier_result="failed:" + ",".join(reply_check.failed_checks),
            english_translation=reply_check.english_translation,
            **usage,
        )
    return build_decision(
        ticket["id"],
        classification,
        "reply",
        verifier_result="passed",
        english_translation=reply_check.english_translation,
        **usage,
    )
