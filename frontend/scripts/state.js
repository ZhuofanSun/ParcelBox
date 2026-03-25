export const state = {
  latestPayload: null,
  latestLockerStatus: null,
  latestSystemStatus: null,
  latestEvents: [],
  visionSocket: null,
  reconnectTimer: null,
  dashboardPollTimer: null,
  buttonToastTimer: null,
  lastHandledButtonEventId: 0,
};

export const CARD_ENROLL_TIMEOUT_SECONDS = 10;
export const DASHBOARD_POLL_INTERVAL_MS = 2000;
