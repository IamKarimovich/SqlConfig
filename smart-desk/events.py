"""Hadisələrin SQLite jurnalı və gündəlik hesabat."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,          -- ISO yerli vaxt
    kind   TEXT NOT NULL,          -- arrived | left | locked | stranger | launched | start | stop
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class EventLog:
    def __init__(self, path: Path = DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def log(self, kind: str, detail: str = "") -> None:
        ts = datetime.now().isoformat(timespec="seconds")
        self.conn.execute("INSERT INTO events(ts, kind, detail) VALUES (?, ?, ?)", (ts, kind, detail))
        self.conn.commit()
        print(f"[{ts}] {kind} {detail}".rstrip())

    def report(self, day: datetime | None = None) -> str:
        day = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        end = day + timedelta(days=1)
        rows = self.conn.execute(
            "SELECT ts, kind FROM events WHERE ts >= ? AND ts < ? ORDER BY ts",
            (day.isoformat(), end.isoformat())).fetchall()

        total = timedelta()
        sessions, strangers, sat_at = 0, 0, None
        longest = timedelta()
        for ts, kind in rows:
            t = datetime.fromisoformat(ts)
            if kind == "arrived" and sat_at is None:
                sat_at = t
            elif kind in ("left", "stop") and sat_at is not None:
                dur = t - sat_at
                total += dur
                longest = max(longest, dur)
                sessions += 1
                sat_at = None
            elif kind == "stranger":
                strangers += 1
        if sat_at is not None:  # hələ də masadasan
            dur = min(datetime.now(), end) - sat_at
            total += dur
            longest = max(longest, dur)
            sessions += 1

        def fmt(td: timedelta) -> str:
            m = int(td.total_seconds() // 60)
            return f"{m // 60} saat {m % 60} dəq"

        return (f"📊 {day:%d.%m.%Y} hesabatı\n"
                f"  Masada ümumi vaxt : {fmt(total)}\n"
                f"  Oturum sayı       : {sessions}\n"
                f"  Ən uzun oturum    : {fmt(longest)}\n"
                f"  Yad şəxs xəbərdarlığı: {strangers}")
