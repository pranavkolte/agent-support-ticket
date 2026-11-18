import random
import time

import httpx

from .config import Settings

MAX_TRANSIENT_FAILURES_PER_REQUEST = 6
MAX_RATE_LIMIT_WAITS_PER_REQUEST = 30
MIN_SECONDS_BETWEEN_REQUESTS = 0.25
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 8.0
DEFAULT_RETRY_AFTER_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 20.0
TICKETS_PER_PAGE = 10
TICKET_LIST_KEYS = ("tickets", "items", "data", "results")
EXAMPLE_LIST_KEYS = ("examples", "items", "data", "results")


class HelpdeskError(Exception):
    pass


class AlreadyHandled(HelpdeskError):
    pass


class FatalHelpdeskError(HelpdeskError):
    pass


class RejectedRequest(HelpdeskError):
    pass


class HelpdeskUnavailable(HelpdeskError):
    pass


def extract_list_from_payload(payload, candidate_keys: tuple[str, ...]) -> list:
    if isinstance(payload, list):
        return payload
    for key in candidate_keys:
        if isinstance(payload.get(key), list):
            return payload[key]
    raise HelpdeskError(f"Could not find a list under any of {candidate_keys} in the response")


def read_json_or_empty(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, (dict, list)) else {}


def build_error_for_rejected_response(response: httpx.Response) -> HelpdeskError:
    payload = read_json_or_empty(response)
    detail = payload if payload else response.text[:300]
    if response.status_code == 401:
        return FatalHelpdeskError(f"401 unauthorized, check HELPDESK_KEY: {detail}")
    if response.status_code == 409:
        return AlreadyHandled(f"409 already handled: {detail}")
    return RejectedRequest(f"{response.status_code} rejected: {detail}")


class Helpdesk:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.Client | None = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        random_fraction=random.random,
    ):
        headers = {
            "Authorization": f"Bearer {settings.helpdesk_key}",
            "X-Candidate-Email": settings.candidate_email,
        }
        if settings.candidate_name:
            headers["X-Candidate-Name"] = settings.candidate_name
        self.http_client = http_client or httpx.Client(
            base_url=settings.helpdesk_url.rstrip("/"),
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self.random_fraction = random_fraction
        self.retries_used = 0
        self.last_request_started_at: float | None = None

    def wait_for_free_rate_limit_slot(self) -> None:
        if self.last_request_started_at is not None:
            elapsed = self.monotonic() - self.last_request_started_at
            if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
                self.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
        self.last_request_started_at = self.monotonic()

    def calculate_backoff_seconds(self, failure_count: int) -> float:
        exponential_seconds = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (failure_count - 1))
        return exponential_seconds + self.random_fraction() * 0.25

    def read_retry_after_seconds(self, response: httpx.Response) -> float:
        try:
            return max(float(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS)), 0.0)
        except ValueError:
            return DEFAULT_RETRY_AFTER_SECONDS

    def send_request_with_retries(self, method: str, path: str, params=None, json_body=None):
        transient_failures = 0
        rate_limit_waits = 0
        while True:
            self.wait_for_free_rate_limit_slot()
            try:
                response = self.http_client.request(method, path, params=params, json=json_body)
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code < 400:
                return read_json_or_empty(response)
            if response is not None and response.status_code == 429:
                rate_limit_waits += 1
                if rate_limit_waits > MAX_RATE_LIMIT_WAITS_PER_REQUEST:
                    raise HelpdeskUnavailable(f"Still rate limited on {method} {path}")
                self.retries_used += 1
                self.sleep(self.read_retry_after_seconds(response))
                continue
            if response is None or response.status_code >= 500:
                transient_failures += 1
                if transient_failures >= MAX_TRANSIENT_FAILURES_PER_REQUEST:
                    raise HelpdeskUnavailable(f"Gave up on {method} {path} after {transient_failures} failures")
                self.retries_used += 1
                self.sleep(self.calculate_backoff_seconds(transient_failures))
                continue
            raise build_error_for_rejected_response(response)

    def fetch_status(self) -> dict:
        return self.send_request_with_retries("GET", "/status")

    def fetch_labelled_examples(self) -> list[dict]:
        return extract_list_from_payload(self.send_request_with_retries("GET", "/examples"), EXAMPLE_LIST_KEYS)

    def fetch_open_tickets(self) -> list[dict]:
        tickets: list[dict] = []
        cursor = None
        while True:
            params = {"limit": TICKETS_PER_PAGE, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            page = self.send_request_with_retries("GET", "/tickets", params=params)
            tickets.extend(extract_list_from_payload(page, TICKET_LIST_KEYS))
            cursor = page.get("next_cursor") if isinstance(page, dict) else None
            if not cursor:
                return tickets

    def fetch_ticket(self, ticket_id: str) -> dict:
        return self.send_request_with_retries("GET", f"/tickets/{ticket_id}")

    def submit_decision(self, ticket_id: str, action: str, request_body: dict) -> dict:
        return self.send_request_with_retries("POST", f"/tickets/{ticket_id}/{action}", json_body=request_body)

    def reset_practice_tickets(self) -> dict:
        return self.send_request_with_retries("POST", "/practice/reset")
