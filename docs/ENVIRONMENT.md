# Environment

## Canonical environment

Use the course conda environment:

```bash
conda activate ads_5984
python --version        # 3.12.13
make doctor             # verifies chromadb + Streamlit + Pydantic
```

Key packages observed on 2026-11-22:

| Package | Version |
| --- | --- |
| Python | 3.12.13 |
| `chromadb` | 1.1.1 |
| `streamlit` | 1.60.0 |
| `pydantic` | 2.12.5 |
| `pydantic-settings` | 2.14.2 |
| `httpx` | 0.28.1 |
| `pytest` | 8.4.2 |
| `ruff` | 0.17.2 |
| `black` | 25.12.0 |

The base Anaconda interpreter (`/opt/anaconda3/bin/python`, Python 3.13.5) can run the offline
tests but does **not** have `chromadb`. Running the capability probe there produces a false
`chromadb import FAIL`; use `ads_5984` for the probe, the app, and any final evidence.

## Commands

```bash
conda activate ads_5984
make doctor          # active interpreter + import check
make test            # offline suite (no network)
make test-cov        # rules.py / screen.py coverage
make lint            # ruff + black
make schemas         # docs/contracts/*.schema.json
make probe           # live capability matrix (network + credentials)
streamlit run app.py # fixture walking skeleton (offline)
```

`python scripts/probe.py --write` is the direct probe entry point. Add `--deep-limits` only when
the shared `systemone` window is idle; it holds four requests for the queue-timeout path.

## Credentials

`.env` is git-ignored and never committed. Copy `.env.example` when starting from a fresh clone.
The probe and fixtures never store an `Authorization` header or key.
