export const state = {
  latestPayload: null,
  latestLockerStatus: null,
  latestSystemStatus: null,
  latestDatabasePayload: null,
  latestEvents: [],
  theme: "light",
  profile: {
    name: "ParcelBox Local",
    role: "Device operator",
    avatarMode: "initials",
    avatarImageUrl: null,
  },
  notificationPreferences: {
    buttonPressed: true,
    accessDenied: true,
    faceNearby: true,
  },
  emailSettings: {
    enabled: true,
    smtpHost: "",
    smtpPort: 0,
    useTls: true,
    timeoutSeconds: 0,
    frontendUrl: "",
    requestSubject: "",
    requestMessage: "",
    duplicateRequestCooldownSeconds: 0,
    schemes: [],
    activeSchemeId: null,
    selectedSchemeId: null,
    draftRecipients: [],
  },
  activePopover: null,
  latestNotificationKey: null,
  seenNotificationKey: null,
  notificationUnreadCount: 0,
  snapshotViewer: {
    open: false,
    sourceKey: null,
    items: [],
    currentIndex: 0,
    snapshot: null,
    loading: false,
    error: null,
    requestToken: 0,
  },
  streamRetryTimer: null,
  streamWatchdogTimer: null,
  visionSocket: null,
  reconnectTimer: null,
  dashboardPollTimer: null,
  buttonToastTimer: null,
  lastHandledButtonEventId: 0,
  lastButtonToastAt: 0,
  debugTableRowLimit: 25,
};

export const CARD_ENROLL_TIMEOUT_SECONDS = 10;
export const DASHBOARD_POLL_INTERVAL_MS = 2000;
export const BUTTON_NOTIFICATION_COOLDOWN_MS = 5000;
export const THEME_STORAGE_KEY = "parcelbox.theme";
export const NOTIFICATION_SETTINGS_STORAGE_KEY = "parcelbox.notification_settings";
