"""Audio feedback sounds for VoiceType.

Generates short distinctive pip sounds programmatically — no external
sound files needed. Uses sounddevice (already a dependency) for playback.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

# Output sample rate for feedback sounds
_RATE = 44100


def _generate_tone(freq: float, duration: float, fade_ms: float = 10.0) -> np.ndarray:
    """Generate a sine tone with fade-in/out to avoid clicks."""
    t = np.linspace(0, duration, int(_RATE * duration), endpoint=False, dtype=np.float32)
    tone = 0.4 * np.sin(2 * np.pi * freq * t)

    # Apply fade envelope
    fade_samples = int(_RATE * fade_ms / 1000)
    if fade_samples > 0 and len(tone) > 2 * fade_samples:
        fade_in = np.linspace(0, 1, fade_samples, dtype=np.float32)
        fade_out = np.linspace(1, 0, fade_samples, dtype=np.float32)
        tone[:fade_samples] *= fade_in
        tone[-fade_samples:] *= fade_out

    return tone


# Pre-generate sounds at import time
# Start: ascending two-note pip (C5 → E5), bright and quick
_start_sound = np.concatenate([
    _generate_tone(523.25, 0.08),   # C5
    np.zeros(int(_RATE * 0.02), dtype=np.float32),  # tiny gap
    _generate_tone(659.25, 0.10),   # E5
])

# Stop: descending two-note pip (E5 → C5), signals completion
_stop_sound = np.concatenate([
    _generate_tone(659.25, 0.08),   # E5
    np.zeros(int(_RATE * 0.02), dtype=np.float32),
    _generate_tone(523.25, 0.10),   # C5
])

# Pause: single mid-tone blip
_pause_sound = _generate_tone(440.0, 0.12)  # A4

# Resume: single higher blip
_resume_sound = _generate_tone(587.33, 0.12)  # D5


def _play_async(sound: np.ndarray) -> None:
    """Play a sound without blocking the caller."""
    def _worker() -> None:
        try:
            sd.play(sound, samplerate=_RATE, blocking=True)
        except Exception as e:
            log.debug("Sound playback failed: %s", e)

    threading.Thread(target=_worker, daemon=True).start()


def play_start() -> None:
    """Play the 'recording started' sound."""
    _play_async(_start_sound)


def play_stop() -> None:
    """Play the 'recording stopped' sound."""
    _play_async(_stop_sound)


def play_pause() -> None:
    """Play the 'paused' sound."""
    _play_async(_pause_sound)


def play_resume() -> None:
    """Play the 'resumed' sound."""
    _play_async(_resume_sound)
