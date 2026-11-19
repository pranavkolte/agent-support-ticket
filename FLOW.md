# Flow per ticket

```
GET /tickets?status=open (all pages)
  -> skip if state.json says done (a ticket that is open again after a reset is handled again)
  -> empty (subject minus "Re:" prefixes, and body)           -> close, no model call
  -> model call 1: classify + draft            (ticket as untrusted JSON, IBAN/card/CVC redacted,
                                               language_detector_result passed in, FAQ in system prompt)
  -> language corrected to the detector's answer if it is 90% sure and disagrees
  -> action resolver (first match wins):
       spam (and no sensitive topic)                     -> close
       always-human topic (model or keyword backstop)    -> handoff
       prompt-injection phrase                           -> handoff
       priority P1                                       -> handoff
       not fully answered by the FAQ / no valid FAQ id   -> handoff
       confidence < 0.8                                  -> handoff
       language disagreed with the detector              -> handoff
  -> reply candidate: code checks (language, payment data, FAQ ids, menu paths, quoted terms, links)
       then model call 2: English back-translation + help-centre quote per claim, quotes verified in code
       any failure                                       -> handoff
  -> save decision to state.json as pending
  -> POST reply | handoff | close   (503 backoff, 429 Retry-After, 409 = already done)
  -> mark done, append one redacted line to logs/run-<time>.jsonl
```

Files: `helpdesk.py` API client, `decide.py` resolver, `classify.py` + `prompts.py` model call, `verify.py` reply checks,
`guards.py` keyword rules, `redaction.py`, `language_detection.py`, `state.py`, `run_log.py`, `agent.py` loop, `evaluate.py`, `llm.py` backends.
