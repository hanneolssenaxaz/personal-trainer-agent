from __future__ import annotations

import json
import re
from datetime import date as date_type
from typing import Any

from .db import (
  add_workout_log,
  get_training_summary,
  get_user_profile,
  get_weekly_plan,
  set_training_summary,
  set_user_profile,
  set_weekly_plan,
)
from .gemini import generate_json_from_model_sync


def sanitize_weekly_plan_text(plan_text: str) -> str:
  """Removes stale progress/log lines from weekly plan text.

  Weekly plan should describe structure for the week, not mutable "already
  completed" history. Current-week progress is shown from DB elsewhere.
  """
  if not plan_text:
    return ""

  noisy_patterns = [
    # Only remove explicit progress-tracking lines.
    r"\bthis\s+week\b.*\b(completed|done|finished|logged)\b",
    r"\b(completed|done|finished|logged)\b.*\bthis\s+week\b",
    r"\bsessions?\s+(completed|done|so far)\b",
    r"\bworkout\s+log\b",
  ]
  compiled = [re.compile(p, re.IGNORECASE) for p in noisy_patterns]

  cleaned_lines: list[str] = []
  for line in plan_text.splitlines():
    if any(p.search(line) for p in compiled):
      continue
    cleaned_lines.append(line.rstrip())

  # Remove long runs of blank lines.
  result = "\n".join(cleaned_lines)
  result = re.sub(r"\n{3,}", "\n\n", result).strip()

  # Safety: never return blank if original had content.
  original = plan_text.strip()
  if original and not result:
    return original
  return result


def prompt_integration_settings() -> dict[str, str]:
  """Beginner-friendly note: where to set your Gemini API key."""
  return {}


def ask_intake_questions() -> dict[str, Any]:
  """Collects a minimal trainer intake from the user (no model call)."""
  print("\nIntake (tell the agent about you):")
  goals = input("1) Main goal (e.g., strength, fat loss, general fitness): ").strip()
  days_per_week_raw = input("2) Days per week you can train (e.g., 3-5): ").strip()
  experience_level = input(
    "3) Your experience level (beginner / intermediate / advanced): "
  ).strip()
  equipment = input(
    "4) Equipment you have (e.g., dumbbells, barbell, machines, none): "
  ).strip()
  injuries = input(
    "5) Injuries/limitations to consider (or 'none'): "
  ).strip()
  schedule_constraints = input(
    "6) Any schedule constraints (e.g., mornings only, max 45 min): "
  ).strip()

  return {
    "goals": goals,
    "days_per_week": days_per_week_raw,
    "experience_level": experience_level,
    "equipment": equipment,
    "injuries": injuries,
    "schedule_constraints": schedule_constraints,
  }


def _format_profile(profile: dict[str, Any]) -> str:
  return json.dumps(profile, indent=2, ensure_ascii=True)


def generate_weekly_plan_and_summary(
  *,
  profile: dict[str, Any],
  current_summary: str,
  model_name: str,
  app_name: str,
  user_id: str,
  session_id: str,
) -> dict[str, str]:
  instruction = """
You are a personal trainer coaching a single user.

Create a safe, practical weekly training plan based on:
- The user's profile
- Their training summary so far (may be empty on first run)

Because there is no exercise library in this PoC, use commonly known movements
and include simple technique notes and alternatives when appropriate.

Output requirements:
- weekly_plan: a clear 7-day plan with warm-up, workout blocks per day,
  sets/reps, rest, and a simple progression idea.
- weekly_plan must NOT include progress tracking text like "you completed X"
  or references to specific logged workouts from this week.
- training_summary: a short memory summary (5-12 bullets) that captures goals,
  constraints, what to focus on, and any safety/adjustments.

Formatting requirements for weekly_plan (important):
- Use this exact high-level structure:
  1) "WEEK OVERVIEW"
  2) "DAY 1 - ...", "DAY 2 - ...", ... up to "DAY 7 - ..."
- Under each DAY section, include these labels when relevant:
  - Warm-up:
  - Main work:
  - Optional cardio:
  - Notes:
- Keep lines short and scannable (bullets preferred with "-" prefix).
"""

  user_message = f"""
USER PROFILE (JSON):
{_format_profile(profile)}

CURRENT TRAINING SUMMARY:
{current_summary or "(empty)"}
"""

  result = generate_json_from_model_sync(
    model_name=model_name,
    app_name=app_name,
    user_id=user_id,
    session_id=session_id,
    instruction=instruction,
    user_message=user_message,
    expected_keys=["weekly_plan", "training_summary"],
  )
  result["weekly_plan"] = sanitize_weekly_plan_text(str(result["weekly_plan"]))
  return result


def generate_workout_update(
  *,
  profile: dict[str, Any],
  weekly_plan: str,
  current_summary: str,
  workouts_this_week: list[dict[str, Any]],
  workout_date: str,
  workout_log_text: str,
  model_name: str,
  app_name: str,
  user_id: str,
  session_id: str,
) -> dict[str, str]:
  instruction = """
You are a personal trainer coaching a single user.

The user is logging what they did. Update their plan and coach them for next time.

Rules:
- Be supportive and clear.
- Adjust the plan based on what they actually did (and how hard it was).
- Keep workouts safe: respect injuries/limitations.
- If you don't have enough info, make reasonable assumptions and say what you assumed.
- Use ONLY the provided "WORKOUTS COMPLETED THIS WEEK" list for week progress.
- Never claim a higher number of completed sessions than the list shows.

Output requirements (JSON only):
- assistant_reply: what to tell the user now (next steps, tips, and the reason for changes)
- weekly_plan: updated weekly plan text
- weekly_plan must NOT include "completed this week" counters or old workout log details.
- training_summary: short updated memory summary (5-12 bullets)

Formatting requirements for weekly_plan (important):
- Keep this structure:
  1) "WEEK OVERVIEW"
  2) "DAY 1 - ...", "DAY 2 - ...", ... up to "DAY 7 - ..."
- Use short bullets under each day and include:
  - Warm-up:
  - Main work:
  - Optional cardio:
  - Notes:
"""

  user_message = f"""
USER PROFILE (JSON):
{_format_profile(profile)}

CURRENT TRAINING SUMMARY:
{current_summary or "(empty)"}

CURRENT WEEKLY PLAN:
{weekly_plan or "(empty)"}

WORKOUTS COMPLETED THIS WEEK (JSON):
{json.dumps(workouts_this_week, ensure_ascii=True, indent=2)}

NEW WORKOUT LOG:
- Date: {workout_date}
- Log: {workout_log_text}
"""

  result = generate_json_from_model_sync(
    model_name=model_name,
    app_name=app_name,
    user_id=user_id,
    session_id=session_id,
    instruction=instruction,
    user_message=user_message,
    expected_keys=["assistant_reply", "weekly_plan", "training_summary"],
  )
  result["weekly_plan"] = sanitize_weekly_plan_text(str(result["weekly_plan"]))
  return result


def generate_coach_chat_response(
  *,
  profile: dict[str, Any],
  weekly_plan: str,
  current_summary: str,
  workouts_this_week: list[dict[str, Any]],
  user_message: str,
  model_name: str,
  app_name: str,
  user_id: str,
  session_id: str,
) -> dict[str, str]:
  """Handles general chat questions (not workout logs) via Gemini."""
  instruction = """
You are a personal trainer coaching a single user.

The user is asking a general coaching question right now.

You MUST use:
- The user profile
- The weekly plan (current)
- The training summary (memory so far)
- Workouts completed this week (Monday to Sunday)

Rules:
- Be supportive, clear, and practical.
- Do NOT invent new workouts the user did. If info is missing, ask a short question.
- Safety first: respect injuries/limitations in the user profile.
- Use ONLY the provided "WORKOUTS COMPLETED THIS WEEK" list for this-week progress.
- Never claim a higher number of completed sessions than the list shows.

Output requirements (JSON only):
- assistant_reply: your response to the user
- weekly_plan: return the weekly plan. If you do not change it, return it unchanged.
- weekly_plan must NOT include stale progress counts or old workout log details.
- training_summary: updated summary (5-12 bullets). If nothing changes, return the current summary.

Formatting requirements for weekly_plan:
- Preserve a clear structure with "WEEK OVERVIEW" + "DAY 1..DAY 7" sections.
- Keep bullets short and easy to scan.
"""

  user_message_block = f"{user_message.strip()}"

  user_prompt = f"""
USER PROFILE (JSON):
{_format_profile(profile)}

CURRENT TRAINING SUMMARY:
{current_summary or "(empty)"}

CURRENT WEEKLY PLAN:
{weekly_plan or "(empty)"}

WORKOUTS COMPLETED THIS WEEK (JSON):
{json.dumps(workouts_this_week, ensure_ascii=True, indent=2)}

USER QUESTION:
{user_message_block}
"""

  result = generate_json_from_model_sync(
    model_name=model_name,
    app_name=app_name,
    user_id=user_id,
    session_id=session_id,
    instruction=instruction,
    user_message=user_prompt,
    expected_keys=["assistant_reply", "weekly_plan", "training_summary"],
  )
  result["weekly_plan"] = sanitize_weekly_plan_text(str(result["weekly_plan"]))
  return result


def get_default_workout_date() -> str:
  return date_type.today().isoformat()

