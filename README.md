# Roosterly support ticket agent

Reads every open helpdesk ticket and posts one decision: `reply` (draft in the customer's language, from the help centre only), `handoff` (English note for a human) or `close` (spam, empty).

## How to run

```bash
git clone https://github.com/pranavkolte/agent-support-ticket && cd agent-support-ticket
uv sync
cp .env.example .env     # fill HELPDESK_KEY, CANDIDATE_EMAIL, GEMINI_API_KEY
uv run python -m ticket_agent --dry-run                 # decide and print, post nothing
uv run python -m ticket_agent                           # run the agent
uv run python -m ticket_agent --reset-practice-first    # re-open the 30 practice tickets, then run
uv run python -m ticket_agent.evaluate --name baseline  # eval on the 10 labelled examples
uv run pytest                                           # 45 offline tests
```

`LLM_BACKEND` is `gemini` (default), `groq` or `anthropic`. The scored final run is `logs/run-20261119T052711Z.jsonl`.

## Decisions

1. **Dutch directly, checked by code.** One model call classifies and drafts in the customer's language. I can't read Dutch, so a reply is only sent if code checks pass (language, no payment data, every menu path, quoted term and link exists in `faq.md`) and a second call back-translates it to English and gives an exact help-centre quote for each fact, which code finds in `faq.md`. Any failure becomes a handoff. Cost: one extra call per reply.
2. **The model labels, code decides.** Always-human topics, spam/empty, injection phrases, P1, confidence below 0.8 and a missing FAQ citation are rules in code, so a wrong or manipulated model answer cannot force a reply.
3. **Language is detected in code** (`langdetect`, only when 90% sure), passed to the model and checked again after.

Assumptions: unsure = confidence below 0.8, no valid FAQ citation or a failed check. A ticket mixing a covered and an uncovered question goes to a human.
AI tools: an AI coding assistant wrote the code and tests, and stood in as the model for offline pipeline tests before I had model keys. The agent uses Gemini 3.1 Flash-Lite (free tier).

## Reliability

- **503:** backoff with jitter, 6 tries, then the ticket stays pending. **429:** wait `Retry-After`; calls are spaced to max 4/s. **409:** never retried, logged as `already_handled`.
- **Crash:** each decision is saved to `state.json` before posting; a re-run re-sends saved decisions and skips finished tickets. Tested live: killed with `kill -9` after 14 of 30, the re-run posted the other 16, no duplicates.
- **Security:** keys from env only. Ticket text is passed as untrusted JSON, with IBANs, card numbers and CVC redacted first. The model has no tools. Injection phrases go to a human. Logs hold no ticket text.

## Eval and fix

| 10 labelled examples | language | category | priority | action |
|---|---|---|---|---|
| Baseline | 90% | 100% | 90% | 100% |
| After fix | 100% | 100% | 100% | 100% |

**Found:** E01, an English ticket, was labelled `nl` and answered in Dutch. **Fix:** detect the language in code, pass it to the model and cross-check afterwards. A prompt-only first attempt made E01 a handoff (`results-attempt1_*`). Tuned on these 10, so 100% is optimistic.

**Cost per 100 tickets** (measured, 30 tickets: 93,205 input + 7,335 output tokens): at $0.25 / $1.50 per million tokens, 0.311 × 0.25 + 0.0245 × 1.50 = **about $0.11 (€0.10)**. Actual spend: €0 on the free tier.

## What I would improve

Next: a larger labelled set with a regression run per prompt change. Known gaps: evidence quotes prove a quote exists, not that it supports the claim; roadmap replies (T004, T025) imply the idea is already listed. Brief change: define the always-human rules by intent with examples, not by topic ("how do I upgrade?" and "where is our data stored?" were first escalated as contract and GDPR cases).
