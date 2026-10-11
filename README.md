# Screening Room — let your AI watch videos

Send your AI a YouTube, X/Twitter or TikTok link, and it can **hear** the video (a transcript) and **see** it (key frames, each stamped with its timestamp).

- **Free.** No API keys, no subscriptions. The local edition costs nothing; the cloud edition fits in Modal's free monthly credits for normal use.
- **Private.** Nothing goes to an AI company: the local edition runs entirely on your computer, and the cloud edition runs on your own Modal account.
- **Works on videos without captions.** If a video has no subtitles (most X and TikTok videos), it transcribes the audio locally with Whisper.

It gives your AI three tools:

| Tool | What it does |
|---|---|
| `hear_video` | Transcript: what's said in the video |
| `see_video` | Evenly spaced frames, sent straight to the AI as pictures, each stamped with its time (e.g. `0:12`) |
| `screen_video` | Both at once |

---

## Two editions: pick one

| | ☁ **Cloud** (`screening_room_cloud.py`) | 💻 **Local** (`screening_room.py`) |
|---|---|---|
| Works in | **Everywhere**: Claude phone app, claude.ai, Claude Desktop, ChatGPT, anything that takes an MCP link | Desktop apps only (Claude Desktop, Claude Code) |
| Needs | A free [Modal](https://modal.com) account | Python, ffmpeg, Node on your computer |
| YouTube | ❌ YouTube blocks cloud servers (see below) | ✅ |
| X, TikTok, Instagram, Reddit, Vimeo… | ✅ | ✅ |
| Uses your computer's memory | No | Yes (Whisper ~0.6 GB while transcribing) |
| Privacy | Videos pass through your own Modal account | Nothing leaves your computer |

**Not sure? Start with Cloud.** It's the one that works on your phone. Add Local later if you want YouTube.

> **Why no YouTube in the cloud?** YouTube refuses downloads from data-center addresses and asks the server to *"confirm you're not a bot"*. Every cloud host gets this; it's not a bug in this tool. The cloud edition tells your AI this clearly instead of failing silently.

---

# ☁ Cloud edition

### 1. Make a free Modal account

Sign up at [modal.com](https://modal.com). The free monthly credits cover casual video-sharing easily, and the server scales to zero (costs nothing) when nobody's using it.

### 2. Install Modal and log in

```bash
pip install modal
modal setup
```

`modal setup` opens your browser to connect the CLI to your account.

### 3. Create your secret key

Your server's address includes a secret key, and anyone without it gets "Not found". Make a long random one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then store it in Modal, pasting your key where it says so:

```bash
modal secret create screening-room-key SCREENING_ROOM_KEY=PASTE_YOUR_KEY_HERE
```

### 4. Deploy

```bash
modal deploy screening_room_cloud.py
```

The first deploy takes a couple of minutes: it builds ffmpeg, yt-dlp and Whisper into your server. At the end it prints an address like:

`https://YOURNAME--screening-room-serve.modal.run`

### 5. Build your link

Add your key and `/mcp` to the end:

`https://YOURNAME--screening-room-serve.modal.run/YOUR_KEY/mcp`

> 🔒 **This link works like a password.** Anyone who has it can use your server and your Modal credits. Don't post it publicly or put it in screenshots. If it leaks, create a new key with `modal secret create screening-room-key SCREENING_ROOM_KEY=NEW_KEY --force` and deploy again. The old link then stops working.

### 6. Connect it

- **Claude (web, phone, desktop):** Settings → Connectors → **Add custom connector** → paste your link. Connectors sync across your Claude apps.
- **ChatGPT and other apps:** anywhere that accepts a remote MCP server link.

Then test it with a TikTok: *"Watch this with me: https://www.tiktok.com/…"*

**Updating later:** run `modal deploy screening_room_cloud.py` again. Your link stays the same.

---

# 💻 Local edition

## 1. What you need

- **Python 3.10 or newer**: [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add Python to PATH"** during install.
- **ffmpeg**: cuts frames out of the video.
- **Node.js** (or Deno): YouTube now makes downloaders solve a small JavaScript puzzle, and this runs it. If you already have Node installed, you're done. Otherwise get it from [nodejs.org](https://nodejs.org).

### Install ffmpeg

| System | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| Mac | `brew install ffmpeg` |
| Linux | `sudo apt install ffmpeg` |

Close and reopen your terminal afterwards so it's found.

## 2. Install the Python packages

```bash
pip install fastmcp "yt-dlp[default,curl-cffi]" faster-whisper
```

| Package | Job |
|---|---|
| `yt-dlp[default,curl-cffi]` | Downloads from YouTube, X, TikTok and about 1,000 other sites. `default` brings the YouTube puzzle solver (**without it, YouTube fails**); `curl-cffi` lets it pose as a normal browser when a site blocks downloaders |
| `faster-whisper` | Local speech-to-text for videos without captions |
| `fastmcp` | Turns the script into an MCP server |

## 3. Get the server file

Save `screening_room.py` somewhere permanent, for example:

- Windows: `C:\Users\YOU\mcp\screening_room.py`
- Mac/Linux: `~/mcp/screening_room.py`

## 4. Connect it to your AI

### Claude Code

```bash
claude mcp add screening-room -- python /full/path/to/screening_room.py
```

### Claude Desktop

Open **Settings → Developer → Edit Config** and add this inside `"mcpServers"`:

```json
"screening-room": {
  "command": "python",
  "args": ["C:/Users/YOU/mcp/screening_room.py"]
}
```

Use forward slashes `/` in the path, even on Windows. Then **fully quit Claude Desktop** (from the tray icon, not just the window) and open it again.

### Other MCP apps

Any app that runs stdio MCP servers works. The command is `python /path/to/screening_room.py`.

> 🖼 Frames are sent to your AI **as pictures inside the chat**, so it sees them directly in Claude Desktop, Claude Code and anywhere else MCP runs. No file access setup needed. A copy of the latest frames is also kept in `screening-room-frames` in your home folder.

## 5. Test it

Ask your AI:

> Use hear_video on https://www.youtube.com/watch?v=jNQXAC9IVRw

It should come back with *"All right, so here we are, in front of the elephants…"* That's "Me at the zoo", the first video ever uploaded to YouTube.

Then try `see_video` on the same link and ask what it sees.

---

## Settings (optional)

**Local edition:** set these as environment variables, or change them at the top of `screening_room.py`.
**Cloud edition:** change `WHISPER_MODEL` at the top of `screening_room_cloud.py`, then run `modal deploy screening_room_cloud.py` again. It runs on CPU, so `small` or `base` is the sweet spot.

| Setting | Default | What it does |
|---|---|---|
| `SCREENING_ROOM_OUTPUT` | `~/screening-room-frames` | Where a copy of the latest frames is kept |
| `SCREENING_ROOM_WHISPER` | `small` | Whisper model size (see below) |
| `SCREENING_ROOM_LANG` | `en` | Caption language to try first |

### Choosing a Whisper model

Whisper only runs when a video has no captions. Bigger models are more accurate, but slower and use more memory.

| Model | Rough RAM | Good for |
|---|---|---|
| `tiny` | ~0.2 GB | Old or low-memory laptops |
| `base` | ~0.3 GB | Fast, okay accuracy |
| **`small`** | ~0.6 GB | **The default: good balance on a normal computer** |
| `medium` | ~1.5 GB | Better accuracy, slow without a GPU |
| `large-v3-turbo` | ~2 GB | Best accuracy; use it if you have an NVIDIA GPU |

The model downloads automatically the first time it's needed, so that first transcript takes longer. If you have an NVIDIA GPU with CUDA set up, Whisper uses it automatically.

---

## Troubleshooting

| You see | Fix |
|---|---|
| ☁ *"YouTube blocks downloads from cloud servers"* | Expected in the cloud edition: YouTube refuses data-center addresses. Use the local edition for YouTube. |
| ☁ The connector won't connect / "Not found" | The link must end in `/YOUR_KEY/mcp`, and the key must match your Modal secret exactly. Changed the secret? Run `modal deploy screening_room_cloud.py` again. |
| ☁ First request after a while is slow | The server sleeps when unused (that's why it costs nothing) and takes a few seconds to wake. |
| ☁ X or TikTok start failing in the cloud | Redeploy to pick up the newest yt-dlp: bump its version in `screening_room_cloud.py`, then `modal deploy screening_room_cloud.py`. |
| 💻 `HTTP Error 403: Forbidden` on YouTube | yt-dlp is out of date. Run `pip install -U "yt-dlp[default,curl-cffi]"`. YouTube changes often, so **update it once a month**. |
| `Requested format is not available` | Same fix: update both packages. Also check that Node (or Deno) is installed. |
| Warning about *"No supported JavaScript runtime"* | Install Node.js, then restart your AI app. |
| `yt-dlp not found on PATH` / `ffmpeg not found` | Reopen the terminal after installing. On Windows, check that Python's `Scripts` folder and ffmpeg are on PATH. |
| *"No speech found in this video"* | Normal for music-only clips: there's genuinely nothing to transcribe. |
| First transcript is slow | Whisper is downloading and loading its model. Later ones are much faster. |
| The tools don't show up in Claude | Check the path in your config, use forward slashes, and fully quit and reopen the app. |
| Private or login-only videos fail | Only public videos work out of the box. |

---

## Good to know

- Up to 12 frames per request. Each frame is a picture in the AI's conversation, and small JPEGs keep that light.
- The timestamp on each frame lets the AI say *when* something happens ("at 0:12 he points at the elephant").

## Privacy note

Nothing in this tool sends your videos, audio or transcripts to an AI company. yt-dlp downloads the video from the site you gave it, and everything else happens on your machine. Frames stay in your frames folder until you delete them.

---

*Made by Code & Chaos.*
