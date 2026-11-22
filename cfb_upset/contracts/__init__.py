"""Public contract catalogue.

Import from ``cfb_upset.contracts`` rather than from the individual modules so
that a later refactor cannot silently change an agent handoff.
"""

from cfb_upset.contracts.common import Citation, Provenance, StrictModel, UTCDateTime
from cfb_upset.contracts.monitor import (
    AgentEvent,
    MatchedSpec,
    RuleEvidence,
    ScreenMatch,
    ScreenState,
)
from cfb_upset.contracts.scoring import (
    RankedAlert,
    RunResult,
    RunStatus,
    ScoreBackend,
    UpsetScore,
)
from cfb_upset.contracts.slate import (
    FavoriteSource,
    GameStatus,
    MarketProbSource,
    OddsInfo,
    SlateGame,
    TeamInfo,
    VenueInfo,
    WeatherInfo,
)
from cfb_upset.contracts.spec import (
    MissingPolicy,
    PreconditionSpec,
    PreconditionStatus,
    RuleOp,
    RuleSpec,
)

__all__ = [
    "AgentEvent",
    "Citation",
    "FavoriteSource",
    "GameStatus",
    "MarketProbSource",
    "MatchedSpec",
    "MissingPolicy",
    "OddsInfo",
    "PreconditionSpec",
    "PreconditionStatus",
    "Provenance",
    "RankedAlert",
    "RuleEvidence",
    "RuleOp",
    "RuleSpec",
    "RunResult",
    "RunStatus",
    "ScoreBackend",
    "ScreenMatch",
    "ScreenState",
    "SlateGame",
    "StrictModel",
    "TeamInfo",
    "UTCDateTime",
    "UpsetScore",
    "VenueInfo",
    "WeatherInfo",
]
