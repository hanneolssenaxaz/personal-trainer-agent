from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _to_text(value: Any) -> str:
  """Converts arbitrary values to a SQLite-storable text string.

  Gemini outputs may sometimes be dicts/lists depending on formatting.
  SQLite's `sqlite3` driver can only bind scalar types directly, so we
  serialize non-string values.
  """
  if value is None:
    return ""
  if isinstance(value, str):
    return value
  if isinstance(value, (bytes, bytearray)):
    return bytes(value).decode("utf-8", errors="replace")
  # For dict/list/etc store stable JSON representation.
  try:
    return json.dumps(value, ensure_ascii=True)
  except TypeError:
    return str(value)


@contextmanager
def get_conn(db_path: str):
  """Creates a SQLite connection and closes it when done."""
  os.makedirs(os.path.dirname(db_path), exist_ok=True)
  conn = sqlite3.connect(db_path)
  try:
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
  except Exception:
    # If something goes wrong during a run, don't keep partial writes.
    conn.rollback()
    raise
  else:
    conn.commit()
  finally:
    conn.close()


def init_db(db_path: str) -> None:
  """Creates tables for user profile, plan, summary, and workout logs."""
  with get_conn(db_path) as conn:
    conn.executescript(
      """
      CREATE TABLE IF NOT EXISTS user_profile (
        user_id INTEGER PRIMARY KEY,
        profile_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS training_summary (
        user_id INTEGER PRIMARY KEY,
        summary_text TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS weekly_plan (
        user_id INTEGER PRIMARY KEY,
        plan_text TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS workout_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        workout_date TEXT NOT NULL,
        log_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
          ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS chat_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
          ON DELETE CASCADE
      );
      """
    )
    conn.commit()


def has_user_profile(conn: sqlite3.Connection, user_id: int) -> bool:
  cur = conn.execute(
    "SELECT 1 FROM user_profile WHERE user_id = ? LIMIT 1", (user_id,)
  )
  return cur.fetchone() is not None


def list_user_ids_with_profiles(conn: sqlite3.Connection) -> list[int]:
  cur = conn.execute("SELECT user_id FROM user_profile ORDER BY user_id")
  return [int(row[0]) for row in cur.fetchall()]


def get_user_profile(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
  cur = conn.execute(
    "SELECT profile_json FROM user_profile WHERE user_id = ?",
    (user_id,),
  )
  row = cur.fetchone()
  if not row:
    return None
  return json.loads(row[0])


def set_user_profile(
  conn: sqlite3.Connection, user_id: int, profile: dict[str, Any]
) -> None:
  now = _utc_now_iso()
  profile_json = json.dumps(profile, ensure_ascii=True)
  if has_user_profile(conn, user_id):
    conn.execute(
      """
      UPDATE user_profile
      SET profile_json = ?, updated_at = ?
      WHERE user_id = ?
      """,
      (profile_json, now, user_id),
    )
  else:
    conn.execute(
      """
      INSERT INTO user_profile(user_id, profile_json, created_at, updated_at)
      VALUES (?, ?, ?, ?)
      """,
      (user_id, profile_json, now, now),
    )
  conn.commit()


def get_training_summary(
  conn: sqlite3.Connection, user_id: int
) -> str:
  cur = conn.execute(
    "SELECT summary_text FROM training_summary WHERE user_id = ?",
    (user_id,),
  )
  row = cur.fetchone()
  return row[0] if row else ""


def set_training_summary(
  conn: sqlite3.Connection, user_id: int, summary_text: Any
) -> None:
  now = _utc_now_iso()
  summary_text = _to_text(summary_text)
  if cur := conn.execute(
    "SELECT 1 FROM training_summary WHERE user_id = ? LIMIT 1",
    (user_id,),
  ):
    if cur.fetchone():
      conn.execute(
        """
        UPDATE training_summary
        SET summary_text = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (summary_text, now, user_id),
      )
      return

  conn.execute(
    """
    INSERT INTO training_summary(user_id, summary_text, updated_at)
    VALUES (?, ?, ?)
    """,
    (user_id, summary_text, now),
  )
  conn.commit()


def get_weekly_plan(
  conn: sqlite3.Connection, user_id: int
) -> str:
  cur = conn.execute(
    "SELECT plan_text FROM weekly_plan WHERE user_id = ?",
    (user_id,),
  )
  row = cur.fetchone()
  return row[0] if row else ""


def set_weekly_plan(
  conn: sqlite3.Connection, user_id: int, plan_text: Any
) -> None:
  now = _utc_now_iso()
  plan_text = _to_text(plan_text)
  if cur := conn.execute(
    "SELECT 1 FROM weekly_plan WHERE user_id = ? LIMIT 1",
    (user_id,),
  ):
    if cur.fetchone():
      conn.execute(
        """
        UPDATE weekly_plan
        SET plan_text = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (plan_text, now, user_id),
      )
      return

  conn.execute(
    """
    INSERT INTO weekly_plan(user_id, plan_text, updated_at)
    VALUES (?, ?, ?)
    """,
    (user_id, plan_text, now),
  )
  conn.commit()


def add_workout_log(
  conn: sqlite3.Connection,
  user_id: int,
  workout_date: str,
  log_text: Any,
) -> None:
  log_text = _to_text(log_text)
  conn.execute(
    """
    INSERT INTO workout_logs(user_id, workout_date, log_text, created_at)
    VALUES (?, ?, ?, ?)
    """,
    (user_id, workout_date, log_text, _utc_now_iso()),
  )
  conn.commit()


def log_chat_turn(
  conn: sqlite3.Connection,
  user_id: int,
  role: str,
  content: Any,
) -> None:
  content = _to_text(content)
  conn.execute(
    """
    INSERT INTO chat_log(user_id, role, content, created_at)
    VALUES (?, ?, ?, ?)
    """,
    (user_id, role, content, _utc_now_iso()),
  )
  conn.commit()


def get_recent_chat_history(
  conn: sqlite3.Connection, user_id: int, limit: int = 50
) -> list[dict[str, Any]]:
  """Returns recent chat turns for the UI."""
  limit = max(1, int(limit))
  rows = conn.execute(
    """
    SELECT role, content, created_at
    FROM chat_log
    WHERE user_id = ?
    ORDER BY created_at DESC, id DESC
    LIMIT ?
    """,
    (user_id, limit),
  ).fetchall()
  # Reverse to chronological order for display.
  rows.reverse()
  return [
    {"role": r[0], "content": r[1], "created_at": r[2]}
    for r in rows
  ]


def _current_week_bounds(today: date | None = None) -> tuple[str, str]:
  """Returns current week bounds (Monday..Sunday) as YYYY-MM-DD strings."""
  today = today or date.today()
  monday = today.fromordinal(today.toordinal() - today.weekday())
  sunday = monday.fromordinal(monday.toordinal() + 6)
  return monday.isoformat(), sunday.isoformat()


def get_current_week_bounds(today: date | None = None) -> tuple[str, str]:
  """Public helper for current week bounds (Monday..Sunday)."""
  return _current_week_bounds(today=today)


def get_workouts_for_current_week(
  conn: sqlite3.Connection,
  user_id: int,
  today: date | None = None,
) -> list[dict[str, Any]]:
  """Returns workouts for the current week (Monday to Sunday).

  Uses workout_date range filtering with actual current date by default.
  """
  week_start, week_end = _current_week_bounds(today=today)
  rows = conn.execute(
    """
    SELECT workout_date, log_text, created_at
    FROM workout_logs
    WHERE user_id = ?
      AND workout_date >= ?
      AND workout_date <= ?
    ORDER BY workout_date ASC, id ASC
    """,
    (user_id, week_start, week_end),
  ).fetchall()
  return [
    {
      "workout_date": r[0],
      "log_text": r[1],
      "created_at": r[2],
    }
    for r in rows
  ]

