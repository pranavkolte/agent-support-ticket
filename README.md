# Roosterly support ticket agent

Reads all open helpdesk tickets and posts one decision each: `reply` (draft in the customer's language, from the help centre only), `handoff` (English note for a human) or `close` (spam, empty).

## How to run

```bash
git clone <repo> && cd support-ticket-agent
uv sync
cp .env.example .env
uv run python -m ticket_agent --dry-run
uv run python -m ticket_agent
uv run python -m ticket_agent.evaluate --name baseline
uv run pytest
```

Fill `.env` first: `HELPDESK_KEY`, `CANDIDATE_EMAIL`, `ANTHROPIC_API_KEY`. `--reset-practice-first` re-opens the 30 practice tickets and clears local state (used once for the final run). Logs go to `logs/run-<time>.jsonl`.

## Decisions

TODO(final): three choices and why. Draft:
1. **Dutch directly, verified mechanically.** One model call classifies and drafts in the customer's language. A reply is only sent if code checks pass (language, no payment details, every menu path, quoted term and link exists in `faq.md`) and a second call back-translates the draft to English and confirms it contains nothing beyond the cited FAQ entries. Any failure becomes a handoff. Cost: one extra call per reply.
2. **The model labels, code decides.** The always-human rules, spam/empty, prompt-injection phrases, the 0.8 confidence floor and the FAQ-citation check are in code, so a wrong or manipulated model answer cannot force a reply.
3. **Unsure means handoff.** Assumptions: unsure = confidence below 0.8, no valid FAQ citation, or a failed check. A ticket mixing a covered question with an uncovered one goes to a human. Tickets in other languages go to a human.

AI tools: TODO(final) how an AI coding assistant was used.

## Reliability

- **503 and network errors:** exponential backoff with jitter, 6 tries, then the ticket stays pending for the next run.
- **429:** wait the `Retry-After` seconds and retry; calls are also spaced 0.25 s apart (max 4/s).
- **409:** never retried, treated as already handled.
- **Crash:** the decision is saved to `state.json` before it is sent. A re-run re-sends saved decisions (a landed one answers 409 and is marked done) and skips every ticket it already knows. Only open tickets are fetched.
- **Security:** keys from environment only. Ticket text goes to the model as JSON data, labelled untrusted, with IBANs and card numbers redacted. Output is schema-checked and code has the final say. Injection phrases go to a human. Logs hold no ticket text and are redacted again.

## Eval and fix

TODO(final): baseline vs after table on the 10 labelled examples, the fix, and the cost per 100 tickets with the calculation (tokens from `logs/`, model price).

## What I would improve

TODO(final): next step, and one thing in the brief to change.
