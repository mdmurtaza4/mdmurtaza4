# Review of the hardware-specific implementation plan

The plan is sound in its fundamentals: local-first, sequential processing, an editable EDL, NVENC with
CPU fallback, and Whisper Small as the default model. Building the first milestone surfaced the
following corrections. Items marked **verified** were reproduced in this repository's test environment.

## Corrections

| # | Plan says | Issue | Change made |
|---|-----------|-------|-------------|
| 1 | Check NVENC with `ffmpeg -encoders \| findstr nvenc` | **Verified:** the test machine lists `h264_nvenc` but every NVENC encode fails (no GPU). The list shows what FFmpeg was compiled with, not what works. | `hardware.py` and `check-hardware.ps1` run a 0.2 s test encode per encoder. |
| 2 | Read VRAM from dxdiag "Display Memory" | That figure includes shared system RAM, so a 4 GB card can show 10+ GB. | Use `nvidia-smi` (dedicated and *free* VRAM), which the model choice now uses. |
| 3 | `pip install faster-whisper` then use it | **Verified:** faster-whisper 1.2.1 with PyAV 19 fails (`metadata_errors` error) on every file. | Audio is decoded by FFmpeg to WAV and passed to Whisper as samples; PyAV is bypassed. |
| 4 | "Whisper may not transcribe Kashmiri reliably" | Stronger than that: Whisper has no Kashmiri language at all. Kashmiri speech will come out as Urdu/Hindi text or a loose translation. | Transcript review is a first-class step; QA flags unreviewed transcripts. |
| 5 | SQLite in both Python and Electron (`better-sqlite3`) | Two owners of one database invites corruption; `better-sqlite3` is a native module that must be rebuilt for each Electron version on Windows. | Python owns SQLite; the UI talks only to the local API. Drop `better-sqlite3`. |
| 6 | Remotion for motion graphics | Remotion requires a paid company licence for organisations above a small headcount (check current terms), and adds a headless-Chrome render step that competes for the 16 GB. | Milestone 1 uses libass captions + FFmpeg overlays. Revisit only if animated intros justify the cost. |
| 7 | Not mentioned | **Verified:** a looped logo image is an infinite FFmpeg input; the render buffered it until RAM passed 2 GB and never finished. | Still images are bounded with `-t`; every render has a watchdog timeout. |
| 8 | Not mentioned | Phone footage is usually variable frame rate, which causes audio drift after cuts. | Renders normalise to a constant 30 fps; QA checks A/V drift (5 ms on test output). |
| 9 | Silence removal from AI | Whisper word timestamps can drift by a few hundred ms, so cutting on transcript gaps clips words. | Cuts come from audio energy (`silencedetect`), then are shrunk so no transcribed word is clipped; 150 ms padding and 12 ms audio fades at every cut. |

## Strategic recommendation: build a pipeline, not a full timeline editor

DaVinci Resolve (free) and CapCut already provide general-purpose timelines that a school cannot
out-build. What they do not provide is a **one-step, brand-consistent workflow** that a teacher with no
editing skill can run: import, review transcript, approve, export three formats. That is where this
tool earns its place.

Recommended scope for the desktop UI (milestone 2), in priority order:
1. Import + progress view (driven by `/jobs`).
2. Transcript review screen: low-confidence words highlighted, student names correctable.
3. Simple cut review: list of removed pauses with "restore" buttons (not a free-form timeline).
4. Export panel: 9:16 / 16:9 / 1:1 with QA results.

A full multitrack timeline should wait until real usage proves it is needed.

## Safeguarding (not in the plan)

Videos of students are personal data of children. Under India's DPDP Act 2023, processing children's
data requires verifiable parental consent. Keeping processing local helps, but the school should also
maintain a media-consent register and check it before anything is published. This is a policy matter
for the school, not something software can settle; I recommend legal confirmation of current rules.

## Still unknown
- Exact RTX model and free VRAM - run `scripts\check-hardware.ps1` and share the output.
- Whether GPU Whisper works on the machine (depends on the CUDA 12 / cuDNN 9 DLLs).
- Real-footage quality: noise reduction and pause thresholds are tuned on synthetic speech only.
