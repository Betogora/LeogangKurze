# Player Counter Dashboard (Streamlit)

Eine Streamlit-App fuer 8 Spieler mit laufendem Counter und Linienplots.
Die Historie wird in einer externen PostgreSQL-Datenbank gespeichert, damit Daten auch nach Sleep/Inaktivitaet der Streamlit Community Cloud erhalten bleiben.

## Spieler

- Niklas
- Kai
- Damian
- Jan
- Noemi
- Lotti
- Bengt
- Eddy

## Features

- 8 Counter-Karten mit konfigurierbaren Schritten (z. B. `-5`, `-1`, `+1`, `+5`) und `Reset`
- Direkte Editierbarkeit pro Spieler ueber `Direkt setzen`
- Undo des letzten Events pro Spieler
- Persistente Event-Historie in PostgreSQL
- Linienplot-Dashboard mit Zeitfenster-Filter und Spieler-Filter
- CSV-Export fuer den aktuell gefilterten Zeitraum
- Anzeige der letzten Events

## Projektstruktur

- `app.py` - Streamlit UI und Interaktionen
- `db.py` - DB-Verbindung, Schema-Init, Inserts/Reads
- `schema.sql` - SQL-Schema und Initialdaten
- `requirements.txt` - Python-Abhaengigkeiten
- `.streamlit/config.toml` - Streamlit-Konfiguration

## Lokaler Start

1. Python-Umgebung erstellen und aktivieren
2. Abhaengigkeiten installieren:
   - `pip install -r requirements.txt`
3. `DATABASE_URL` setzen (PostgreSQL)
4. App starten:
   - `streamlit run app.py`

## Deployment auf Streamlit Community Cloud

1. Repo nach GitHub pushen
2. In Streamlit Community Cloud neues App-Deployment anlegen
3. Repository: `Betogora/LeogangKurze`, Branch: `main`, File: `app.py`
4. In den App-Secrets setzen:

```toml
DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DBNAME"
```

## Persistenz-Hinweis

Die Community Cloud kann Apps bei Inaktivitaet schlafen legen. Durch die externe DB bleiben alle Counter-Events dauerhaft gespeichert.
