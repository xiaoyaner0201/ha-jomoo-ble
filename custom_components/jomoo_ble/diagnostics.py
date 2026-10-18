"""Diagnostics with the Bluetooth address redacted."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

TO_REDACT = {"address", "unique_id", "title"}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    frames = {}
    if snapshot is not None:
        frames = {
            f"0x{command:02X}": frame.payload.hex() for command, frame in snapshot.frames.items()
        }
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options), "title": entry.title},
            TO_REDACT,
        ),
        "controls_enabled": coordinator.controls_enabled,
        "experimental_enabled": coordinator.experimental_enabled,
        "session_blocked": coordinator.session.blocked,
        "status_stream": {
            "enabled": coordinator.stream_enabled,
            "connected": coordinator.session.stream_connected,
            "error": coordinator.stream_error,
            "last_received": coordinator.last_received.isoformat()
            if coordinator.last_received
            else None,
            "frame_received_at": {
                f"0x{command:02X}": value.isoformat()
                for command, value in (snapshot.received_at.items() if snapshot else [])
            },
        },
        "last_refresh": coordinator.last_refresh.isoformat() if coordinator.last_refresh else None,
        "last_warning": coordinator.last_warning,
        "frames": frames,
    }
