"""Hardware inspection and capability-based configuration.

Encoders are verified by a real test encode. A build listing ``h264_nvenc`` in
``ffmpeg -encoders`` proves only that support was compiled in, not that the GPU,
driver and session limits allow it.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import psutil

from .tools import ToolError, ffmpeg_bin, run

log = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    name: str
    vram_total_mb: int
    vram_free_mb: int
    driver: str
    cuda_version: str | None = None


@dataclass
class WhisperPlan:
    model: str
    device: str
    compute_type: str
    reason: str


@dataclass
class HardwareReport:
    os: str
    cpu: str
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    gpus: list[GPUInfo] = field(default_factory=list)
    ffmpeg_version: str | None = None
    encoders_listed: list[str] = field(default_factory=list)
    encoders_working: list[str] = field(default_factory=list)
    cuda_for_whisper: bool = False
    whisper: WhisperPlan | None = None
    video_encoder: str = "libx264"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def query_gpus() -> tuple[list[GPUInfo], str | None]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return [], None
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
        header = subprocess.run([smi], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], None
    cuda = None
    for line in header.splitlines():
        if "CUDA Version" in line:
            cuda = line.split("CUDA Version:")[-1].strip(" |")
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                gpus.append(GPUInfo(parts[0], int(float(parts[1])), int(float(parts[2])), parts[3], cuda))
            except ValueError:
                continue
    return gpus, cuda


def encoder_works(encoder: str) -> bool:
    """Prove an encoder works with a tiny real encode (about 0.2 s of video)."""
    try:
        run(
            [
                ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=size=256x256:rate=30:duration=0.2", "-c:v", encoder, "-f", "null", "-",
            ],
            timeout=60,
        )
        return True
    except ToolError as exc:
        log.info("encoder %s unavailable: %s", encoder, str(exc).splitlines()[-1] if str(exc) else exc)
        return False


def cuda_available_for_ctranslate2() -> bool:
    try:
        import ctranslate2  # noqa: PLC0415

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # pragma: no cover - depends on local CUDA install
        return False


def plan_whisper(vram_free_mb: int | None, cuda_ok: bool, ram_available_gb: float) -> WhisperPlan:
    """Pick a conservative faster-whisper configuration.

    Thresholds use *free* VRAM with headroom, because NVENC, the desktop compositor
    and the browser all share the card. These are starting points to benchmark,
    not guarantees.
    """
    if not cuda_ok or not vram_free_mb:
        model = "small" if ram_available_gb >= 4 else "base"
        return WhisperPlan(model, "cpu", "int8", "No usable CUDA runtime for CTranslate2; CPU int8 is reliable but slower.")
    if vram_free_mb >= 7000:
        return WhisperPlan("large-v3-turbo", "cuda", "int8_float16", f"{vram_free_mb} MB free VRAM; benchmark Turbo against Small on real school footage.")
    if vram_free_mb >= 4500:
        return WhisperPlan("medium", "cuda", "int8_float16", f"{vram_free_mb} MB free VRAM; Medium int8 fits with headroom.")
    if vram_free_mb >= 1800:
        return WhisperPlan("small", "cuda", "int8_float16", f"{vram_free_mb} MB free VRAM; Small int8 is the safe default.")
    return WhisperPlan("small", "cpu", "int8", f"Only {vram_free_mb} MB free VRAM; running on CPU to avoid out-of-memory failures.")


@lru_cache(maxsize=1)
def detect(test_encoders: bool = True) -> HardwareReport:
    vm = psutil.virtual_memory()
    report = HardwareReport(
        os=f"{platform.system()} {platform.release()}",
        cpu=platform.processor() or platform.machine(),
        cpu_threads=os.cpu_count() or 1,
        ram_total_gb=round(vm.total / 1024**3, 1),
        ram_available_gb=round(vm.available / 1024**3, 1),
    )
    report.gpus, _ = query_gpus()

    try:
        ver = run([ffmpeg_bin(), "-hide_banner", "-version"]).stdout.splitlines()[0]
        report.ffmpeg_version = ver
        listed = run([ffmpeg_bin(), "-hide_banner", "-encoders"]).stdout
        report.encoders_listed = [e for e in ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "libx264") if f" {e} " in listed]
    except ToolError as exc:
        report.warnings.append(str(exc))
        return report

    if test_encoders:
        report.encoders_working = [e for e in report.encoders_listed if encoder_works(e)]
    if "h264_nvenc" in report.encoders_working:
        report.video_encoder = "h264_nvenc"
    elif "h264_nvenc" in report.encoders_listed:
        report.warnings.append("h264_nvenc is compiled into FFmpeg but a test encode failed; using CPU (libx264).")
    if "libx264" not in report.encoders_working and test_encoders:
        report.warnings.append("libx264 not available: install a full (GPL) FFmpeg build.")

    report.cuda_for_whisper = cuda_available_for_ctranslate2()
    free = max((g.vram_free_mb for g in report.gpus), default=None)
    report.whisper = plan_whisper(free, report.cuda_for_whisper, report.ram_available_gb)

    if report.ram_total_gb < 15:
        report.warnings.append("Under 16 GB RAM: keep projects short and close other applications while rendering.")
    if report.gpus and not report.cuda_for_whisper:
        report.warnings.append(
            "NVIDIA GPU present but CTranslate2 cannot use CUDA. Install the CUDA 12 cuBLAS + cuDNN 9 "
            "libraries described in the faster-whisper README to enable GPU transcription."
        )
    return report
