from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types


def _extract_json(text: str) -> dict[str, Any]:
  """Best-effort extraction of a JSON object from model output."""
  text = text.strip()
  # Common case: the model returns only JSON.
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    pass

  # Fallback: grab content between the first "{" and the last "}".
  start = text.find("{")
  end = text.rfind("}")
  if start != -1 and end != -1 and end > start:
    candidate = text[start : end + 1]
    return json.loads(candidate)

  # Last-resort fallback: regex for a JSON-ish object.
  match = re.search(r"\{[\s\S]*?\}", text)
  if not match:
    raise
  return json.loads(match.group(0))


async def _run_model_text(
  *,
  model_name: str,
  app_name: str,
  user_id: str,
  session_id: str,
  instruction: str,
  user_message: str,
) -> str:
  agent = LlmAgent(
    name="trainer",
    description="Personal training assistant",
    model=model_name,
    instruction=instruction,
    include_contents="none",
  )

  runner = Runner(
    app_name=app_name,
    agent=agent,
    session_service=InMemorySessionService(),
    auto_create_session=True,
  )

  new_message = types.UserContent(
    parts=[types.Part(text=user_message)],
  )

  last_text = ""
  try:
    async for event in runner.run_async(
      user_id=user_id,
      session_id=session_id,
      new_message=new_message,
    ):
      if event.author != agent.name:
        continue
      if not event.is_final_response():
        continue
      if not event.content or not event.content.parts:
        continue
      parts_text = [
        p.text
        for p in event.content.parts
        if getattr(p, "text", None) and not getattr(p, "thought", False)
      ]
      if parts_text:
        last_text = "".join(parts_text).strip()
  finally:
    # Runner has async cleanup; safe to call after the generator finishes.
    await runner.close()

  return last_text


async def generate_json_from_model(
  *,
  model_name: str,
  app_name: str,
  user_id: str,
  session_id: str,
  instruction: str,
  user_message: str,
  expected_keys: list[str],
) -> dict[str, Any]:
  """Calls Gemini and expects a single JSON object response."""
  # We ask for JSON only. This is important so the parser can work.
  json_only_instruction = (
    instruction.strip()
    + "\n\nReturn ONLY valid JSON. No markdown, no backticks, no extra text."
  )

  full_user_message = (
    user_message.strip()
    + "\n\nJSON schema (keys you must include): "
    + ", ".join(expected_keys)
  )

  raw_text = await _run_model_text(
    model_name=model_name,
    app_name=app_name,
    user_id=user_id,
    session_id=session_id,
    instruction=json_only_instruction,
    user_message=full_user_message,
  )

  try:
    data = _extract_json(raw_text)
  except Exception:
    # One retry with a stricter nudge.
    retry_user_message = full_user_message + (
      "\n\nIMPORTANT: Your previous response was not valid JSON. "
      "Respond again with ONLY the JSON object."
    )
    raw_text = await _run_model_text(
      model_name=model_name,
      app_name=app_name,
      user_id=user_id,
      session_id=session_id,
      instruction=json_only_instruction,
      user_message=retry_user_message,
    )
    data = _extract_json(raw_text)

  # Soft validation: check keys exist.
  missing = [k for k in expected_keys if k not in data]
  if missing:
    raise ValueError(f"Model JSON missing keys: {missing}. Raw: {raw_text}")
  return data


def generate_json_from_model_sync(**kwargs) -> dict[str, Any]:
  """Synchronous wrapper for the async generate_json_from_model()."""
  return asyncio.run(generate_json_from_model(**kwargs))

