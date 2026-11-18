import json

import httpx
import pytest

from ticket_agent.config import Settings
from ticket_agent.helpdesk import Helpdesk
from ticket_agent.llm import LlmResponse


@pytest.fixture
def settings():
    return Settings(
        helpdesk_url="https://helpdesk.test",
        helpdesk_key="key",
        candidate_email="me@example.com",
        candidate_name=None,
        llm_backend="file_exchange",
        model="m",
        anthropic_api_key=None,
    )


def build_helpdesk_with_script(settings, handler):
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://helpdesk.test",
        headers={"Authorization": "Bearer key", "X-Candidate-Email": "me@example.com"},
    )
    sleeps = []
    helpdesk = Helpdesk(settings, http_client=client, sleep=sleeps.append, random_fraction=lambda: 0.0)
    helpdesk.recorded_sleeps = sleeps
    return helpdesk


class ScriptedBackend:
    def __init__(self, classification: dict, judgement: dict | None = None):
        self.classification = classification
        self.judgement = judgement or {
            "english_translation": "Go to Team, Add employee.",
            "extra_claims": [],
            "only_uses_cited_faq_content": True,
            "answers_the_question": True,
        }
        self.purposes_asked = []

    def ask_for_structured_answer(self, purpose, system_prompt, user_message, output_schema):
        self.purposes_asked.append(purpose)
        data = self.classification if purpose == "classify" else self.judgement
        return LlmResponse(dict(data), 10, 5)


def build_classification(**changes) -> dict:
    classification = {
        "language": "nl",
        "category": "question",
        "priority": "P4",
        "reason": "How-to question answered by FAQ F02.",
        "always_human_topic": "none",
        "is_spam": False,
        "faq_ids": ["F02"],
        "answer_fully_in_faq": True,
        "draft_reply": "Hoi, ga naar Team → Medewerker toevoegen, vul de gegevens in en klik op Uitnodigen. Je betaalt alleen voor actieve medewerkers.",
        "handoff_note": "Customer asks how to add an employee.",
        "confidence": 0.95,
    }
    classification.update(changes)
    return classification


def json_response(status: int, payload=None, headers=None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload or {}), headers=headers)
