import os
import time
from typing import Callable, Dict, Optional

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

try:
    from db import DatabaseConfigError
except ImportError:
    # Backward compatibility for deployments with older db.py
    DatabaseConfigError = RuntimeError

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

CONFIRM_TIMEOUT_SECONDS = 8
ACTION_COOLDOWN_SECONDS = 0.75


def _init_ui_state() -> None:
    defaults = {
        "step_small": 1,
        "step_large": 5,
        "visible_players": PLAYERS.copy(),
        "selected_window": "Letzte 24 Stunden",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _show_db_setup_error(message: str) -> None:
    st.error("Die Datenbank ist nicht konfiguriert.")
    st.markdown(
        "\n".join(
            [
                "Bitte setze `DATABASE_URL` in den Streamlit-Secrets oder als Umgebungsvariable.",
                "",
                "Checkliste:",
                "- Streamlit Cloud: App -> Settings -> Secrets",
                "- Lokal: Umgebungsvariable `DATABASE_URL` setzen",
                "- Danach die App neu starten",
            ]
        )
    )
    st.code('DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DBNAME"')
    st.caption(message)
    st.stop()


def _show_db_runtime_error(error: Exception) -> None:
    st.error("Datenbankzugriff fehlgeschlagen.")
    st.caption("Bitte pruefe Verbindungsdaten, Host-Erreichbarkeit und Datenbankstatus.")
    with st.expander("Technische Details"):
        st.code(str(error))
    st.stop()


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

    _init_ui_state()

    try:
        engine = get_db_engine()
    except DatabaseConfigError as exc:
        _show_db_setup_error(str(exc))
    except SQLAlchemyError as exc:
        _show_db_runtime_error(exc)
    except Exception as exc:
        _show_db_runtime_error(exc)

    try:
        counters = get_latest_counters(engine, PLAYERS)
    except Exception as exc:
        _show_db_runtime_error(exc)

    with st.sidebar:
        st.subheader("QoL Einstellungen")
        step_small = int(st.number_input("Kleiner Schritt", min_value=1, step=1, key="step_small"))
        step_large = int(st.number_input("Grosser Schritt", min_value=2, step=1, key="step_large"))
        visible_players = st.multiselect(
            "Spieler im Plot",
            options=PLAYERS,
            key="visible_players",
        )
        if step_large <= step_small:
            st.info("Hinweis: Grosser Schritt ist kleiner/gleich kleinem Schritt.")

    st.subheader("Counter Steuerung")
    for row_start in (0, 4):
        cols = st.columns(4)
        for index, col in enumerate(cols):
            player = PLAYERS[row_start + index]
            with col:
                current_value = counters.get(player, 0)
                st.metric(label=player, value=current_value)
                b1, b2, b3, b4, b5 = st.columns(5)
                reset_action_key = f"{player}:reset"
                undo_action_key = f"{player}:undo"

                if b1.button(f"-{step_large}", key=f"{player}-minus-large", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:minus_large",
                        callback=lambda p=player, step=step_large: add_counter_event(engine, p, -int(step)),
                    ):
                        st.rerun()
                if b2.button(f"-{step_small}", key=f"{player}-minus-small", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:minus_small",
                        callback=lambda p=player, step=step_small: add_counter_event(engine, p, -int(step)),
                    ):
                        st.rerun()
                if b3.button(f"+{step_small}", key=f"{player}-plus-small", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:plus_small",
                        callback=lambda p=player, step=step_small: add_counter_event(engine, p, int(step)),
                    ):
                        st.rerun()
                if b4.button(f"+{step_large}", key=f"{player}-plus-large", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:plus_large",
                        callback=lambda p=player, step=step_large: add_counter_event(engine, p, int(step)),
                    ):
                        st.rerun()

                reset_label = "Reset bestaetigen" if _is_action_armed(reset_action_key) else "Reset"
                if b5.button(reset_label, key=f"{player}-reset", use_container_width=True):
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

                target_value = st.number_input(
                    "Direkt setzen",
                    value=int(current_value),
                    step=1,
                    key=f"{player}-target-value",
                )
                e1, e2 = st.columns(2)
                if e1.button("Setzen", key=f"{player}-set-exact", use_container_width=True):
                    if _run_db_action(
                        action_key=f"{player}:set",
                        callback=lambda p=player, value=target_value: set_counter_value(engine, p, int(value)),
                    ):
                        st.rerun()

                undo_label = "Undo bestaetigen" if _is_action_armed(undo_action_key) else "Undo"
                if e2.button(undo_label, key=f"{player}-undo", use_container_width=True):
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

    st.divider()
    st.subheader("Linienplots")

    left, right = st.columns([2, 1])
    with left:
        selected_window = st.selectbox("Zeitraum", options=list(TIME_WINDOWS.keys()), key="selected_window")
    with right:
        if st.button("Aktualisieren", use_container_width=True):
            st.rerun()

    hours = TIME_WINDOWS[selected_window]
    try:
        event_history = get_event_history(engine, hours=hours)
    except Exception as exc:
        _show_db_runtime_error(exc)

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
