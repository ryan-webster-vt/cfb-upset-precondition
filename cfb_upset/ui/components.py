"""Streamlit rendering helpers for the Phase 0 walking skeleton."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import streamlit as st

from cfb_upset.contracts import AgentEvent, RunResult, ScreenMatch, SlateGame


def slate_rows(
    games: Iterable[SlateGame], matches: Iterable[ScreenMatch]
) -> list[dict[str, object]]:
    """Build the sortable/filterable slate table body."""

    match_by_id = {match.game_id: match for match in matches}
    rows: list[dict[str, object]] = []
    for game in games:
        match = match_by_id.get(game.game_id)
        favorite = "—"
        market_prob = "—"
        if game.odds:
            favorite_team = game.odds.favorite_team_id
            if favorite_team == game.home.team_id:
                favorite = f"{game.home.school} {abs(game.odds.spread or 0):.1f}"
            elif favorite_team == game.away.team_id:
                favorite = f"{game.away.school} {abs(game.odds.spread or 0):.1f}"
            if game.odds.market_prob is not None:
                market_prob = f"{game.odds.market_prob:.0%}"
        rows.append(
            {
                "Matchup": game.display_name,
                "Kickoff (UTC)": game.kickoff_utc.strftime("%Y-%m-%d %H:%M"),
                "Favorite (spread)": favorite,
                "Market P(fav)": market_prob,
                "Rules matched": match.matched_count if match else 0,
                "game_id": game.game_id,
            }
        )
    return rows


def render_slate(games: Iterable[SlateGame], matches: Iterable[ScreenMatch]) -> None:
    """Render the slate table (kept separate so AppTest can find it)."""

    frame = pd.DataFrame(slate_rows(games, matches))
    st.dataframe(frame, hide_index=True, use_container_width=True)


def render_alerts(result: RunResult) -> None:
    """Render ranked alert cards with evidence and citations."""

    st.subheader(f"Ranked upset alerts ({len(result.alerts)})")
    if not result.alerts:
        st.info(result.reason or "No qualifying upset alerts")
        return

    for alert in result.alerts:
        st.markdown(f"### #{alert.rank} — {alert.game.display_name}")
        st.progress(alert.score.probability)
        st.caption(
            f"Upset probability {alert.score.probability:.1%} · "
            f"confidence {alert.score.confidence:.1%} · "
            f"backend `{alert.score.backend.value}` · model `{alert.score.model_version}`"
        )
        st.write(alert.rationale)
        st.markdown("**Matched preconditions**")
        for matched in alert.matched_specs:
            evidence = matched.evidence
            st.markdown(
                f"- `{matched.spec_id}` — {matched.title}: "
                f"{evidence.field} {evidence.op.value} {evidence.threshold} "
                f"(observed `{evidence.observed}`)"
            )
        if alert.citations:
            st.markdown("**Citations**")
            for citation in alert.citations:
                st.markdown(f"- [{citation.title}]({citation.url})")


def render_timeline(events: Iterable[AgentEvent]) -> None:
    """Render the per-agent activity timeline."""

    st.subheader("Agent activity")
    for event in events:
        payload = ", ".join(f"{key}={value}" for key, value in event.payload.items())
        suffix = f" — {payload}" if payload else ""
        st.markdown(
            f"- **{event.agent}** · `{event.phase}/{event.event_type}` · "
            f"{event.ts.strftime('%H:%M:%S')}{suffix}"
        )
