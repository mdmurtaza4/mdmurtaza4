# ELiXIR AI Video Studio

A local-first video tool for The ELiXIR School. It turns a raw student speech or school event video
into a captioned, audio-enhanced, branded 1080p MP4 in vertical, landscape and square formats.

## Status

| Milestone | Scope | State |
|-----------|-------|-------|
| 1. Processing engine | Hardware detection, transcription, pause removal, captions, audio enhancement, branding, rendering, QA, local API | Working and tested (19 tests) |
| 2. Desktop app | Electron + React: import, transcript review, cut review, export | Not started |
| 3. Visual intelligence | Scene detection, subject-aware 9:16 reframing | Not started |

Milestone 1 has been tested on a synthetic speech video in a Linux environment without a GPU. It has
**not yet run on the target Windows machine or on real school footage**.

## Quick start (Windows)

1. Make sure the NVIDIA driver is up to date.
2. Download `scripts/install.ps1` and run: `powershell -ExecutionPolicy Bypass -File install.ps1`
   It installs Python 3.11, Git and FFmpeg via winget, downloads the project to `C:\ELiXIR-Video-Studio`,
   sets up the engine, prints a hardware report and runs the tests. It is safe to run again.
3. Optional detailed check: `powershell -ExecutionPolicy Bypass -File scripts\check-hardware.ps1`
4. Process a video:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m elixir_studio process C:\Videos\speech.mp4 --preset vertical --preset landscape
```

Output appears in `backend\projects\<video name>\output\` with an `.srt` caption file and a QA report.
To correct the transcript, edit `transcript.json` in the project folder, delete `project.json`, and
run the command again; the saved transcript is reused rather than re-transcribed.

## What happens to a video

1. **Inspect** with FFprobe (resolution, frame rate, variable-frame-rate detection). The source is only read.
2. **Transcribe** with faster-whisper (model chosen from free VRAM; GPU first, CPU fallback).
3. **Find pauses** from audio energy; never cut through a transcribed word.
4. **Write the EDL** (`project.json`): segments, words, audio, colour, caption, branding and export settings.
5. **Render** with FFmpeg: cuts with click-free fades, 30 fps normalisation, blurred-background framing,
   word-highlighted captions, voice enhancement to -14 LUFS, logo overlay. NVENC when proven, else libx264.
6. **QA**: codec, resolution, duration, A/V sync, loudness and transcript-review status.

See `docs/PLAN-REVIEW.md` for design decisions and corrections to the original plan, and `CLAUDE.md`
for engineering rules.
