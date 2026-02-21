import os
import time
import base64
from pathlib import Path
from typing import Callable, Dict, Optional

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from db import (
    add_counter_event,
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

CONFIRM_TIMEOUT_SECONDS = 8
ACTION_COOLDOWN_SECONDS = 0.75
STEP_SMALL = 1
GLOBAL_HISTORY_START_UTC = pd.Timestamp("2026-02-21 13:30:00", tz="UTC")


def _init_ui_state() -> None:
    defaults = {
        "visible_players": PLAYERS.copy(),
        "selected_window": "Letzte 24 Stunden",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_data
def _load_background_image_data_uri(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _resolve_background_image_data_uri() -> str:
    candidates = [
        Path(__file__).resolve().parent / "assets" / "kai.jpg",
        Path(
            "C:/Users/bengt/.cursor/projects/"
            "c-Users-bengt-OneDrive-Desktop-10-Desktop/assets/"
            "c__Users_bengt_OneDrive_Desktop_10_Desktop_assets_kai.jpg"
        ),
    ]
    for candidate in candidates:
        data_uri = _load_background_image_data_uri(str(candidate))
        if data_uri:
            return data_uri
    return ""


def _apply_theme_mode(bg_data_uri: str) -> None:
    bg_overlay_css = ""
    if bg_data_uri:
        bg_overlay_css = f"""
        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            background-image: url('{bg_data_uri}');
            background-repeat: no-repeat;
            background-position: right top;
            background-size: auto 100%;
            opacity: 0.5;
            -webkit-mask-image: linear-gradient(to left, rgba(0, 0, 0, 1) 0%, rgba(0, 0, 0, 0) 100%);
            mask-image: linear-gradient(to left, rgba(0, 0, 0, 1) 0%, rgba(0, 0, 0, 0) 100%);
            pointer-events: none;
            z-index: 0;
        }}
        .stApp > header, .stApp > div {{
            position: relative;
            z-index: 1;
        }}
        """

    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: #0b1220;
            color: #e5e7eb;
        }}
        [data-testid="stSidebar"] {{
            background-color: rgba(15, 23, 42, 0.88);
        }}
        [data-testid="stMetricValue"],
        [data-testid="stMetricLabel"],
        [data-testid="stMarkdownContainer"],
        [data-testid="stHeader"] {{
            color: #e5e7eb;
        }}
        {bg_overlay_css}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_db_runtime_error(error: Exception) -> None:
    st.error("Datenbankzugriff fehlgeschlagen.")
    st.caption("Bitte pruefe Verbindungsdaten, Host-Erreichbarkeit und Datenbankstatus.")
    with st.expander("Technische Details"):
        st.code(str(error))
    st.stop()


def _render_history_chart(chart_df) -> None:
    plot_df = chart_df.reset_index().melt(
        id_vars="created_at",
        var_name="player_name",
        value_name="counter_value",
    )
    axis_color = "#e5e7eb"
    grid_color = "#374151"
    plot_fill = "#0f172a"
    chart = (
        alt.Chart(plot_df)
        .mark_line()
        .encode(
            x=alt.X("created_at:T", title="Zeit"),
            y=alt.Y("counter_value:Q", title="Counter"),
            color=alt.Color(
                "player_name:N",
                title="Spieler",
                scale=alt.Scale(scheme="tableau10"),
            ),
            tooltip=[
                alt.Tooltip("created_at:T", title="Zeit"),
                alt.Tooltip("player_name:N", title="Spieler"),
                alt.Tooltip("counter_value:Q", title="Counter"),
            ],
        )
        .properties(height=360)
        .configure_axis(
            labelColor=axis_color,
            titleColor=axis_color,
            gridColor=grid_color,
        )
        .configure_legend(
            labelColor=axis_color,
            titleColor=axis_color,
        )
        .configure_view(strokeOpacity=0, fill=plot_fill)
        .configure(background="transparent")
    )
    st.altair_chart(chart, use_container_width=True)


def _apply_global_history_start(event_history: pd.DataFrame) -> pd.DataFrame:
    if event_history.empty:
        return event_history
    filtered = event_history.copy()
    created_at_utc = pd.to_datetime(filtered["created_at"], errors="coerce", utc=True)
    filtered = filtered.loc[created_at_utc >= GLOBAL_HISTORY_START_UTC].copy()
    filtered["created_at"] = pd.to_datetime(filtered["created_at"], errors="coerce")
    return filtered


def _counter_value_color(value: int) -> str:
    magnitude = min(abs(int(value)), 50)
    intensity = magnitude / 50.0
    low = (34, 211, 238)
    high = (6, 182, 212)
    r = int(low[0] + (high[0] - low[0]) * intensity)
    g = int(low[1] + (high[1] - low[1]) * intensity)
    b = int(low[2] + (high[2] - low[2]) * intensity)
    return f"rgb({r}, {g}, {b})"


def _render_counter_header(player: str, current_value: int) -> None:
    value_color = _counter_value_color(current_value)
    label_color = "#d1d5db"
    st.markdown(
        f"""
        <div style="line-height:1.1; margin-bottom:0.4rem;">
            <div style="font-size:0.9rem; color:{label_color};">{player}</div>
            <div style="font-size:2rem; font-weight:700; color:{value_color};">{current_value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _arm_action(action_key: str) -> None:
    st.session_state[f"armed_until:{action_key}"] = time.time() + CONFIRM_TIMEOUT_SECONDS


def _is_action_armed(action_key: str) -> bool:
    return float(st.session_state.get(f"armed_until:{action_key}", 0.0)) > time.time()


def _disarm_action(action_key: str) -> None:
    st.session_state.pop(f"armed_until:{action_key}", None)


def _run_db_action(action_key: str, callback: Callable[[], None]) -> bool:
    now = time.time()
    cooldown_key = f"last_action:{action_key}"
    last_action_at = float(st.session_state.get(cooldown_key, 0.0))
    if now - last_action_at < ACTION_COOLDOWN_SECONDS:
        st.warning("Bitte kurz warten, um Doppelklicks zu vermeiden.")
        return False

    try:
        callback()
    except SQLAlchemyError as exc:
        st.warning(f"DB-Aktion fehlgeschlagen: {exc}")
        return False
    except Exception as exc:
        st.warning(f"Aktion fehlgeschlagen: {exc}")
        return False

    st.session_state[cooldown_key] = now
    return True


@st.cache_resource
def get_db_engine():
    database_url = st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
    if not database_url:
        database_url = "sqlite:///counter_local.db"
    engine = get_engine(database_url)
    init_db(engine, PLAYERS)
    return engine


def main() -> None:
    st.set_page_config(page_title="Player Counter Dashboard", layout="wide")
    _init_ui_state()
    bg_data_uri = _resolve_background_image_data_uri()
    _apply_theme_mode(bg_data_uri)
    st.title("LeoGÄNG")
    st.caption("Kai hat heute frei")

    using_fallback_db = not bool(st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", "")).strip())

    try:
        engine = get_db_engine()
    except SQLAlchemyError as exc:
        _show_db_runtime_error(exc)
    except Exception as exc:
        _show_db_runtime_error(exc)

    try:
        counters = get_latest_counters(engine, PLAYERS)
    except Exception as exc:
        _show_db_runtime_error(exc)

    st.subheader("Linienplots")

    hours = TIME_WINDOWS[st.session_state["selected_window"]]
    try:
        event_history = get_event_history(engine, hours=hours)
    except Exception as exc:
        _show_db_runtime_error(exc)
    event_history = _apply_global_history_start(event_history)

    visible_players = st.session_state["visible_players"]
    if event_history.empty:
        st.info("Noch keine Daten vorhanden. Bitte zuerst Counter klicken.")
    else:
        if visible_players:
            event_history = event_history[event_history["player_name"].isin(visible_players)]
        else:
            st.warning("Keine Spieler fuer den Plot ausgewaehlt.")
            event_history = event_history.iloc[0:0]

        if not event_history.empty:
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

            _render_history_chart(chart_df)

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

    st.subheader("Einstellungen")
    st.selectbox("Zeitraum", options=list(TIME_WINDOWS.keys()), key="selected_window")
    visible_players = st.multiselect(
        "Spieler im Plot",
        options=PLAYERS,
        key="visible_players",
    )
    if st.button("Aktualisieren", use_container_width=True):
        st.rerun()
    if using_fallback_db:
        st.caption(
            "Hinweis: Kein `DATABASE_URL` gesetzt, derzeit SQLite (`counter_local.db`). "
            "Bei App-Sleep/Neustart in der Cloud sind diese Daten nicht verlaesslich dauerhaft."
        )
    else:
        st.caption("Externe DB aktiv: Daten bleiben auch nach Inaktivitaet/Neustart erhalten.")
    if not bg_data_uri:
        st.caption("Hintergrundbild fehlt: bitte `assets/kai.jpg` ins Projekt legen.")

    st.subheader("Counter Steuerung")
    for row_start in (0, 4):
        cols = st.columns(4)
        for index, col in enumerate(cols):
            player = PLAYERS[row_start + index]
            with col:
                current_value = counters.get(player, 0)
                _render_counter_header(player, current_value)
                d1, d2 = st.columns(2)
                a1, a2 = st.columns(2)
                reset_action_key = f"{player}:reset"
                undo_action_key = f"{player}:undo"

                if d1.button(
                    f"-{STEP_SMALL}",
                    key=f"{player}-minus-small",
                    use_container_width=True,
                ):
                    if _run_db_action(
                        action_key=f"{player}:minus_small",
                        callback=lambda p=player: add_counter_event(engine, p, -STEP_SMALL),
                    ):
                        st.rerun()
                if d2.button(f"+{STEP_SMALL}", key=f"{player}-plus-small", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:plus_small",
                        callback=lambda p=player: add_counter_event(engine, p, STEP_SMALL),
                    ):
                        st.rerun()

                reset_label = "Reset bestaetigen" if _is_action_armed(reset_action_key) else "Reset"
                if a1.button(reset_label, key=f"{player}-reset", use_container_width=True):
                    if _is_action_armed(reset_action_key):
                        _disarm_action(reset_action_key)
                        if _run_db_action(
                            action_key=reset_action_key,
                            callback=lambda p=player: reset_counter(engine, p),
                        ):
                            st.rerun()
                    else:
                        _arm_action(reset_action_key)
                        st.info(f"{player}: Reset innerhalb von {CONFIRM_TIMEOUT_SECONDS}s bestaetigen.")

                undo_label = "Undo bestaetigen" if _is_action_armed(undo_action_key) else "Undo"
                if a2.button(undo_label, key=f"{player}-undo", use_container_width=True):
                    if _is_action_armed(undo_action_key):
                        _disarm_action(undo_action_key)
                        if _run_db_action(
                            action_key=undo_action_key,
                            callback=lambda p=player: undo_last_event(engine, p),
                        ):
                            st.rerun()
                    else:
                        _arm_action(undo_action_key)
                        st.info(f"{player}: Undo innerhalb von {CONFIRM_TIMEOUT_SECONDS}s bestaetigen.")

                target_value = st.number_input(
                    "Direkt setzen",
                    value=int(current_value),
                    step=1,
                    key=f"{player}-target-value",
                )
                if st.button("Setzen", key=f"{player}-set-exact", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:set",
                        callback=lambda p=player, value=target_value: set_counter_value(engine, p, int(value)),
                    ):
                        st.rerun()


if __name__ == "__main__":
    main()
