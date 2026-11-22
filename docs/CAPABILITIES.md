# Capability Matrix — Phase 0

**Generated:** 2026-11-22T20:29:32.518572+00:00  
**Probe version:** p0.1  
**Status legend:** PASS = verified live; FAIL = unavailable/contrary to plan; SKIP = no credential/endpoint; PARTIAL = observed but incomplete.

## Summary

| Status | Count |
| --- | ---: |
| FAIL | 1 |
| PARTIAL | 2 |
| PASS | 34 |
| SKIP | 5 |

## Checks

| Capability | Status | Detail | Evidence (redacted) |
| --- | --- | --- | --- |
| ESPN historical scoreboard | **PASS** | HTTP 200; 53 events; odds_present=False (72 ms) | `{"events": 53, "kind": "json", "status": 200}` |
| ESPN future slate + odds | **PASS** | HTTP 200; 53 events; 53 with odds (125 ms) | `{"events": 53, "status": 200, "with_odds": 53}` |
| ESPN summary | **PASS** | HTTP 200; keys=['againstTheSpread', 'article', 'boxscore', 'broadcasts', 'drives', 'format', 'gameInfo', 'header', 'leaders', 'meta'] (89 ms) | `{"keys": ["againstTheSpread", "article", "boxscore", "broadcasts", "drives"], "status": 200}` |
| ESPN core odds | **PASS** | HTTP 200; 2 items; providers=['ESPN BET', 'ESPN Bet - Live Odds'] (47 ms) | `{"items": 2, "providers": ["ESPN BET", "ESPN Bet - Live Odds"], "status": 200}` |
| ESPN weekly rankings | **PASS** | HTTP 200; 2 ranking collections; polls=['AP Top 25', 'AFCA Coaches Poll'] (56 ms) | `{"polls": ["AP Top 25", "AFCA Coaches Poll"], "rankings": 2, "status": 200}` |
| ESPN teams | **PASS** | HTTP 200; 763 teams (44 ms) | `{"status": 200, "teams": 763}` |
| ESPN group 80 (FBS) | **PASS** | HTTP 200; name=FBS (11 ms) | `{"name": "FBS", "status": 200}` |
| ESPN group 81 (FCS) | **PASS** | HTTP 200; name=FCS (10 ms) | `{"name": "FCS", "status": 200}` |
| ARC /models | **PASS** | HTTP 200; 14 model ids (168 ms) | `{"models": ["vt-arc-llm", "GLM-5.3", "GLM-5.3-thinking-high", "gpt-oss-120b", "gpt-oss-120b-thinking-high"], "status": 200}` |
| ARC chat JSON mode | **PASS** | HTTP 200; json_parse=True; finish_reason=stop; content='{"ok": true}' (4194 ms) | `{"content_chars": 12, "finish_reason": "stop", "json_parse": true, "kind": "json", "reasoning_chars": 295, "status": 200}` |
| systemone noul | **PASS** | HTTP 200; kind=json; answer_keys=['upset_likely'] (113 ms) | `{"status": 200, "usage": {"input_tokens": 134, "output_tokens": 0}}` |
| systemone choice | **PASS** | HTTP 200; kind=json; answer_keys=['confirm'] (110 ms) | `{"status": 200, "usage": {"input_tokens": 161, "output_tokens": 0}}` |
| systemone score | **PASS** | HTTP 200; kind=json; answer_keys=['risk'] (117 ms) | `{"status": 200, "usage": {"input_tokens": 143, "output_tokens": 0}}` |
| systemone determinism (noul x3) | **PASS** | values=[0.02825084428381916, 0.02825084428381916, 0.02825084428381916]; latencies_ms=[113, 113, 110] | `{"latencies_ms": [113.29902458190918, 112.86637115478516, 109.94038200378418], "values": [0.02825084428381916, 0.02825084428381916, 0.02825084428381916]}` |
| systemone determinism (long payload x2) | **PASS** | values=[0.35116546408574767, 0.35116546408574767]; latencies_ms=[844, 828] | `{"chars": 20099, "latencies_ms": [844.1589002609253, 828.0099010467529], "usage": [{"input_tokens": 4291, "output_tokens": 0}, {"input_tokens": 4291, "output_tokens": 0}], "values": [0.35116546408574767, 0.35116546408574767]}` |
| systemone 400 envelope | **PASS** | HTTP 400; body={'error': {'code': 400, 'message': '"questions" must be a non-empty object', 'type': 'invalid_request_error'}} (59 ms) | `{"body": {"error": {"code": 400, "message": "\"questions\" must be a non-empty object", "type": "invalid_request_error"}}, "status": 400}` |
| systemone 404 on /chat/completions | **PASS** | HTTP 404; body={'error': 'd3 is a decision model and cannot chat or complete text: use POST /v1/systemone with a state and questions'} (46 ms) | `{"body": {"error": "d3 is a decision model and cannot chat or complete text: use POST /v1/systemone with a state and questions"}, "status": 404}` |
| systemone 5-way burst (429) | **PARTIAL** | statuses=[200, 200, 200, 200, 200]; 429_observed=False (175 ms) | `{"results": [{"body": "{'model': 'vllm-sr/d3-mini', 'answers': {'upset_likely': {'type': 'noul', 'noul': 0.03036596393867679}}, 'usage': {'input_tokens': 141, 'output_tokens': 0}}", "status": 200}, {"body": "{'model': 'vllm-sr/d3-mini', 'answers': {'upset_likely': {'type': 'noul', 'noul': 0.02632255576954074}}, 'usage': {'input_tokens': 141, 'output_tokens': 0}}", "status": 200}, {"body": "{'model': 'vllm-sr/d3-mini', 'answers': {'upset_likely': {'type': 'noul', 'noul': 0.026151513400913096}}, 'usage': {'input_tokens': 141, 'output_tokens': 0}}", "status": 200}, {"body": "{'model': 'vllm-sr/d3-mini', 'answers': {'upset_likely': {'type': 'noul', 'noul': 0.026627641451289263}}, 'usage': {'inpu…` |
| systemone oversized body (413) | **PASS** | HTTP 413; body={'detail': 'Request body too large'} (160 ms) | `{"body": {"detail": "Request body too large"}, "status": 413}` |
| systemone near-8k input | **PASS** | chars=30000; HTTP 200; usage={'input_tokens': 6091, 'output_tokens': 0} (1597 ms) | `{"chars": 30000, "status": 200, "usage": {"input_tokens": 6091, "output_tokens": 0}}` |
| systemone queue timeout (503) | **SKIP** | opt-in --deep-limits; holding four requests for 30 s would consume the shared window | `{}` |
| Ollama qwen3-embedding:8b width/norm | **PASS** | HTTP 200; dims=[4096, 4096, 4096]; norms=[1.000001, 1.0, 1.0] (181 ms) | `{"dims": [4096, 4096, 4096], "expected_dim": 4096, "kind": "json", "norms": [1.0000008629661503, 0.9999997378543456, 0.9999998014046935], "status": 200}` |
| Ollama qwen3-embedding:8b batch cap | **PASS** | results=[{'size': 1, 'status': 200, 'returned': 1}, {'size': 4, 'status': 200, 'returned': 4}, {'size': 8, 'status': 200, 'returned': 8}, {'size': 16, 'status': 200, 'returned': 16}, {'size': 32, 'status': 200, 'returned': 32}] | `{"batches": [{"returned": 1, "size": 1, "status": 200}, {"returned": 4, "size": 4, "status": 200}, {"returned": 8, "size": 8, "status": 200}, {"returned": 16, "size": 16, "status": 200}, {"returned": 32, "size": 32, "status": 200}]}` |
| Ollama qwen3-embedding:8b over-context | **PASS** | chars=144000; HTTP 200; dim=4096 (3479 ms) | `{"chars": 144000, "dim": 4096, "status": 200}` |
| Ollama qwen3-embedding:8b instruction prefix | **PASS** | cosine(raw, instruct)=0.672282 | `{"cosine": 0.6722816516176133, "template": "Instruct: \u2026\\nQuery: \u2026"}` |
| ARC Qwen3-Embedding-4B width/norm | **PASS** | HTTP 200; dims=[2560, 2560, 2560]; norms=[1.0, 1.0, 1.0] (83 ms) | `{"dims": [2560, 2560, 2560], "expected_dim": 2560, "kind": "json", "norms": [0.9999999535694962, 0.9999999634967504, 0.9999999745842773], "status": 200}` |
| ARC Qwen3-Embedding-4B batch cap | **PASS** | results=[{'size': 1, 'status': 200, 'returned': 1}, {'size': 4, 'status': 200, 'returned': 4}, {'size': 8, 'status': 200, 'returned': 8}, {'size': 16, 'status': 200, 'returned': 16}, {'size': 32, 'status': 200, 'returned': 32}] | `{"batches": [{"returned": 1, "size": 1, "status": 200}, {"returned": 4, "size": 4, "status": 200}, {"returned": 8, "size": 8, "status": 200}, {"returned": 16, "size": 16, "status": 200}, {"returned": 32, "size": 32, "status": 200}]}` |
| ARC Qwen3-Embedding-4B over-context | **PARTIAL** | chars=144000; HTTP 400; dim=0 (91 ms) | `{"chars": 144000, "dim": 0, "status": 400}` |
| CFBD /lines 2021 week 1 | **PASS** | HTTP 200; games=89; lines=353; spreadOpen_null=268 (75.9%); providers=['Bovada', 'Caesars (Pennsylvania)', 'William Hill (New Jersey)', 'consensus', 'numberfire', 'teamrankings'] (607 ms) | `{"games": 89, "lines": 353, "over_under_open_null": 268, "providers": ["Bovada", "Caesars (Pennsylvania)", "William Hill (New Jersey)", "consensus", "numberfire"], "spread_open_null": 268, "spread_open_null_rate": 0.7592067988668555, "status": 200}` |
| CFBD /lines 2025 week 1 | **PASS** | HTTP 200; games=127; lines=270; spreadOpen_null=31 (11.5%); providers=['Bovada', 'DraftKings', 'ESPN Bet'] (85 ms) | `{"games": 127, "lines": 270, "over_under_open_null": 33, "providers": ["Bovada", "DraftKings", "ESPN Bet"], "spread_open_null": 31, "spread_open_null_rate": 0.11481481481481481, "status": 200}` |
| CFBD /venues | **PASS** | HTTP 200; venues=854; non_null={'latitude': 806, 'longitude': 806, 'elevation': 379, 'dome': 851, 'timezone': 364} (135 ms) | `{"non_null": {"dome": 851, "elevation": 379, "latitude": 806, "longitude": 806, "timezone": 364}, "rates": {"dome": 0.9964871194379391, "elevation": 0.44379391100702575, "latitude": 0.9437939110070258, "longitude": 0.9437939110070258, "timezone": 0.4262295081967213}, "status": 200, "venues": 854}` |
| Open-Meteo historical forecast 2021-09-04 | **PASS** | HTTP 200; hours=24; variables=['cloud_cover', 'precipitation', 'temperature_2m', 'time', 'wind_speed_10m'] (540 ms) | `{"generationtime_ms": 0.1176595687866211, "hours": 24, "kind": "json", "status": 200, "variables": ["cloud_cover", "precipitation", "temperature_2m", "time", "wind_speed_10m"]}` |
| Open-Meteo historical forecast 2025-11-15 | **PASS** | HTTP 200; hours=24; variables=['cloud_cover', 'precipitation', 'temperature_2m', 'time', 'wind_speed_10m'] (135 ms) | `{"generationtime_ms": 0.17976760864257812, "hours": 24, "kind": "json", "status": 200, "variables": ["cloud_cover", "precipitation", "temperature_2m", "time", "wind_speed_10m"]}` |
| Open-Meteo previous-runs archive | **PASS** | HTTP 200; hourly_keys=['temperature_2m', 'time'] (564 ms) | `{"hourly_keys": ["temperature_2m", "time"], "status": 200}` |
| Brave Search | **SKIP** | HTTP 422; key_configured=False; results=0 (192 ms) | `{"results": 0, "status": 422}` |
| Fetch MCP | **SKIP** | FETCH_BASE_URL is empty | `{}` |
| Deep Research MCP | **SKIP** | DEEP_RESEARCH_BASE_URL is empty | `{}` |
| MCP transport | **SKIP** | runtime adapters (D9) are used; no harness-level MCP servers are configured | `{}` |
| chromadb import | **FAIL** | not installed (P1.11 adds it) | `{}` |
| Disk space | **PASS** | free=2811.0 GiB; total=3753.4 GiB | `{"free_gib": 2811.0}` |
| Secret hygiene | **PASS** | .env=True; .env.example=True; git_check_ignore_exit=0 | `{"git_check_ignore": ".env"}` |
| Docs toolchain | **PASS** | quarto=True; npx=True; pandoc=True | `{"npx": true, "pandoc": true, "quarto": true}` |

## Chosen backends (P0.8)

- **scorer (D1):** d3_mini via POST /systemone (primary); calibrated_rules fallback
- **research provider (D2):** seeded_literature (no MCP endpoint configured)
- **weather (D3):** open_meteo historical forecast; WEATHER_LEAD_HOURS_MAX=6 (recorded actual lead)
- **embeddings (D8):** ollama qwen3-embedding:8b (4096-d, primary); ARC Qwen3-Embedding-4B (2560-d, optional)
- **odds / venues (D17):** CFBD /lines + /venues primary; ESPN open + strength proxy fallback
- **MCP transport (D9):** runtime HTTP adapters with recorded fixtures; no harness MCP

## `systemone` operating envelope

| Limit | Value |
| --- | --- |
| model | decision.vllm-sr/d3-mini |
| endpoint | https://llm-api.arc.vt.edu/api/v1/systemone |
| max_concurrency | 4 |
| max_input_tokens_per_question | 8192 |
| max_request_bytes | 8388608 |
| queue_wait_s | 30 |
| questions_per_game_cap | 2 |


## Captured fixtures

- `tests/fixtures/arc/chat_json.json`
- `tests/fixtures/cfbd/lines_2021_w1.json`
- `tests/fixtures/cfbd/lines_2025_w1.json`
- `tests/fixtures/cfbd/venues.json`
- `tests/fixtures/embeddings/arc_qwen3-embedding-4b_over_context.json`
- `tests/fixtures/embeddings/arc_qwen3-embedding-4b_response.json`
- `tests/fixtures/embeddings/ollama_qwen3-embedding-8b_over_context.json`
- `tests/fixtures/embeddings/ollama_qwen3-embedding-8b_response.json`
- `tests/fixtures/espn/odds_401628543.json`
- `tests/fixtures/espn/rankings_2024_w10.json`
- `tests/fixtures/espn/scoreboard_20251115.json`
- `tests/fixtures/espn/scoreboard_20261128.json`
- `tests/fixtures/espn/summary_401628543.json`
- `tests/fixtures/systemone/README.md`
- `tests/fixtures/systemone/choice_request.json`
- `tests/fixtures/systemone/choice_response.json`
- `tests/fixtures/systemone/error_400_empty_questions_request.json`
- `tests/fixtures/systemone/error_400_empty_questions_response.json`
- `tests/fixtures/systemone/error_404_chat_completions_request.json`
- `tests/fixtures/systemone/error_404_chat_completions_response.json`
- `tests/fixtures/systemone/limit_413_payload.json`
- `tests/fixtures/systemone/limit_429_burst.json`
- `tests/fixtures/systemone/limit_input.json`
- `tests/fixtures/systemone/noul_request.json`
- `tests/fixtures/systemone/noul_response.json`
- `tests/fixtures/systemone/score_request.json`
- `tests/fixtures/systemone/score_response.json`
- `tests/fixtures/weather/historical_2021-09-04.json`
- `tests/fixtures/weather/historical_2025-11-15.json`

## Notes

- Golden `systemone` fixtures are committed under `tests/fixtures/systemone/`.
- The 5-way burst, oversized-body, and queue-timeout probes are best-effort because `systemone` is a shared per-user service.
- CFBD 2021 week-1 open-line coverage is measured live; the strength proxy remains the fallback when `spreadOpen` is null.
- No credential is written to the report or fixtures.

- A fifth concurrent `systemone` request returned 429 `user_concurrent` in the first 2026-11-22 run; a later run accepted all five. The 429 path is therefore verified but not reproducible on demand; the 4-request semaphore remains mandatory.

## Redaction

No `Authorization` header, API key, or token is written to this report or to the committed fixtures. Evidence contains status codes, counts, field names, measured widths, and model ids only.

