const userId = new URLSearchParams(window.location.search).get("user_id") || "1";

const $ = (id) => document.getElementById(id);

async function apiGet(path) {
  const res = await fetch(path, { method: "GET" });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`GET ${path} failed: ${res.status} ${t}`);
  }
  return await res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`POST ${path} failed: ${res.status} ${t}`);
  }
  return await res.json();
}

function appendChatMessage(role, content) {
  const chatHistory = $("chatHistory");
  const wrap = document.createElement("div");
  wrap.className = "chatMsg";

  const roleEl = document.createElement("div");
  roleEl.className = "chatRole";
  roleEl.textContent = role === "user" ? "You" : "Coach";

  const contentEl = document.createElement("div");
  contentEl.className = `chatContent ${role}`;
  contentEl.textContent = formatChatMessageForDisplay(role, content);

  wrap.appendChild(roleEl);
  wrap.appendChild(contentEl);
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function prettifyIntakeAnswers(rawText) {
  // Handles stored text like:
  // Intake answers: {'goals': 'Strength', 'days_per_week': '4', ...}
  const pairs = [...rawText.matchAll(/'([^']+)'\s*:\s*'([^']*)'/g)];
  if (!pairs.length) return rawText;

  const keyLabels = {
    goals: "Goal",
    days_per_week: "Days/week",
    experience_level: "Experience",
    equipment: "Equipment",
    injuries: "Injuries/limits",
    schedule_constraints: "Schedule",
  };

  const lines = ["🧾 Intake profile"];
  for (const [, key, value] of pairs) {
    const label = keyLabels[key] || key.replaceAll("_", " ");
    lines.push(`- ${label}: ${value}`);
  }
  return lines.join("\n");
}

function prettifyJsonArrayText(rawText) {
  // Handles summaries stored as JSON arrays.
  const trimmed = (rawText || "").trim();
  if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) return rawText;
  try {
    const arr = JSON.parse(trimmed);
    if (!Array.isArray(arr)) return rawText;
    if (!arr.length) return rawText;
    return arr.map((item) => `• ${String(item)}`).join("\n");
  } catch {
    return rawText;
  }
}

function formatChatMessageForDisplay(role, content) {
  let text = String(content || "").trim();
  if (!text) return "";

  if (text.startsWith("Intake answers:")) {
    return prettifyIntakeAnswers(text);
  }

  text = prettifyJsonArrayText(text);

  // Make coach messages a bit easier to scan.
  if (role === "trainer") {
    text = text
      .replace(/\n{3,}/g, "\n\n")
      .replace(/(Next steps?:)/gi, "\n$1")
      .replace(/(Tips?:)/gi, "\n$1")
      .trim();
  }
  return text;
}

function beautifyWeeklyPlan(planText) {
  if (!planText) return "";
  const lines = planText.split("\n");
  const out = [];

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      out.push("");
      continue;
    }

    // Day headings: "Day 1", "Monday", etc.
    if (/^(day\s*\d+|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.test(line)) {
      out.push(`🏃‍♀️ ${raw}`);
      continue;
    }

    if (/^warm-?up\b/i.test(line)) {
      out.push(`🔥 ${raw}`);
      continue;
    }
    if (/^(workout|main block|strength|session)\b/i.test(line)) {
      out.push(`💪 ${raw}`);
      continue;
    }
    if (/^(conditioning|cardio|run)\b/i.test(line)) {
      out.push(`🏁 ${raw}`);
      continue;
    }
    if (/^(rest|recovery|mobility)\b/i.test(line)) {
      out.push(`🧘 ${raw}`);
      continue;
    }
    if (/^(progression|notes?|tips?)\b/i.test(line)) {
      out.push(`✨ ${raw}`);
      continue;
    }
    if (/^(sets?|reps?|tempo|rest)\b/i.test(line)) {
      out.push(`📌 ${raw}`);
      continue;
    }

    out.push(raw);
  }

  return out.join("\n");
}

function formatWeeklyOverviewText(text) {
  const lines = String(text || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  if (!lines.length) return "";

  const pretty = [];
  for (const line of lines) {
    if (/^week overview$/i.test(line)) {
      pretty.push("🗓️ WEEK OVERVIEW");
      continue;
    }
    if (/^goal/i.test(line)) {
      pretty.push(`🎯 ${line}`);
      continue;
    }
    if (/^focus/i.test(line)) {
      pretty.push(`✨ ${line}`);
      continue;
    }
    if (/^progression/i.test(line)) {
      pretty.push(`📈 ${line}`);
      continue;
    }
    if (/^notes?/i.test(line)) {
      pretty.push(`📝 ${line}`);
      continue;
    }
    if (line.startsWith("-") || line.startsWith("•")) {
      pretty.push(line);
    } else {
      pretty.push(`• ${line}`);
    }
  }
  return pretty.join("\n");
}

function splitPlanSections(planText) {
  const lines = planText.split("\n");
  const dayHeaderRe = /^(day\s*\d+\s*[-:]?.*|monday\b.*|tuesday\b.*|wednesday\b.*|thursday\b.*|friday\b.*|saturday\b.*|sunday\b.*)/i;
  const sections = [];
  let current = null;
  let overviewLines = [];

  for (const raw of lines) {
    const trimmed = raw.trim();
    // Support lines that start with emoji/icon prefixes, e.g. "🏃‍♀️ DAY 1 - ..."
    const normalized = trimmed.replace(/^[^A-Za-z0-9]+/, "");
    if (dayHeaderRe.test(normalized)) {
      if (current) sections.push(current);
      current = { title: normalized, lines: [] };
      continue;
    }
    if (current) {
      current.lines.push(raw);
    } else {
      overviewLines.push(raw);
    }
  }
  if (current) sections.push(current);
  return { overview: overviewLines.join("\n").trim(), days: sections };
}

function renderWeeklyPlanPretty(planText) {
  const pretty = $("weeklyPlanPretty");
  const raw = $("weeklyPlan");
  pretty.innerHTML = "";

  const text = beautifyWeeklyPlan(planText || "");
  const parsed = splitPlanSections(text);

  // If parsing fails to find day sections, show plain fallback.
  if (!parsed.days.length) {
    raw.style.display = "block";
    raw.textContent = text;
    return;
  }

  raw.style.display = "none";
  raw.textContent = text;

  if (parsed.overview) {
    const overview = document.createElement("div");
    overview.className = "planOverview";
    overview.textContent = formatWeeklyOverviewText(parsed.overview);
    pretty.appendChild(overview);
  }

  for (const day of parsed.days) {
    const card = document.createElement("div");
    card.className = "planDayCard";

    const title = document.createElement("div");
    title.className = "planDayTitle";
    title.textContent = `🏃‍♀️ ${day.title}`;

    const body = document.createElement("div");
    body.className = "planDayBody";
    renderPlanDayBody(body, day.lines.join("\n").trim());

    card.appendChild(title);
    card.appendChild(body);
    pretty.appendChild(card);
  }
}

function renderPlanDayBody(container, text) {
  container.innerHTML = "";
  const lines = String(text || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  if (!lines.length) return;

  let currentList = null;
  const flushList = () => {
    if (currentList && currentList.children.length > 0) {
      container.appendChild(currentList);
    }
    currentList = null;
  };

  for (const line of lines) {
    const normalizedLine = line.replace(/^[^A-Za-z0-9]+/, "");
    const isSection = /^[A-Za-z].*:\s*$/.test(normalizedLine);
    const isBullet = line.startsWith("- ") || line.startsWith("• ");

    if (isSection) {
      flushList();
      const section = document.createElement("div");
      section.className = "planSectionTitle";
      section.textContent = normalizedLine;
      container.appendChild(section);
      continue;
    }

    if (isBullet) {
      if (!currentList) {
        currentList = document.createElement("ul");
        currentList.className = "planBulletList";
      }
      const li = document.createElement("li");
      li.textContent = line.replace(/^(-|•)\s+/, "");
      currentList.appendChild(li);
      continue;
    }

    flushList();
    const p = document.createElement("div");
    p.textContent = line;
    container.appendChild(p);
  }

  flushList();
}

function setWeeklyPlan(planText) {
  renderWeeklyPlanPretty(planText || "");
}

function renderWeekProgress(workoutsThisWeek) {
  const list = Array.isArray(workoutsThisWeek) ? workoutsThisWeek : [];
  $("weekProgressSummary").textContent = `✅ Completed this week: ${list.length} session${list.length === 1 ? "" : "s"}`;
  $("weekProgressCount").textContent = `This week total: ${list.length}`;

  const container = $("weekWorkoutList");
  container.innerHTML = "";

  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "weekWorkoutItem";
    empty.textContent = "No workouts logged this week yet.";
    container.appendChild(empty);
    return;
  }

  for (const item of list) {
    const wrap = document.createElement("div");
    wrap.className = "weekWorkoutItem";

    const dateEl = document.createElement("div");
    dateEl.className = "weekWorkoutDate";
    dateEl.textContent = item.workout_date || "";

    const textEl = document.createElement("div");
    textEl.className = "weekWorkoutText";
    textEl.textContent = prettifyWorkoutLogText(item.log_text || "");

    wrap.appendChild(dateEl);
    wrap.appendChild(textEl);
    container.appendChild(wrap);
  }
}

function prettifyWorkoutLogText(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  // If already multiline bullets, keep as-is.
  if (text.includes("\n- ") || text.startsWith("- ")) return text;

  // Split comma-separated chunks into bullet lines.
  const parts = text.split(",").map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return text;
  return parts.map((p) => `- ${p}`).join("\n");
}

function setBusy(isBusy) {
  const chatInput = $("chatInput");
  const chatForm = $("chatForm");
  const logBtn = $("logWorkoutBtn");
  chatInput.disabled = isBusy;
  chatForm.querySelector("button").disabled = isBusy;
  logBtn.disabled = isBusy;
  if (isBusy) {
    logBtn.textContent = "Working...";
  } else {
    logBtn.textContent = "Log workout";
  }
}

function showIntake(show) {
  $("intakePanel").classList.toggle("hidden", !show);
}

async function loadStatus() {
  const status = await apiGet(`/api/status?user_id=${encodeURIComponent(userId)}`);

  showIntake(!status.has_profile);
  setWeeklyPlan(status.weekly_plan || "");
  renderWeekProgress(status.workouts_this_week || []);
  if (status.week_start && status.week_end) {
    $("weekProgressCount").textContent = `This week (${status.week_start} to ${status.week_end}): ${status.workouts_this_week_count ?? (status.workouts_this_week || []).length}`;
  }

  // Disable actions until intake exists.
  const hasProfile = Boolean(status.has_profile);
  $("chatInput").disabled = !hasProfile;
  $("chatForm").querySelector("button").disabled = !hasProfile;
  $("logWorkoutBtn").disabled = !hasProfile;

  // Reset chat history.
  $("chatHistory").innerHTML = "";
  (status.chat_history || []).forEach((m) => appendChatMessage(m.role, m.content));
}

async function handleIntakeSubmit(e) {
  e.preventDefault();
  setBusy(true);
  try {
    const form = e.target;
    const fd = new FormData(form);
    const payload = {
      goals: fd.get("goals"),
      days_per_week: fd.get("days_per_week"),
      experience_level: fd.get("experience_level"),
      equipment: fd.get("equipment"),
      injuries: fd.get("injuries"),
      schedule_constraints: fd.get("schedule_constraints"),
    };

    const resp = await apiPost(`/api/intake?user_id=${encodeURIComponent(userId)}`, payload);
    // Refresh UI from server state.
    await loadStatus();
    if (resp && resp.assistant_reply) {
      // status already includes history, so no need to double append.
    }
  } catch (err) {
    alert(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

async function handleChatSubmit(e) {
  e.preventDefault();
  setBusy(true);
  try {
    const input = $("chatInput");
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";

    appendChatMessage("user", msg);

    const resp = await apiPost(`/api/chat?user_id=${encodeURIComponent(userId)}`, { message: msg });
    appendChatMessage("trainer", resp.assistant_reply || "");

    // Update plan text if it changed.
    if (resp.weekly_plan !== undefined) setWeeklyPlan(resp.weekly_plan);
    await loadStatus();
  } catch (err) {
    alert(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

async function handleWorkoutLog(e) {
  e.preventDefault();
  setBusy(true);
  try {
    const date = $("workoutDate").value;
    const builtText = buildWorkoutLogFromRows();
    const rawOverride = $("workoutLogText").value.trim();
    const notes = $("workoutNotes").value.trim();
    const logText = rawOverride || [builtText, notes ? `Notes: ${notes}` : ""]
      .filter(Boolean)
      .join("\n");
    if (!logText) {
      alert("Please enter what you did.");
      return;
    }

    const payload = { workout_date: date, log_text: logText };
    appendChatMessage("user", `Workout log (${date}):\n${logText}`);
    $("workoutLogText").value = "";
    $("workoutNotes").value = "";
    resetExerciseRows();

    const resp = await apiPost(
      `/api/workout-log?user_id=${encodeURIComponent(userId)}`,
      payload
    );
    appendChatMessage("trainer", resp.assistant_reply || "");
    if (resp.weekly_plan !== undefined) setWeeklyPlan(resp.weekly_plan);
    await loadStatus();
  } catch (err) {
    alert(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

function createExerciseRow(initial = {}) {
  const row = document.createElement("div");
  row.className = "exerciseRow";

  const exercise = document.createElement("input");
  exercise.type = "text";
  exercise.placeholder = "Exercise (e.g. Squat)";
  exercise.value = initial.exercise || "";

  const setsReps = document.createElement("input");
  setsReps.type = "text";
  setsReps.placeholder = "Sets x reps (3x8)";
  setsReps.value = initial.setsReps || "";

  const effort = document.createElement("input");
  effort.type = "text";
  effort.placeholder = "Effort / load";
  effort.value = initial.effort || "";

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "removeExerciseBtn";
  removeBtn.textContent = "Remove";
  removeBtn.addEventListener("click", () => row.remove());

  row.appendChild(exercise);
  row.appendChild(setsReps);
  row.appendChild(effort);
  row.appendChild(removeBtn);
  return row;
}

function addExerciseRow(initial = {}) {
  $("exerciseRows").appendChild(createExerciseRow(initial));
}

function resetExerciseRows() {
  $("exerciseRows").innerHTML = "";
  addExerciseRow();
  addExerciseRow();
}

function buildWorkoutLogFromRows() {
  const rows = [...$("exerciseRows").querySelectorAll(".exerciseRow")];
  const lines = [];
  for (const row of rows) {
    const inputs = row.querySelectorAll("input");
    const exercise = (inputs[0]?.value || "").trim();
    const setsReps = (inputs[1]?.value || "").trim();
    const effort = (inputs[2]?.value || "").trim();
    if (!exercise && !setsReps && !effort) continue;

    const parts = [exercise];
    if (setsReps) parts.push(setsReps);
    if (effort) parts.push(effort);
    lines.push(parts.filter(Boolean).join(" - "));
  }
  return lines.map((l) => `- ${l}`).join("\n");
}

function setDefaultWorkoutDate() {
  // Use YYYY-MM-DD for input[type=date].
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  $("workoutDate").value = `${yyyy}-${mm}-${dd}`;
}

document.addEventListener("DOMContentLoaded", async () => {
  setDefaultWorkoutDate();
  resetExerciseRows();

  $("intakeForm").addEventListener("submit", handleIntakeSubmit);
  $("chatForm").addEventListener("submit", handleChatSubmit);
  $("addExerciseBtn").addEventListener("click", () => addExerciseRow());
  $("logWorkoutBtn").addEventListener("click", (e) => {
    // Convert button click into "submit" behavior.
    e.preventDefault();
    handleWorkoutLog(e);
  });

  await loadStatus();
});

