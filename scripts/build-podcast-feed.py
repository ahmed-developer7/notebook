"""
Emit podcast RSS feeds for the generated audio, one per language.

Why bother instead of copying MP3s to the phone: AntennaPod takes a feed URL
and handles the rest -- download, real episode titles, resume position per
episode, and picking up new chapters automatically when this is re-run. Moving
files by hand means redoing it every time a chapter is regenerated.

Serve the audio directory over the LAN and subscribe to the feed URL:
    py -m http.server 8321 --bind 0.0.0.0      (run inside audio/)
    py scripts/build-podcast-feed.py --host 192.168.25.218 --port 8321
"""

from __future__ import annotations

import argparse
import html
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIO_ROOT = REPO_ROOT / "audio"

FEEDS = {
    "en": {
        "subdir": "",
        "title": ".NET Mastery Guide",
        "desc": "Senior .NET interview preparation, read aloud.",
    },
    "ur": {
        "subdir": "ur",
        "title": ".NET Mastery Guide (Urdu)",
        "desc": "سینئر ڈاٹ نیٹ انٹرویو کی تیاری، اردو میں۔",
    },
}


def duration_seconds(path: Path) -> int:
    try:
        from mutagen.mp3 import MP3
        return int(MP3(path).info.length)
    except Exception:
        return 0


def tag_of(path: Path, frame: str, fallback: str) -> str:
    try:
        from mutagen.id3 import ID3
        return str(ID3(path)[frame])
    except Exception:
        return fallback


def hhmmss(total: int) -> str:
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def collect(lang_dir: Path, skip_ur: bool) -> list[Path]:
    files = []
    for p in sorted(lang_dir.rglob("*.mp3")):
        if "_samples" in p.parts:
            continue
        # The English feed lives at the audio root, so it must not swallow the
        # Urdu tracks sitting in the ur/ subtree.
        if skip_ur and "ur" in p.relative_to(lang_dir).parts[:1]:
            continue
        files.append(p)
    return files


def build(lang: str, cfg: dict, host: str, port: int, pub: datetime) -> Path | None:
    lang_dir = AUDIO_ROOT / cfg["subdir"] if cfg["subdir"] else AUDIO_ROOT
    if not lang_dir.exists():
        return None
    files = collect(lang_dir, skip_ur=(lang == "en"))
    if not files:
        return None

    base = f"http://{host}:{port}"
    items = []
    for i, mp3 in enumerate(files):
        rel = mp3.relative_to(AUDIO_ROOT).as_posix()
        url = f"{base}/{rel}"
        secs = duration_seconds(mp3)
        title = tag_of(mp3, "TIT2", mp3.stem)
        album = tag_of(mp3, "TALB", "Mastery Guide")
        # Oldest first by pubDate so the natural podcast ordering (newest at
        # the top) still lets you play through in chapter order.
        when = pub - timedelta(minutes=len(files) - i)
        items.append(f"""    <item>
      <title>{escape(title)}</title>
      <description>{escape(album)}</description>
      <guid isPermaLink="false">{escape(rel)}</guid>
      <pubDate>{format_datetime(when)}</pubDate>
      <enclosure url="{escape(url)}" length="{mp3.stat().st_size}" type="audio/mpeg"/>
      <itunes:duration>{hhmmss(secs)}</itunes:duration>
    </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(cfg['title'])}</title>
    <link>{base}/</link>
    <description>{escape(cfg['desc'])}</description>
    <language>{'ur' if lang == 'ur' else 'en'}</language>
    <itunes:author>.NET Mastery Guide</itunes:author>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""
    dest = AUDIO_ROOT / f"feed-{lang}.xml"
    dest.write_text(xml, encoding="utf-8")
    print(f"{dest.name:14} {len(files)} episode(s)  ->  {base}/{dest.name}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", required=True, help="LAN IP of this machine")
    ap.add_argument("--port", type=int, default=8321)
    args = ap.parse_args()

    pub = datetime.now(timezone.utc)
    made = [build(l, c, args.host, args.port, pub) for l, c in FEEDS.items()]
    if not any(made):
        print("No audio found. Generate some with build-audio.ps1 first.")
        return 1
    print("\nIn AntennaPod: Add Podcast -> Add Podcast by RSS address -> paste a URL above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
