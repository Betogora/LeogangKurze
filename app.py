import os
from typing import Dict, Optional

import streamlit as st

from db import (
    add_counter_event,
    get_database_url,
    get_engine,
    get_event_history,
    get_latest_counters,
    init_db,
    reset_counter,
    set_counter_value,
    undo_last_event,
)

PLAYERS = [
    "Niklas",
    "Kai",
    "Damian",
    "Jan",
    "Noemi",
    "Lotti",
    "Bengt",
    "Eddy",
]

TIME_WINDOWS: Dict[str, Optional[int]] = {
    "Letzte 2 Stunden": 2,
    "Letzte 24 Stunden": 24,
    "Letzte 7 Tage": 24 * 7,
    "Alles": None,
}


@st.cache_resource
def get_db_engine():
    database_url = st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", ""))
    if not database_url:
        database_url = get_database_url()
    engine = get_engine(database_url)
    init_db(engine, PLAYERS)
    return engine


def main() -> None:
    st.set_page_config(page_title="Player Counter Dashboard", layout="wide")
    st.title("Player Counter Dashboard")
    st.caption("Persistente Counter-Historie fuer 8 Spieler")

    engine = get_db_engine()
    counters = get_latest_counters(engine, PLAYERS)

    with st.sidebar:
        st.subheader("QoL Einstellungen")
        step_small = st.number_input("Kleiner Schritt", min_value=1, value=1, step=1)
        step_large = st.number_input("Grosser Schritt", min_value=2, value=5, step=1)
        visible_players = st.multiselect(
            "Spieler im Plot",
            options=PLAYERS,
            default=PLAYERS,
        )

    st.subheader("Counter Steuerung")
    for row_start in (0, 4):
        cols = st.columns(4)
        for index, col in enumerate(cols):
            player = PLAYERS[row_start + index]
            with col:
                current_value = counters.get(player, 0)
                st.metric(label=player, value=current_value)
                b1, b2, b3, b4, b5 = st.columns(5)
                if b1.button(f"-{step_large}", key=f"{player}-minus-large", use_container_width=True):
                    add_counter_event(engine, player, -int(step_large))
                    st.rerun()
                if b2.button(f"-{step_small}", key=f"{player}-minus-small", use_container_width=True):
                    add_counter_event(engine, player, -int(step_small))
                    st.rerun()
                if b3.button(f"+{step_small}", key=f"{player}-plus-small", use_container_width=True):
                    add_counter_event(engine, player, int(step_small))
                    st.rerun()
                if b4.button(f"+{step_large}", key=f"{player}-plus-large", use_container_width=True):
                    add_counter_event(engine, player, int(step_large))
                    st.rerun()
                if b5.button("Reset", key=f"{player}-reset", use_container_width=True):
                    reset_counter(engine, player)
                    st.rerun()

                target_value = st.number_input(
                    "Direkt setzen",
                    value=int(current_value),
                    step=1,
                    key=f"{player}-target-value",
                )
                e1, e2 = st.columns(2)
                if e1.button("Setzen", key=f"{player}-set-exact", use_container_width=True):
                    set_counter_value(engine, player, int(target_value))
                    st.rerun()
                if e2.button("Undo", key=f"{player}-undo", use_container_width=True):
                    undo_last_event(engine, player)
                    st.rerun()

    st.divider()
    st.subheader("Linienplots")

    left, right = st.columns([2, 1])
    with left:
        selected_window = st.selectbox("Zeitraum", options=list(TIME_WINDOWS.keys()), index=1)
    with right:
        if st.button("Aktualisieren", use_container_width=True):
            st.rerun()

    hours = TIME_WINDOWS[selected_window]
    event_history = get_event_history(engine, hours=hours)

    if event_history.empty:
        st.info("Noch keine Daten vorhanden. Bitte zuerst Counter klicken.")
    else:
        if visible_players:
            event_history = event_history[event_history["player_name"].isin(visible_players)]
        else:
            st.warning("Keine Spieler fuer den Plot ausgewaehlt.")
            return

        chart_df = event_history.pivot_table(
            index="created_at",
            columns="player_name",
            values="counter_value",
            aggfunc="last",
        ).sort_index()
        chart_df = chart_df.ffill().fillna(0)

        for player in visible_players:
            if player not in chart_df.columns:
                chart_df[player] = 0
        chart_df = chart_df[visible_players]

        st.line_chart(chart_df, use_container_width=True)
        st.download_button(
            "CSV Export (aktueller Zeitraum)",
            data=event_history.to_csv(index=False).encode("utf-8"),
            file_name="counter_events.csv",
            mime="text/csv",
            use_container_width=True,
        )

        with st.expander("Letzte Events anzeigen"):
            st.dataframe(
                event_history.sort_values("created_at", ascending=False).head(100),
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
