"""Camera mount advisory service.

This Phase 2 skeleton does not drive GPIO or move real servos yet.
It only translates the latest vision target into pan / tilt guidance so the
future mount-control path can be wired into the app and frontend first.
"""

from __future__ import annotations

import math
import threading
import time

from config import config


class CameraMountService:
    """Compute suggested camera-mount movement from vision payloads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self._home_pending_reason: str | None = None
        self._tracking_face_active = False
        self._latest_advice = self._build_idle_advice()

    def start(self) -> None:
        """Mark the advisory service as active."""
        with self._lock:
            self._started = True
            self._home_pending_reason = "startup"
            self._tracking_face_active = False
            self._latest_advice = self._build_idle_advice()

    def stop(self) -> None:
        """Reset the advisory state."""
        with self._lock:
            self._started = False
            self._home_pending_reason = None
            self._tracking_face_active = False
            self._latest_advice = self._build_idle_advice()

    def enrich_payload(self, payload: dict) -> dict:
        """Attach current camera-mount advice to a vision payload."""
        with self._lock:
            advice = self._build_advice(payload, started=self._started)
            self._latest_advice = advice

        enriched_payload = dict(payload)
        enriched_payload["camera_mount"] = advice
        return enriched_payload

    def get_status(self) -> dict:
        """Return service status and the latest computed advice."""
        with self._lock:
            return {
                "started": self._started,
                "enabled": config.camera_mount.enabled,
                "pins": {
                    "pan_servo_pin": config.gpio.camera_pan_servo_pin,
                    "tilt_servo_pin": config.gpio.camera_tilt_servo_pin,
                },
                "home_angles": {
                    "pan": config.camera_mount.pan_home_angle,
                    "tilt": config.camera_mount.tilt_home_angle,
                },
                "direction_inversion": {
                    "pan": config.camera_mount.invert_pan_direction,
                    "tilt": config.camera_mount.invert_tilt_direction,
                },
                "latest_advice": self._latest_advice,
            }

    def _build_advice(self, payload: dict, *, started: bool) -> dict:
        frame_width, frame_height = self._extract_frame_size(payload)
        if not frame_width or not frame_height:
            return self._build_idle_advice(started=started, status="frame_unavailable")

        if self._home_pending_reason is not None:
            advice = self._build_home_advice(
                started=started,
                reason=self._home_pending_reason,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            self._home_pending_reason = None
            return advice

        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2
        target = self._extract_face_target(payload)
        if payload.get("status") != "ok" or target is None:
            if self._tracking_face_active:
                self._tracking_face_active = False
                return self._build_home_advice(
                    started=started,
                    reason="face_lost",
                    frame_width=frame_width,
                    frame_height=frame_height,
                )
            return self._build_idle_advice(
                started=started,
                status="waiting_for_face",
                frame_width=frame_width,
                frame_height=frame_height,
            )

        target_center_x = float(target["center_x"])
        target_center_y = float(target["center_y"])
        offset_x_px = target_center_x - frame_center_x
        offset_y_px = target_center_y - frame_center_y
        if config.camera_mount.invert_pan_direction:
            offset_x_px *= -1
        if config.camera_mount.invert_tilt_direction:
            offset_y_px *= -1
        offset_x_ratio = offset_x_px / max(frame_center_x, 1.0)
        offset_y_ratio = offset_y_px / max(frame_center_y, 1.0)
        distance_px = math.hypot(offset_x_px, offset_y_px)
        distance_ratio = min(
            1.0,
            math.hypot(offset_x_ratio, offset_y_ratio) / math.sqrt(2),
        )
        deadzone = max(0.0, config.camera_mount.center_deadzone_ratio)

        pan_direction = self._axis_direction(offset_x_ratio, deadzone, negative="left", positive="right")
        tilt_direction = self._axis_direction(offset_y_ratio, deadzone, negative="up", positive="down")
        overall_direction = self._combine_direction(pan_direction, tilt_direction)
        status = "centered" if overall_direction == "centered" else "tracking"
        self._tracking_face_active = True

        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "status": status,
            "has_target": True,
            "tracking_label": "face",
            "should_home": False,
            "home_reason": None,
            "direction": overall_direction,
            "distance_ratio": round(distance_ratio, 3),
            "distance_px": round(distance_px, 1),
            "frame_center": {
                "x": round(frame_center_x, 1),
                "y": round(frame_center_y, 1),
            },
            "target_center": {
                "x": round(target_center_x, 1),
                "y": round(target_center_y, 1),
            },
            "pan": {
                "direction": pan_direction,
                "offset_ratio": round(abs(offset_x_ratio), 3),
                "offset_px": round(abs(offset_x_px), 1),
            },
            "tilt": {
                "direction": tilt_direction,
                "offset_ratio": round(abs(offset_y_ratio), 3),
                "offset_px": round(abs(offset_y_px), 1),
            },
            "updated_at": time.time(),
        }

    def _build_home_advice(
        self,
        *,
        started: bool,
        reason: str,
        frame_width: float,
        frame_height: float,
    ) -> dict:
        self._tracking_face_active = False
        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "status": "returning_home",
            "has_target": False,
            "tracking_label": None,
            "should_home": True,
            "home_reason": reason,
            "direction": "home",
            "distance_ratio": 0.0,
            "distance_px": 0.0,
            "frame_center": {
                "x": round(frame_width / 2, 1),
                "y": round(frame_height / 2, 1),
            },
            "target_center": None,
            "pan": {
                "direction": "home",
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "tilt": {
                "direction": "home",
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "updated_at": time.time(),
        }

    def _build_idle_advice(
        self,
        *,
        started: bool = False,
        status: str = "idle",
        frame_width: float | None = None,
        frame_height: float | None = None,
    ) -> dict:
        frame_center = None
        if frame_width and frame_height:
            frame_center = {
                "x": round(frame_width / 2, 1),
                "y": round(frame_height / 2, 1),
            }

        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "status": status,
            "has_target": False,
            "tracking_label": None,
            "should_home": False,
            "home_reason": None,
            "direction": "hold",
            "distance_ratio": 0.0,
            "distance_px": 0.0,
            "frame_center": frame_center,
            "target_center": None,
            "pan": {
                "direction": "hold",
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "tilt": {
                "direction": "hold",
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "updated_at": time.time(),
        }

    @staticmethod
    def _extract_frame_size(payload: dict) -> tuple[float | None, float | None]:
        frame_size = payload.get("frame_size")
        if not isinstance(frame_size, dict):
            return None, None

        try:
            return float(frame_size["width"]), float(frame_size["height"])
        except (KeyError, TypeError, ValueError):
            return None, None

    @staticmethod
    def _extract_face_target(payload: dict) -> dict | None:
        target = payload.get("target")
        if (
            isinstance(target, dict)
            and str(target.get("label", "")).lower() == "face"
            and "center_x" in target
            and "center_y" in target
        ):
            return target

        boxes = payload.get("boxes")
        if not isinstance(boxes, list):
            return None

        for box in boxes:
            if not isinstance(box, dict):
                continue
            if str(box.get("label", "")).lower() != "face":
                continue
            try:
                return {
                    "label": "face",
                    "center_x": (float(box["x1"]) + float(box["x2"])) / 2,
                    "center_y": (float(box["y1"]) + float(box["y2"])) / 2,
                }
            except (KeyError, TypeError, ValueError):
                continue

        return None

    @staticmethod
    def _axis_direction(value: float, deadzone: float, *, negative: str, positive: str) -> str:
        if value <= -deadzone:
            return negative
        if value >= deadzone:
            return positive
        return "hold"

    @staticmethod
    def _combine_direction(pan_direction: str, tilt_direction: str) -> str:
        if pan_direction == "hold" and tilt_direction == "hold":
            return "centered"
        if pan_direction == "hold":
            return tilt_direction
        if tilt_direction == "hold":
            return pan_direction
        return f"{tilt_direction}-{pan_direction}"
