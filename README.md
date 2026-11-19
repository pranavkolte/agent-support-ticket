# Roosterly support ticket agent

Reads every open helpdesk ticket and posts one decision each: `reply` (draft in the customer's language, from the help centre only), `handoff` (English note for a human) or `close` (spam, empty).

## How to run

```bash
git clone <repo> && cd support-ticket-agent
uv sync
cp .env.example .env        # fill HELPDESK_KEY, CANDIDATE_EMAIL, GEMINI_API_KEY
uv run python -m ticket_agent --dry-run                 # decide and print, post nothing
uv run python -m ticket_agent                           # the agent
uv run python -m ticket_agent --reset-practice-first    # re-open the 30 practice tickets, clear state, run
uv run python -m ticket_agent.evaluate --name baseline  # eval on the 10 labelled examples
uv run pytest                                           # 45 offline tests
```

`LLM_BACKEND` is `gemini` (default), `groq` or `anthropic`. Logs: `logs/run-<time>.jsonl`; the scored final run is `logs/run-20261119T052711Z.jsonl`.

## Decisions

1. **Dutch directly, checked by code.** One model call classifies and drafts in the customer's language, with no translation step. I can't read Dutch, so a reply is only sent if it passes: language, no payment data, no entry ids, every `→` menu path, quoted term and link exists in `faq.md`; then a second call back-translates it to English and lists each fact with an exact help-centre quote that code finds in `faq.md`. Any failure becomes a handoff. Cost: one extra call per reply, and the English translation is kept for audit.
2. **The model labels, code decides.** Always-human topics, spam/empty, prompt-injection phrases, P1, confidence below 0.8 and a missing FAQ citation are in code, so a wrong or manipulated model answer cannot force a reply.
3. **Language is detected in code** (`langdetect`, only when 90% sure), given to the model and checked again after (see Eval).

Assumptions: unsure = confidence below 0.8, no valid FAQ citation or a failed check; a ticket mixing a covered question with an uncovered one, or a P1, goes to a human; other languages get low confidence and go to a human.
AI tools: an AI coding assistant wrote the code and tests. Before I had model keys it answered the model prompts itself through a file-exchange backend (`eval/pending`, gitignored) to test the pipeline offline. The agent itself uses Gemini 3.1 Flash-Lite on the free AI Studio tier.

## Reliability

- **503 / network errors:** exponential backoff with jitter, 6 tries, then the ticket stays pending for the next run. **429:** wait `Retry-After` and retry; calls are spaced 0.25 s apart (max 4/s). **409:** never retried, logged as `already_handled`.
- **Crash:** each decision is saved to `state.json` (atomic write) before it is posted. A re-run re-sends saved decisions and skips finished tickets; a landed POST answers 409 and is marked done. Tested live: killed with `kill -9` after 14 of 30 tickets, the re-run posted the other 16, 30 handled, no duplicates. An accidental race of two agents got 409 on the duplicates.
- **Security:** keys only from env. Ticket text goes to the model as JSON data labelled untrusted, with IBANs, card numbers and CVC redacted first; the model has no tools and its output is schema-checked. Injection phrases (including hidden notes to "the AI assistant") go to a human. Logs hold no ticket text and are redacted again.

## Eval and fix

10 labelled examples from `GET /examples` (labels never written by the model; scored per field, plus unsafe replies and needless escalations):

| | language | category | priority | action |
|---|---|---|---|---|
| Baseline | 90% | 100% | 90% | 100% |
| After fix | 100% | 100% | 100% | 100% |

**Found:** E01, an English ticket, was labelled `nl` and answered in Dutch; the reply check only compared the reply with the model's own label. **Fix:** detect the language in code, pass it to the model, cross-check afterwards (a disagreement becomes a handoff). My first attempt (prompt only) made E01 a handoff instead (`results-attempt1_*`), and a flaky model judge later rejected correct replies, which led to the code-verified evidence quotes. I tuned on these 10, so 100% is optimistic.

**Cost per 100 tickets**, measured on the final run (30 tickets): 93,205 input + 7,335 output tokens, so 310,683 + 24,450 per 100. At $0.25 / $1.50 per million tokens (list price from aggregator sites, check ai.google.dev/gemini-api/docs/pricing): 0.311 × 0.25 + 0.0245 × 1.50 = $0.078 + $0.037 = **about $0.11 (about €0.10)**. Actual spend was €0 on the free tier.

## What I would improve

Next step: a larger labelled set with a regression run per prompt change, since each edit moved other tickets. Known gaps: the evidence quotes prove a quote exists, not that it supports the claim; roadmap replies (T004, T025) say "you can find your idea", which implies it is listed; T016 ("Is this possible?") got a roadmap-only reply in earlier runs. One change to the brief: define the always-human rules by intent with examples, not by topic. "How do I upgrade?" and "where is our data stored?" were first escalated as contract and GDPR cases although F05 and F09 answer them.
