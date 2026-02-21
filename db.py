import os
from typing import Dict, Iterable, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class DatabaseConfigError(RuntimeError):
    """Raised when required database configuration is missing."""


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise DatabaseConfigError(
            "DATABASE_URL fehlt. Bitte in Streamlit Secrets oder als Umgebungsvariable setzen."
        )
    return database_url


def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, future=True)


def init_db(engine: Engine, players: Iterable[str]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS players (
                    player_name TEXT PRIMARY KEY
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS counter_events (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    player_name TEXT NOT NULL REFERENCES players(player_name),
                    delta INTEGER NOT NULL,
                    counter_value INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_counter_events_player_time
                ON counter_events (player_name, created_at);
                """
            )
        )

        for player in players:
            conn.execute(
                text(
                    """
                    INSERT INTO players (player_name)
                    VALUES (:player_name)
                    ON CONFLICT (player_name) DO NOTHING;
                    """
                ),
                {"player_name": player},
            )


def get_latest_counters(engine: Engine, players: Iterable[str]) -> Dict[str, int]:
    player_values = list(players)
    result: Dict[str, int] = {player: 0 for player in player_values}

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    p.player_name,
                    COALESCE(last_event.counter_value, 0) AS counter_value
                FROM players p
                LEFT JOIN LATERAL (
                    SELECT ce.counter_value
                    FROM counter_events ce
                    WHERE ce.player_name = p.player_name
                    ORDER BY ce.created_at DESC, ce.id DESC
                    LIMIT 1
                ) AS last_event ON TRUE
                WHERE p.player_name = ANY(:players);
                """
            ),
            {"players": player_values},
        )
        for row in rows:
            result[row.player_name] = int(row.counter_value)

    return result


def add_counter_event(engine: Engine, player_name: str, delta: int) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                WITH current_value AS (
                    SELECT COALESCE((
                        SELECT ce.counter_value
                        FROM counter_events ce
                        WHERE ce.player_name = :player_name
                        ORDER BY ce.created_at DESC, ce.id DESC
                        LIMIT 1
                    ), 0) AS value
                )
                INSERT INTO counter_events (player_name, delta, counter_value)
                SELECT :player_name, :delta, current_value.value + :delta
                FROM current_value
                RETURNING counter_value;
                """
            ),
            {"player_name": player_name, "delta": delta},
        ).one()
    return int(row.counter_value)


def reset_counter(engine: Engine, player_name: str) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                WITH current_value AS (
                    SELECT COALESCE((
                        SELECT ce.counter_value
                        FROM counter_events ce
                        WHERE ce.player_name = :player_name
                        ORDER BY ce.created_at DESC, ce.id DESC
                        LIMIT 1
                    ), 0) AS value
                )
                INSERT INTO counter_events (player_name, delta, counter_value)
                SELECT :player_name, -current_value.value, 0
                FROM current_value
                RETURNING counter_value;
                """
            ),
            {"player_name": player_name},
        ).one()
    return int(row.counter_value)


def set_counter_value(engine: Engine, player_name: str, target_value: int) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                WITH current_value AS (
                    SELECT COALESCE((
                        SELECT ce.counter_value
                        FROM counter_events ce
                        WHERE ce.player_name = :player_name
                        ORDER BY ce.created_at DESC, ce.id DESC
                        LIMIT 1
                    ), 0) AS value
                )
                INSERT INTO counter_events (player_name, delta, counter_value)
                SELECT
                    :player_name,
                    :target_value - current_value.value,
                    :target_value
                FROM current_value
                RETURNING counter_value;
                """
            ),
            {"player_name": player_name, "target_value": target_value},
        ).one()
    return int(row.counter_value)


def undo_last_event(engine: Engine, player_name: str) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM counter_events
                WHERE id = (
                    SELECT id
                    FROM counter_events
                    WHERE player_name = :player_name
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                );
                """
            ),
            {"player_name": player_name},
        )

    latest = get_latest_counters(engine, [player_name])
    return int(latest.get(player_name, 0))


def get_event_history(engine: Engine, hours: Optional[int] = None) -> pd.DataFrame:
    query = """
        SELECT player_name, delta, counter_value, created_at
        FROM counter_events
    """
    params = {}
    if hours is not None:
        query += " WHERE created_at >= NOW() - (:hours || ' hours')::interval"
        params["hours"] = hours

    query += " ORDER BY created_at ASC, id ASC"
    return pd.read_sql_query(text(query), engine, params=params)
