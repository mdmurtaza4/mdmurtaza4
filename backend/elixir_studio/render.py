"""FFmpeg rendering engine: executes an EDL into a finished, branded MP4.

The source file is opened read-only. Output is written to a temporary name and
renamed only after FFmpeg succeeds, so a failed render never leaves a broken file
that looks finished.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .brand import watermark_png
from .captions import PRESETS, write_captions
from .edl import EDL, remap_words
from .hardware import detect
from .tools import ToolError, ffmpeg_bin, run

log = logging.getLogger(__name__)
FADE = 0.012  # seconds of audio fade at every cut, to prevent clicks


@dataclass
class RenderResult:
    output: Path
    encoder: str
    captions_ass: Path | None
    captions_srt: Path | None
    command: list[str]


def video_args(encoder: str, quality: int) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(quality),
                "-b:v", "0", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality), "-profile:v", "high", "-pix_fmt", "yuv420p"]


def choose_encoder(requested: str) -> str:
    if requested == "x264":
        return "libx264"
    hw = detect()
    if requested == "nvenc" and hw.video_encoder != "h264_nvenc":
        log.warning("NVENC requested but not working on this machine; using libx264")
    return hw.video_encoder


def build_filtergraph(edl: EDL, has_captions: bool, has_logo: bool) -> str:
    out_w, out_h = PRESETS[edl.export.preset]["size"]
    fps = edl.export.fps
    parts: list[str] = []
    concat_inputs = ""
    for i, seg in enumerate(edl.segments):
        d = seg.duration
        parts.append(f"[0:v]trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS[v{i}]")
        fade_out = max(0.0, d - FADE)
        parts.append(
            f"[0:a]atrim=start={seg.start:.3f}:end={seg.end:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={FADE},afade=t=out:st={fade_out:.3f}:d={FADE}[a{i}]"
        )
        concat_inputs += f"[v{i}][a{i}]"
    n = len(edl.segments)
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vcat][acat]")

    # Normalise variable phone frame rates, then frame for the chosen aspect ratio.
    chain = f"[vcat]fps={fps},setsar=1"
    if edl.export.framing == "crop":
        parts.append(
            f"{chain},scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h}[vframed]"
        )
    else:
        parts.append(f"{chain},split[vbg_src][vfg_src]")
        parts.append(
            f"[vbg_src]scale={out_w // 4}:{out_h // 4}:force_original_aspect_ratio=increase,"
            f"crop={out_w // 4}:{out_h // 4},boxblur=10:2,eq=brightness=-0.08,scale={out_w}:{out_h}[vbg]"
        )
        parts.append(f"[vfg_src]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[vfg]")
        parts.append("[vbg][vfg]overlay=(W-w)/2:(H-h)/2[vframed]")

    last = "vframed"
    if edl.color.mode == "subtle":
        c = edl.color
        parts.append(f"[{last}]eq=contrast={c.contrast}:saturation={c.saturation}:brightness={c.brightness}[vcol]")
        last = "vcol"
    if has_captions:
        parts.append(f"[{last}]ass=captions.ass[vcap]")
        last = "vcap"
    if has_logo:
        margin = int(out_w * 0.04)
        parts.append(f"[1:v]format=rgba,colorchannelmixer=aa={edl.branding.opacity}[logo]")
        parts.append(f"[{last}][logo]overlay=W-w-{margin}:{margin}:format=auto:shortest=1[vlogo]")
        last = "vlogo"
    parts.append(f"[{last}]format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[vout]")

    a = edl.audio
    if a.enhance:
        parts.append(
            f"[acat]highpass=f={a.highpass_hz},afftdn=nf={a.denoise_floor_db},"
            f"equalizer=f=3000:t=q:w=1.2:g={a.presence_gain_db},"
            f"acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=2,"
            f"loudnorm=I={a.target_lufs}:TP={a.true_peak_db}:LRA=11,aresample=48000[aout]"
        )
    else:
        parts.append("[acat]aresample=48000[aout]")
    return ";\n".join(parts)


def render(edl: EDL, output: str | Path, work_dir: str | Path) -> RenderResult:
    output = Path(output).resolve()
    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = Path(edl.source).resolve()
    if output == source:
        raise ValueError("Refusing to overwrite the original footage")
    output.parent.mkdir(parents=True, exist_ok=True)

    ass = srt = None
    if edl.captions.enabled and edl.words:
        words = remap_words(edl.words, edl.segments)
        ass, srt = write_captions(words, edl.export.preset, edl.captions, work)

    logo = None
    if edl.branding.watermark:
        logo = watermark_png(work / "watermark.png", PRESETS[edl.export.preset]["size"][0], edl.branding.logo_path)

    graph = build_filtergraph(edl, ass is not None, logo is not None)
    (work / "filtergraph.txt").write_text(graph, encoding="utf-8")

    tmp_out = output.with_name(f".{output.stem}.rendering{output.suffix}")
    encoder = choose_encoder(edl.export.encoder)

    def cmd_for(enc: str) -> list[str]:
        cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]
        if logo:
            # A looped still is an infinite stream; bound it, or FFmpeg buffers it without limit.
            cmd += ["-loop", "1", "-framerate", str(edl.export.fps),
                    "-t", f"{edl.output_duration + 1:.3f}", "-i", str(logo)]
        # Inline graph where it fits the Windows command-line limit; script file for very long edits.
        graph_arg = ["-filter_complex", graph] if len(graph) < 20000 else ["-filter_complex_script", "filtergraph.txt"]
        cmd += graph_arg + ["-map", "[vout]", "-map", "[aout]"]
        cmd += video_args(enc, edl.export.quality)
        cmd += ["-r", str(edl.export.fps), "-c:a", "aac", "-b:a", edl.export.audio_bitrate, "-ar", "48000",
                "-shortest", "-movflags", "+faststart", str(tmp_out)]
        return cmd

    # cwd=work keeps the captions path free of Windows drive-letter escaping problems.
    # Watchdog: a render should never run unbounded (generous: 30x real time, minimum 10 minutes).
    limit = max(600.0, edl.output_duration * 30)
    cmd = cmd_for(encoder)
    try:
        run(cmd, cwd=work, timeout=limit)
    except ToolError:
        if encoder == "libx264":
            raise
        log.warning("GPU encode failed; retrying on CPU (libx264)")
        encoder = "libx264"
        cmd = cmd_for(encoder)
        run(cmd, cwd=work, timeout=limit)

    os.replace(tmp_out, output)
    if srt:
        shutil.copyfile(srt, output.with_suffix(".srt"))
    return RenderResult(output, encoder, ass, srt, cmd)
