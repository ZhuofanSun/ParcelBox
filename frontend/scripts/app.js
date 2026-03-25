import { ui } from "./dom.js";
import {
  DASHBOARD_POLL_INTERVAL_MS,
  NOTIFICATION_SETTINGS_STORAGE_KEY,
  THEME_STORAGE_KEY,
  state,
} from "./state.js";
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
  deleteProfileAvatar,
  enrollCard,
  fetchProfileSettings,
  refreshDashboardData,
  runLockerAction,
  runSnapshotAction,
  saveProfileSettings,
  uploadProfileAvatar,
} from "./api.js";

const PROFILE_DEFAULT_NAME = "ParcelBox Local";
const PROFILE_DEFAULT_ROLE = "Device operator";
const PROFILE_AVATAR_SIZE = 192;
const PROFILE_AVATAR_MAX_BYTES = 5 * 1024 * 1024;

function buildVisionWebSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/vision`;
}

function getStoredTheme() {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return storedTheme === "dark" ? "dark" : "light";
}

function getStoredNotificationPreferences() {
  try {
    const raw = window.localStorage.getItem(NOTIFICATION_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return { ...state.notificationPreferences };
    }
    const parsed = JSON.parse(raw);
    return {
      buttonPressed: parsed?.buttonPressed !== false,
      accessDenied: parsed?.accessDenied !== false,
      faceNearby: parsed?.faceNearby !== false,
    };
  } catch {
    return { ...state.notificationPreferences };
  }
}

function normalizeProfile(profile) {
  const normalized = {
    name: typeof profile?.name === "string" && profile.name.trim() ? profile.name.trim() : PROFILE_DEFAULT_NAME,
    role: typeof profile?.role === "string" && profile.role.trim() ? profile.role.trim() : PROFILE_DEFAULT_ROLE,
    avatarMode: profile?.avatarMode === "uploaded" ? "uploaded" : "initials",
    avatarImageUrl:
      typeof profile?.avatarImageUrl === "string" && profile.avatarImageUrl.trim()
        ? profile.avatarImageUrl
        : null,
  };

  if (normalized.avatarMode === "uploaded" && !normalized.avatarImageUrl) {
    normalized.avatarMode = "initials";
  }

  return normalized;
}

function profileFromServer(profile) {
  return {
    name: profile?.name,
    role: profile?.role,
    avatarMode: profile?.has_avatar ? "uploaded" : "initials",
    avatarImageUrl: profile?.avatar_url || null,
  };
}

function computeProfileInitials(name) {
  const tokens = String(name || "")
    .trim()
    .split(/[\s_-]+/)
    .map((token) => token.replace(/[^\p{L}\p{N}]/gu, ""))
    .filter(Boolean);

  if (tokens.length >= 2) {
    return `${tokens[0][0]}${tokens[1][0]}`.toUpperCase();
  }

  if (tokens.length === 1) {
    return tokens[0].slice(0, 2).toUpperCase();
  }

  return "PB";
}

function renderProfileAvatars(profile = state.profile) {
  const initials = computeProfileInitials(profile.name);
  const hasUploadedAvatar = profile.avatarMode === "uploaded" && Boolean(profile.avatarImageUrl);

  ui.profileAvatarRoots.forEach((root) => {
    const image = root.querySelector(".profile-avatar-image");
    const fallback = root.querySelector(".profile-avatar-fallback");
    if (!image || !fallback) {
      return;
    }

    fallback.textContent = initials;
    fallback.hidden = hasUploadedAvatar;
    image.hidden = !hasUploadedAvatar;

    if (hasUploadedAvatar) {
      image.src = profile.avatarImageUrl;
    } else {
      image.removeAttribute("src");
    }
  });

  ui.settingsProfileAvatarStatus.textContent = hasUploadedAvatar
    ? "Custom avatar is stored on the ParcelBox device and served back to this page."
    : `Using initials avatar based on Display Name: ${initials}.`;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Failed to read image file"));
    reader.readAsDataURL(file);
  });
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Failed to load selected image"));
    image.src = dataUrl;
  });
}

async function buildAvatarDataUrl(file) {
  if (!(file instanceof File)) {
    throw new Error("Please choose an image file");
  }
  if (!file.type.startsWith("image/")) {
    throw new Error("Avatar must be an image");
  }
  if (file.size > PROFILE_AVATAR_MAX_BYTES) {
    throw new Error("Avatar image must be 5 MB or smaller");
  }

  const sourceDataUrl = await readFileAsDataUrl(file);
  if (typeof sourceDataUrl !== "string" || !sourceDataUrl.startsWith("data:image/")) {
    throw new Error("Unsupported avatar image");
  }

  const image = await loadImage(sourceDataUrl);
  const sourceWidth = image.naturalWidth || image.width;
  const sourceHeight = image.naturalHeight || image.height;
  const squareSize = Math.min(sourceWidth, sourceHeight);
  if (!squareSize) {
    throw new Error("Avatar image is empty");
  }

  const offsetX = (sourceWidth - squareSize) / 2;
  const offsetY = (sourceHeight - squareSize) / 2;
  const canvas = document.createElement("canvas");
  canvas.width = PROFILE_AVATAR_SIZE;
  canvas.height = PROFILE_AVATAR_SIZE;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Avatar canvas is unavailable");
  }

  context.drawImage(
    image,
    offsetX,
    offsetY,
    squareSize,
    squareSize,
    0,
    0,
    PROFILE_AVATAR_SIZE,
    PROFILE_AVATAR_SIZE
  );

  return canvas.toDataURL("image/webp", 0.9);
}

function syncSettingsForm() {
  ui.settingsProfileNameInput.value = state.profile.name;
  ui.settingsProfileRoleInput.value = state.profile.role;
  ui.settingsThemeSelect.value = state.theme;
  ui.settingsThemeValue.textContent = state.theme === "dark" ? "Dark" : "Light";
  ui.settingsAlertButtonInput.checked = state.notificationPreferences.buttonPressed;
  ui.settingsAlertDeniedInput.checked = state.notificationPreferences.accessDenied;
  ui.settingsAlertFaceInput.checked = state.notificationPreferences.faceNearby;
}

function captureProfileSettingsDraft() {
  return {
    name: ui.settingsProfileNameInput.value,
    role: ui.settingsProfileRoleInput.value,
    theme: ui.settingsThemeSelect.value,
  };
}

function restoreProfileSettingsDraft(draft) {
  if (!draft) {
    return;
  }
  ui.settingsProfileNameInput.value = draft.name;
  ui.settingsProfileRoleInput.value = draft.role;
  ui.settingsThemeSelect.value = draft.theme;
}

function applyProfile(profile, options = {}) {
  state.profile = normalizeProfile({
    ...state.profile,
    ...profile,
  });
  ui.headerProfileName.textContent = state.profile.name;
  ui.headerProfileRole.textContent = state.profile.role;
  ui.popoverProfileName.textContent = state.profile.name;
  ui.popoverProfileRole.textContent = state.profile.role;
  renderProfileAvatars();
  syncSettingsForm();
  if (options.preserveSettingsDraft) {
    restoreProfileSettingsDraft(options.draft || captureProfileSettingsDraft());
  }
}

function applyNotificationPreferences(preferences, persist = true) {
  state.notificationPreferences = {
    buttonPressed: preferences.buttonPressed !== false,
    accessDenied: preferences.accessDenied !== false,
    faceNearby: preferences.faceNearby !== false,
  };
  if (persist) {
    window.localStorage.setItem(
      NOTIFICATION_SETTINGS_STORAGE_KEY,
      JSON.stringify(state.notificationPreferences)
    );
  }
  syncSettingsForm();
  renderNotificationCenter();
}

function applyTheme(theme, persist = true) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  ui.themeToggleButton.setAttribute("aria-pressed", String(state.theme === "dark"));
  ui.themeToggleLabel.textContent = state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  ui.profileThemeValue.textContent = state.theme === "dark" ? "Dark" : "Light";
  ui.settingsThemeValue.textContent = state.theme === "dark" ? "Dark" : "Light";
  ui.settingsThemeSelect.value = state.theme;
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

function activateSettingsSection(sectionName) {
  ui.settingsSectionButtons.forEach((button) => {
    button.classList.toggle("settings-tab-active", button.dataset.settingsSectionTarget === sectionName);
  });
  ui.settingsSections.forEach((section) => {
    section.classList.toggle("settings-section-active", section.dataset.settingsSection === sectionName);
  });
}

function openSettings(sectionName = "profile") {
  closeAllPopovers();
  activateView("settings");
  activateSettingsSection(sectionName);
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
  openSettings("profile");
});

ui.profileNotificationSettingsButton.addEventListener("click", () => {
  openSettings("notifications");
});

ui.settingsBackButton.addEventListener("click", () => {
  activateView("overview");
});

ui.settingsSectionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activateSettingsSection(button.dataset.settingsSectionTarget);
  });
});

ui.settingsProfileAvatarUploadButton.addEventListener("click", () => {
  ui.settingsProfileAvatarInput.click();
});

ui.settingsProfileAvatarInput.addEventListener("change", async () => {
  const file = ui.settingsProfileAvatarInput.files?.[0];
  ui.settingsProfileAvatarInput.value = "";
  if (!file) {
    return;
  }
  const draft = captureProfileSettingsDraft();

  try {
    const avatarDataUrl = await buildAvatarDataUrl(file);
    const profile = await uploadProfileAvatar(avatarDataUrl);
    applyProfile(profileFromServer(profile), { preserveSettingsDraft: true, draft });
    showToast("Avatar uploaded to the ParcelBox device.");
  } catch (error) {
    showToast(`Avatar update failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsProfileAvatarResetButton.addEventListener("click", async () => {
  const draft = captureProfileSettingsDraft();
  try {
    const profile = await deleteProfileAvatar();
    applyProfile(profileFromServer(profile), { preserveSettingsDraft: true, draft });
    showToast("Avatar reset to initials.");
  } catch (error) {
    showToast(`Avatar reset failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsProfileSaveButton.addEventListener("click", async () => {
  applyTheme(ui.settingsThemeSelect.value);
  try {
    const profile = await saveProfileSettings({
      name: ui.settingsProfileNameInput.value,
      role: ui.settingsProfileRoleInput.value,
    });
    applyProfile(profileFromServer(profile));
    showToast("Profile settings saved on the ParcelBox device.");
  } catch (error) {
    showToast(`Profile settings update failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsNotificationsSaveButton.addEventListener("click", () => {
  applyNotificationPreferences({
    buttonPressed: ui.settingsAlertButtonInput.checked,
    accessDenied: ui.settingsAlertDeniedInput.checked,
    faceNearby: ui.settingsAlertFaceInput.checked,
  });
  showToast("Notification settings saved locally.");
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
  applyProfile(state.profile);
  applyTheme(getStoredTheme(), false);
  applyNotificationPreferences(getStoredNotificationPreferences(), false);
  activateSettingsSection("profile");
  renderNotificationCenter();

  const initialView = window.location.hash.replace("#", "") || "overview";
  activateView(["overview", "cards", "events", "debug", "settings"].includes(initialView) ? initialView : "overview");
  connectVisionSocket();

  try {
    const profile = await fetchProfileSettings();
    applyProfile(profileFromServer(profile));
    await refreshDashboardData();
  } catch (error) {
    ui.dbBadge.textContent = "Sync Error";
    showToast(`Initial dashboard load failed: ${error.message}`);
  }

  startDashboardPolling();
}

bootstrap();
