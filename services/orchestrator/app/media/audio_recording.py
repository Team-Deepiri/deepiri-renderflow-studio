"""Audio recording service for voice input."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def check_microphone() -> dict[str, Any]:
    """Check if microphone input is available."""
    if os.name == "nt":
        result = shutil.which("powershell")
        if result:
            try:
                proc = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        "Get-WmiObject -Class Win32_SoundDevice | Select-Object -First 1 Name",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return {"ok": True, "available": True, "device": proc.stdout.strip()}
            except Exception:
                pass
        return {"ok": True, "available": False, "reason": "no audio device"}

    result = shutil.which("arecord")
    if result:
        return {"ok": True, "available": True, "tool": "arecord"}

    result = shutil.which("sox")
    if result:
        return {"ok": True, "available": True, "tool": "sox"}

    return {"ok": False, "available": False, "reason": "no recording tool found"}


def record_audio(
    output_path: str,
    duration_secs: int = 60,
    sample_rate: int = 48000,
    channels: int = 1,
) -> dict[str, Any]:
    """Record audio from microphone to file."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found on PATH"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        if os.name == "nt":
            cmd = [
                exe,
                "-y",
                "-f",
                "dshow",
                "-i",
                "audio=virtual-audio-capturer",
                "-t",
                str(duration_secs),
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-acodec",
                "pcm_s16le",
                output_path,
            ]
        else:
            cmd = [
                exe,
                "-y",
                "-f",
                "alsa",
                "-i",
                "default",
                "-t",
                str(duration_secs),
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-acodec",
                "pcm_s16le",
                output_path,
            ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration_secs + 10,
        )

        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or "recording failed")[:500],
            }

        return {"ok": True, "output": output_path, "duration": duration_secs}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "recording timeout"}
    except Exception as e:
        logger.warning("record_audio: %s", e)
        return {"ok": False, "error": str(e)}


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._stop_event = threading.Event()
        self._process: subprocess.Popen | None = None
        self._output_path: str = ""

    def start_recording(self, output_path: str) -> dict[str, Any]:
        if self._recording:
            return {"ok": False, "error": "already recording"}

        self._output_path = output_path
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        exe = shutil.which("ffmpeg")
        if not exe:
            return {"ok": False, "error": "ffmpeg not found"}

        cmd = [
            exe,
            "-y",
            "-f",
            "dshow" if os.name == "nt" else "alsa",
            "-i",
            "audio=virtual-audio-capturer" if os.name == "nt" else "default",
            "-ar",
            str(self.sample_rate),
            "-ac",
            str(self.channels),
            "-acodec",
            "pcm_s16le",
            output_path,
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._recording = True
            self._stop_event.clear()
            return {"ok": True, "recording": True}
        except Exception as e:
            logger.warning("start_recording: %s", e)
            return {"ok": False, "error": str(e)}

    def stop_recording(self) -> dict[str, Any]:
        if not self._recording or not self._process:
            return {"ok": False, "error": "not recording"}

        self._recording = False
        self._stop_event.set()

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

        if os.path.exists(self._output_path):
            size = os.path.getsize(self._output_path)
            return {
                "ok": True,
                "output": self._output_path,
                "size_bytes": size,
            }
        return {"ok": False, "error": "output file not found"}

    def is_recording(self) -> bool:
        return self._recording


_recorder_instance: AudioRecorder | None = None


def get_recorder(sample_rate: int = 48000) -> AudioRecorder:
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = AudioRecorder(sample_rate=sample_rate)
    return _recorder_instance