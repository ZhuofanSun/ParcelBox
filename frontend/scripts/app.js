import { ui } from "./dom.js";
import { DASHBOARD_POLL_INTERVAL_MS, state } from "./state.js";
import { humanizeToken, statusToneClass } from "./formatters.js";
import {
  drawOverlay,
  resizeOverlay,
  setPillState,
  showToast,
  syncButtonStatus,
  updateOverviewFromVisionPayload,
} from "./renderers.js";
import {
  enrollCard,
  refreshDashboardData,
  runLockerAction,
  runSnapshotAction,
} from "./api.js";

function buildVisionWebSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/vision`;
}

function scheduleReconnect() {
  if (state.reconnectTimer) return;
  state.reconnectTimer = window.setTimeout(() => {
    state.reconnectTimer = null;
    connectVisionSocket();
  }, 1000);
}

function connectVisionSocket() {
  if (state.visionSocket) {
    state.visionSocket.close();
    state.visionSocket = null;
  }

  setPillState(ui.streamBadge, "Connecting", "status-pill-muted");
  state.visionSocket = new WebSocket(buildVisionWebSocketUrl());

  state.visionSocket.addEventListener("open", () => {
    setPillState(ui.streamBadge, "Connected", "status-pill-success");
  });

  state.visionSocket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    state.latestPayload = payload;
    syncButtonStatus({ latest_event: payload.button_event }, true);
    setPillState(
      ui.streamBadge,
      humanizeToken(payload.active_mode || payload.mode || "connected"),
      statusToneClass(String(payload.active_mode || payload.mode || "connected"))
    );
    updateOverviewFromVisionPayload(payload);
    drawOverlay();
  });

  state.visionSocket.addEventListener("close", () => {
    setPillState(ui.streamBadge, "Disconnected", "status-pill-danger");
    scheduleReconnect();
  });

  state.visionSocket.addEventListener("error", () => {
    setPillState(ui.streamBadge, "Socket Error", "status-pill-danger");
  });
}

function activateView(viewName) {
  ui.viewButtons.forEach((button) => {
    button.classList.toggle("nav-link-active", button.dataset.viewTarget === viewName);
  });
  ui.viewPanels.forEach((panel) => {
    panel.classList.toggle("view-panel-active", panel.dataset.viewPanel === viewName);
  });

  const nextHash = `#${viewName}`;
  if (window.location.hash !== nextHash) {
    history.replaceState(null, "", nextHash);
  }

  if (viewName === "overview") {
    window.requestAnimationFrame(resizeOverlay);
  }
}

function startDashboardPolling() {
  if (state.dashboardPollTimer) return;
  state.dashboardPollTimer = window.setInterval(() => {
    refreshDashboardData().catch((error) => {
      ui.dbBadge.textContent = "Sync Error";
      showToast(`Dashboard refresh failed: ${error.message}`);
    });
  }, DASHBOARD_POLL_INTERVAL_MS);
}

ui.viewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activateView(button.dataset.viewTarget);
  });
});

ui.headerOpenDebugButton.addEventListener("click", () => {
  activateView("debug");
});

ui.openDoorButton.addEventListener("click", () => {
  runLockerAction("/api/locker/open", "Open door").catch(() => {});
});

ui.closeDoorButton.addEventListener("click", () => {
  runLockerAction("/api/locker/close", "Close door").catch(() => {});
});

ui.captureSnapshotButton.addEventListener("click", () => {
  runSnapshotAction().catch(() => {});
});

ui.cardEnrollButton.addEventListener("click", () => {
  enrollCard().catch(() => {});
});

ui.cardEnrollNameInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  enrollCard().catch(() => {});
});

window.addEventListener("resize", resizeOverlay);
ui.streamImage.addEventListener("load", resizeOverlay);

window.addEventListener("beforeunload", () => {
  if (state.dashboardPollTimer) {
    window.clearInterval(state.dashboardPollTimer);
  }
  if (state.reconnectTimer) {
    window.clearTimeout(state.reconnectTimer);
  }
  if (state.visionSocket) {
    state.visionSocket.close();
  }
  if (state.buttonToastTimer) {
    window.clearTimeout(state.buttonToastTimer);
  }
});

async function bootstrap() {
  const initialView = window.location.hash.replace("#", "") || "overview";
  activateView(["overview", "cards", "events", "debug"].includes(initialView) ? initialView : "overview");
  connectVisionSocket();

  try {
    await refreshDashboardData();
  } catch (error) {
    ui.dbBadge.textContent = "Sync Error";
    showToast(`Initial dashboard load failed: ${error.message}`);
  }

  startDashboardPolling();
}

bootstrap();
