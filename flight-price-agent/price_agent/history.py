from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import Quote, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    run_date    TEXT NOT NULL,
    route       TEXT NOT NULL,
    departure   TEXT NOT NULL,
    return_date TEXT,
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    airline     TEXT,
    stops       INTEGER,
    PRIMARY KEY (run_date, route, departure)
);
"""


class History:
    def __init__(self, path: str | Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def save(self, run_date: date, quotes: list[Quote]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_date.isoformat(),
                    q.route.key,
                    q.departure.isoformat(),
                    q.return_date.isoformat() if q.return_date else None,
                    q.price,
                    q.currency,
                    q.airline,
                    q.stops,
                )
                for q in quotes
            ],
        )
        self.conn.commit()

    def previous(self, route: Route, before: date, currency: str) -> dict[date, float]:
        """Precios por fecha de salida del último run anterior a `before`."""
        row = self.conn.execute(
            "SELECT MAX(run_date) FROM prices WHERE route = ? AND run_date < ? AND currency = ?",
            (route.key, before.isoformat(), currency),
        ).fetchone()
        if not row or not row[0]:
            return {}
        rows = self.conn.execute(
            "SELECT departure, price FROM prices WHERE route = ? AND run_date = ? AND currency = ?",
            (route.key, row[0], currency),
        ).fetchall()
        return {date.fromisoformat(d): p for d, p in rows}

    def historical_min(self, route: Route, currency: str) -> float | None:
        row = self.conn.execute(
            "SELECT MIN(price) FROM prices WHERE route = ? AND currency = ?",
            (route.key, currency),
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()
