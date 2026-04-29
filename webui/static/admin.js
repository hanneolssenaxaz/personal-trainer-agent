const $ = (id) => document.getElementById(id);

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

async function loadSnapshot() {
  const userId = Number($("userIdInput").value || 1);
  const res = await fetch(`/api/admin/snapshot?user_id=${encodeURIComponent(userId)}`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Snapshot failed: ${res.status} ${t}`);
  }
  const data = await res.json();

  $("meta").textContent = pretty(data.meta || {});
  $("logicView").textContent = pretty(data.logic_view || {});
  $("tableCounts").textContent = pretty(data.table_counts || {});

  const currentState = data.current_state || {};
  const compactState = {
    profile: currentState.profile,
    weekly_plan_preview: (currentState.weekly_plan || "").slice(0, 1200),
    training_summary_preview: (currentState.training_summary || "").slice(0, 1200),
    chat_history_preview: (currentState.chat_history || []).slice(-8),
  };
  $("currentState").textContent = pretty(compactState);

  $("rawTables").textContent = pretty(data.raw_tables || {});
}

document.addEventListener("DOMContentLoaded", () => {
  $("refreshBtn").addEventListener("click", async () => {
    $("refreshBtn").disabled = true;
    $("refreshBtn").textContent = "Refreshing...";
    try {
      await loadSnapshot();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      $("refreshBtn").disabled = false;
      $("refreshBtn").textContent = "Refresh Snapshot";
    }
  });

  // Initial load.
  $("refreshBtn").click();
});

