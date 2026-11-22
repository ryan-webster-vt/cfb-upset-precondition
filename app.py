"""Streamlit entry point: the Phase 0 walking skeleton.

Run with ``streamlit run app.py``. It uses fixture data only: no network, no
LLM, no database. The button runs the deterministic screen and stub scorer, then
renders ranked alerts and the agent timeline.
"""

from __future__ import annotations

import streamlit as st

from cfb_upset.domain.screen import screen_slate
from cfb_upset.fixtures.demo import demo_contexts, demo_games, demo_specs
from cfb_upset.pipelines.skeleton import run_walking_skeleton
from cfb_upset.ui.components import render_alerts, render_slate, render_timeline


def main() -> None:
    st.set_page_config(
        page_title="CFB Upset Condition Profiler",
        page_icon="🏈",
        layout="wide",
    )
    st.title("CFB Upset Condition Profiler")
    st.caption(
        "Phase 0 walking skeleton — fixture slate, deterministic rule screen, "
        "stubbed scorer. No network or LLM is used on this page."
    )

    games = demo_games()
    specs = demo_specs()
    contexts = demo_contexts()
    preview_matches = screen_slate(games, specs, contexts)

    st.subheader("Today's fixture slate")
    render_slate(games, preview_matches)

    labels = {game.game_id: game.display_name for game in games}
    selected_ids = st.multiselect(
        "Games to analyze",
        options=list(labels),
        default=list(labels),
        format_func=lambda game_id: labels[game_id],
    )
    analyzed = st.button("Analyze", type="primary")

    if analyzed:
        if not selected_ids:
            st.warning("Select at least one game before analyzing.")
            st.session_state.pop("cfb_result", None)
        else:
            selected_games = [game for game in games if game.game_id in selected_ids]
            selected_contexts = {game_id: contexts[game_id] for game_id in selected_ids}
            st.session_state["cfb_result"] = run_walking_skeleton(
                selected_games,
                specs,
                selected_contexts,
            )

    result = st.session_state.get("cfb_result")
    if result is not None:
        st.divider()
        st.caption(
            f"Run `{result.run_id}` · status `{result.status.value}` · "
            f"degraded `{result.degraded}`"
        )
        render_alerts(result)
        st.divider()
        render_timeline(result.events)


main()
