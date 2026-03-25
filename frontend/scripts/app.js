import { ui } from "./dom.js";
import { DASHBOARD_POLL_INTERVAL_MS, THEME_STORAGE_KEY, state } from "./state.js";
import { humanizeToken, statusToneClass } from "./formatters.js";
import {
  drawOverlay,
  markNotificationsSeen,
  renderNotificationCenter,
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

function getStoredTheme() {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return storedTheme === "dark" ? "dark" : "light";
}

function applyTheme(theme, persist = true) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  ui.themeToggleButton.setAttribute("aria-pressed", String(state.theme === "dark"));
  ui.themeToggleLabel.textContent = state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  ui.profileThemeValue.textContent = state.theme === "dark" ? "Dark" : "Light";
  if (persist) {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  }
}

function toggleTheme() {
  applyTheme(state.theme === "dark" ? "light" : "dark");
}

function scheduleReconnect() {
  if (state.reconnectTimer) return;
  state.reconnectTimer = window.setTimeout(() => {
    state.reconnectTimer = null;
    connectVisionSocket();
  }, 1000);
}

function setPopoverState(button, popover, isOpen) {
  button.setAttribute("aria-expanded", String(isOpen));
  button.classList.toggle("toolbar-button-active", isOpen);
  button.classList.toggle("profile-trigger-active", isOpen);
  popover.hidden = !isOpen;
}

function closeAllPopovers() {
  state.activePopover = null;
  setPopoverState(ui.notificationsTriggerButton, ui.notificationsPopover, false);
  setPopoverState(ui.profileTriggerButton, ui.profilePopover, false);
}

function openPopover(name) {
  closeAllPopovers();
  state.activePopover = name;
  if (name === "notifications") {
    setPopoverState(ui.notificationsTriggerButton, ui.notificationsPopover, true);
    markNotificationsSeen();
    return;
  }
  if (name === "profile") {
    setPopoverState(ui.profileTriggerButton, ui.profilePopover, true);
  }
}

function togglePopover(name) {
  if (state.activePopover === name) {
    closeAllPopovers();
    return;
  }
  openPopover(name);
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
  closeAllPopovers();

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

ui.themeToggleButton.addEventListener("click", () => {
  toggleTheme();
});

ui.notificationsTriggerButton.addEventListener("click", () => {
  togglePopover("notifications");
});

ui.notificationsOpenEventsButton.addEventListener("click", () => {
  activateView("events");
});

ui.profileTriggerButton.addEventListener("click", () => {
  togglePopover("profile");
});

ui.profileSettingsButton.addEventListener("click", () => {
  closeAllPopovers();
  showToast("Profile settings page is planned but not wired yet.");
});

ui.profileNotificationSettingsButton.addEventListener("click", () => {
  closeAllPopovers();
  showToast("Notification settings page is planned but not wired yet.");
});

ui.profileLogoutButton.addEventListener("click", () => {
  closeAllPopovers();
  showToast("Local console mode does not use sign-in yet.");
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

document.addEventListener("click", (event) => {
  if (!ui.headerToolbar.contains(event.target)) {
    closeAllPopovers();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeAllPopovers();
  }
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
  applyTheme(getStoredTheme(), false);
  renderNotificationCenter();

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
