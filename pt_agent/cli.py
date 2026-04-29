from __future__ import annotations

import os
import sqlite3
from argparse import ArgumentParser
from pathlib import Path

from dotenv import load_dotenv

from .db import (
  add_workout_log,
  get_training_summary,
  get_user_profile,
  get_weekly_plan,
  get_conn,
  init_db,
  has_user_profile,
  list_user_ids_with_profiles,
  set_training_summary,
  set_user_profile,
  set_weekly_plan,
  log_chat_turn,
)
from .flow import (
  ask_intake_questions,
  generate_weekly_plan_and_summary,
  generate_workout_update,
  get_default_workout_date,
)


MENU = """
Choose an option:
1) View weekly plan
2) Log workout (updates plan + memory summary)
3) View training memory summary
4) Exit
"""


def _require_google_api_key() -> None:
  if not os.environ.get("GOOGLE_API_KEY"):
    raise RuntimeError(
      "Missing GOOGLE_API_KEY environment variable.\n"
      "Set it to your Gemini API key, then run again.\n\n"
      "Example:\n"
      "  export GOOGLE_API_KEY='YOUR_KEY'\n"
    )


def main():
  # Loads variables from a local `.env` file into `os.environ` (if present).
  # This makes `GOOGLE_API_KEY` available without manual `export` calls.
  load_dotenv()

  parser = ArgumentParser(description="Personal trainer agent (local PoC)")
  parser.add_argument("--db", default="data/training_memory.sqlite")
  parser.add_argument("--user-id", default="1")
  parser.add_argument("--model", default="gemini-2.5-flash")
  parser.add_argument("--app-name", default="personal_trainer_agent_poc")
  parser.add_argument("--session-id", default="pt_session_1")
  args = parser.parse_args()

  _require_google_api_key()

  # Resolve DB path to an absolute path so restarts don't accidentally create
  # a second database due to different working directories.
  repo_root = Path(__file__).resolve().parents[1]
  raw_db_path = os.path.expanduser(args.db)
  if os.path.isabs(raw_db_path):
    db_path = raw_db_path
  else:
    db_path = str((repo_root / raw_db_path).resolve())

  print(f"Using SQLite DB: {db_path}")

  user_id_int = int(args.user_id)
  user_id_str = str(user_id_int)
  model_name = args.model
  app_name = args.app_name
  session_id = args.session_id

  init_db(db_path)

  with get_conn(db_path) as conn:
    if not has_user_profile(conn, user_id_int):
      # If the user_id doesn't match, but there is a single stored profile in
      # the DB, use it automatically (useful during PoC iterations).
      existing_ids = list_user_ids_with_profiles(conn)
      if len(existing_ids) == 1:
        user_id_int = existing_ids[0]
        user_id_str = str(user_id_int)
        print(f"Loaded existing profile for user_id={user_id_int}. Skipping intake.")

      if not has_user_profile(conn, user_id_int):
        profile = ask_intake_questions()
        set_user_profile(conn, user_id_int, profile)

        print("\nGenerating your first weekly plan with Gemini (this may take a moment)...")
        result = generate_weekly_plan_and_summary(
          profile=profile,
          current_summary="",
          model_name=model_name,
          app_name=app_name,
          user_id=user_id_str,
          session_id=session_id,
        )
        set_weekly_plan(conn, user_id_int, result["weekly_plan"])
        set_training_summary(conn, user_id_int, result["training_summary"])

        log_chat_turn(conn, user_id_int, "user", f"Intake answers: {profile}")
        log_chat_turn(
          conn,
          user_id_int,
          "trainer",
          "Generated weekly plan:\n"
          f"{result['weekly_plan']}\n\nTraining memory summary:\n{result['training_summary']}",
        )

        print("\n=== Weekly plan (generated) ===")
        print(result["weekly_plan"])
        print("\n=== Training summary (memory) ===")
        print(result["training_summary"])

    while True:
      print(MENU)
      choice = input("Enter choice number: ").strip()

      if choice == "1":
        plan = get_weekly_plan(conn, user_id_int)
        if not plan:
          print("No plan found yet. Log a workout or restart intake.")
        else:
          print("\n=== Weekly plan ===")
          print(plan)

      elif choice == "2":
        profile = get_user_profile(conn, user_id_int)
        if not profile:
          print("Missing profile. Restart intake.")
          continue

        plan = get_weekly_plan(conn, user_id_int)
        summary = get_training_summary(conn, user_id_int)

        workout_date = input(
          f"Workout date (YYYY-MM-DD) [default {get_default_workout_date()}]: "
        ).strip() or get_default_workout_date()
        log_text = input(
          "Describe what you did (exercises + sets/reps + how hard it felt): "
        ).strip()

        log_chat_turn(
          conn,
          user_id_int,
          "user",
          f"Workout log ({workout_date}):\n{log_text}",
        )

        add_workout_log(conn, user_id_int, workout_date, log_text)

        print("\nUpdating plan + memory summary with Gemini (may take a moment)...")
        result = generate_workout_update(
          profile=profile,
          weekly_plan=plan,
          current_summary=summary,
          workout_date=workout_date,
          workout_log_text=log_text,
          model_name=model_name,
          app_name=app_name,
          user_id=user_id_str,
          session_id=session_id,
        )

        set_weekly_plan(conn, user_id_int, result["weekly_plan"])
        set_training_summary(conn, user_id_int, result["training_summary"])

        log_chat_turn(
          conn,
          user_id_int,
          "trainer",
          f"{result['assistant_reply']}\n\nUpdated weekly plan:\n{result['weekly_plan']}",
        )

        print("\n=== Coach reply ===")
        print(result["assistant_reply"])

      elif choice == "3":
        summary = get_training_summary(conn, user_id_int)
        if not summary:
          print("No summary found yet.")
        else:
          print("\n=== Training memory summary ===")
          print(summary)

      elif choice == "4":
        print("Goodbye.")
        break
      else:
        print("Unknown choice. Please enter 1, 2, 3, or 4.")


if __name__ == "__main__":
  main()

