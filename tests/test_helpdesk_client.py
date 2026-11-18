import pytest

from tests.conftest import build_helpdesk_with_script, json_response
from ticket_agent.helpdesk import (
    AlreadyHandled,
    FatalHelpdeskError,
    HelpdeskUnavailable,
    RejectedRequest,
)


def test_503_is_retried_with_backoff_until_success(settings):
    responses = iter([json_response(503), json_response(503), json_response(200, {"open": 3})])
    helpdesk = build_helpdesk_with_script(settings, lambda request: next(responses))
    assert helpdesk.fetch_status() == {"open": 3}
    assert helpdesk.retries_used == 2


def test_429_waits_for_retry_after_header(settings):
    responses = iter([json_response(429, headers={"Retry-After": "2"}), json_response(200, {"ok": True})])
    helpdesk = build_helpdesk_with_script(settings, lambda request: next(responses))
    helpdesk.fetch_status()
    assert 2.0 in helpdesk.recorded_sleeps


def test_409_raises_already_handled_and_is_never_retried(settings):
    calls = []

    def handler(request):
        calls.append(request)
        return json_response(409, {"error": "already_handled"})

    helpdesk = build_helpdesk_with_script(settings, handler)
    with pytest.raises(AlreadyHandled):
        helpdesk.submit_decision("T001", "reply", {})
    assert len(calls) == 1


def test_401_is_fatal_and_422_is_rejected_without_retry(settings):
    helpdesk = build_helpdesk_with_script(settings, lambda request: json_response(401))
    with pytest.raises(FatalHelpdeskError):
        helpdesk.fetch_status()
    helpdesk = build_helpdesk_with_script(settings, lambda request: json_response(422, {"problems": ["x"]}))
    with pytest.raises(RejectedRequest):
        helpdesk.submit_decision("T001", "reply", {})


def test_persistent_503_gives_up(settings):
    helpdesk = build_helpdesk_with_script(settings, lambda request: json_response(503))
    with pytest.raises(HelpdeskUnavailable):
        helpdesk.fetch_status()


def test_pagination_follows_next_cursor_until_null(settings):
    pages = {
        None: {"tickets": [{"id": "T001"}, {"id": "T002"}], "next_cursor": "T002"},
        "T002": {"tickets": [{"id": "T003"}], "next_cursor": None},
    }
    helpdesk = build_helpdesk_with_script(
        settings, lambda request: json_response(200, pages[request.url.params.get("cursor")])
    )
    assert [ticket["id"] for ticket in helpdesk.fetch_open_tickets()] == ["T001", "T002", "T003"]


def test_requests_are_spaced_to_stay_under_five_per_second(settings):
    helpdesk = build_helpdesk_with_script(settings, lambda request: json_response(200, {}))
    helpdesk.fetch_status()
    helpdesk.fetch_status()
    assert any(0 < seconds <= 0.25 for seconds in helpdesk.recorded_sleeps)
