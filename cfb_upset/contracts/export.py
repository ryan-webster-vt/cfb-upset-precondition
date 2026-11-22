"""Export Pydantic JSON Schemas for the docs/UML appendix.

Run with ``make schemas`` or ``python -m cfb_upset.contracts.export``.
"""

from __future__ import annotations

import json
from pathlib import Path

from cfb_upset.contracts import (
    AgentEvent,
    Citation,
    OddsInfo,
    PreconditionSpec,
    Provenance,
    RankedAlert,
    RuleSpec,
    RunResult,
    ScreenMatch,
    SlateGame,
    UpsetScore,
)

OUTPUT_DIR = Path("docs/contracts")

MODELS = {
    "AgentEvent": AgentEvent,
    "Citation": Citation,
    "OddsInfo": OddsInfo,
    "PreconditionSpec": PreconditionSpec,
    "Provenance": Provenance,
    "RankedAlert": RankedAlert,
    "RuleSpec": RuleSpec,
    "RunResult": RunResult,
    "ScreenMatch": ScreenMatch,
    "SlateGame": SlateGame,
    "UpsetScore": UpsetScore,
}


def export_schemas(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    """Write one schema file per contract and return the written paths."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = output_dir / f"{name}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main() -> None:
    for path in export_schemas():
        print(path)


if __name__ == "__main__":
    main()
