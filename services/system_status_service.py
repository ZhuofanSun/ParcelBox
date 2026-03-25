"""Lightweight runtime and host metrics for the local dashboard."""

from __future__ import annotations

import os
import platform
import socket
import threading
import time
from pathlib import Path


class SystemStatusService:
    """Collect low-overhead process and host metrics without extra dependencies."""

    def __init__(self) -> None:
        self._app_started_at = time.time()
        self._app_started_monotonic = time.monotonic()
        self._lock = threading.Lock()
        self._previous_cpu_sample = self._read_cpu_sample()

    def get_status(self) -> dict:
        """Return the current process uptime and best-effort host metrics."""
        with self._lock:
            current_cpu_sample = self._read_cpu_sample()
            cpu_usage_percent = self._calculate_cpu_usage_percent(
                self._previous_cpu_sample,
                current_cpu_sample,
            )
            if current_cpu_sample is not None:
                self._previous_cpu_sample = current_cpu_sample

        memory = self._read_memory_status()
        load_average = self._read_load_average()
        return {
            "hostname": socket.gethostname(),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_version": platform.python_version(),
            },
            "app_started_at": self._app_started_at,
            "app_uptime_seconds": max(0.0, time.monotonic() - self._app_started_monotonic),
            "system_uptime_seconds": self._read_system_uptime_seconds(),
            "cpu": {
                "usage_percent": cpu_usage_percent,
                "temperature_c": self._read_cpu_temperature_c(),
                "load_average": load_average,
            },
            "memory": memory,
        }

    @staticmethod
    def _read_text_file(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    @classmethod
    def _read_cpu_temperature_c(cls) -> float | None:
        raw_value = cls._read_text_file(Path("/sys/class/thermal/thermal_zone0/temp"))
        if raw_value is None:
            return None

        try:
            value = float(raw_value)
        except ValueError:
            return None

        if value > 1000:
            value /= 1000.0
        return round(value, 1)

    @classmethod
    def _read_system_uptime_seconds(cls) -> float | None:
        raw_value = cls._read_text_file(Path("/proc/uptime"))
        if raw_value is None:
            return None

        first_field = raw_value.split(maxsplit=1)[0]
        try:
            return float(first_field)
        except ValueError:
            return None

    @classmethod
    def _read_memory_status(cls) -> dict:
        raw_value = cls._read_text_file(Path("/proc/meminfo"))
        if raw_value is None:
            return {
                "total_mb": None,
                "available_mb": None,
                "used_mb": None,
                "used_percent": None,
            }

        values_kb: dict[str, int] = {}
        for line in raw_value.splitlines():
            if ":" not in line:
                continue
            key, remainder = line.split(":", 1)
            value_field = remainder.strip().split(maxsplit=1)[0]
            try:
                values_kb[key] = int(value_field)
            except ValueError:
                continue

        total_kb = values_kb.get("MemTotal")
        available_kb = values_kb.get("MemAvailable")
        if total_kb is None or available_kb is None or total_kb <= 0:
            return {
                "total_mb": None,
                "available_mb": None,
                "used_mb": None,
                "used_percent": None,
            }

        used_kb = max(total_kb - available_kb, 0)
        return {
            "total_mb": round(total_kb / 1024.0, 1),
            "available_mb": round(available_kb / 1024.0, 1),
            "used_mb": round(used_kb / 1024.0, 1),
            "used_percent": round((used_kb / total_kb) * 100.0, 1),
        }

    @staticmethod
    def _read_load_average() -> dict:
        try:
            load_1m, load_5m, load_15m = os.getloadavg()
        except (AttributeError, OSError):
            return {
                "one_min": None,
                "five_min": None,
                "fifteen_min": None,
            }

        return {
            "one_min": round(load_1m, 2),
            "five_min": round(load_5m, 2),
            "fifteen_min": round(load_15m, 2),
        }

    @classmethod
    def _read_cpu_sample(cls) -> tuple[int, int] | None:
        raw_value = cls._read_text_file(Path("/proc/stat"))
        if raw_value is None:
            return None

        first_line = raw_value.splitlines()[0].split()
        if len(first_line) < 8 or first_line[0] != "cpu":
            return None

        try:
            user, nice, system, idle, iowait, irq, softirq, steal = (
                int(first_line[1]),
                int(first_line[2]),
                int(first_line[3]),
                int(first_line[4]),
                int(first_line[5]),
                int(first_line[6]),
                int(first_line[7]),
                int(first_line[8]) if len(first_line) > 8 else 0,
            )
        except ValueError:
            return None

        idle_total = idle + iowait
        total = user + nice + system + idle + iowait + irq + softirq + steal
        return total, idle_total

    @staticmethod
    def _calculate_cpu_usage_percent(
        previous_sample: tuple[int, int] | None,
        current_sample: tuple[int, int] | None,
    ) -> float | None:
        if previous_sample is None or current_sample is None:
            return None

        previous_total, previous_idle = previous_sample
        current_total, current_idle = current_sample
        total_delta = current_total - previous_total
        idle_delta = current_idle - previous_idle
        if total_delta <= 0:
            return None

        usage = max(0.0, min(100.0, (1.0 - (idle_delta / total_delta)) * 100.0))
        return round(usage, 1)
