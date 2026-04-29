from __future__ import annotations

import ast
import json
import os
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

from dotenv import load_dotenv

from .db import (
  add_workout_log,
  get_conn,
  get_current_week_bounds,
  get_recent_chat_history,
  get_training_summary,
  get_user_profile,
  get_weekly_plan,
  get_workouts_for_current_week,
  has_user_profile,
  init_db,
  log_chat_turn,
  set_training_summary,
  set_user_profile,
  set_weekly_plan,
)
from .flow import (
  generate_coach_chat_response,
  generate_weekly_plan_and_summary,
  generate_workout_update,
  sanitize_weekly_plan_text,
)


def _as_text(value: Any) -> str:
  """Normalize model output values into a text string."""
  if value is None:
    return ""
  if isinstance(value, str):
    return value
  if isinstance(value, list):
    # Lists are commonly used for bullet summaries.
    return "\n".join(str(item) for item in value)
  if isinstance(value, dict):
    return json.dumps(value, ensure_ascii=True)
  return str(value)


def _dict_plan_to_text(plan_obj: dict[str, Any]) -> str:
  """Render structured weekly-plan dict as readable multiline text."""
  lines: list[str] = []

  overview = plan_obj.get("WEEK OVERVIEW")
  if overview:
    lines.append("WEEK OVERVIEW")
    lines.append(str(overview))
    lines.append("")

  # Keep original key order where possible.
  for key, value in plan_obj.items():
    if str(key).strip().upper() == "WEEK OVERVIEW":
      continue

    title = str(key).strip()
    lines.append(title)

    if isinstance(value, dict):
      for sub_key, sub_value in value.items():
        lines.append(f"{sub_key}:")
        if isinstance(sub_value, list):
          for item in sub_value:
            item_text = str(item).strip()
            if item_text.startswith("-"):
              lines.append(item_text)
            else:
              lines.append(f"- {item_text}")
        else:
          lines.append(f"- {str(sub_value).strip()}")
    elif isinstance(value, list):
      for item in value:
        item_text = str(item).strip()
        if item_text.startswith("-"):
          lines.append(item_text)
        else:
          lines.append(f"- {item_text}")
    else:
      lines.append(str(value).strip())

    lines.append("")

  return "\n".join(lines).strip()


def _normalize_weekly_plan_text(plan_text: str) -> str:
  """Convert dict-like plan strings into readable plain text."""
  text = (plan_text or "").strip()
  if not text:
    return ""

  # Try JSON first.
  if text.startswith("{") and text.endswith("}"):
    try:
      obj = json.loads(text)
      if isinstance(obj, dict):
        return _dict_plan_to_text(obj)
    except Exception:
      pass

    # Then try Python-literal dict format from older runs.
    try:
      obj = ast.literal_eval(text)
      if isinstance(obj, dict):
        return _dict_plan_to_text(obj)
    except Exception:
      pass

  return text


def _resolve_db_path(db_arg: str) -> str:
  repo_root = Path(__file__).resolve().parents[1]
  raw_db_path = os.path.expanduser(db_arg)
  if os.path.isabs(raw_db_path):
    return raw_db_path
  return str((repo_root / raw_db_path).resolve())


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
  data = json.dumps(payload, ensure_ascii=False)
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json; charset=utf-8")
  handler.send_header("Content-Length", str(len(data.encode("utf-8"))))
  handler.end_headers()
  handler.wfile.write(data.encode("utf-8"))


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
  length = int(handler.headers.get("Content-Length", "0"))
  if length <= 0:
    return {}
  raw = handler.rfile.read(length).decode("utf-8")
  return json.loads(raw)


class Handler(BaseHTTPRequestHandler):
  # Set these on server start.
  db_path: str = ""
  model_name: str = "gemini-2.5-flash"
  app_name: str = "personal_trainer_agent_poc"
  session_id: str = "pt_session_1"
  web_root: Path = Path()

  def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
    # Cleaner logs for beginners.
    return

  def _get_user_id_from_query(self) -> int:
    parsed = urlparse(self.path)
    qs = parse_qs(parsed.query)
    user_id = qs.get("user_id", [None])[0]
    return int(user_id) if user_id else 1

  def do_GET(self) -> None:  # noqa: N802
    parsed = urlparse(self.path)
    path = parsed.path

    if path == "/":
      return self._serve_static_file("index.html")

    if path.startswith("/static/"):
      # Serve files from webui/static
      rel = path.removeprefix("/static/").lstrip("/")
      return self._serve_static_file(os.path.join("static", rel))

    if path == "/api/status":
      return self._handle_status()

    if path == "/api/weekly-plan":
      return self._handle_weekly_plan()

    if path == "/api/training-summary":
      return self._handle_training_summary()

    if path == "/api/chat-history":
      return self._handle_chat_history()

    self.send_error(404, "Not found")

  def do_POST(self) -> None:  # noqa: N802
    parsed = urlparse(self.path)
    path = parsed.path

    if path == "/api/intake":
      return self._handle_intake()
    if path == "/api/chat":
      return self._handle_chat()
    if path == "/api/workout-log":
      return self._handle_workout_log()

    self.send_error(404, "Not found")

  def _serve_static_file(self, rel_path: str) -> None:
    # Security: keep files inside web_root.
    target = (self.web_root / rel_path).resolve()
    if self.web_root not in target.parents and target != self.web_root:
      self.send_error(403, "Forbidden")
      return

    if not target.exists() or target.is_dir():
      self.send_error(404, "Not found")
      return

    content = target.read_bytes()
    # Minimal content-type handling.
    if target.suffix == ".html":
      ctype = "text/html; charset=utf-8"
    elif target.suffix == ".css":
      ctype = "text/css; charset=utf-8"
    elif target.suffix == ".js":
      ctype = "application/javascript; charset=utf-8"
    else:
      ctype = "application/octet-stream"

    self.send_response(200)
    self.send_header("Content-Type", ctype)
    self.send_header("Content-Length", str(len(content)))
    self.end_headers()
    self.wfile.write(content)

  def _handle_status(self) -> None:
    user_id = self._get_user_id_from_query()
    with get_conn(self.db_path) as conn:
      has_profile = has_user_profile(conn, user_id)
      weekly_plan = get_weekly_plan(conn, user_id) if has_profile else ""
      if has_profile and weekly_plan:
        normalized_plan = _normalize_weekly_plan_text(weekly_plan)
        if normalized_plan != weekly_plan:
          set_weekly_plan(conn, user_id, normalized_plan)
          weekly_plan = normalized_plan
      if has_profile and weekly_plan:
        cleaned_plan = sanitize_weekly_plan_text(weekly_plan)
        if cleaned_plan != weekly_plan:
          # One-time auto-clean of stale plan wording from older runs.
          set_weekly_plan(conn, user_id, cleaned_plan)
          weekly_plan = cleaned_plan
      training_summary = (
        get_training_summary(conn, user_id) if has_profile else ""
      )

      # Recovery path: if plan is empty (e.g. from older sanitize behavior),
      # regenerate it once from profile + current summary.
      if has_profile and not weekly_plan.strip():
        profile = get_user_profile(conn, user_id) or {}
        if profile:
          regenerated = generate_weekly_plan_and_summary(
            profile=profile,
            current_summary=training_summary,
            model_name=self.model_name,
            app_name=self.app_name,
            user_id=str(user_id),
            session_id=self.session_id,
          )
          weekly_plan = _as_text(regenerated.get("weekly_plan", "")).strip()
          if weekly_plan:
            set_weekly_plan(conn, user_id, weekly_plan)
          regenerated_summary = _as_text(
            regenerated.get("training_summary", "")
          ).strip()
          if regenerated_summary:
            set_training_summary(conn, user_id, regenerated_summary)
            training_summary = regenerated_summary

      # Always return workouts_this_week from DB, even if profile is missing,
      # so progress display remains accurate.
      workouts_this_week = get_workouts_for_current_week(conn, user_id)
      week_start, week_end = get_current_week_bounds()
      chat_history = (
        get_recent_chat_history(conn, user_id, limit=50)
        if has_profile
        else []
      )

    _send_json(
      self,
      200,
      {
        "user_id": user_id,
        "has_profile": has_profile,
        "weekly_plan": weekly_plan,
        "training_summary": training_summary,
        "workouts_this_week": workouts_this_week,
        "workouts_this_week_count": len(workouts_this_week),
        "week_start": week_start,
        "week_end": week_end,
        "chat_history": chat_history,
      },
    )

  def _handle_weekly_plan(self) -> None:
    user_id = self._get_user_id_from_query()
    with get_conn(self.db_path) as conn:
      plan = get_weekly_plan(conn, user_id)
    _send_json(self, 200, {"weekly_plan": plan})

  def _handle_training_summary(self) -> None:
    user_id = self._get_user_id_from_query()
    with get_conn(self.db_path) as conn:
      summary = get_training_summary(conn, user_id)
    _send_json(self, 200, {"training_summary": summary})

  def _handle_chat_history(self) -> None:
    user_id = self._get_user_id_from_query()
    qs = parse_qs(urlparse(self.path).query)
    limit = int(qs.get("limit", ["50"])[0])
    with get_conn(self.db_path) as conn:
      history = get_recent_chat_history(conn, user_id, limit=limit)
    _send_json(self, 200, {"chat_history": history})

  def _handle_intake(self) -> None:
    user_id = self._get_user_id_from_query()
    body = _read_json_body(self)
    # Store all provided fields as profile JSON.
    profile = {
      "goals": body.get("goals", ""),
      "days_per_week": body.get("days_per_week", ""),
      "experience_level": body.get("experience_level", ""),
      "equipment": body.get("equipment", ""),
      "injuries": body.get("injuries", ""),
      "schedule_constraints": body.get("schedule_constraints", ""),
    }

    with get_conn(self.db_path) as conn:
      set_user_profile(conn, user_id, profile)

      result = generate_weekly_plan_and_summary(
        profile=profile,
        current_summary="",
        model_name=self.model_name,
        app_name=self.app_name,
        user_id=str(user_id),
        session_id=self.session_id,
      )

      set_weekly_plan(conn, user_id, result["weekly_plan"])
      set_training_summary(conn, user_id, result["training_summary"])

      user_turn = f"Intake answers: {profile}"
      assistant_turn = (
        "Your intake is saved. Your weekly plan is ready.\n\n"
        "Start by logging your first workout when you're ready."
      )
      log_chat_turn(conn, user_id, "user", user_turn)
      log_chat_turn(conn, user_id, "trainer", assistant_turn)

    _send_json(
      self,
      200,
      {
        "assistant_reply": assistant_turn,
        "weekly_plan": result["weekly_plan"],
        "training_summary": result["training_summary"],
      },
    )

  def _require_profile_or_respond(self) -> tuple[int, dict[str, Any] | None]:
    user_id = self._get_user_id_from_query()
    with get_conn(self.db_path) as conn:
      if not has_user_profile(conn, user_id):
        return user_id, {
          "error": "No profile found yet. Please complete intake first."
        }
    return user_id, None

  def _handle_chat(self) -> None:
    user_id, error_payload = self._require_profile_or_respond()
    if error_payload:
      return _send_json(self, 400, error_payload)

    body = _read_json_body(self)
    user_message = str(body.get("message", "")).strip()
    if not user_message:
      return _send_json(self, 400, {"error": "Missing 'message'."})

    with get_conn(self.db_path) as conn:
      profile = get_user_profile(conn, user_id) or {}
      weekly_plan = get_weekly_plan(conn, user_id)
      current_summary = get_training_summary(conn, user_id)
      workouts_this_week = get_workouts_for_current_week(conn, user_id)

      result = generate_coach_chat_response(
        profile=profile,
        weekly_plan=weekly_plan,
        current_summary=current_summary,
        workouts_this_week=workouts_this_week,
        user_message=user_message,
        model_name=self.model_name,
        app_name=self.app_name,
        user_id=str(user_id),
        session_id=self.session_id,
      )

      set_weekly_plan(conn, user_id, result["weekly_plan"])
      set_training_summary(conn, user_id, result["training_summary"])

      log_chat_turn(conn, user_id, "user", user_message)
      log_chat_turn(conn, user_id, "trainer", result["assistant_reply"])

    _send_json(
      self,
      200,
      {
        "assistant_reply": result["assistant_reply"],
        "weekly_plan": result["weekly_plan"],
        "training_summary": result["training_summary"],
      },
    )

  def _handle_workout_log(self) -> None:
    user_id, error_payload = self._require_profile_or_respond()
    if error_payload:
      return _send_json(self, 400, error_payload)

    body = _read_json_body(self)
    workout_date = str(body.get("workout_date", "")).strip()
    log_text = str(body.get("log_text", "")).strip()
    if not workout_date or not log_text:
      return _send_json(
        self,
        400,
        {"error": "Missing 'workout_date' and/or 'log_text'."},
      )

    with get_conn(self.db_path) as conn:
      profile = get_user_profile(conn, user_id) or {}
      weekly_plan = get_weekly_plan(conn, user_id)
      current_summary = get_training_summary(conn, user_id)

      # Save raw workout log.
      add_workout_log(conn, user_id, workout_date, log_text)
      workouts_this_week = get_workouts_for_current_week(conn, user_id)

      user_message = f"Workout log ({workout_date}):\n{log_text}"
      log_chat_turn(conn, user_id, "user", user_message)

      result = generate_workout_update(
        profile=profile,
        weekly_plan=weekly_plan,
        current_summary=current_summary,
        workouts_this_week=workouts_this_week,
        workout_date=workout_date,
        workout_log_text=log_text,
        model_name=self.model_name,
        app_name=self.app_name,
        user_id=str(user_id),
        session_id=self.session_id,
      )

      set_weekly_plan(conn, user_id, result["weekly_plan"])
      set_training_summary(conn, user_id, result["training_summary"])
      log_chat_turn(conn, user_id, "trainer", result["assistant_reply"])

    _send_json(
      self,
      200,
      {
        "assistant_reply": result["assistant_reply"],
        "weekly_plan": result["weekly_plan"],
        "training_summary": result["training_summary"],
      },
    )


def main() -> None:
  load_dotenv()

  parser = ArgumentParser(description="Personal trainer agent web UI (local PoC)")
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--port", default=8000, type=int)
  parser.add_argument("--db", default="data/training_memory.sqlite")
  parser.add_argument("--user-id", default=1, type=int)
  parser.add_argument("--model", default="gemini-2.5-flash")
  parser.add_argument("--app-name", default="personal_trainer_agent_poc")
  parser.add_argument("--session-id", default="pt_session_1")
  args = parser.parse_args()

  db_path = _resolve_db_path(args.db)

  # Where our HTML/CSS/JS lives.
  web_root = Path(__file__).resolve().parents[1] / "webui"
  static_root = web_root / "static"
  if not web_root.exists():
    raise RuntimeError(
      f"Missing web UI directory: {web_root}. (Create it in the repo.)"
    )
  if not static_root.exists():
    # Allow running with only index.html, but keep it simple.
    static_root.mkdir(parents=True, exist_ok=True)

  init_db(db_path)

  Handler.db_path = db_path
  Handler.model_name = args.model
  Handler.app_name = args.app_name
  Handler.session_id = args.session_id
  Handler.web_root = web_root

  server = ThreadingHTTPServer((args.host, args.port), Handler)
  print(f"Web UI running at http://{args.host}:{args.port}")
  print(f"Using SQLite DB: {db_path}")
  server.serve_forever()


if __name__ == "__main__":
  main()

