# `systemone` golden fixtures

Captured live from `POST https://llm-api.arc.vt.edu/api/v1/systemone` on
2026-11-22 with `model = decision.vllm-sr/d3-mini`. They are the contract of
record because the VT ARC gateway exposes no machine-readable OpenAPI document.

| File | Meaning |
| --- | --- |
| `noul_request.json` / `noul_response.json` | `noul` question; response carries `answers.<name>.noul` in `[0, 1]` |
| `choice_request.json` / `choice_response.json` | `choice` question with `criteria`; response carries `choice`, `probabilities`, `confidence` |
| `score_request.json` / `score_response.json` | ordered `criteria` list; response carries `score`, `legend`, `probabilities`, `confidence` |
| `error_400_empty_questions_request.json` / `..._response.json` | empty `questions` object rejected |
| `error_404_chat_completions_request.json` / `..._response.json` | `d3-mini` is decision-only; the chat path returns 404 |
| `limit_413_payload.json` | > 8 MiB body rejected with 413 |
| `limit_429_burst.json` | 5-way burst result; a `429 user_concurrent` was observed in the first 2026-11-22 run (the service does not always reject the fifth request) |
| `limit_input.json` | 30,000-character state accepted (6,091 input tokens), below the 8,192-token per-question cap |

No `Authorization` header, API key, or bearer token is stored in these files.
Response usage counters (`input_tokens`, `output_tokens`) are retained because
they are needed for the P8 payload budgeter.

## Request envelope

```json
{
  "model": "decision.vllm-sr/d3-mini",
  "state": "free text known before kickoff",
  "questions": {
    "question_name": {
      "type": "noul | choice | score",
      "instructions": "one decision question",
      "criteria": "object (choice) or ordered list (score), omitted for noul"
    }
  }
}
```

## Response envelope

```json
{
  "model": "vllm-sr/d3-mini",
  "answers": {
    "question_name": {
      "type": "noul",
      "noul": 0.02825084428381916
    }
  },
  "usage": {"input_tokens": 134, "output_tokens": 0}
}
```

`noul` is deterministic for identical payloads (observed ×3 and ×2 on a long
payload). Treat the value as a calibrated probability only after P8 fits and
validates the calibration; it is not a trained upset model by itself.
