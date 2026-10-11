"""
Screening Room — cloud edition (runs on Modal).

Same three tools as the local edition, reachable from anywhere MCP runs:
the Claude phone app, claude.ai, Claude Desktop, ChatGPT connectors, ...

  hear_video  — transcript (captions if the video has them, else Whisper)
  see_video     — key frames as images, each stamped with its timestamp
  screen_video   — both

Locked with a secret key that lives in the URL:
  https://<workspace>--screening-room-serve.modal.run/<YOUR_KEY>/mcp
Anything without the key gets a 404 and costs you nothing.

Deploy:
  modal secret create screening-room-key SCREENING_ROOM_KEY=<a long random string>
  modal deploy screening_room_cloud.py
"""

import os

import modal

WHISPER_MODEL = "small"  # tiny / base / small / medium / large-v3-turbo


def _bake_whisper():
    # Download the model at build time so the first transcript isn't a cold download.
    from faster_whisper import WhisperModel
    WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "fonts-dejavu-core")
    .pip_install(
        # Pinned as a set: an unpinned mcp resolves to 2.x, which breaks fastmcp 2.14 on import.
        "fastmcp==2.14.1",
        "mcp==1.24.0",
        "pydantic-settings==2.12.0",
        # default = YouTube puzzle solver, curl-cffi = browser disguise, deno = JS runtime
        "yt-dlp[default,curl-cffi,deno]==2026.8.19",
        "faster-whisper==1.2.1",
    )
    .run_function(_bake_whisper)
)

app = modal.App("screening-room", image=image)


@app.function(
    secrets=[modal.Secret.from_name("screening-room-key")],
    cpu=4.0,
    memory=4096,
    timeout=900,
    scaledown_window=120,  # stay warm 2 min after use, then scale to zero (no cost)
)
@modal.concurrent(max_inputs=4)
@modal.asgi_app()
def serve():
    import json
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from fastmcp import FastMCP
    from fastmcp.utilities.types import Image
    from mcp.types import ImageContent, TextContent

    key = os.environ.get("SCREENING_ROOM_KEY", "")
    if len(key) < 24:
        raise RuntimeError("SCREENING_ROOM_KEY secret missing or too short (use 24+ random characters)")

    MAX_SHOTS = 12
    mcp = FastMCP("screening-room")
    whisper = {}

    def ytdlp(args, timeout):
        return subprocess.run(["yt-dlp", "--no-playlist", *args],
                              capture_output=True, text=True, timeout=timeout)

    YOUTUBE_BLOCKED = ("YouTube blocks downloads from cloud servers ('confirm you're not a bot'). "
                       "This is YouTube refusing data-center addresses, not a bug. For YouTube, "
                       "use the local edition of this tool, or paste the video's transcript.")

    def explain(err):
        return YOUTUBE_BLOCKED if any(k in err for k in ("confirm you", "not a bot", "cookies-from-browser", "--cookies")) else err

    def clock(seconds):
        s = int(seconds)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"

    def title(url):
        try:
            return ytdlp(["--print", "%(title)s", "--skip-download", url], 60).stdout.strip() or "Unknown"
        except Exception:
            return "Unknown"

    def captions(url):
        tmp = tempfile.mkdtemp()
        try:
            ytdlp(["--write-subs", "--write-auto-subs", "--skip-download", "--sub-langs", "en",
                   "--sub-format", "srt", "--convert-subs", "srt",
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

    def transcribe(url):
        tmp = tempfile.mkdtemp()
        try:
            result = ytdlp(["-f", "bestaudio/best", "-o", os.path.join(tmp, "audio.%(ext)s"), url], 300)
            audio = next(Path(tmp).glob("audio.*"), None)
            if not audio:
                return f"Error: could not download audio. {explain(result.stderr[-300:])}"
            if "model" not in whisper:
                from faster_whisper import WhisperModel
                whisper["model"] = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            segments, info = whisper["model"].transcribe(str(audio), vad_filter=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            if not text:
                return "No speech found in this video (music or silence only)."
            return f"[transcribed, language: {info.language}]\n{text}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def hear(url):
        if not url.strip():
            return "Error: no URL provided"
        try:
            return f"Title: {title(url)}\n\nTranscript:\n{captions(url) or transcribe(url)}"
        except subprocess.TimeoutExpired:
            return "Error: timed out downloading captions or audio"
        except Exception as e:
            return f"Error: {e}"

    def fetch_clip(url, path):
        fmt = "bv*[height<=480][ext=mp4]/bv*[height<=480]/worst[ext=mp4]/worst"
        err = ""
        for extra in ([], ["--impersonate", "chrome"]):
            result = ytdlp([*extra, "-f", fmt, "-o", path, url], 180)
            if os.path.exists(path):
                return None
            err = result.stderr[-300:]
        return err or "unknown download error"

    def grab_frame(video, at, out):
        base = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1"]
        label = clock(at).replace(":", "\\:")
        stamp = (f"drawtext=text='{label}':x=10:y=10:fontsize=22:fontcolor=0xF5F5F5:"
                 "box=1:boxcolor=0x101010@0.55:boxborderw=6")
        for vf in (f"scale=480:-2,{stamp}", "scale=480:-2"):
            subprocess.run(base + ["-vf", vf, "-q:v", "5", str(out)], capture_output=True, timeout=30)
            if out.exists() and out.stat().st_size > 0:
                return True
        return False

    def look(url, shots):
        """Returns (summary, list of JPEG bytes)."""
        if not url.strip():
            return "Error: no URL provided", []
        shots = max(1, min(int(shots), MAX_SHOTS))
        tmp = tempfile.mkdtemp()
        try:
            video = os.path.join(tmp, "video.mp4")
            err = fetch_clip(url, video)
            if err:
                return f"Error: could not download video. {explain(err)}", []
            probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                                    "-of", "json", video], capture_output=True, text=True, timeout=30)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            frames, stamps, step = [], [], duration / (shots + 1)
            for shot in range(1, shots + 1):
                at, out = step * shot, Path(tmp) / f"shot_{shot:02d}.jpg"
                if grab_frame(video, at, out):
                    frames.append(out.read_bytes())
                    stamps.append(clock(at))
            if not frames:
                return "Error: could not extract frames", []
            return (f"Title: {title(url)}\nDuration: {clock(duration)}\n"
                    f"{len(frames)} frames at: {', '.join(stamps)} (timestamp stamped on each)"), frames
        except subprocess.TimeoutExpired:
            return "Error: timed out", []
        except Exception as e:
            return f"Error: {e}", []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def content(text, frames):
        return [TextContent(type="text", text=text),
                *(Image(data=f, format="jpeg").to_image_content() for f in frames)]

    @mcp.tool()
    def hear_video(url: str) -> str:
        """Get the transcript of a video (what is said). Uses captions when available,
        otherwise transcribes the audio with Whisper.

        Args:
            url: Video URL (YouTube, X/Twitter, TikTok, Instagram, ...)
        """
        return hear(url)

    @mcp.tool()
    def see_video(url: str, shots: int = 5) -> list[TextContent | ImageContent]:
        """See a video: evenly spaced key frames returned as images, each stamped with
        its timestamp. Best for visual clips, dance, memes, scenery.

        Args:
            url: Video URL
            shots: How many stills to take (default 5, max 12)
        """
        return content(*look(url, shots))

    @mcp.tool()
    def screen_video(url: str, shots: int = 5) -> list[TextContent | ImageContent]:
        """Full experience: transcript AND timestamped frames as images.

        Args:
            url: Video URL
            shots: How many stills to take (default 5, max 12)
        """
        text, frames = look(url, shots)
        return content(f"{hear(url)}\n\n---\n\n{text}", frames)

    inner = mcp.http_app(path="/mcp", stateless_http=True)
    prefix = f"/{key}"

    async def locked(scope, receive, send):
        """Only requests under /<key>/ reach the server; everything else is a bare 404."""
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path != prefix and not path.startswith(prefix + "/"):
                await send({"type": "http.response.start", "status": 404,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Not found"})
                return
            scope = dict(scope, path=path[len(prefix):] or "/", root_path=scope.get("root_path", ""))
        await inner(scope, receive, send)

    return locked
