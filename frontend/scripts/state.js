export const state = {
  latestPayload: null,
  latestLockerStatus: null,
  latestSystemStatus: null,
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
  activePopover: null,
  latestNotificationKey: null,
  seenNotificationKey: null,
  notificationUnreadCount: 0,
  visionSocket: null,
  reconnectTimer: null,
  dashboardPollTimer: null,
  buttonToastTimer: null,
  lastHandledButtonEventId: 0,
};

export const CARD_ENROLL_TIMEOUT_SECONDS = 10;
export const DASHBOARD_POLL_INTERVAL_MS = 2000;
export const THEME_STORAGE_KEY = "parcelbox.theme";
export const NOTIFICATION_SETTINGS_STORAGE_KEY = "parcelbox.notification_settings";
