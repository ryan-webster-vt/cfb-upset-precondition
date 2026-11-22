"""Slate table rendering helper tests."""

from __future__ import annotations

from datetime import UTC, datetime

from cfb_upset.contracts import FavoriteSource, OddsInfo
from cfb_upset.domain.screen import screen_slate
from cfb_upset.fixtures.demo import demo_contexts, demo_games, demo_specs
from cfb_upset.ui.components import slate_rows

UTC = UTC


def test_slate_rows_render_real_values() -> None:
    games = demo_games()
    matches = screen_slate(games, demo_specs(), demo_contexts())
    rows = slate_rows(games, matches)

    assert len(rows) == 3
    assert rows[0]["Matchup"] == "Miami at Virginia Tech"
    assert rows[0]["Kickoff (UTC)"] == "2026-11-28 17:00"
    assert rows[0]["Favorite (spread)"] == "Miami 7.5"
    assert rows[0]["Market P(fav)"] == "72%"
    assert rows[0]["Rules matched"] == 3
    assert rows[1]["Rules matched"] == 0
    assert rows[2]["Favorite (spread)"] == "Georgia 14.0"


def test_slate_rows_handle_missing_odds_and_absent_match() -> None:
    game = demo_games()[0].model_copy(update={"odds": None})
    rows = slate_rows([game], [])

    assert rows[0]["Favorite (spread)"] == "—"
    assert rows[0]["Market P(fav)"] == "—"
    assert rows[0]["Rules matched"] == 0


def test_slate_rows_handle_missing_market_probability() -> None:
    game = demo_games()[0]
    updated = game.model_copy(
        update={
            "odds": OddsInfo(
                provider="Test",
                favorite_team_id=game.home.team_id,
                spread=3.0,
                favorite_source=FavoriteSource.STRENGTH_PROXY,
                known_at=datetime(2026, 11, 27, 12, 0, tzinfo=UTC),
            )
        }
    )
    rows = slate_rows([updated], [])

    assert rows[0]["Favorite (spread)"] == "Virginia Tech 3.0"
    assert rows[0]["Market P(fav)"] == "—"


def test_slate_rows_handle_unknown_favorite() -> None:
    game = demo_games()[0]
    updated = game.model_copy(
        update={
            "odds": OddsInfo(
                provider="Test",
                favorite_team_id=None,
                spread=-2.5,
                favorite_source=FavoriteSource.STRENGTH_PROXY,
                known_at=datetime(2026, 11, 27, 12, 0, tzinfo=UTC),
            )
        }
    )
    rows = slate_rows([updated], [])

    assert rows[0]["Favorite (spread)"] == "—"
