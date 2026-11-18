from pathlib import Path

import pytest

from tests.conftest import ScriptedBackend, build_classification, build_helpdesk_with_script, json_response
from ticket_agent.agent import run_agent
from ticket_agent.decide import decide_ticket
from ticket_agent.faq import load_faq_text
from ticket_agent.run_log import RunLog
from ticket_agent.state import StateStore

FAQ_TEXT = load_faq_text(Path("faq.md"))


class FakeHelpdeskServer:
    def __init__(self, ticket_ids):
        self.open_ids = list(ticket_ids)
        self.handled_ids = []
        self.replies_received = []
        self.crash_after_n_posts = None

    def handle(self, request):
        path = request.url.path
        if request.method == "GET" and path.endswith("/tickets"):
            tickets = [{"id": ticket_id, "subject": "Nieuwe medewerker", "body": "Hoe voeg ik iemand toe?"} for ticket_id in self.open_ids]
            return json_response(200, {"tickets": tickets, "next_cursor": None})
        if request.method == "POST":
            ticket_id = path.split("/")[-2]
            if ticket_id in self.handled_ids:
                return json_response(409, {"error": "already_handled"})
            if self.crash_after_n_posts is not None and len(self.replies_received) >= self.crash_after_n_posts:
                raise KeyboardInterrupt
            self.handled_ids.append(ticket_id)
            self.open_ids.remove(ticket_id)
            self.replies_received.append(ticket_id)
            return json_response(200, {"ok": True})
        return json_response(404)


def build_run(tmp_path, settings, server):
    helpdesk = build_helpdesk_with_script(settings, server.handle)
    return helpdesk, StateStore(tmp_path / "state.json"), RunLog(tmp_path / "logs")


def test_crash_mid_run_then_rerun_never_answers_a_customer_twice(tmp_path, settings):
    server = FakeHelpdeskServer(["T1", "T2", "T3", "T4"])
    server.crash_after_n_posts = 2
    backend = ScriptedBackend(build_classification())
    helpdesk, state, log = build_run(tmp_path, settings, server)
    with pytest.raises(KeyboardInterrupt):
        run_agent(helpdesk, backend, FAQ_TEXT, state, log)
    assert server.replies_received == ["T1", "T2"]

    server.crash_after_n_posts = None
    helpdesk, state, log = build_run(tmp_path, settings, server)
    summary = run_agent(helpdesk, backend, FAQ_TEXT, state, log)
    assert sorted(server.replies_received) == ["T1", "T2", "T3", "T4"]
    assert len(server.replies_received) == 4
    assert not summary.has_unfinished_tickets()


def test_pending_ticket_whose_post_already_landed_is_closed_out_via_409(tmp_path, settings):
    server = FakeHelpdeskServer(["T1"])
    server.handled_ids.append("T1")
    helpdesk, state, log = build_run(tmp_path, settings, server)
    saved_decision = decide_ticket({"id": "T1", "subject": "a", "body": "b"}, ScriptedBackend(build_classification()), FAQ_TEXT)
    state.record_decision_before_sending("T1", saved_decision.to_state_dict())
    summary = run_agent(helpdesk, ScriptedBackend(build_classification()), FAQ_TEXT, state, log)
    assert summary.outcomes == {"already_handled": 1}
    assert state.is_done("T1")


def test_log_lines_contain_no_ticket_body_or_payment_details(tmp_path, settings):
    server = FakeHelpdeskServer(["T1"])
    backend = ScriptedBackend(build_classification(reason="Customer IBAN NL91 ABNA 0417 1643 00 asks how to add staff."))
    helpdesk, state, log = build_run(tmp_path, settings, server)
    run_agent(helpdesk, backend, FAQ_TEXT, state, log)
    log_text = log.log_path.read_text()
    assert "NL91" not in log_text and "Hoe voeg ik iemand toe" not in log_text
    assert log_text.count("\n") == 1
