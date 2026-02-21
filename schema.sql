CREATE TABLE IF NOT EXISTS players (
    player_name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS counter_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_name TEXT NOT NULL REFERENCES players(player_name),
    delta INTEGER NOT NULL,
    counter_value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_counter_events_player_time
ON counter_events (player_name, created_at);

INSERT INTO players (player_name) VALUES
('Niklas'),
('Kai'),
('Damian'),
('Jan'),
('Noemi'),
('Lotti'),
('Bengt'),
('Eddy')
ON CONFLICT (player_name) DO NOTHING;
