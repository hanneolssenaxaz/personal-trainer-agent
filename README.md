# Personal Trainer Agent (Local PoC)

This is a beginner-friendly local proof-of-concept that:
- uses **Google ADK** to call **Gemini**
- keeps **memory and context in SQLite**
- runs in a simple **CLI loop** (intake → weekly plan → workout logs)

## 1) Set your Gemini API key

Create a `.env` file in the repo root with your Gemini key:

```bash
GOOGLE_API_KEY="YOUR_KEY_HERE"
```

## 2) Run the CLI

From the repo root:

```bash
python -m pt_agent.cli
```

It will:
1. Ask you intake questions
2. Generate your first weekly plan
3. Then let you log workouts
4. After each workout log, Gemini updates:
   - your weekly plan
   - a short memory summary (saved in SQLite)

## Notes / Next steps

- The model is asked to return **JSON only** for easier parsing.
- For a fuller “agent flow”, the next upgrade is to add more structured steps (and stricter JSON schemas), plus unit tests for the DB + parsing.

## Web UI (local)

1. Start the web server:
   ```bash
   python -m pt_agent.web --port 8000
   ```
2. Open your browser at:
   - `http://127.0.0.1:8000`

The UI will:
- ask intake questions once (saved in SQLite)
- show your weekly plan
- provide a chat box (general coaching questions)
- provide a “Log workout” form (updates your plan + memory summary)

