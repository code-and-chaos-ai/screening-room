"""
Screening Room — let your AI watch videos.

Tools:
  hear_video  — transcript (captions if the video has them, else local Whisper)
  see_video     — key frames as images, each stamped with its timestamp
  screen_video   — both

Works with YouTube, X/Twitter, TikTok and most sites yt-dlp supports.
Everything runs on your own machine. No API keys, no per-use cost.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from mcp.types import ImageContent, TextContent

# --- Settings you may want to change -----------------------------------------
# Where extracted frames are saved.
OUTPUT_DIR = Path(os.environ.get("SCREENING_ROOM_OUTPUT", Path.home() / "screening-room-frames"))
# Whisper model for videos without captions: tiny / base / small / medium / large-v3-turbo.
# Bigger = more accurate but slower and more RAM. "small" is a good default on a CPU.
WHISPER_MODEL = os.environ.get("SCREENING_ROOM_WHISPER", "small")
# Caption language to try first.
CAPTION_LANG = os.environ.get("SCREENING_ROOM_LANG", "en")
# Each frame is an image in the conversation, so keep the count sane.
MAX_SHOTS = 12
# ------------------------------------------------------------------------------

YTDLP = shutil.which("yt-dlp")
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
# YouTube requires a JavaScript runtime to solve its playback challenge.
# yt-dlp uses Deno by default; if you only have Node, we point it at Node.
_NODE = shutil.which("node")
JS_RUNTIME = [] if shutil.which("deno") or not _NODE else ["--js-runtimes", f"node:{_NODE}"]

mcp = FastMCP("screening-room")
_whisper = None


def _ytdlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    if not YTDLP:
        raise RuntimeError("yt-dlp not found on PATH. Install it: pip install yt-dlp yt-dlp-ejs")
    return subprocess.run([YTDLP, *JS_RUNTIME, *args], capture_output=True, text=True, timeout=timeout)


def _title(url: str) -> str:
    try:
        return _ytdlp(["--print", "%(title)s", "--skip-download", url], 60).stdout.strip() or "Unknown"
    except Exception:
        return "Unknown"


def _captions(url: str) -> str | None:
    """Return cleaned captions, or None if the video has none."""
    tmp = tempfile.mkdtemp()
    try:
        _ytdlp(["--write-subs", "--write-auto-subs", "--skip-download",
                "--sub-langs", CAPTION_LANG, "--sub-format", "srt", "--convert-subs", "srt",
                "-o", os.path.join(tmp, "%(id)s"), url], 90)
        srt = next(Path(tmp).glob("*.srt"), None)
        if not srt:
            return None
        lines, seen = [], set()
        for line in srt.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.isdigit() or re.match(r"\d{2}:\d{2}:\d{2}", line):
                continue
            clean = re.sub(r"<[^>]+>", "", line)
            if clean and clean not in seen:
                seen.add(clean)
                lines.append(clean)
        return " ".join(lines) or None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _whisper_transcript(url: str) -> str:
    """No captions (typical for X and TikTok): download the audio, transcribe locally."""
    global _whisper
    tmp = tempfile.mkdtemp()
    try:
        result = _ytdlp(["-f", "bestaudio/best", "-o", os.path.join(tmp, "audio.%(ext)s"), url], 300)
        audio = next(Path(tmp).glob("audio.*"), None)
        if not audio:
            return f"Error: could not download audio. {result.stderr[-300:]}"
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")
        segments, info = _whisper.transcribe(str(audio), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        if not text:
            return "No speech found in this video (music or silence only)."
        return f"[transcribed locally, language: {info.language}]\n{text}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _hear(url: str) -> str:
    if not url.strip():
        return "Error: no URL provided"
    try:
        transcript = _captions(url) or _whisper_transcript(url)
        return f"Title: {_title(url)}\n\nTranscript:\n{transcript}"
    except subprocess.TimeoutExpired:
        return "Error: timed out downloading captions or audio"
    except Exception as e:
        return f"Error: {e}"


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _fetch_clip(url: str, path: str) -> str | None:
    """Small video-only stream (frames need no sound). None on success, else the error.
    The second attempt poses as a normal browser, for sites that block plain downloaders
    (needs the curl-cffi extra; harmless if it's missing)."""
    fmt = "bv*[height<=480][ext=mp4]/bv*[height<=480]/worst[ext=mp4]/worst"
    err = ""
    for extra in ([], ["--impersonate", "chrome"]):
        result = _ytdlp([*extra, "-f", fmt, "--no-playlist", "-o", path, url], 180)
        if os.path.exists(path):
            return None
        err = result.stderr[-300:]
    return err or "unknown download error"


def _grab_frame(video: str, at: float, out: Path) -> bool:
    """One 480px JPEG at `at` seconds with its timestamp stamped in the corner.
    Falls back to an unstamped frame if this ffmpeg can't draw text."""
    base = [FFMPEG, "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1"]
    label = _clock(at).replace(":", "\\:")
    stamp = (f"drawtext=text='{label}':x=10:y=10:fontsize=22:fontcolor=0xF5F5F5:"
             "box=1:boxcolor=0x101010@0.55:boxborderw=6")
    for vf in (f"scale=480:-2,{stamp}", "scale=480:-2"):
        subprocess.run(base + ["-vf", vf, "-q:v", "5", str(out)], capture_output=True, timeout=30)
        if out.exists() and out.stat().st_size > 0:
            return True
    return False


def _look(url: str, shots: int = 5) -> tuple[str, list[Path]]:
    """Returns (summary text, frame files). The frame list is empty on error."""
    if not url.strip():
        return "Error: no URL provided", []
    if not (FFMPEG and FFPROBE):
        return "Error: ffmpeg/ffprobe not found on PATH. Install ffmpeg.", []
    shots = max(1, min(int(shots), MAX_SHOTS))
    tmp = tempfile.mkdtemp()
    try:
        video = os.path.join(tmp, "video.mp4")
        err = _fetch_clip(url, video)
        if err:
            return f"Error: could not download video. {err}", []

        probe = subprocess.run([FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
                                "-of", "json", video], capture_output=True, text=True, timeout=30)
        duration = float(json.loads(probe.stdout)["format"]["duration"])

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for old in OUTPUT_DIR.glob("shot_*.*"):
            old.unlink(missing_ok=True)
        frames, stamps, step = [], [], duration / (shots + 1)
        for shot in range(1, shots + 1):
            at, out = step * shot, OUTPUT_DIR / f"shot_{shot:02d}.jpg"
            if _grab_frame(video, at, out):
                frames.append(out)
                stamps.append(_clock(at))
        if not frames:
            return "Error: could not extract frames", []
        return (f"Title: {_title(url)}\nDuration: {_clock(duration)}\n"
                f"{len(frames)} frames at: {', '.join(stamps)} (timestamp stamped on each)"), frames
    except subprocess.TimeoutExpired:
        return "Error: timed out", []
    except Exception as e:
        return f"Error: {e}", []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _content(text: str, frames: list[Path]) -> list[TextContent | ImageContent]:
    """Text first, then each frame as a real image the AI sees directly —
    no file access needed (works in Claude Desktop, claude.ai, Claude Code)."""
    return [TextContent(type="text", text=text),
            *(Image(path=f).to_image_content() for f in frames)]


@mcp.tool()
def hear_video(url: str) -> str:
    """Get the transcript of a video (what is said). Uses captions when available,
    otherwise transcribes the audio locally with Whisper.

    Args:
        url: Video URL (YouTube, X/Twitter, TikTok, ...)
    """
    return _hear(url)


@mcp.tool()
def see_video(url: str, shots: int = 5) -> list[TextContent | ImageContent]:
    """See a video: evenly spaced key frames returned as images, each stamped with
    its timestamp. Best for visual clips, dance, memes, scenery.

    Args:
        url: Video URL
        shots: How many stills to take (default 5, max 12)
    """
    return _content(*_look(url, shots))


@mcp.tool()
def screen_video(url: str, shots: int = 5) -> list[TextContent | ImageContent]:
    """Full experience: transcript AND timestamped frames as images.

    Args:
        url: Video URL
        shots: How many stills to take (default 5, max 12)
    """
    text, frames = _look(url, shots)
    return _content(f"{_hear(url)}\n\n---\n\n{text}", frames)


if __name__ == "__main__":
    mcp.run()
