"""Speech-to-text with faster-whisper, GPU first with automatic CPU fallback.

Only one model is held in memory at a time (16 GB RAM budget).
"""

from __future__ import annotations

import gc
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from .edl import Word

log = logging.getLogger(__name__)

# Whisper has no Kashmiri language token. Kashmiri speech is usually transcribed
# as Urdu or Hindi and must be corrected by hand before captions are published.
UNSUPPORTED_NOTE = {"ks": "Kashmiri is not a Whisper language; review the transcript manually."}


@dataclass
class Transcript:
    language: str
    language_probability: float
    words: list[Word]
    device: str
    model: str

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "device": self.device,
            "model": self.model,
            "words": [w.model_dump() for w in self.words],
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Transcript:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["language"], d.get("language_probability", 1.0), [Word(**w) for w in d["words"]], d.get("device", "?"), d.get("model", "?"))


class _ModelCache:
    """Holds at most one loaded model; loading another releases the previous one."""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._model = None
        self._lock = threading.Lock()

    def get(self, model: str, device: str, compute_type: str, download_root: str | None):
        from faster_whisper import WhisperModel  # noqa: PLC0415 - heavy import, load lazily

        key = (model, device, compute_type)
        with self._lock:
            if self._key != key:
                self.release()
                log.info("loading whisper %s on %s (%s)", model, device, compute_type)
                self._model = WhisperModel(model, device=device, compute_type=compute_type, download_root=download_root)
                self._key = key
            return self._model

    def release(self) -> None:
        self._model = None
        self._key = None
        gc.collect()


MODELS = _ModelCache()


def load_wav_16k(path: str | Path):
    """Read the 16 kHz mono PCM WAV produced by media.extract_audio.

    Decoding here (instead of inside faster-whisper) avoids its PyAV dependency,
    whose API changes have broken faster-whisper's own decoder (PyAV >= 17).
    """
    import wave  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    with wave.open(str(path), "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("expected 16 kHz mono 16-bit WAV; create it with media.extract_audio")
        data = wf.readframes(wf.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(
    audio_path: str | Path,
    model: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
    download_root: str | None = None,
    initial_prompt: str | None = "The ELiXIR School.",
) -> Transcript:
    attempts: list[tuple[str, str]] = []
    if device in ("auto", "cuda"):
        attempts.append(("cuda", "int8_float16" if compute_type == "int8" else compute_type))
    if device in ("auto", "cpu"):
        attempts.append(("cpu", "int8"))

    audio = load_wav_16k(audio_path)
    last_err: Exception | None = None
    for dev, ctype in attempts:
        try:
            m = MODELS.get(model, dev, ctype, download_root)
            segments, info = m.transcribe(
                audio,
                language=language,
                word_timestamps=True,
                vad_filter=True,
                beam_size=5,
                initial_prompt=initial_prompt,
            )
            words = [
                Word(text=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3), probability=round(w.probability, 3))
                for seg in segments
                for w in (seg.words or [])
                if w.word.strip()
            ]
            return Transcript(info.language, round(info.language_probability, 3), words, dev, model)
        except Exception as exc:  # CUDA DLL missing, out of memory, etc.
            log.warning("transcription on %s failed (%s); trying next option", dev, exc)
            last_err = exc
            MODELS.release()
    raise RuntimeError(f"Transcription failed on every device: {last_err}")


def low_confidence(words: list[Word], threshold: float = 0.5) -> list[Word]:
    """Words a teacher should check before publishing captions."""
    return [w for w in words if w.probability < threshold]
