import asyncio
import html
import importlib.util
import re
import subprocess
import sys
import urllib.request
from typing import Dict, Iterable, Optional


def ensure_packages(packages: Iterable[str]) -> None:
    """Install required packages if they are missing."""
    for package in packages:
        if importlib.util.find_spec(package) is None:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])


auto_packages = ["fastapi", "uvicorn", "yt-dlp"]
ensure_packages(auto_packages)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl
from yt_dlp import YoutubeDL


app = FastAPI(title="YouTube Transcript Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"]
)


class TranscriptRequest(BaseModel):
    url: HttpUrl


def pick_caption_track(captions: Dict[str, list]) -> Optional[list]:
    if not captions:
        return None

    priority = ("en", "en-US", "en-GB")
    for lang in priority:
        if lang in captions:
            return captions[lang]

    return next(iter(captions.values()))


def vtt_to_text(vtt_content: str) -> str:
    lines = []
    for raw_line in vtt_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^[0-9]+$", line):
            continue
        if re.match(r"\d{2}:\d{2}:\d{2}\.\d{3} \-\-> ", line):
            continue
        lines.append(html.unescape(line))
    return "\n".join(lines)


def fetch_transcript(url: str) -> str:
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "quiet": True,
        "subtitlesformat": "vtt",
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    subtitles = info.get("subtitles") or {}
    auto_captions = info.get("automatic_captions") or {}
    track = pick_caption_track(subtitles) or pick_caption_track(auto_captions)

    if not track:
        raise HTTPException(status_code=404, detail="No subtitles available for this video.")

    subtitle_url = track[0].get("url")
    if not subtitle_url:
        raise HTTPException(status_code=500, detail="Subtitle URL could not be resolved.")

    with urllib.request.urlopen(subtitle_url) as response:
        content = response.read().decode("utf-8")

    transcript_text = vtt_to_text(content)
    if not transcript_text:
        raise HTTPException(status_code=500, detail="Unable to parse transcript from subtitles.")

    return transcript_text


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    with open("index.html", "r", encoding="utf-8") as page:
        return HTMLResponse(page.read())


@app.post("/api/transcript")
async def transcript(request: TranscriptRequest):
    transcript_text = await asyncio.to_thread(fetch_transcript, str(request.url))
    return {"transcript": transcript_text}


def run() -> None:
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
