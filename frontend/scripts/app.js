import { ui } from "./dom.js";
import {
  DASHBOARD_POLL_INTERVAL_MS,
  NOTIFICATION_SETTINGS_STORAGE_KEY,
  THEME_STORAGE_KEY,
  state,
} from "./state.js";
import { describeEvent, humanizeToken, snapshotLabel, statusToneClass } from "./formatters.js";
import {
  drawOverlay,
  markNotificationsSeen,
  renderDatabaseTables,
  renderNotificationCenter,
  renderSnapshotViewer,
  resizeOverlay,
  setPillState,
  showToast,
  syncButtonStatus,
  updateOverviewFromVisionPayload,
} from "./renderers.js";
import {
  createEmailScheme,
  deleteEmailScheme,
  deleteProfileAvatar,
  enrollCard,
  fetchEmailSettings,
  fetchProfileSettings,
  fetchSnapshotDetail,
  refreshDashboardData,
  runLockerAction,
  runSnapshotAction,
  saveProfileSettings,
  sendEmailTest,
  updateEmailScheme,
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeSchemeId(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function normalizeEmailScheme(rawScheme) {
  return {
    id: normalizeSchemeId(rawScheme?.id),
    name: typeof rawScheme?.name === "string" ? rawScheme.name : "",
    enabled: rawScheme?.enabled !== false,
    username: typeof rawScheme?.username === "string" ? rawScheme.username : "",
    password: typeof rawScheme?.password === "string" ? rawScheme.password : "",
    from_address: typeof rawScheme?.from_address === "string" ? rawScheme.from_address : "",
    recipients: Array.isArray(rawScheme?.recipients)
      ? rawScheme.recipients
          .map((entry) => ({
            id: normalizeSchemeId(entry?.id),
            email: typeof entry?.email === "string" ? entry.email : "",
          }))
          .filter((entry) => entry.email)
      : [],
  };
}

function blankEmailSchemeDraft() {
  return {
    selectedSchemeId: null,
    name: "",
    enabled: state.emailSettings.schemes.length === 0,
    username: "",
    password: "",
    from_address: "",
    recipients: [],
  };
}

function schemeToDraft(scheme) {
  if (!scheme) {
    return blankEmailSchemeDraft();
  }
  return {
    selectedSchemeId: scheme.id,
    name: scheme.name,
    enabled: scheme.enabled !== false,
    username: scheme.username || "",
    password: scheme.password || "",
    from_address: scheme.from_address || "",
    recipients: scheme.recipients.map((entry) => entry.email),
  };
}

function currentSelectedEmailScheme() {
  return state.emailSettings.schemes.find((scheme) => scheme.id === state.emailSettings.selectedSchemeId) || null;
}

function captureEmailSchemeDraft() {
  return {
    selectedSchemeId: state.emailSettings.selectedSchemeId,
    name: ui.settingsEmailSchemeNameInput.value.trim(),
    enabled: ui.settingsEmailEnabledInput.checked,
    username: ui.settingsEmailUsernameInput.value.trim(),
    password: ui.settingsEmailPasswordInput.value,
    from_address: ui.settingsEmailFromAddressInput.value.trim(),
    recipients: [...state.emailSettings.draftRecipients],
  };
}

function loadEmailSchemeDraft(draft) {
  state.emailSettings.selectedSchemeId = normalizeSchemeId(draft?.selectedSchemeId);
  ui.settingsEmailSchemeNameInput.value = draft?.name || "";
  ui.settingsEmailEnabledInput.checked = draft?.enabled !== false;
  ui.settingsEmailUsernameInput.value = draft?.username || "";
  ui.settingsEmailPasswordInput.value = draft?.password || "";
  ui.settingsEmailFromAddressInput.value = draft?.from_address || "";
  state.emailSettings.draftRecipients = Array.isArray(draft?.recipients)
    ? draft.recipients.map((email) => String(email || "").trim().toLowerCase()).filter(Boolean)
    : [];
  ui.settingsEmailRecipientInput.value = "";
  ui.settingsEmailPasswordInput.type = "password";
  ui.settingsEmailPasswordVisibilityButton.setAttribute("aria-pressed", "false");
  ui.settingsEmailPasswordVisibilityButton.setAttribute("aria-label", "Show password");
  renderEmailSchemeSelect();
  renderEmailRecipientDraft();
  const hasSelectedScheme = state.emailSettings.selectedSchemeId !== null;
  ui.settingsEmailDeleteButton.disabled = !hasSelectedScheme;
  ui.settingsEmailTestButton.disabled = !hasSelectedScheme;
}

function renderEmailSchemeSelect() {
  const options = ['<option value="">New scheme draft</option>'].concat(
    state.emailSettings.schemes.map((scheme) => {
      const suffix = scheme.enabled ? " (Enabled)" : "";
      return `<option value="${scheme.id}">${escapeHtml(scheme.name)}${suffix}</option>`;
    })
  );
  ui.settingsEmailSchemeSelect.innerHTML = options.join("");
  ui.settingsEmailSchemeSelect.value = state.emailSettings.selectedSchemeId ? String(state.emailSettings.selectedSchemeId) : "";
}

function renderEmailRecipientDraft() {
  const recipients = state.emailSettings.draftRecipients;
  ui.settingsEmailRecipientEmpty.hidden = recipients.length > 0;
  ui.settingsEmailRecipientList.innerHTML = recipients
    .map(
      (email, index) => `
        <button class="recipient-pill" type="button" data-email-recipient-index="${index}">
          <span class="recipient-pill-label">${escapeHtml(email)}</span>
          <span class="recipient-pill-remove">Remove</span>
        </button>
      `
    )
    .join("");
}

function renderEmailConfigSummary() {
  const activeScheme = state.emailSettings.schemes.find((scheme) => scheme.enabled) || null;
  ui.settingsEmailConfigEnabledValue.textContent = state.emailSettings.enabled ? "On" : "Off";
  ui.settingsEmailConfigHostValue.textContent = state.emailSettings.smtpHost || "-";
  ui.settingsEmailConfigPortValue.textContent = state.emailSettings.smtpPort ? String(state.emailSettings.smtpPort) : "-";
  ui.settingsEmailConfigTlsValue.textContent = state.emailSettings.useTls ? "Enabled" : "Disabled";
  ui.settingsEmailConfigTimeoutValue.textContent = state.emailSettings.timeoutSeconds
    ? `${state.emailSettings.timeoutSeconds}s`
    : "-";
  ui.settingsEmailConfigCooldownValue.textContent = state.emailSettings.duplicateRequestCooldownSeconds
    ? `${state.emailSettings.duplicateRequestCooldownSeconds}s`
    : "0s";
  ui.settingsEmailConfigSubjectValue.textContent = state.emailSettings.requestSubject || "No subject configured";
  ui.settingsEmailConfigFrontendUrlValue.textContent = state.emailSettings.frontendUrl || "No frontend URL configured";

  if (!activeScheme) {
    ui.settingsEmailActiveSchemeValue.textContent = "No enabled scheme";
    ui.settingsEmailActiveRecipientsValue.textContent =
      "Enable a scheme to send hardware button request emails.";
    return;
  }

  ui.settingsEmailActiveSchemeValue.textContent = activeScheme.name;
  ui.settingsEmailActiveRecipientsValue.textContent = `${activeScheme.recipients.length} recipient(s) | ${
    activeScheme.from_address || activeScheme.username || "from address falls back to username"
  }`;
}

function applyEmailSettings(settings, options = {}) {
  state.emailSettings.enabled = settings?.enabled !== false;
  state.emailSettings.smtpHost = typeof settings?.smtp_host === "string" ? settings.smtp_host : "";
  state.emailSettings.smtpPort = Number(settings?.smtp_port) || 0;
  state.emailSettings.useTls = settings?.use_tls !== false;
  state.emailSettings.timeoutSeconds = Number(settings?.timeout_seconds) || 0;
  state.emailSettings.frontendUrl = typeof settings?.frontend_url === "string" ? settings.frontend_url : "";
  state.emailSettings.requestSubject = typeof settings?.request_subject === "string" ? settings.request_subject : "";
  state.emailSettings.requestMessage = typeof settings?.request_message === "string" ? settings.request_message : "";
  state.emailSettings.duplicateRequestCooldownSeconds =
    Number(settings?.duplicate_request_cooldown_seconds) || 0;
  state.emailSettings.schemes = Array.isArray(settings?.schemes) ? settings.schemes.map(normalizeEmailScheme) : [];
  state.emailSettings.activeSchemeId = normalizeSchemeId(settings?.active_scheme_id);

  const preferredSelected =
    options.selectedSchemeId !== undefined
      ? normalizeSchemeId(options.selectedSchemeId)
      : state.emailSettings.selectedSchemeId;
  const selectedExists = state.emailSettings.schemes.some((scheme) => scheme.id === preferredSelected);
  state.emailSettings.selectedSchemeId = selectedExists
    ? preferredSelected
    : state.emailSettings.activeSchemeId || state.emailSettings.schemes[0]?.id || null;

  renderEmailConfigSummary();
  renderEmailSchemeSelect();

  const draft =
    options.preserveDraft && options.draft
      ? {
          ...options.draft,
          selectedSchemeId:
            state.emailSettings.selectedSchemeId && options.draft.selectedSchemeId === state.emailSettings.selectedSchemeId
              ? state.emailSettings.selectedSchemeId
              : normalizeSchemeId(options.draft.selectedSchemeId),
        }
      : schemeToDraft(currentSelectedEmailScheme());
  loadEmailSchemeDraft(draft);
}

function emailDraftSignature(draft) {
  return JSON.stringify({
    selectedSchemeId: normalizeSchemeId(draft?.selectedSchemeId),
    name: String(draft?.name || "").trim(),
    enabled: draft?.enabled !== false,
    username: String(draft?.username || "").trim(),
    password: String(draft?.password || ""),
    from_address: String(draft?.from_address || "").trim(),
    recipients: Array.isArray(draft?.recipients)
      ? draft.recipients.map((email) => String(email || "").trim().toLowerCase()).filter(Boolean)
      : [],
  });
}

function isEmailSchemeDirty() {
  const baseline = schemeToDraft(currentSelectedEmailScheme());
  const draft = captureEmailSchemeDraft();
  return emailDraftSignature(draft) !== emailDraftSignature(baseline);
}

function confirmDiscardEmailDraft() {
  if (!isEmailSchemeDirty()) {
    return true;
  }
  return window.confirm("Discard unsaved email scheme changes?");
}

function switchEmailSchemeSelection(nextSchemeId) {
  if (!confirmDiscardEmailDraft()) {
    renderEmailSchemeSelect();
    return;
  }
  state.emailSettings.selectedSchemeId = normalizeSchemeId(nextSchemeId);
  loadEmailSchemeDraft(
    state.emailSettings.selectedSchemeId ? schemeToDraft(currentSelectedEmailScheme()) : blankEmailSchemeDraft()
  );
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || "").trim());
}

function normalizeSnapshotId(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function uniqueSnapshotItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item || !item.id || seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

function buildEventSnapshotViewerItems(events) {
  return uniqueSnapshotItems(
    (Array.isArray(events) ? events : [])
      .map((event) => {
        const id = normalizeSnapshotId(event?.snapshot?.storage_id ?? event?.storage_id);
        if (!id) {
          return null;
        }
        return {
          id,
          title: snapshotLabel(event.snapshot) || humanizeToken(event.type || event.event_type || "snapshot"),
          trigger: event?.snapshot?.trigger || "snapshot",
          capturedAt: event?.snapshot?.captured_at || event?.snapshot?.saved_at || event?.timestamp || null,
          contextLabel: humanizeToken(event.type || event.event_type || "event"),
          contextNote: describeEvent(event) || "Snapshot linked to this event.",
        };
      })
      .filter(Boolean)
  );
}

function buildTableSnapshotViewerItems(snapshots) {
  return uniqueSnapshotItems(
    (Array.isArray(snapshots) ? snapshots : [])
      .map((snapshot) => {
        const id = normalizeSnapshotId(snapshot?.id ?? snapshot?.storage_id);
        if (!id) {
          return null;
        }
        const contextLabel =
          snapshot?.access_attempt_id !== null && snapshot?.access_attempt_id !== undefined
            ? `Access #${snapshot.access_attempt_id}`
            : snapshot?.button_request_id !== null && snapshot?.button_request_id !== undefined
              ? `Button #${snapshot.button_request_id}`
              : "Standalone";
        return {
          id,
          title: snapshot.filename || "Snapshot",
          trigger: snapshot.trigger || "snapshot",
          capturedAt: snapshot.captured_at || null,
          contextLabel,
          contextNote: `${humanizeToken(snapshot.trigger || "snapshot")} snapshot stored on the device.`,
        };
      })
      .filter(Boolean)
  );
}

function snapshotViewerItemsForSource(sourceKey) {
  switch (sourceKey) {
    case ui.overviewEventsList.id:
      return buildEventSnapshotViewerItems(state.latestEvents.slice(0, 6));
    case ui.eventsFeedList.id:
      return buildEventSnapshotViewerItems(state.latestEvents);
    case ui.snapshotList.id:
      return buildTableSnapshotViewerItems(state.latestDatabasePayload?.tables?.snapshot || []);
    default:
      return [];
  }
}

function addEmailRecipientToDraft() {
  const pending = ui.settingsEmailRecipientInput.value.trim().toLowerCase();
  if (!pending) {
    return;
  }
  if (!isValidEmail(pending)) {
    showToast("Recipient email is invalid.");
    return;
  }
  if (state.emailSettings.draftRecipients.includes(pending)) {
    showToast("Recipient already added.");
    return;
  }
  state.emailSettings.draftRecipients = [...state.emailSettings.draftRecipients, pending];
  ui.settingsEmailRecipientInput.value = "";
  renderEmailRecipientDraft();
}

function buildEmailSchemePayload() {
  if (ui.settingsEmailRecipientInput.value.trim()) {
    throw new Error("Add or clear the pending recipient email before saving");
  }
  return {
    name: ui.settingsEmailSchemeNameInput.value.trim(),
    enabled: ui.settingsEmailEnabledInput.checked,
    username: ui.settingsEmailUsernameInput.value.trim(),
    password: ui.settingsEmailPasswordInput.value,
    from_address: ui.settingsEmailFromAddressInput.value.trim(),
    recipients: [...state.emailSettings.draftRecipients],
  };
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

function closeSnapshotViewer() {
  state.snapshotViewer.open = false;
  state.snapshotViewer.sourceKey = null;
  state.snapshotViewer.items = [];
  state.snapshotViewer.currentIndex = 0;
  state.snapshotViewer.snapshot = null;
  state.snapshotViewer.loading = false;
  state.snapshotViewer.error = null;
  state.snapshotViewer.requestToken += 1;
  renderSnapshotViewer();
}

async function loadSnapshotViewerSnapshot(snapshotId) {
  const normalizedSnapshotId = normalizeSnapshotId(snapshotId);
  if (!normalizedSnapshotId || !state.snapshotViewer.open) {
    return;
  }

  const requestToken = state.snapshotViewer.requestToken + 1;
  state.snapshotViewer.requestToken = requestToken;
  state.snapshotViewer.loading = true;
  state.snapshotViewer.error = null;
  state.snapshotViewer.snapshot = null;
  renderSnapshotViewer();

  try {
    const snapshot = await fetchSnapshotDetail(normalizedSnapshotId);
    if (!state.snapshotViewer.open || state.snapshotViewer.requestToken !== requestToken) {
      return;
    }
    state.snapshotViewer.snapshot = snapshot;
    state.snapshotViewer.loading = false;
    state.snapshotViewer.error = null;
    renderSnapshotViewer();
  } catch (error) {
    if (!state.snapshotViewer.open || state.snapshotViewer.requestToken !== requestToken) {
      return;
    }
    const message = error instanceof Error ? error.message : String(error);
    state.snapshotViewer.snapshot = null;
    state.snapshotViewer.loading = false;
    state.snapshotViewer.error =
      /not found|no longer available|404/i.test(message)
        ? "This snapshot is no longer stored on the device."
        : `Failed to load snapshot: ${message}`;
    renderSnapshotViewer();
  }
}

function openSnapshotViewer(snapshotId, sourceKey) {
  const normalizedSnapshotId = normalizeSnapshotId(snapshotId);
  if (!normalizedSnapshotId) {
    return;
  }

  closeAllPopovers();
  const items = snapshotViewerItemsForSource(sourceKey);
  const fallbackItem = {
    id: normalizedSnapshotId,
    title: "Snapshot",
    trigger: "snapshot",
    capturedAt: null,
    contextLabel: "Standalone",
    contextNote: "Snapshot lookup from the ParcelBox device.",
  };
  const nextItems = items.length ? items : [fallbackItem];
  let currentIndex = nextItems.findIndex((item) => item.id === normalizedSnapshotId);
  if (currentIndex === -1) {
    nextItems.unshift(fallbackItem);
    currentIndex = 0;
  }

  state.snapshotViewer.open = true;
  state.snapshotViewer.sourceKey = sourceKey || null;
  state.snapshotViewer.items = nextItems;
  state.snapshotViewer.currentIndex = currentIndex;
  state.snapshotViewer.snapshot = null;
  state.snapshotViewer.loading = false;
  state.snapshotViewer.error = null;
  renderSnapshotViewer();
  loadSnapshotViewerSnapshot(normalizedSnapshotId);
}

function stepSnapshotViewer(offset) {
  if (!state.snapshotViewer.open) {
    return;
  }
  const nextIndex = state.snapshotViewer.currentIndex + offset;
  if (nextIndex < 0 || nextIndex >= state.snapshotViewer.items.length) {
    return;
  }
  state.snapshotViewer.currentIndex = nextIndex;
  loadSnapshotViewerSnapshot(state.snapshotViewer.items[nextIndex].id);
}

function handleSnapshotLauncherClick(event) {
  const target = event.target instanceof Element ? event.target.closest("[data-snapshot-id]") : null;
  if (!target) {
    return;
  }
  const snapshotId = normalizeSnapshotId(target.dataset.snapshotId);
  if (!snapshotId) {
    return;
  }
  openSnapshotViewer(snapshotId, target.dataset.snapshotSource || "");
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

ui.settingsEmailSchemeSelect.addEventListener("change", () => {
  switchEmailSchemeSelection(ui.settingsEmailSchemeSelect.value);
});

ui.settingsEmailNewSchemeButton.addEventListener("click", () => {
  switchEmailSchemeSelection(null);
});

ui.settingsEmailPasswordVisibilityButton.addEventListener("click", () => {
  const nextVisible = ui.settingsEmailPasswordInput.type === "password";
  ui.settingsEmailPasswordInput.type = nextVisible ? "text" : "password";
  ui.settingsEmailPasswordVisibilityButton.setAttribute("aria-pressed", String(nextVisible));
  ui.settingsEmailPasswordVisibilityButton.setAttribute(
    "aria-label",
    nextVisible ? "Hide password" : "Show password"
  );
});

ui.settingsEmailRecipientAddButton.addEventListener("click", () => {
  addEmailRecipientToDraft();
});

ui.settingsEmailRecipientInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  addEmailRecipientToDraft();
});

ui.settingsEmailRecipientList.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const pill = target ? target.closest("[data-email-recipient-index]") : null;
  if (!pill) {
    return;
  }
  const index = Number(pill.dataset.emailRecipientIndex);
  if (!Number.isInteger(index) || index < 0) {
    return;
  }
  state.emailSettings.draftRecipients = state.emailSettings.draftRecipients.filter((_, current) => current !== index);
  renderEmailRecipientDraft();
});

ui.settingsEmailSaveButton.addEventListener("click", async () => {
  const schemeId = state.emailSettings.selectedSchemeId;
  if (!schemeId) {
    showToast("No saved scheme selected. Use Save As New for a new email scheme.");
    return;
  }
  try {
    const emailSettings = await updateEmailScheme(schemeId, buildEmailSchemePayload());
    applyEmailSettings(emailSettings, { selectedSchemeId: schemeId });
    showToast("Email scheme updated.");
  } catch (error) {
    showToast(`Email scheme update failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsEmailSaveAsNewButton.addEventListener("click", async () => {
  try {
    const payload = buildEmailSchemePayload();
    const emailSettings = await createEmailScheme(payload);
    const createdScheme = emailSettings.schemes?.find(
      (scheme) => String(scheme.name || "").trim().toLowerCase() === payload.name.trim().toLowerCase()
    );
    applyEmailSettings(emailSettings, { selectedSchemeId: createdScheme?.id || null });
    showToast("New email scheme saved.");
  } catch (error) {
    showToast(`Email scheme save failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsEmailDeleteButton.addEventListener("click", async () => {
  const schemeId = state.emailSettings.selectedSchemeId;
  if (!schemeId) {
    showToast("No saved scheme selected.");
    return;
  }
  if (!window.confirm("Delete this email scheme?")) {
    return;
  }
  try {
    const emailSettings = await deleteEmailScheme(schemeId);
    applyEmailSettings(emailSettings, { selectedSchemeId: null });
    showToast("Email scheme deleted.");
  } catch (error) {
    showToast(`Email scheme delete failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.settingsEmailTestButton.addEventListener("click", async () => {
  const schemeId = state.emailSettings.selectedSchemeId;
  if (!schemeId) {
    showToast("Save a scheme before sending a test email.");
    return;
  }
  if (isEmailSchemeDirty()) {
    showToast("Save the current email scheme before sending a test email.");
    return;
  }
  try {
    const result = await sendEmailTest(schemeId);
    if (result.status === "sent") {
      showToast(`Test email sent via ${result.scheme_name}.`);
    } else if (result.status === "error") {
      showToast(`Test email failed: ${result.error || "unknown error"}`);
    } else {
      showToast(`Test email status: ${result.reason || result.status}`);
    }
  } catch (error) {
    showToast(`Test email failed: ${error instanceof Error ? error.message : String(error)}`);
  }
});

ui.overviewEventsList.addEventListener("click", handleSnapshotLauncherClick);
ui.eventsFeedList.addEventListener("click", handleSnapshotLauncherClick);
ui.snapshotList.addEventListener("click", handleSnapshotLauncherClick);

ui.snapshotViewerCloseButton.addEventListener("click", () => {
  closeSnapshotViewer();
});

ui.snapshotViewerPrevButton.addEventListener("click", () => {
  stepSnapshotViewer(-1);
});

ui.snapshotViewerNextButton.addEventListener("click", () => {
  stepSnapshotViewer(1);
});

ui.snapshotViewerBackdrop.addEventListener("click", (event) => {
  if (event.target === ui.snapshotViewerBackdrop) {
    closeSnapshotViewer();
  }
});

ui.snapshotViewerImage.addEventListener("error", () => {
  if (!state.snapshotViewer.open) {
    return;
  }
  state.snapshotViewer.snapshot = state.snapshotViewer.snapshot
    ? {
        ...state.snapshotViewer.snapshot,
        file_exists: false,
        file_url: null,
      }
    : null;
  state.snapshotViewer.error = "This snapshot file is no longer available on the device.";
  renderSnapshotViewer();
});

ui.debugTableLimitSelect.addEventListener("change", () => {
  const nextLimit = Number(ui.debugTableLimitSelect.value);
  state.debugTableRowLimit = Number.isFinite(nextLimit) && nextLimit >= 0 ? nextLimit : 25;
  if (state.latestDatabasePayload) {
    renderDatabaseTables(state.latestDatabasePayload);
  }
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
    if (state.snapshotViewer.open) {
      closeSnapshotViewer();
      return;
    }
    closeAllPopovers();
    return;
  }
  if (!state.snapshotViewer.open) {
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    stepSnapshotViewer(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    stepSnapshotViewer(1);
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
  ui.debugTableLimitSelect.value = String(state.debugTableRowLimit);
  renderEmailConfigSummary();
  loadEmailSchemeDraft(blankEmailSchemeDraft());
  activateSettingsSection("profile");
  renderNotificationCenter();
  renderSnapshotViewer();

  const initialView = window.location.hash.replace("#", "") || "overview";
  activateView(["overview", "cards", "events", "debug", "settings"].includes(initialView) ? initialView : "overview");
  connectVisionSocket();

  try {
    const [profile, emailSettings] = await Promise.all([fetchProfileSettings(), fetchEmailSettings()]);
    applyProfile(profileFromServer(profile));
    applyEmailSettings(emailSettings);
    await refreshDashboardData();
  } catch (error) {
    ui.dbBadge.textContent = "Sync Error";
    showToast(`Initial dashboard load failed: ${error.message}`);
  }

  startDashboardPolling();
}

bootstrap();
