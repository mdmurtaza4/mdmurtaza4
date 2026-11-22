# ELiXIR AI Video Studio - working rules for Claude Code

Local-first Windows desktop tool for The ELiXIR School: turns a raw speech or event video into a
captioned, audio-enhanced, branded 1080p MP4. Target machine: Intel Core i7, 16 GB RAM, NVIDIA RTX
(exact model to be confirmed with `scripts/check-hardware.ps1`), SSD.

## Layout
- `backend/elixir_studio/` - Python 3.11 engine (FFmpeg, faster-whisper, FastAPI on 127.0.0.1)
  - `hardware.py` detection + model/encoder choice · `media.py` probe/proxy · `transcribe.py` Whisper
  - `silence.py` pause cuts · `edl.py` Edit Decision List · `captions.py` ASS/SRT · `brand.py` wordmark
  - `render.py` FFmpeg graph + encoder fallback · `qa.py` output checks · `pipeline.py` orchestration
  - `jobs.py` single-worker queue · `api.py` HTTP API · `__main__.py` CLI
- `frontend/` - Electron + React + TypeScript (milestone 2; not started)
- `scripts/` - Windows setup and hardware check

## Commands (from `backend/`)
- Tests: `python -m pytest -q` (end-to-end tests need `espeak-ng`; `ELIXIR_TEST_MODEL=small` for the real model)
- Lint: `ruff check .`
- Hardware: `python -m elixir_studio detect`
- Process: `python -m elixir_studio process speech.mp4 --preset vertical --preset landscape`
- API: `python -m elixir_studio serve`

## Non-negotiables
1. Never modify, overwrite or re-encode-in-place source footage. Renders go to a temp name, then rename.
2. Never regenerate, reshape, beautify or retouch faces. Only global, whole-frame colour adjustments.
3. One heavy job at a time (the `JobQueue`). Hold at most one Whisper model in memory.
4. Prove an encoder by a test encode; a name in `ffmpeg -encoders` is not proof. Always keep the libx264 fallback.
5. Every FFmpeg input must be finite (bound looped stills with `-t`); every render has a timeout.
6. The EDL is the source of truth. AI writes it; people can correct it; the renderer only executes it.
7. Captions are not "publish-ready" until a person has reviewed the transcript (`transcript_reviewed`).
   Whisper has no Kashmiri support and is weak on student names and Urdu script.
8. Do not install additional heavyweight models without checking free VRAM and RAM first.
9. Student footage and transcripts never leave the machine; never commit media, `projects/` or `studio.db`.
10. Brand: always write "The ELiXIR School" exactly. Supply the official logo via `BrandingSettings.logo_path`;
    the generated wordmark is a fallback only.

## Known dependency traps
- faster-whisper 1.2.x + PyAV >= 17: its internal decoder breaks. We decode the WAV ourselves (`load_wav_16k`).
- GPU Whisper on Windows needs CUDA 12 cuBLAS + cuDNN 9 DLLs on PATH; otherwise it falls back to CPU.
- `-filter_complex_script` is deprecated in newer FFmpeg; it is only used for very long edits.
