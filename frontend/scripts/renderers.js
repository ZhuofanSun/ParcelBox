import { ui, ctx } from "./dom.js";
import { state } from "./state.js";
import {
  describeAccessResult,
  describeEvent,
  describeMountAdvice,
  escapeHtml,
  formatDateTime,
  formatDuration,
  formatLoadAverage,
  formatMemory,
  formatPayloadForDisplay,
  formatPercentage,
  formatTableValue,
  formatTemperature,
  formatTimestampLabel,
  humanizeToken,
  snapshotLabel,
  statusToneClass,
} from "./formatters.js";

const BUTTON_NOTIFICATION_COOLDOWN_MS = 5000;

export function setPillState(element, label, tone) {
  if (!element) return;
  element.textContent = label;
  element.className = `status-pill ${tone || "status-pill-muted"}`.trim();
}

export function renderTableRows(tbody, rows, columns) {
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="cell-empty" colspan="${columns.length}">No rows</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map((row) => {
      const cells = columns
        .map((column) => {
          const { text, empty, wrap } = formatTableValue(column.key, row[column.key]);
          const classes = [empty ? "cell-empty" : "", wrap ? "cell-wrap" : ""]
            .filter(Boolean)
            .join(" ");
          return `<td${classes ? ` class="${classes}"` : ""}>${escapeHtml(text)}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
}

export function renderEmptyCollection(container, message) {
  container.innerHTML = `<div class="placeholder-block">${escapeHtml(message)}</div>`;
}

function normalizeSnapshotId(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function snapshotRelationLabel(snapshot, fallbackLabel = "Standalone") {
  if (snapshot?.access_attempt_id !== null && snapshot?.access_attempt_id !== undefined) {
    return `Access #${snapshot.access_attempt_id}`;
  }
  if (snapshot?.button_request_id !== null && snapshot?.button_request_id !== undefined) {
    return `Button #${snapshot.button_request_id}`;
  }
  return fallbackLabel;
}

export function renderEventCollection(container, events, emptyMessage) {
  if (!Array.isArray(events) || events.length === 0) {
    renderEmptyCollection(container, emptyMessage);
    return;
  }

  container.innerHTML = events
    .map((event) => {
      const title = humanizeToken(event.type || event.event_type || "event");
      const timeLabel = formatTimestampLabel(event.timestamp);
      const detailLine = describeEvent(event);
      const snapshotId = normalizeSnapshotId(event?.snapshot?.storage_id ?? event?.storage_id);
      const isSnapshotOpenable = snapshotId !== null;
      const tags = [];
      if (event.allowed === true) tags.push('<span class="tag tag-success">Allowed</span>');
      if (event.allowed === false) tags.push('<span class="tag tag-danger">Denied</span>');
      if (event.snapshot) tags.push('<span class="tag">Snapshot</span>');
      if (event.source) tags.push(`<span class="tag">${escapeHtml(humanizeToken(event.source))}</span>`);
      if (isSnapshotOpenable) {
        tags.push('<span class="tag tag-action">Open Viewer</span>');
      }

      const rootTag = isSnapshotOpenable ? "button" : "div";
      const rootAttributes = isSnapshotOpenable
        ? `type="button" class="collection-item collection-item-event collection-item-button" data-snapshot-id="${snapshotId}" data-snapshot-source="${escapeHtml(container.id || "events")}" aria-label="Open snapshot for ${escapeHtml(title)}"`
        : 'class="collection-item collection-item-event"';

      return `
        <${rootTag} ${rootAttributes}>
          <div class="collection-kicker">Event</div>
          <div class="collection-topline">
            <div class="collection-title">${escapeHtml(title)}</div>
            <div class="collection-time">${escapeHtml(timeLabel)}</div>
          </div>
          <div class="collection-meta">${escapeHtml(detailLine || "No extra details")}</div>
          <div class="collection-tags">${tags.join("")}</div>
        </${rootTag}>
      `;
    })
    .join("");
}

function buildNotificationKey(event) {
  if (!event) return null;
  return [
    event.timestamp ?? "",
    event.type ?? event.event_type ?? "",
    event.reason ?? "",
    event.card_uid ?? "",
    event.source ?? "",
  ].join("|");
}

function isNotificationEvent(event) {
  if (!event || typeof event !== "object") return false;
  if (
    event.type === "unauthorized_card_alarm" ||
    event.type === "button_press_burst_alarm" ||
    event.type === "access_denied_burst_alarm"
  ) {
    return true;
  }
  if (event.type === "button_pressed") {
    return state.notificationPreferences.buttonPressed;
  }
  if (event.type === "access_denied") {
    return state.notificationPreferences.accessDenied;
  }
  if (event.type === "face_snapshot_captured") {
    return state.notificationPreferences.faceNearby;
  }
  return false;
}

function notificationEventsWithCooldown(events) {
  const filteredEvents = [];
  let lastButtonNotificationAt = null;

  for (const event of Array.isArray(events) ? events : []) {
    if (!isNotificationEvent(event)) {
      continue;
    }

    if (event.type === "button_pressed") {
      const timestampMs = Number(event.timestamp) * 1000;
      if (Number.isFinite(timestampMs)) {
        if (
          lastButtonNotificationAt !== null &&
          Math.abs(lastButtonNotificationAt - timestampMs) < BUTTON_NOTIFICATION_COOLDOWN_MS
        ) {
          continue;
        }
        lastButtonNotificationAt = timestampMs;
      }
    }

    filteredEvents.push(event);
  }

  return filteredEvents;
}

function buildNotificationModel(event) {
  const timeLabel = formatTimestampLabel(event.timestamp);
  const snapshotFile = snapshotLabel(event.snapshot);

  if (event.type === "unauthorized_card_alarm") {
    return {
      title: "Unauthorized Card Alarm",
      kicker: "Security Alarm",
      toneClass: "notification-item-danger",
      meta: event.uid ? `Unauthorized RFID scan | UID ${event.uid}` : "Unauthorized RFID scan detected",
      timeLabel,
    };
  }

  if (event.type === "button_press_burst_alarm") {
    return {
      title: "Button Spam Alarm",
      kicker: "Security Alarm",
      toneClass: "notification-item-danger",
      meta: "Hardware button was pressed rapidly five times.",
      timeLabel,
    };
  }

  if (event.type === "access_denied_burst_alarm") {
    return {
      title: "Repeated RFID Denials",
      kicker: "Security Alarm",
      toneClass: "notification-item-danger",
      meta: "Multiple unauthorized card scans were detected in a short window.",
      timeLabel,
    };
  }

  if (event.type === "button_pressed") {
    const notificationStatus = event.notification?.status
      ? humanizeToken(event.notification.status)
      : event.notification_error
        ? "Email failed"
        : "Local event";
    return {
      title: "Button Pressed",
      kicker: "Open Request",
      toneClass: "notification-item-amber",
      meta: snapshotFile
        ? `Hardware button | ${snapshotFile} | ${notificationStatus}`
        : `Hardware button | ${notificationStatus}`,
      timeLabel,
    };
  }

  if (event.type === "access_denied") {
    const reason = humanizeToken(event.reason || "denied");
    const uid = event.uid ? `UID ${event.uid}` : "Unknown UID";
    return {
      title: "RFID Access Denied",
      kicker: "Access Control",
      toneClass: "notification-item-danger",
      meta: snapshotFile
        ? `${reason} | ${uid} | ${snapshotFile}`
        : `${reason} | ${uid}`,
      timeLabel,
    };
  }

  return {
    title: "Face Nearby",
    kicker: "Vision Alert",
    toneClass: "notification-item-blue",
    meta: snapshotFile
      ? `Close-range face snapshot | ${snapshotFile}`
      : "Close-range face detected by vision service",
    timeLabel,
  };
}

export function markNotificationsSeen() {
  const alertEvents = notificationEventsWithCooldown(state.latestEvents);
  state.seenNotificationKey = buildNotificationKey(alertEvents[0]);
  state.notificationUnreadCount = 0;
  renderNotificationCenter();
}

export function renderNotificationCenter() {
  const alertEvents = notificationEventsWithCooldown(state.latestEvents);
  const latestAlert = alertEvents[0] || null;
  const latestKey = buildNotificationKey(latestAlert);

  if (latestKey && state.latestNotificationKey === null) {
    state.latestNotificationKey = latestKey;
    if (state.seenNotificationKey === null) {
      state.seenNotificationKey = latestKey;
    }
  } else if (latestKey && latestKey !== state.latestNotificationKey) {
    state.latestNotificationKey = latestKey;
    if (state.activePopover === "notifications") {
      state.seenNotificationKey = latestKey;
    }
  }

  state.notificationUnreadCount = latestKey && latestKey !== state.seenNotificationKey ? 1 : 0;
  ui.notificationsUnreadDot.hidden = state.notificationUnreadCount === 0;
  ui.notificationsUnreadCount.textContent = state.notificationUnreadCount > 0
    ? "Unread"
    : "All read";

  const notifications = alertEvents.slice(0, 5);
  ui.notificationsEmpty.hidden = notifications.length > 0;
  ui.notificationsEmpty.textContent = Object.values(state.notificationPreferences).some(Boolean)
    ? "No recent high-priority alerts."
    : "All in-app alert types are currently disabled.";
  ui.notificationsList.innerHTML = notifications
    .map((event) => {
      const model = buildNotificationModel(event);
      return `
        <div class="notification-item ${model.toneClass}">
          <div class="notification-kicker">${escapeHtml(model.kicker)}</div>
          <div class="notification-topline">
            <div class="notification-title">${escapeHtml(model.title)}</div>
            <div class="notification-time">${escapeHtml(model.timeLabel)}</div>
          </div>
          <div class="notification-meta">${escapeHtml(model.meta)}</div>
        </div>
      `;
    })
    .join("");
}

export function renderCardCollection(container, cards) {
  if (!Array.isArray(cards) || cards.length === 0) {
    renderEmptyCollection(container, "No RFID cards stored yet.");
    return;
  }

  container.innerHTML = cards
    .slice(0, 8)
    .map((card) => {
      const windows = Array.isArray(card.access_windows) && card.access_windows.length
        ? card.access_windows
          .map((window) => {
            const days = Array.isArray(window.days) ? window.days.join(",") : "";
            return `${days} ${window.start}-${window.end}`.trim();
          })
          .join(" | ")
        : "Always";
      const enabledTag = card.enabled
        ? '<span class="tag tag-success">Enabled</span>'
        : '<span class="tag tag-danger">Disabled</span>';
      return `
        <div class="collection-item collection-item-card">
          <div class="collection-kicker">Card Record</div>
          <div class="collection-topline">
            <div class="collection-title">${escapeHtml(card.name || "Unnamed Card")}</div>
            <div class="collection-time">${escapeHtml(card.uid || "Unknown UID")}</div>
          </div>
          <div class="collection-meta">${escapeHtml(windows)}</div>
          <div class="collection-tags">
            ${enabledTag}
            <span class="tag">${escapeHtml(formatTimestampLabel(card.updated_at))}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

export function renderAccessCollection(container, attempts) {
  if (!Array.isArray(attempts) || attempts.length === 0) {
    renderEmptyCollection(container, "No access attempts recorded yet.");
    return;
  }

  container.innerHTML = attempts
    .slice(0, 10)
    .map((attempt) => {
      const verdictTag = attempt.allowed
        ? '<span class="tag tag-success">Allowed</span>'
        : '<span class="tag tag-danger">Denied</span>';
      return `
        <div class="collection-item collection-item-access">
          <div class="collection-kicker">Access Attempt</div>
          <div class="collection-topline">
            <div class="collection-title">${escapeHtml(attempt.card_uid || "Unknown UID")}</div>
            <div class="collection-time">${escapeHtml(formatTimestampLabel(attempt.checked_at))}</div>
          </div>
          <div class="collection-meta">${escapeHtml(humanizeToken(attempt.reason || "unknown"))}</div>
          <div class="collection-tags">
            ${verdictTag}
            <span class="tag">${escapeHtml(humanizeToken(attempt.source || "unknown"))}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

export function renderSnapshotCollection(container, snapshots) {
  if (!Array.isArray(snapshots) || snapshots.length === 0) {
    renderEmptyCollection(container, "No snapshots saved yet.");
    return;
  }

  container.innerHTML = snapshots
    .slice(0, 10)
    .map((snapshot) => {
      const relation = snapshotRelationLabel(snapshot);
      const snapshotId = normalizeSnapshotId(snapshot?.id ?? snapshot?.storage_id);
      return `
        <button
          class="collection-item collection-item-snapshot collection-item-button"
          type="button"
          data-snapshot-id="${snapshotId}"
          data-snapshot-source="${escapeHtml(container.id || "snapshots")}"
          aria-label="Open snapshot ${escapeHtml(snapshot.filename || "Snapshot")}"
        >
          <div class="collection-kicker">Snapshot</div>
          <div class="collection-topline">
            <div class="collection-title">${escapeHtml(snapshot.filename || "Snapshot")}</div>
            <div class="collection-time">${escapeHtml(formatTimestampLabel(snapshot.captured_at))}</div>
          </div>
          <div class="collection-meta">${escapeHtml(humanizeToken(snapshot.trigger || "snapshot"))}</div>
          <div class="collection-tags">
            <span class="tag">${escapeHtml(relation)}</span>
            <span class="tag tag-action">Open Viewer</span>
          </div>
        </button>
      `;
    })
    .join("");
}

export function renderSnapshotViewer() {
  const viewer = state.snapshotViewer;
  const item = viewer.items[viewer.currentIndex] || null;
  const snapshot = viewer.snapshot;
  const fileUrl =
    !viewer.loading && !viewer.error && snapshot?.file_exists !== false && typeof snapshot?.file_url === "string"
      ? snapshot.file_url
      : null;

  ui.snapshotViewerBackdrop.hidden = !viewer.open;
  document.body.classList.toggle("modal-open", viewer.open);

  if (!viewer.open) {
    ui.snapshotViewerImage.hidden = true;
    ui.snapshotViewerImage.removeAttribute("src");
    ui.snapshotViewerEmpty.hidden = true;
    ui.snapshotViewerOpenLink.hidden = true;
    ui.snapshotViewerOpenLink.removeAttribute("href");
    return;
  }

  ui.snapshotViewerTitle.textContent = snapshot?.filename || item?.title || "Snapshot";
  ui.snapshotViewerSubtitle.textContent = formatTimestampLabel(snapshot?.captured_at || item?.capturedAt);
  ui.snapshotViewerTrigger.textContent = humanizeToken(snapshot?.trigger || item?.trigger || "snapshot");
  ui.snapshotViewerRelation.textContent = snapshotRelationLabel(snapshot, item?.contextLabel || "Standalone");
  ui.snapshotViewerCounter.textContent = viewer.items.length
    ? `${viewer.currentIndex + 1} / ${viewer.items.length}`
    : "0 / 0";
  ui.snapshotViewerStatus.textContent = viewer.error
    ? viewer.error
    : viewer.loading
      ? "Loading snapshot from the ParcelBox device..."
      : item?.contextNote || "Stored on the ParcelBox device.";

  if (fileUrl) {
    if (ui.snapshotViewerImage.dataset.currentUrl !== fileUrl) {
      ui.snapshotViewerImage.src = fileUrl;
      ui.snapshotViewerImage.dataset.currentUrl = fileUrl;
    }
    ui.snapshotViewerImage.hidden = false;
    ui.snapshotViewerEmpty.hidden = true;
    ui.snapshotViewerOpenLink.hidden = false;
    ui.snapshotViewerOpenLink.href = fileUrl;
  } else {
    ui.snapshotViewerImage.hidden = true;
    ui.snapshotViewerImage.removeAttribute("src");
    delete ui.snapshotViewerImage.dataset.currentUrl;
    ui.snapshotViewerEmpty.hidden = false;
    ui.snapshotViewerEmpty.textContent = viewer.error
      ? viewer.error
      : viewer.loading
        ? "Loading snapshot from the device..."
        : "Snapshot file is unavailable.";
    ui.snapshotViewerOpenLink.hidden = true;
    ui.snapshotViewerOpenLink.removeAttribute("href");
  }

  ui.snapshotViewerPrevButton.disabled = viewer.currentIndex <= 0;
  ui.snapshotViewerNextButton.disabled = viewer.currentIndex >= viewer.items.length - 1;
}

export function setControlButtonsDisabled(disabled) {
  ui.openDoorButton.disabled = disabled;
  ui.closeDoorButton.disabled = disabled;
  ui.captureSnapshotButton.disabled = disabled;
  ui.cardEnrollButton.disabled = disabled;
  ui.cardEnrollNameInput.disabled = disabled;
}

export function showToast(message) {
  if (!message) return;
  ui.buttonToast.textContent = message;
  ui.buttonToast.classList.add("toast-visible");
  if (state.buttonToastTimer) {
    window.clearTimeout(state.buttonToastTimer);
  }
  state.buttonToastTimer = window.setTimeout(() => {
    ui.buttonToast.classList.remove("toast-visible");
    state.buttonToastTimer = null;
  }, 4200);
}

export function resizeOverlay() {
  const rect = ui.streamImage.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  ui.overlay.width = rect.width;
  ui.overlay.height = rect.height;
  drawOverlay();
}

function toOverlayPoint(x, y, frameWidth, frameHeight) {
  return {
    x: x * (ui.overlay.width / frameWidth),
    y: y * (ui.overlay.height / frameHeight),
  };
}

function drawBox(box, frameWidth, frameHeight) {
  const topLeft = toOverlayPoint(box.x1, box.y1, frameWidth, frameHeight);
  const bottomRight = toOverlayPoint(box.x2, box.y2, frameWidth, frameHeight);
  const x = topLeft.x;
  const y = topLeft.y;
  const width = bottomRight.x - topLeft.x;
  const height = bottomRight.y - topLeft.y;

  ctx.strokeStyle = "#ff6a3d";
  ctx.lineWidth = 3;
  ctx.strokeRect(x, y, width, height);

  const label = `${box.label} ${(box.score * 100).toFixed(0)}%`;
  ctx.font = "14px 'Avenir Next', 'Segoe UI', sans-serif";
  const textWidth = ctx.measureText(label).width + 18;
  const textHeight = 28;
  ctx.fillStyle = "#ff6a3d";
  ctx.fillRect(x, Math.max(0, y - textHeight), textWidth, textHeight);
  ctx.fillStyle = "#fffaf2";
  ctx.fillText(label, x + 9, Math.max(18, y - 9));
}

function drawMountAdvice() {
  const advice = state.latestPayload?.camera_mount;
  if (!advice) return;

  const label = describeMountAdvice(advice);
  ctx.font = "14px 'Avenir Next', 'Segoe UI', sans-serif";
  const paddingX = 12;
  const paddingY = 8;
  const textWidth = ctx.measureText(label).width;
  const boxWidth = textWidth + paddingX * 2;
  const boxHeight = 32;
  const x = 14;
  const y = ui.overlay.height - boxHeight - 14;

  ctx.fillStyle = "rgba(8, 18, 31, 0.74)";
  ctx.fillRect(x, y, boxWidth, boxHeight);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
  ctx.lineWidth = 1;
  ctx.strokeRect(x, y, boxWidth, boxHeight);
  ctx.fillStyle = "#fff8ea";
  ctx.fillText(label, x + paddingX, y + boxHeight - paddingY - 2);
}

export function drawOverlay() {
  ctx.clearRect(0, 0, ui.overlay.width, ui.overlay.height);
  const frameWidth = state.latestPayload?.frame_size?.width;
  const frameHeight = state.latestPayload?.frame_size?.height;
  if (!frameWidth || !frameHeight) return;

  if (state.latestPayload) {
    for (const box of state.latestPayload.boxes || []) {
      drawBox(box, frameWidth, frameHeight);
    }
  }

  drawMountAdvice();
}

export function renderLiveDetailStrip() {
  const primaryBox = Array.isArray(state.latestPayload?.boxes) && state.latestPayload.boxes.length > 0
    ? state.latestPayload.boxes[0]
    : null;
  const latestEvent = state.latestEvents[0] || state.latestLockerStatus?.recent_events?.[0] || null;
  const activeMode = state.latestPayload?.active_mode || state.latestPayload?.mode || "waiting";

  ui.liveTargetValue.textContent = primaryBox
    ? humanizeToken(primaryBox.label || "target")
    : humanizeToken(activeMode === "face_hold" ? "predicted hold" : "waiting");
  ui.liveTargetNote.textContent = primaryBox
    ? `${(Number(primaryBox.score || 0) * 100).toFixed(0)}% | ${Math.max(0, primaryBox.x2 - primaryBox.x1)}x${Math.max(0, primaryBox.y2 - primaryBox.y1)} px`
    : "No face box in frame";

  ui.liveDetectionFpsValue.textContent = Number.isFinite(state.latestPayload?.runtime?.current_detection_fps_target)
    ? `${state.latestPayload.runtime.current_detection_fps_target} FPS`
    : "—";
  ui.liveDetectionNote.textContent = Number.isFinite(state.latestPayload?.latency_ms)
    ? `${humanizeToken(activeMode)} | ${state.latestPayload.latency_ms.toFixed(0)} ms latency`
    : `${humanizeToken(activeMode)} | latency unavailable`;

  const frameWidth = state.latestPayload?.frame_size?.width;
  const frameHeight = state.latestPayload?.frame_size?.height;
  const detectionWidth = state.latestPayload?.detection_size?.width;
  const detectionHeight = state.latestPayload?.detection_size?.height;
  ui.liveFrameValue.textContent = frameWidth && frameHeight ? `${frameWidth}x${frameHeight}` : "—";
  ui.liveFrameNote.textContent = detectionWidth && detectionHeight
    ? `Detection ${detectionWidth}x${detectionHeight}`
    : "Detection size unavailable";

  ui.liveLastEventValue.textContent = latestEvent
    ? humanizeToken(latestEvent.type || latestEvent.event_type || "event")
    : "None";
  ui.liveLastEventNote.textContent = latestEvent
    ? `${describeEvent(latestEvent) || "No extra details"}${latestEvent.timestamp ? ` | ${formatDateTime(latestEvent.timestamp * 1000)}` : ""}`
    : "No recent events yet";
}

export function updateOverviewFromVisionPayload(payload) {
  const activeMode = humanizeToken(payload?.active_mode || payload?.mode || "waiting");
  ui.visionModeValue.textContent = activeMode;
  setPillState(ui.overviewModeBadge, activeMode, statusToneClass(String(payload?.active_mode || "")));

  const mountAdvice = payload?.camera_mount;
  const mountStatus = humanizeToken(mountAdvice?.status || "mount idle");
  ui.mountStatusValue.textContent = describeMountAdvice(mountAdvice);
  setPillState(ui.overviewMountBadge, mountStatus, statusToneClass(String(mountAdvice?.status || "")));

  ui.debugVisionJson.textContent = JSON.stringify(formatPayloadForDisplay(payload), null, 2);
  renderLiveDetailStrip();
}

export function renderLockerStatus(payload) {
  state.latestLockerStatus = payload;
  const occupancy = payload?.occupancy?.latest_measurement || {};
  ui.doorStateValue.textContent = humanizeToken(payload?.door_state || "unknown");
  ui.occupancyStateValue.textContent = humanizeToken(occupancy.state || "unknown");
  ui.occupancyDistanceValue.textContent = Number.isFinite(occupancy.distance_cm)
    ? `${occupancy.distance_cm.toFixed(1)} cm`
    : "Distance unavailable";
  ui.rfidReaderValue.textContent = payload?.rfid?.reader_enabled ? "Ready" : "Offline";
  ui.rfidCardCountValue.textContent = Number.isFinite(payload?.rfid?.card_count) ? String(payload.rfid.card_count) : "—";
  ui.lastAccessValue.textContent = describeAccessResult(payload?.last_access_result);
  ui.lastErrorValue.textContent = payload?.last_error || payload?.rfid?.last_error || payload?.occupancy?.last_error || "No runtime errors reported.";
  ui.debugLockerJson.textContent = JSON.stringify(formatPayloadForDisplay(payload), null, 2);
  renderLiveDetailStrip();
}

export function renderSystemStatus(payload) {
  state.latestSystemStatus = payload;
  ui.systemHostnameValue.textContent = payload?.hostname || "—";
  ui.profileHostValue.textContent = payload?.hostname || "Local device";
  ui.settingsHostValue.textContent = payload?.hostname || "Local device";
  ui.systemCpuTempValue.textContent = formatTemperature(payload?.cpu?.temperature_c);
  ui.systemCpuUsageValue.textContent = formatPercentage(payload?.cpu?.usage_percent);
  ui.systemMemoryValue.textContent = formatMemory(payload?.memory);
  ui.systemAppUptimeValue.textContent = formatDuration(payload?.app_uptime_seconds);
  ui.systemLoadValue.textContent = formatLoadAverage(payload?.cpu?.load_average);
  ui.systemPlatformValue.textContent = [
    payload?.platform?.system,
    payload?.platform?.release,
    payload?.platform?.machine,
  ].filter(Boolean).join(" / ") || "—";
  ui.debugSystemJson.textContent = JSON.stringify(formatPayloadForDisplay(payload), null, 2);
}

export function renderDatabaseTables(payload) {
  const tables = payload.tables || {};
  const status = payload.status || {};
  const tableLimit = Number(state.debugTableRowLimit) || 0;
  const limitRows = (rows) => {
    if (!Array.isArray(rows)) {
      return [];
    }
    return tableLimit > 0 ? rows.slice(0, tableLimit) : rows;
  };

  renderTableRows(ui.rfidCardBody, limitRows(tables.rfid_card), [
    { key: "uid" },
    { key: "name" },
    { key: "enabled" },
    { key: "access_windows" },
    { key: "created_at" },
    { key: "updated_at" },
  ]);
  renderTableRows(ui.accessAttemptBody, limitRows(tables.access_attempt), [
    { key: "id" },
    { key: "card_uid" },
    { key: "source" },
    { key: "allowed" },
    { key: "reason" },
    { key: "checked_at" },
  ]);
  renderTableRows(ui.doorSessionBody, limitRows(tables.door_session), [
    { key: "id" },
    { key: "access_attempt_id" },
    { key: "open_source" },
    { key: "opened_at" },
    { key: "close_source" },
    { key: "closed_at" },
    { key: "auto_closed" },
    { key: "occupancy_state" },
    { key: "occupancy_distance_cm" },
    { key: "occupancy_measured_at" },
  ]);
  renderTableRows(ui.buttonRequestBody, limitRows(tables.button_request), [
    { key: "id" },
    { key: "pressed_at" },
    { key: "email_sent" },
    { key: "email_duplicated" },
    { key: "email_sent_at" },
    { key: "email_error" },
  ]);
  renderTableRows(ui.snapshotBody, limitRows(tables.snapshot), [
    { key: "id" },
    { key: "path" },
    { key: "filename" },
    { key: "trigger" },
    { key: "captured_at" },
    { key: "access_attempt_id" },
    { key: "button_request_id" },
  ]);
  renderTableRows(ui.emailSubscriptionSchemeBody, limitRows(tables.email_subscription_scheme), [
    { key: "id" },
    { key: "name" },
    { key: "enabled" },
    { key: "username" },
    { key: "password" },
    { key: "from_address" },
    { key: "created_at" },
    { key: "updated_at" },
  ]);
  renderTableRows(ui.emailSubscriptionRecipientBody, limitRows(tables.email_subscription_recipient), [
    { key: "id" },
    { key: "scheme_id" },
    { key: "email" },
    { key: "created_at" },
    { key: "updated_at" },
  ]);

  renderCardCollection(ui.cardsPageList, tables.rfid_card || []);
  renderAccessCollection(ui.accessPageList, tables.access_attempt || []);
  renderSnapshotCollection(ui.snapshotList, tables.snapshot || []);

  ui.summaryCardsCount.textContent = String(status.card_count || 0);
  ui.summaryEventsCount.textContent = String(status.event_count || 0);
  ui.summarySnapshotsCount.textContent = String(status.snapshot_count || 0);
  ui.summaryDoorSessionsCount.textContent = String(status.door_session_count || 0);
  ui.dbBadge.textContent = `Live ${formatDateTime(Date.now())}`;
  renderLiveDetailStrip();
}

export function syncButtonStatus(buttonStatus, announce = false) {
  const buttonEvent = buttonStatus?.latest_event || null;
  if (!buttonEvent || !Number.isFinite(buttonEvent.id)) {
    return;
  }

  if (buttonEvent.id <= state.lastHandledButtonEventId) {
    return;
  }

  state.lastHandledButtonEventId = buttonEvent.id;
  if (!announce) {
    return;
  }

  const eventTimestampMs = Number(buttonEvent.timestamp) * 1000;
  if (
    Number.isFinite(eventTimestampMs) &&
    state.lastButtonToastAt > 0 &&
    Math.abs(eventTimestampMs - state.lastButtonToastAt) < BUTTON_NOTIFICATION_COOLDOWN_MS
  ) {
    return;
  }
  if (Number.isFinite(eventTimestampMs)) {
    state.lastButtonToastAt = eventTimestampMs;
  }

  const errorMessage = buttonEvent.snapshot_error;
  const notification = buttonEvent.notification;
  const notificationError = buttonEvent.notification_error;
  const fileLabel = snapshotLabel(buttonEvent.snapshot);
  const photoMessage = errorMessage
    ? `snapshot failed (${errorMessage})`
    : buttonEvent.snapshot_skipped_reason === "cooldown"
      ? "snapshot cooldown active"
      : fileLabel
        ? `photo saved as ${fileLabel}`
        : "photo saved locally";

  let notificationMessage = "email notification not configured";
  if (notificationError) {
    notificationMessage = `email failed (${notificationError})`;
  } else if (notification?.status === "sent") {
    notificationMessage = "open-request email sent";
  } else if (notification?.status === "duplicate_filtered") {
    notificationMessage = "duplicate open request filtered";
  } else if (notification?.status === "disabled") {
    notificationMessage = "email notification disabled";
  } else if (notification?.status === "error") {
    notificationMessage = `email failed (${notification.error})`;
  }

  showToast(`Button pressed: ${photoMessage}; ${notificationMessage}`);
}
