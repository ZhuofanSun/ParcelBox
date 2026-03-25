import { ui } from "./dom.js";
import { CARD_ENROLL_TIMEOUT_SECONDS, state } from "./state.js";
import {
  renderDatabaseTables,
  renderEventCollection,
  renderLockerStatus,
  renderLiveDetailStrip,
  renderSystemStatus,
  setControlButtonsDisabled,
  showToast,
} from "./renderers.js";

export async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(payload?.detail || `${response.status} ${response.statusText}`);
  }
  return payload;
}

export async function refreshDatabaseView() {
  const payload = await fetchJson("/api/logs/tables", { headers: {} });
  renderDatabaseTables(payload);
  return payload;
}

export async function refreshLockerOverview() {
  const payload = await fetchJson("/api/locker/status", { headers: {} });
  renderLockerStatus(payload);
  return payload;
}

export async function refreshSystemOverview() {
  const payload = await fetchJson("/api/system/status", { headers: {} });
  renderSystemStatus(payload);
  return payload;
}

export async function refreshEventsView() {
  const payload = await fetchJson("/api/logs/events?limit=10", { headers: {} });
  state.latestEvents = payload.events || [];
  renderEventCollection(
    ui.overviewEventsList,
    state.latestEvents.slice(0, 6),
    "No recent business events yet."
  );
  renderEventCollection(
    ui.eventsFeedList,
    state.latestEvents,
    "No recent events available."
  );
  renderLiveDetailStrip();
  return payload;
}

export async function refreshDashboardData() {
  const results = await Promise.allSettled([
    refreshDatabaseView(),
    refreshLockerOverview(),
    refreshSystemOverview(),
    refreshEventsView(),
  ]);

  const failed = results.find((result) => result.status === "rejected");
  if (failed) {
    throw failed.reason;
  }
}

export async function enrollCard() {
  const name = ui.cardEnrollNameInput.value.trim();
  if (!name) {
    showToast("Save card failed: name is required");
    return;
  }

  setControlButtonsDisabled(true);
  showToast("Ready to save card: present the card to the reader");
  try {
    const payload = await fetchJson("/api/cards/enroll", {
      method: "POST",
      body: JSON.stringify({
        name,
        scan_timeout_seconds: CARD_ENROLL_TIMEOUT_SECONDS,
      }),
    });
    ui.cardEnrollNameInput.value = "";
    showToast(`Card saved: ${payload.card.uid} (${payload.card.name || "unnamed"})`);
    await refreshDashboardData().catch(() => {});
    return payload;
  } catch (error) {
    showToast(`Save card failed: ${error.message}`);
    throw error;
  } finally {
    setControlButtonsDisabled(false);
  }
}

export async function runLockerAction(path, label) {
  setControlButtonsDisabled(true);
  try {
    const payload = await fetchJson(path, {
      method: "POST",
      body: JSON.stringify({ source: "frontend" }),
    });
    showToast(`${label} succeeded`);
    await refreshDashboardData().catch(() => {});
    return payload;
  } catch (error) {
    showToast(`${label} failed: ${error.message}`);
    throw error;
  } finally {
    setControlButtonsDisabled(false);
  }
}

export async function runSnapshotAction() {
  setControlButtonsDisabled(true);
  try {
    const payload = await fetchJson("/api/camera/snapshot", {
      method: "POST",
      body: JSON.stringify({ source: "frontend" }),
    });
    showToast("Photo captured");
    await refreshDashboardData().catch(() => {});
    return payload;
  } catch (error) {
    showToast(`Capture photo failed: ${error.message}`);
    throw error;
  } finally {
    setControlButtonsDisabled(false);
  }
}
