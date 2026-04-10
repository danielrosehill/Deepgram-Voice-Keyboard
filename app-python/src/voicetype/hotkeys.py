"""Global hotkey listener using evdev.

Monitors keyboard devices for configured hotkeys and emits Qt signals.
Supports toggle mode (press to start/stop) and push-to-talk mode
(hold to record, release to stop).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from evdev import InputDevice, ecodes, list_devices
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# Map config key names to evdev key codes
_KEY_NAME_MAP: dict[str, int] = {}


def _build_key_map() -> dict[str, int]:
    m: dict[str, int] = {}
    # Function keys F1-F24
    for i in range(1, 25):
        name = f"F{i}"
        code = getattr(ecodes, f"KEY_F{i}", None)
        if code is not None:
            m[name] = code
            m[name.lower()] = code

    # Common modifier combos aren't real evdev keys — we only support
    # single physical keys for now. Add more as needed.
    for name in dir(ecodes):
        if name.startswith("KEY_"):
            short = name[4:]
            code = getattr(ecodes, name)
            if isinstance(code, int):
                m[short] = code
                m[short.lower()] = code
    return m


_KEY_NAME_MAP = _build_key_map()


def resolve_key(name: str) -> Optional[int]:
    """Resolve a key name like 'F13' to an evdev keycode."""
    if not name:
        return None
    return _KEY_NAME_MAP.get(name) or _KEY_NAME_MAP.get(name.upper())


class HotkeySignals(QObject):
    """Signals emitted by the hotkey listener."""
    toggle = pyqtSignal()          # default hotkey pressed (toggle mode)
    start = pyqtSignal()           # dedicated start key pressed
    stop = pyqtSignal()            # dedicated stop key pressed
    pause = pyqtSignal()           # dedicated pause key pressed
    ptt_pressed = pyqtSignal()     # push-to-talk key pressed down
    ptt_released = pyqtSignal()    # push-to-talk key released


class HotkeyListener:
    """Listens for global hotkeys via evdev in a background thread."""

    def __init__(self) -> None:
        self.signals = HotkeySignals()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Configured keycodes (set before calling start())
        self._toggle_key: Optional[int] = None
        self._start_key: Optional[int] = None
        self._stop_key: Optional[int] = None
        self._pause_key: Optional[int] = None
        self._ptt_key: Optional[int] = None
        self._ptt_mode = False

    def configure(
        self,
        toggle_key: str = "",
        start_key: str = "",
        stop_key: str = "",
        pause_key: str = "",
        ptt_key: str = "",
        ptt_mode: bool = False,
    ) -> None:
        """Set which keys to listen for."""
        self._toggle_key = resolve_key(toggle_key)
        self._start_key = resolve_key(start_key)
        self._stop_key = resolve_key(stop_key)
        self._pause_key = resolve_key(pause_key)
        self._ptt_key = resolve_key(ptt_key)
        self._ptt_mode = ptt_mode

        keys = {
            "toggle": (toggle_key, self._toggle_key),
            "start": (start_key, self._start_key),
            "stop": (stop_key, self._stop_key),
            "pause": (pause_key, self._pause_key),
            "ptt": (ptt_key, self._ptt_key),
        }
        active = {k: v[0] for k, v in keys.items() if v[1] is not None}
        log.info("Hotkey config: %s, ptt_mode=%s", active, ptt_mode)

    def start(self) -> None:
        """Start the listener thread."""
        if self._thread is not None:
            return

        # Check if any keys are configured
        any_key = any([
            self._toggle_key, self._start_key, self._stop_key,
            self._pause_key, self._ptt_key,
        ])
        if not any_key:
            log.info("No hotkeys configured — listener not started")
            return

        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the listener thread."""
        self._running = False
        # Thread will exit on its own since it checks _running

    def _find_keyboard_devices(self) -> list[InputDevice]:
        """Find input devices that look like keyboards."""
        devices = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
                caps = dev.capabilities()
                if ecodes.EV_KEY in caps:
                    key_caps = caps[ecodes.EV_KEY]
                    # Must have typical keyboard keys
                    if ecodes.KEY_A in key_caps and ecodes.KEY_ENTER in key_caps:
                        devices.append(dev)
                        log.debug("Found keyboard: %s (%s)", dev.name, dev.path)
            except (PermissionError, OSError) as e:
                log.debug("Cannot open %s: %s", path, e)
        return devices

    def _listen(self) -> None:
        """Main listener loop — reads events from all keyboard devices."""
        import select

        devices = self._find_keyboard_devices()
        if not devices:
            log.warning("No keyboard devices found for hotkey listening")
            return

        log.info("Hotkey listener started on %d device(s)", len(devices))
        fd_map = {dev.fd: dev for dev in devices}

        while self._running:
            try:
                r, _, _ = select.select(list(fd_map.keys()), [], [], 0.5)
            except (ValueError, OSError):
                break

            for fd in r:
                dev = fd_map.get(fd)
                if dev is None:
                    continue
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        self._handle_key_event(event.code, event.value)
                except (OSError, IOError):
                    log.debug("Device disconnected: %s", dev.name)
                    del fd_map[fd]

        for dev in fd_map.values():
            try:
                dev.close()
            except Exception:
                pass

        log.info("Hotkey listener stopped")

    def _handle_key_event(self, code: int, value: int) -> None:
        """Handle a key press/release event.

        value: 0=released, 1=pressed, 2=repeat (ignored)
        """
        if value == 2:  # key repeat — ignore
            return

        pressed = value == 1

        # Push-to-talk mode
        if self._ptt_mode and code == self._ptt_key:
            if pressed:
                self.signals.ptt_pressed.emit()
            else:
                self.signals.ptt_released.emit()
            return

        # Only act on key press (not release) for toggle/start/stop/pause
        if not pressed:
            return

        if code == self._toggle_key:
            self.signals.toggle.emit()
        elif code == self._start_key:
            self.signals.start.emit()
        elif code == self._stop_key:
            self.signals.stop.emit()
        elif code == self._pause_key:
            self.signals.pause.emit()
