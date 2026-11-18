import re
from dataclasses import dataclass, field

from langdetect import DetectorFactory, LangDetectException, detect

from .classify import Classification
from .llm import LlmUnavailable
from .prompts import REPLY_JUDGE_OUTPUT_SCHEMA, REPLY_JUDGE_SYSTEM_PROMPT, build_reply_judge_user_message
from .redaction import contains_payment_details

DetectorFactory.seed = 0

SUPPORTED_LANGUAGE_CODES = {"nl", "en", "de"}
QUOTED_PHRASE_PATTERN = re.compile(r"[\"“„]([^\"”“]{3,60})[\"”“]")
MENU_ARROW_PATTERN = re.compile(r"(\S+)\s*→\s*(\S+)")
WEB_ADDRESS_PATTERN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:nl|com|org|eu)(?:/[^\s,;)]*)?", re.IGNORECASE)


@dataclass
class ReplyCheckResult:
    passed: bool
    failed_checks: list[str] = field(default_factory=list)
    english_translation: str | None = None
    extra_claims: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def normalise_for_comparison(text: str) -> str:
    without_parenthetical_translations = re.sub(r"\([^)]*\)", " ", text)
    return re.sub(r"[^\w→]+", " ", without_parenthetical_translations.lower()).strip()


def find_menu_links_missing_from_faq(draft_reply: str, faq_text: str) -> list[str]:
    normalised_faq = re.sub(r"\s*→\s*", " → ", normalise_for_comparison(faq_text))
    missing_links = []
    for before, after in MENU_ARROW_PATTERN.findall(draft_reply):
        link = f"{normalise_for_comparison(before)} → {normalise_for_comparison(after)}"
        if link not in normalised_faq:
            missing_links.append(link)
    return missing_links


def find_quoted_phrases_missing_from_faq(draft_reply: str, faq_text: str) -> list[str]:
    normalised_faq = normalise_for_comparison(faq_text)
    return [
        phrase
        for phrase in QUOTED_PHRASE_PATTERN.findall(draft_reply)
        if normalise_for_comparison(phrase) not in normalised_faq
    ]


def find_web_addresses_missing_from_faq(draft_reply: str, faq_text: str) -> list[str]:
    lowered_faq = faq_text.lower()
    addresses = [address.rstrip(".").lower() for address in WEB_ADDRESS_PATTERN.findall(draft_reply)]
    return [address for address in addresses if address not in lowered_faq]


def draft_is_written_in_wrong_language(draft_reply: str, expected_language: str) -> bool:
    try:
        detected_language = detect(draft_reply)
    except LangDetectException:
        return False
    return detected_language in SUPPORTED_LANGUAGE_CODES and detected_language != expected_language


def run_deterministic_reply_checks(draft_reply: str, expected_language: str, faq_text: str) -> list[str]:
    failed_checks = []
    if draft_is_written_in_wrong_language(draft_reply, expected_language):
        failed_checks.append("reply_language_mismatch")
    if contains_payment_details(draft_reply):
        failed_checks.append("payment_details_in_reply")
    draft_without_bracketed_translations = re.sub(r"\([^)]*\)", " ", draft_reply)
    if find_menu_links_missing_from_faq(draft_without_bracketed_translations, faq_text):
        failed_checks.append("menu_path_not_in_faq")
    if find_quoted_phrases_missing_from_faq(draft_without_bracketed_translations, faq_text):
        failed_checks.append("quoted_term_not_in_faq")
    if find_web_addresses_missing_from_faq(draft_reply, faq_text):
        failed_checks.append("web_address_not_in_faq")
    return failed_checks


def check_reply_draft(backend, ticket: dict, classification: Classification, faq_text: str) -> ReplyCheckResult:
    failed_checks = run_deterministic_reply_checks(classification.draft_reply, classification.language, faq_text)
    if failed_checks:
        return ReplyCheckResult(passed=False, failed_checks=failed_checks)
    try:
        judgement = backend.ask_for_structured_answer(
            purpose="judge_reply",
            system_prompt=REPLY_JUDGE_SYSTEM_PROMPT,
            user_message=build_reply_judge_user_message(ticket, classification.draft_reply, faq_text),
            output_schema=REPLY_JUDGE_OUTPUT_SCHEMA,
        )
    except LlmUnavailable:
        return ReplyCheckResult(passed=False, failed_checks=["reply_judge_unavailable"])
    answer = judgement.data
    if answer.get("extra_claims") or not answer.get("only_uses_cited_faq_content"):
        failed_checks.append("reply_has_claims_outside_faq")
    if not answer.get("answers_the_question"):
        failed_checks.append("reply_does_not_answer_question")
    return ReplyCheckResult(
        passed=not failed_checks,
        failed_checks=failed_checks,
        english_translation=answer.get("english_translation"),
        extra_claims=[str(claim) for claim in answer.get("extra_claims") or []],
        input_tokens=judgement.input_tokens,
        output_tokens=judgement.output_tokens,
    )
