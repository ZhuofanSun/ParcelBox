"""Camera mount control service."""

from __future__ import annotations

import copy
import math
import threading
import time
from typing import TYPE_CHECKING

from config import config
from drivers.servo import Servo

if TYPE_CHECKING:
    from services.vision_service import VisionService


class CameraMountService:
    """Track face detections with two servos and expose current advice."""

    def __init__(
        self,
        vision_service: VisionService | None = None,
        servo_factory=Servo,
    ) -> None:
        self._vision_service = vision_service
        self._servo_factory = servo_factory
        self._lock = threading.Lock()
        self._move_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._started = False
        self._home_pending_reason: str | None = None
        self._tracking_face_active = False
        self._face_lost_deadline_at: float | None = None
        self._face_recovery_waypoints: list[float] = []
        self._standby_anchor_at: float | None = None
        self._last_seen_version = 0
        self._last_tracking_move_at = 0.0
        self._last_tracking_move_version: int | None = None
        self._last_home_issue_at = 0.0
        self._pan_servo = None
        self._tilt_servo = None
        self._pan_angle: float | None = None
        self._tilt_angle: float | None = None
        self._servo_control_enabled = False
        self._last_error: str | None = None
        self._latest_advice = self._build_idle_advice()

    def start(self) -> None:
        """Start the mount-control worker and initialize the servos."""
        with self._lock:
            if self._started:
                return

            self._stop_event.clear()
            self._started = True
            self._home_pending_reason = "startup"
            self._tracking_face_active = False
            self._face_lost_deadline_at = None
            self._face_recovery_waypoints = []
            self._standby_anchor_at = None
            self._last_seen_version = 0
            self._last_tracking_move_at = 0.0
            self._last_tracking_move_version = None
            self._last_home_issue_at = 0.0
            self._latest_advice = self._build_idle_advice(started=True)
            self._last_error = None
            self._initialize_servos_locked()

            if self._vision_service is None:
                return

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="camera-mount-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop the mount-control worker and release servo resources."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._lock:
            self._cleanup_servos_locked()
            self._started = False
            self._home_pending_reason = None
            self._tracking_face_active = False
            self._face_lost_deadline_at = None
            self._face_recovery_waypoints = []
            self._standby_anchor_at = None
            self._latest_advice = self._build_idle_advice()
            self._last_seen_version = 0
            self._last_tracking_move_at = 0.0
            self._last_tracking_move_version = None
            self._last_home_issue_at = 0.0

    def move_home(self) -> None:
        """Move both servos back to the configured home angles."""
        self._execute_movement_request(
            {
                "kind": "home",
                "pan_target": config.camera_mount.pan_home_angle,
                "tilt_target": config.camera_mount.tilt_home_angle,
                "step": self._home_step(),
                "delay": self._home_delay(),
                "version": None,
            }
        )

    def move_to_angles(
        self,
        *,
        pan_angle: float | None = None,
        tilt_angle: float | None = None,
    ) -> None:
        """Move one or both servos to explicit angles."""
        with self._lock:
            pan_target = None
            tilt_target = None
            if pan_angle is not None:
                pan_target = self._clamp(
                    pan_angle,
                    config.camera_mount.pan_min_angle,
                    config.camera_mount.pan_max_angle,
                )

            if tilt_angle is not None:
                tilt_target = self._clamp(
                    tilt_angle,
                    config.camera_mount.tilt_min_angle,
                    config.camera_mount.tilt_max_angle,
                )

        self._execute_movement_request(
            {
                "kind": "manual",
                "pan_target": pan_target,
                "tilt_target": tilt_target,
                "step": self._movement_step(),
                "delay": self._movement_delay(),
                "version": None,
            }
        )

    def enrich_payload(self, payload: dict) -> dict:
        """Attach the latest mount state to an outgoing vision payload."""
        with self._lock:
            advice = copy.deepcopy(self._latest_advice)

        enriched_payload = dict(payload)
        enriched_payload["camera_mount"] = advice
        return enriched_payload

    def get_status(self) -> dict:
        """Return service status and current servo state."""
        with self._lock:
            return {
                "started": self._started,
                "enabled": config.camera_mount.enabled,
                "servo_control_enabled": self._servo_control_enabled,
                "pins": {
                    "pan_servo_pin": config.gpio.camera_pan_servo_pin,
                    "tilt_servo_pin": config.gpio.camera_tilt_servo_pin,
                },
                "servo_backends": {
                    "pan": getattr(self._pan_servo, "backend_name", None) if self._pan_servo is not None else None,
                    "tilt": getattr(self._tilt_servo, "backend_name", None) if self._tilt_servo is not None else None,
                },
                "home_angles": {
                    "pan": config.camera_mount.pan_home_angle,
                    "tilt": config.camera_mount.tilt_home_angle,
                },
                "current_angles": {
                    "pan": round(self._pan_angle, 2) if self._pan_angle is not None else None,
                    "tilt": round(self._tilt_angle, 2) if self._tilt_angle is not None else None,
                },
                "direction_inversion": {
                    "pan": config.camera_mount.invert_pan_direction,
                    "tilt": config.camera_mount.invert_tilt_direction,
                },
                "last_error": self._last_error,
                "standby_anchor_at": self._standby_anchor_at,
                "latest_advice": copy.deepcopy(self._latest_advice),
            }

    def get_standby_anchor_timestamp(self) -> float | None:
        """Return the monotonic timestamp after which standby delay should count."""
        with self._lock:
            return self._standby_anchor_at

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload, version = self._vision_service.wait_for_latest_boxes(
                    self._last_seen_version,
                    0.5,
                )
            except TimeoutError:
                continue
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                self._stop_event.wait(0.1)
                continue

            self._last_seen_version = version
            self._process_payload(payload, version=version)

    def _process_payload(self, payload: dict, version: int | None = None) -> dict:
        with self._lock:
            advice = self._build_advice(payload, started=self._started)
            self._latest_advice = advice
            movement_request = self._build_movement_request_locked(advice, version=version)

        self._execute_movement_request(movement_request)
        return copy.deepcopy(advice)

    def _initialize_servos_locked(self) -> None:
        self._servo_control_enabled = False
        self._pan_angle = None
        self._tilt_angle = None

        if not config.camera_mount.enabled:
            self._last_error = "camera mount disabled in config"
            return

        pan_pin = config.gpio.camera_pan_servo_pin
        tilt_pin = config.gpio.camera_tilt_servo_pin
        if pan_pin is None or tilt_pin is None:
            self._last_error = "camera mount servo pins are not configured"
            return

        try:
            self._pan_servo = self._servo_factory(
                pan_pin,
                min_angle=config.camera_mount.pan_min_angle,
                max_angle=config.camera_mount.pan_max_angle,
            )
            self._tilt_servo = self._servo_factory(
                tilt_pin,
                min_angle=config.camera_mount.tilt_min_angle,
                max_angle=config.camera_mount.tilt_max_angle,
            )
            self._servo_control_enabled = True
            self._last_error = None
        except Exception as error:
            self._cleanup_servos_locked()
            self._last_error = str(error)

    def _cleanup_servos_locked(self) -> None:
        for servo in (self._pan_servo, self._tilt_servo):
            if servo is None:
                continue
            try:
                servo.cleanup()
            except Exception:
                pass

        self._pan_servo = None
        self._tilt_servo = None
        self._pan_angle = None
        self._tilt_angle = None
        self._servo_control_enabled = False

    def _build_movement_request_locked(self, advice: dict, *, version: int | None = None) -> dict | None:
        if not self._servo_control_enabled:
            return None

        if advice.get("should_home"):
            return {
                "kind": "home",
                "pan_target": config.camera_mount.pan_home_angle,
                "tilt_target": config.camera_mount.tilt_home_angle,
                "step": self._home_step(),
                "delay": self._home_delay(),
                "reason": advice.get("home_reason"),
                "version": None,
            }

        if advice.get("status") == "searching":
            search_step = self._current_face_recovery_step_locked()
            if search_step is None:
                return None
            return {
                "kind": "search",
                "pan_target": search_step["pan_target"],
                "tilt_target": search_step["tilt_target"],
                "step": self._home_step(),
                "delay": self._home_delay(),
                "reason": "face_search",
                "version": None,
            }

        if not advice.get("has_target"):
            return None

        if not self._can_apply_tracking_move_locked(version):
            return None

        pan_target = self._target_angle_for_axis(
            axis="pan",
            direction=advice["pan"]["direction"],
            move_angle=advice["pan"]["move_angle"],
        )
        tilt_target = self._target_angle_for_axis(
            axis="tilt",
            direction=advice["tilt"]["direction"],
            move_angle=advice["tilt"]["move_angle"],
        )

        return {
            "kind": "tracking",
            "pan_target": pan_target,
            "tilt_target": tilt_target,
            "step": self._movement_step(),
            "delay": self._movement_delay(),
            "reason": None,
            "version": version,
        }

    def _target_angle_for_axis(
        self,
        *,
        axis: str,
        direction: str,
        move_angle: float,
    ) -> float | None:
        if direction in {"hold", "home"}:
            return None

        if move_angle <= 0:
            return None

        current_angle = self._current_angle(axis)
        if current_angle is None:
            current_angle = self._home_angle(axis)

        if direction in {"left", "up"}:
            target_angle = current_angle - move_angle
        elif direction in {"right", "down"}:
            target_angle = current_angle + move_angle
        else:
            return None

        return self._clamp(
            target_angle,
            self._min_angle(axis),
            self._max_angle(axis),
        )

    def _execute_movement_request(self, request: dict | None) -> bool:
        if not request:
            return False

        with self._move_lock:
            with self._lock:
                if not self._servo_control_enabled:
                    return False
                request_kind = request.get("kind")
                request_reason = request.get("reason")
                axes = self._prepare_axes_locked(
                    pan_target=request.get("pan_target"),
                    tilt_target=request.get("tilt_target"),
                )
                if not axes:
                    if request_kind == "home" and request_reason == "face_lost":
                        self._standby_anchor_at = time.monotonic()
                    return False
                step = float(request.get("step", self._movement_step()))
                delay = float(request.get("delay", self._movement_delay()))
                interrupt_check = None
                if request_kind == "search":
                    interrupt_check = self._should_interrupt_search_move

            moved, error = self._move_axes_together(
                axes,
                step=step,
                delay=delay,
                interrupt_check=interrupt_check,
            )

            with self._lock:
                if error is not None:
                    self._last_error = str(error)
                    return False
                if not moved:
                    return False

                for axis_state in axes:
                    if axis_state["axis"] == "pan":
                        self._pan_angle = axis_state["target"]
                    else:
                        self._tilt_angle = axis_state["target"]

                if request_kind == "tracking":
                    self._last_tracking_move_at = time.monotonic()
                    self._last_tracking_move_version = request.get("version")
                    self._standby_anchor_at = None
                elif request_kind == "search":
                    self._standby_anchor_at = None
                elif request_kind == "home":
                    self._last_tracking_move_version = None
                    if request_reason == "face_lost":
                        self._standby_anchor_at = time.monotonic()
            return True

    def _prepare_axes_locked(
        self,
        *,
        pan_target: float | None = None,
        tilt_target: float | None = None,
    ) -> list[dict]:
        axes = []
        if pan_target is not None:
            axes.append({"axis": "pan", "servo": self._pan_servo, "target": pan_target, "current": self._pan_angle})
        if tilt_target is not None:
            axes.append({"axis": "tilt", "servo": self._tilt_servo, "target": tilt_target, "current": self._tilt_angle})

        axes = [
            axis_state
            for axis_state in axes
            if axis_state["servo"] is not None
            and (
                axis_state["current"] is None
                or abs(axis_state["target"] - axis_state["current"]) >= 0.01
            )
        ]
        return axes

    @staticmethod
    def _move_axes_together(
        axes: list[dict],
        *,
        step: float,
        delay: float,
        interrupt_check=None,
    ) -> tuple[bool, Exception | None]:
        if not axes:
            return False, None

        settle_time = max(delay, 0.3)
        try:
            if any(axis_state["current"] is None for axis_state in axes):
                for axis_state in axes:
                    axis_state["servo"].set_angle(axis_state["target"], 0, False)
                    axis_state["reached"] = axis_state["target"]
                time.sleep(settle_time)
            else:
                max_delta = max(abs(axis_state["target"] - axis_state["current"]) for axis_state in axes)
                total_steps = max(1, int(math.ceil(max_delta / step)))
                for index in range(1, total_steps + 1):
                    if interrupt_check is not None and interrupt_check():
                        break
                    progress = index / total_steps
                    for axis_state in axes:
                        interpolated_angle = axis_state["current"] + (
                            axis_state["target"] - axis_state["current"]
                        ) * progress
                        axis_state["servo"].set_angle(interpolated_angle, 0, False)
                        axis_state["reached"] = interpolated_angle
                    if delay > 0:
                        time.sleep(delay)

            for axis_state in axes:
                if "reached" not in axis_state:
                    axis_state["reached"] = axis_state["target"]
                axis_state["target"] = axis_state["reached"]
                axis_state["servo"].release()
        except Exception as error:
            return False, error
        return True, None

    def _should_interrupt_search_move(self) -> bool:
        if self._vision_service is None:
            return False

        try:
            payload = self._vision_service.get_boxes()
        except Exception:
            return False

        target = self._extract_face_target(payload)
        return payload.get("status") == "ok" and target is not None

    def _move_axis_to_locked(self, axis: str, target_angle: float) -> bool:
        servo = self._pan_servo if axis == "pan" else self._tilt_servo
        current_angle = self._current_angle(axis)
        if servo is None:
            return False
        if current_angle is not None and abs(target_angle - current_angle) < 0.01:
            return False

        try:
            servo.move_to(
                target_angle,
                step=self._movement_step(),
                delay=self._movement_delay(),
                release=True,
            )
        except Exception as error:
            self._last_error = str(error)
            return False

        if axis == "pan":
            self._pan_angle = target_angle
        else:
            self._tilt_angle = target_angle
        return True

    @staticmethod
    def _movement_step() -> float:
        return float(config.camera_mount.tracking_step)

    @staticmethod
    def _movement_delay() -> float:
        return float(config.camera_mount.tracking_delay)

    @staticmethod
    def _home_step() -> float:
        return max(config.camera_mount.home_step, 0.5)

    @staticmethod
    def _home_delay() -> float:
        return max(config.camera_mount.home_delay, 0.0)

    @staticmethod
    def _step_towards(current: float, target: float, max_step: float) -> float:
        max_step = max(max_step, 1e-6)
        delta = target - current
        if abs(delta) <= max_step:
            return target
        return current + math.copysign(max_step, delta)

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
            search_advice = self._build_face_recovery_advice_locked(
                started=started,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            if search_advice is not None:
                return search_advice
            if self._should_issue_no_face_home_locked():
                return self._build_home_advice(
                    started=started,
                    reason="no_face_idle",
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
        pan_abs_ratio = abs(offset_x_ratio)
        tilt_abs_ratio = abs(offset_y_ratio)
        distance_px = math.hypot(offset_x_px, offset_y_px)
        distance_ratio = min(
            1.0,
            math.hypot(offset_x_ratio, offset_y_ratio) / math.sqrt(2),
        )
        deadzone = max(0.0, config.camera_mount.center_deadzone_ratio)

        pan_direction = self._axis_direction(offset_x_ratio, deadzone, negative="left", positive="right")
        tilt_direction = self._axis_direction(offset_y_ratio, deadzone, negative="up", positive="down")
        pan_move_angle = self._move_angle_for_offset("pan", pan_abs_ratio, deadzone)
        tilt_move_angle = self._move_angle_for_offset("tilt", tilt_abs_ratio, deadzone)
        overall_direction = self._combine_direction(pan_direction, tilt_direction)
        status = "centered" if overall_direction == "centered" else "tracking"
        self._tracking_face_active = True
        self._face_lost_deadline_at = None
        self._face_recovery_waypoints = []
        self._standby_anchor_at = None

        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "servo_control_enabled": self._servo_control_enabled,
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
            "current_angles": {
                "pan": round(self._pan_angle, 2) if self._pan_angle is not None else None,
                "tilt": round(self._tilt_angle, 2) if self._tilt_angle is not None else None,
            },
            "pan": {
                "direction": pan_direction,
                "move_angle": round(pan_move_angle, 2),
                "offset_ratio": round(pan_abs_ratio, 3),
                "offset_px": round(abs(offset_x_px), 1),
            },
            "tilt": {
                "direction": tilt_direction,
                "move_angle": round(tilt_move_angle, 2),
                "offset_ratio": round(tilt_abs_ratio, 3),
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
        self._face_lost_deadline_at = None
        self._face_recovery_waypoints = []
        if reason == "startup":
            self._standby_anchor_at = None
        self._last_home_issue_at = time.monotonic()
        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "servo_control_enabled": self._servo_control_enabled,
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
            "current_angles": {
                "pan": round(self._pan_angle, 2) if self._pan_angle is not None else None,
                "tilt": round(self._tilt_angle, 2) if self._tilt_angle is not None else None,
            },
            "pan": {
                "direction": "home",
                "move_angle": 0.0,
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "tilt": {
                "direction": "home",
                "move_angle": 0.0,
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "updated_at": time.time(),
        }

    def _build_search_advice(
        self,
        *,
        started: bool,
        frame_width: float,
        frame_height: float,
        search_step: dict,
    ) -> dict:
        pan_direction = search_step["pan_direction"]
        tilt_direction = search_step["tilt_direction"]
        direction = self._combine_direction(pan_direction, tilt_direction)
        return {
            "started": started,
            "enabled": config.camera_mount.enabled,
            "servo_control_enabled": self._servo_control_enabled,
            "status": "searching",
            "has_target": False,
            "tracking_label": None,
            "should_home": False,
            "home_reason": None,
            "direction": direction,
            "distance_ratio": 0.0,
            "distance_px": 0.0,
            "frame_center": {
                "x": round(frame_width / 2, 1),
                "y": round(frame_height / 2, 1),
            },
            "target_center": None,
            "current_angles": {
                "pan": round(self._pan_angle, 2) if self._pan_angle is not None else None,
                "tilt": round(self._tilt_angle, 2) if self._tilt_angle is not None else None,
            },
            "pan": {
                "direction": pan_direction,
                "move_angle": round(search_step["pan_move_angle"], 2),
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "tilt": {
                "direction": tilt_direction,
                "move_angle": round(search_step["tilt_move_angle"], 2),
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
            "servo_control_enabled": self._servo_control_enabled,
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
            "current_angles": {
                "pan": round(self._pan_angle, 2) if self._pan_angle is not None else None,
                "tilt": round(self._tilt_angle, 2) if self._tilt_angle is not None else None,
            },
            "pan": {
                "direction": "hold",
                "move_angle": 0.0,
                "offset_ratio": 0.0,
                "offset_px": 0.0,
            },
            "tilt": {
                "direction": "hold",
                "move_angle": 0.0,
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

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _move_angle_for_offset(self, axis: str, offset_ratio: float, deadzone: float) -> float:
        if offset_ratio <= deadzone:
            return 0.0

        active_ratio = (offset_ratio - deadzone) / max(1.0 - deadzone, 1e-6)
        max_move = (
            config.camera_mount.pan_max_single_move_angle
            if axis == "pan"
            else config.camera_mount.tilt_max_single_move_angle
        )
        return self._clamp(active_ratio, 0.0, 1.0) * max(max_move, 0.0)

    def _can_apply_tracking_move_locked(self, version: int | None) -> bool:
        if version is not None and version == self._last_tracking_move_version:
            return False

        cooldown = max(config.camera_mount.tracking_cooldown_seconds, 0.0)
        if cooldown <= 0:
            return True
        if self._last_tracking_move_at <= 0:
            return True
        return (time.monotonic() - self._last_tracking_move_at) >= cooldown

    def _should_issue_no_face_home_locked(self) -> bool:
        interval = max(config.camera_mount.no_face_home_interval_seconds, 0.0)
        if interval <= 0:
            return False
        if (
            self._tracking_face_active
            or self._face_lost_deadline_at is not None
            or self._face_recovery_waypoints
        ):
            return False
        if self._last_home_issue_at <= 0:
            return True
        return (time.monotonic() - self._last_home_issue_at) >= interval

    def _build_face_recovery_advice_locked(
        self,
        *,
        started: bool,
        frame_width: float,
        frame_height: float,
    ) -> dict | None:
        if self._face_recovery_waypoints:
            search_step = self._current_face_recovery_step_locked()
            if search_step is None:
                self._clear_face_recovery_locked()
                return self._build_home_advice(
                    started=started,
                    reason="face_lost",
                    frame_width=frame_width,
                    frame_height=frame_height,
                )
            return self._build_search_advice(
                started=started,
                frame_width=frame_width,
                frame_height=frame_height,
                search_step=search_step,
            )

        if not self._is_face_lost_search_due_locked():
            return None

        self._start_face_recovery_locked()
        search_step = self._current_face_recovery_step_locked()
        if search_step is None:
            self._clear_face_recovery_locked()
            return self._build_home_advice(
                started=started,
                reason="face_lost",
                frame_width=frame_width,
                frame_height=frame_height,
            )
        return self._build_search_advice(
            started=started,
            frame_width=frame_width,
            frame_height=frame_height,
            search_step=search_step,
        )

    def _start_face_recovery_locked(self) -> None:
        current_pan = self._current_angle("pan")
        if current_pan is None:
            current_pan = self._home_angle("pan")

        if current_pan >= config.camera_mount.pan_home_angle:
            self._face_recovery_waypoints = [
                config.camera_mount.pan_max_angle,
                config.camera_mount.pan_min_angle,
            ]
        else:
            self._face_recovery_waypoints = [
                config.camera_mount.pan_min_angle,
                config.camera_mount.pan_max_angle,
            ]

        self._tracking_face_active = False
        self._face_lost_deadline_at = None

    def _clear_face_recovery_locked(self) -> None:
        self._face_recovery_waypoints = []
        self._face_lost_deadline_at = None

    def _current_face_recovery_step_locked(self) -> dict | None:
        current_pan = self._current_angle("pan")
        current_tilt = self._current_angle("tilt")
        if current_pan is None:
            current_pan = self._home_angle("pan")
        if current_tilt is None:
            current_tilt = self._home_angle("tilt")

        while self._face_recovery_waypoints and abs(current_pan - self._face_recovery_waypoints[0]) < 0.01:
            self._face_recovery_waypoints.pop(0)

        next_pan_waypoint = self._face_recovery_waypoints[0] if self._face_recovery_waypoints else None
        pan_target = None
        if next_pan_waypoint is not None:
            pan_target = next_pan_waypoint

        tilt_target = None
        tilt_home = config.camera_mount.tilt_home_angle
        if abs(current_tilt - tilt_home) >= 0.01:
            tilt_target = tilt_home

        if pan_target is None and tilt_target is None:
            return None

        pan_delta = 0.0 if pan_target is None else pan_target - current_pan
        tilt_delta = 0.0 if tilt_target is None else tilt_target - current_tilt
        pan_direction = "hold"
        tilt_direction = "hold"
        if pan_delta < -0.01:
            pan_direction = "left"
        elif pan_delta > 0.01:
            pan_direction = "right"
        if tilt_delta < -0.01:
            tilt_direction = "up"
        elif tilt_delta > 0.01:
            tilt_direction = "down"

        return {
            "pan_target": pan_target,
            "tilt_target": tilt_target,
            "pan_direction": pan_direction,
            "tilt_direction": tilt_direction,
            "pan_move_angle": abs(pan_delta),
            "tilt_move_angle": abs(tilt_delta),
        }

    def _is_face_lost_search_due_locked(self) -> bool:
        if not self._tracking_face_active and self._face_lost_deadline_at is None:
            return False

        if self._face_lost_deadline_at is None:
            delay = max(config.camera_mount.face_lost_home_delay_seconds, 0.0)
            if delay <= 0:
                self._tracking_face_active = False
                return True
            self._face_lost_deadline_at = time.monotonic() + delay
            return False

        if time.monotonic() < self._face_lost_deadline_at:
            return False

        self._tracking_face_active = False
        self._face_lost_deadline_at = None
        return True

    def _current_angle(self, axis: str) -> float | None:
        return self._pan_angle if axis == "pan" else self._tilt_angle

    @staticmethod
    def _home_angle(axis: str) -> float:
        return config.camera_mount.pan_home_angle if axis == "pan" else config.camera_mount.tilt_home_angle

    @staticmethod
    def _min_angle(axis: str) -> float:
        return config.camera_mount.pan_min_angle if axis == "pan" else config.camera_mount.tilt_min_angle

    @staticmethod
    def _max_angle(axis: str) -> float:
        return config.camera_mount.pan_max_angle if axis == "pan" else config.camera_mount.tilt_max_angle
