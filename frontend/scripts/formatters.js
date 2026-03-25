export function humanizeToken(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatDateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);

  const year = String(date.getFullYear()).padStart(4, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

export function formatTimestampLabel(value, fallback = "Time unavailable") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    const normalized = value > 1_000_000_000_000 ? value : value * 1000;
    return formatDateTime(normalized);
  }

  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
      return formatDateTime(parsed);
    }
  }

  return String(value);
}

function formatTimestampField(key, value) {
  if (!key) return value;
  const isTimestampKey = key === "timestamp" || key.endsWith("_at") || key === "measured_at";
  if (!isTimestampKey) return value;

  if (typeof value === "number" && Number.isFinite(value)) {
    return formatDateTime(value * 1000);
  }

  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
      return formatDateTime(parsed);
    }
  }

  return value;
}

export function formatPayloadForDisplay(value, key = "") {
  if (Array.isArray(value)) {
    return value.map((item) => formatPayloadForDisplay(item));
  }

  if (value && typeof value === "object") {
    const formatted = {};
    for (const [childKey, childValue] of Object.entries(value)) {
      formatted[childKey] = formatPayloadForDisplay(childValue, childKey);
    }
    return formatted;
  }

  return formatTimestampField(key, value);
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";

  const totalSeconds = Math.floor(seconds);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || parts.length) parts.push(`${hours}h`);
  if (minutes || parts.length) parts.push(`${minutes}m`);
  parts.push(`${remainingSeconds}s`);
  return parts.join(" ");
}

export function formatPercentage(value) {
  if (!Number.isFinite(value)) return "—";
  return `${value.toFixed(1)}%`;
}

export function formatTemperature(value) {
  if (!Number.isFinite(value)) return "—";
  return `${value.toFixed(1)} C`;
}

export function formatLoadAverage(loadAverage) {
  if (!loadAverage) return "—";
  const values = [loadAverage.one_min, loadAverage.five_min, loadAverage.fifteen_min]
    .filter((value) => value !== null && value !== undefined)
    .map((value) => Number(value).toFixed(2));
  return values.length ? values.join(" / ") : "—";
}

export function formatMemory(memory) {
  if (!memory || !Number.isFinite(memory.used_mb) || !Number.isFinite(memory.total_mb)) {
    return "—";
  }

  const usedPercent = Number.isFinite(memory.used_percent) ? ` (${memory.used_percent.toFixed(1)}%)` : "";
  return `${memory.used_mb.toFixed(1)} / ${memory.total_mb.toFixed(1)} MB${usedPercent}`;
}

export function statusToneClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (["connected", "ready", "enabled", "open", "granted", "occupied", "face", "face_hold", "tracking"].includes(normalized)) {
    return "status-pill-success";
  }
  if (["warning", "door_not_closed", "searching", "standby", "waiting"].includes(normalized)) {
    return "status-pill-warning";
  }
  if (["error", "offline", "disconnected", "denied", "closed"].includes(normalized)) {
    return "status-pill-danger";
  }
  return "status-pill-muted";
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function snapshotLabel(snapshot) {
  if (!snapshot) return null;
  if (snapshot.filename) return snapshot.filename;
  if (typeof snapshot.path === "string") {
    const parts = snapshot.path.split("/");
    return parts[parts.length - 1] || snapshot.path;
  }
  return null;
}

export function describeAccessResult(result) {
  if (!result || typeof result !== "object") {
    return "No access result yet";
  }

  const verdict = result.allowed ? "Allowed" : "Denied";
  const reason = result.reason ? humanizeToken(result.reason) : "Unknown";
  const uid = result.uid ? ` | ${result.uid}` : "";
  return `${verdict} | ${reason}${uid}`;
}

export function describeMountAdvice(advice) {
  if (!advice) return "Mount advice unavailable";
  if (advice.should_home) {
    return `Returning home | ${humanizeToken(advice.home_reason)}`;
  }
  if (!advice.has_target) {
    return `Waiting | ${humanizeToken(advice.direction)}`;
  }
  return (
    `${humanizeToken(advice.direction)} | pan ${Number(advice.pan.move_angle || 0).toFixed(1)} deg` +
    ` | tilt ${Number(advice.tilt.move_angle || 0).toFixed(1)} deg`
  );
}

export function describeEvent(event) {
  const details = [];
  if (event.reason) details.push(humanizeToken(event.reason));
  if (event.card_uid) details.push(`UID ${event.card_uid}`);
  if (event.source) details.push(humanizeToken(event.source));
  if (event.snapshot) {
    const label = snapshotLabel(event.snapshot);
    if (label) details.push(label);
  }
  if (event.occupancy_state) details.push(humanizeToken(event.occupancy_state));
  return details.join(" | ");
}

export function formatTableValue(key, value) {
  const formatted = formatPayloadForDisplay(value, key);
  if (formatted === null || formatted === undefined || formatted === "") {
    return { text: "—", empty: true, wrap: false };
  }

  if (key === "access_windows" && Array.isArray(formatted)) {
    if (formatted.length === 0) {
      return { text: "Always", empty: false, wrap: false };
    }
    const text = formatted
      .map((window) => {
        const days = Array.isArray(window.days) ? window.days.join(",") : "";
        return `${days} ${window.start}-${window.end}`.trim();
      })
      .join(" | ");
    return { text, empty: false, wrap: true };
  }

  if (Array.isArray(formatted)) {
    return { text: formatted.join(", "), empty: false, wrap: true };
  }

  if (typeof formatted === "object") {
    return {
      text: Object.entries(formatted)
        .map(([childKey, childValue]) => `${childKey}: ${childValue}`)
        .join(", "),
      empty: false,
      wrap: true,
    };
  }

  return { text: String(formatted), empty: false, wrap: String(formatted).length > 48 };
}
