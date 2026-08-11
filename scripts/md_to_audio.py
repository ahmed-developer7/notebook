"""
Convert mastery-guide markdown into listenable MP3s.

The guide is ~35% code blocks, ASCII diagrams and tables, and most of its
value sits inside collapsed <details> blocks. Browser read-aloud gets both
of those wrong: it reads the diagrams as gibberish and skips the collapsed
content entirely. This script does the opposite -- strips what cannot be
spoken, and unwraps what browsers hide.

Pipeline:  select -> strip -> pronounce -> chunk -> synthesize -> tag

Output goes to audio/<chapter>/<topic>.mp3 with a .txt sidecar containing
exactly what was spoken, so stripping rules can be tuned by reading rather
than listening.

Invoked by scripts/build-audio.ps1. Run --help for flags.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Stamped into every generated filename so you can tell regenerations apart on
# the phone without opening them. Computed once per run, so all parts of one
# build share a stamp.
RUN_STAMP = datetime.now().strftime("%Y%m%d-%H%M")

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_ROOT = REPO_ROOT / "mastery-guide"
AUDIO_ROOT = REPO_ROOT / "audio"
PRONUNCIATION_FILE = Path(__file__).resolve().parent / "audio-pronunciation.json"

DEFAULT_VOICE = "en-IN-PrabhatNeural"
DEFAULT_RATE = "-10%"
CHUNK_CHARS = 3000
# Calibrated against a measured run: 11,137 words -> 102.5 min at rate -10%,
# i.e. ~109 effective wpm. Lower than a plain 150 wpm reading estimate because
# the stripper adds terminal punctuation, and every one of those is a pause.
WPM = 120

SAMPLE_VOICES = [
    "en-IN-PrabhatNeural",          # chosen default
    "en-IN-NeerjaExpressiveNeural",  # expressive prosody -- less monotony over an hour
    "en-GB-RyanNeural",
    "en-US-AndrewNeural",
]

URDU_VOICE = "ur-PK-AsadNeural"

# Dense on purpose: acronyms, decimals, config keys and big numbers all in a
# few sentences, so a voice that mangles technical prose reveals itself fast.
SAMPLE_TEXT = (
    "Durability internals. The basics. "
    "A producer sends a record to the partition leader. "
    "The leader appends it to its own log file. That is one copy, on one machine. "
    "The followers are separately fetching from the leader, and a moment later "
    "they pull that record across. Now three copies exist. "
    "Only at that point is the record safe from any single machine dying. "
    "So at any instant there are two different positions on a partition: "
    "how far the leader has written, and how far every in-sync copy has caught up to. "
    "The high watermark is the minimum log end offset across the ISR. "
    "Consumers can only read up to the high watermark. "
    "Sizing example: two hundred thousand messages per second at 2 KB each, "
    "with RF of 3 and 7-day retention, needs roughly 310 TB including headroom. "
    "In .NET, the canonical client is Confluent dot Kafka."
)

# Urdu pilot. Pointing an Urdu voice at the existing English files does NOT
# produce Urdu audio -- the content itself has to be translated. These three
# variants settle that empirically on one short passage, before anyone commits
# to translating 841k words of technical material.
URDU_SAMPLES = {
    # A: the zero-effort hope -- Urdu voice, untranslated English text.
    "urdu-a-english-text": (SAMPLE_TEXT, URDU_VOICE),

    # B: full Urdu in Urdu script, terms translated where a translator would.
    "urdu-b-full-urdu": (
        "پائیداری کی اندرونی تفصیلات۔ بنیادی باتیں۔ "
        "ایک پروڈیوسر ریکارڈ پارٹیشن لیڈر کو بھیجتا ہے۔ "
        "لیڈر اسے اپنی لاگ فائل میں شامل کرتا ہے۔ یہ ایک مشین پر ایک کاپی ہے۔ "
        "فالوورز الگ سے لیڈر سے ڈیٹا کھینچتے رہتے ہیں، اور تھوڑی دیر بعد "
        "وہ اس ریکارڈ کو اپنے پاس لے آتے ہیں۔ اب تین کاپیاں موجود ہیں۔ "
        "صرف اسی وقت وہ ریکارڈ کسی ایک مشین کے خراب ہونے سے محفوظ ہوتا ہے۔ "
        "ہائی واٹر مارک اِن سِنک ریپلیکاز میں سب سے کم لاگ اینڈ آفسیٹ ہوتا ہے۔ "
        "کنزیومرز صرف ہائی واٹر مارک تک ہی پڑھ سکتے ہیں۔",
        URDU_VOICE,
    ),

    # C: code-switched -- Urdu sentence structure, English technical terms,
    # which is how this is actually explained in Pakistani engineering teams.
    "urdu-c-codeswitched": (
        "Durability internals۔ بنیادی بات یہ ہے۔ "
        "ایک producer ایک record کو partition leader کو بھیجتا ہے۔ "
        "Leader اسے اپنی log file میں append کرتا ہے۔ یہ ایک copy ہے، ایک machine پر۔ "
        "Followers الگ سے leader سے fetch کرتے رہتے ہیں، اور تھوڑی دیر میں "
        "وہ record ان کے پاس بھی آ جاتا ہے۔ اب تین copies ہیں۔ "
        "اسی وقت وہ record کسی ایک machine کے fail ہونے سے safe ہوتا ہے۔ "
        "High watermark وہ سب سے کم log end offset ہے جو ISR کے تمام replicas کے پاس ہے۔ "
        "Consumers صرف high watermark تک پڑھ سکتے ہیں۔ اس سے آگے نہیں۔",
        URDU_VOICE,
    ),
}

EXCLUDED_DIR_PARTS = {"_templates", "_reports", "node_modules", ".vitepress", ".github"}
EXCLUDED_NAMES = {"README.md", "INTERVIEW_INDEX.md", "STUDY-PLAN.md", "PUBLISH-PLAN.md"}

# Sections whose bodies are links, URLs or navigation -- nothing speakable.
SKIP_SECTIONS = {"contents", "sources", "cross-references"}

SYMBOL_WORDS = {
    "→": " to ",          # →
    "←": " back to ",     # ←
    "↔": " to and from ", # ↔
    "⇒": " implies ",     # ⇒
    "≈": " approximately ",
    "≠": " not equal to ",
    "≤": " at most ",
    "≥": " at least ",
    "×": " times ",       # ×
    "÷": " divided by ",  # ÷
    "±": " plus or minus ",
    "–": ", ",            # en dash
    "—": ", ",            # em dash
    "…": ". ",            # ellipsis
    "•": ", ",            # bullet
    "·": ", ",            # middle dot
    "›": ", ",            # ›
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    " ": " ",             # nbsp
    "‑": "-",             # non-breaking hyphen
}


# --------------------------------------------------------------------------
# Stripping
# --------------------------------------------------------------------------

def strip_emoji(text: str) -> str:
    """Drop pictographs but keep ordinary punctuation and letters."""
    out = []
    for ch in text:
        if ch in ("\n", "\t"):
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        # So = "Symbol, other" -- emoji, arrows already handled, box drawing.
        if cat in ("So", "Cf", "Sk"):
            continue
        out.append(ch)
    return "".join(out)


def is_ascii_art(line: str) -> bool:
    """Diagram rows that escaped a code fence (box drawing, rules, arrows)."""
    stripped = line.strip()
    if not stripped:
        return False
    arty = sum(1 for c in stripped if c in "─│┌┐└┘├┤┬┴┼━┃╔╗╚╝║═▄▀█▓▒░+-|_=*^v<>/\\ ")
    return arty / len(stripped) > 0.75 and len(stripped) > 8


LINK_ONLY = re.compile(r"^\[[^\]]+\]\([^)]*\)$")


def render_table(rows: list[str]) -> list[str]:
    """
    Two-column tables become 'left, maps to, right' -- that shape is nearly
    always a mapping (the Newspaper analogy, comparison tables) and reads well.
    Wider tables are flattened to comma-joined cells, which is clunky but keeps
    the content; dropping them silently loses things like the prerequisite gate.
    Status/metadata tables carry no spoken value and are skipped.
    """
    cells = []
    for row in rows:
        parts = [p.strip() for p in row.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", p) for p in parts if p):
            continue  # separator row
        cells.append(parts)
    if not cells:
        return []

    header = [c.lower() for c in cells[0]]
    if "status" in header and ("priority" in header or "phase" in header):
        return []

    out = []
    for i, parts in enumerate(cells):
        if i == 0:
            continue  # header
        # Nav columns are pure links; drop them rather than reading them out.
        kept = [p for p in parts if p and not LINK_ONLY.fullmatch(p)]
        kept = [strip_emoji(inline_clean(p)).strip() for p in kept]
        kept = [p for p in kept if p]
        if not kept:
            continue
        if len(kept) == 2 and re.fullmatch(r"\d+", kept[0]):
            # Numbered list rendered as a table -- "3, maps to, ..." is wrong.
            body = kept[1]
            out.append(f"{kept[0]}. {body}" + ("" if body[-1] in ".!?" else "."))
        elif len(kept) == 2:
            out.append(f"{kept[0]}, maps to, {kept[1]}.")
        else:
            out.append(", ".join(kept).rstrip(".") + ".")
    return out


def inline_clean(text: str) -> str:
    """Markdown inline syntax -> plain words."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)       # links -> label
    text = re.sub(r"<https?://[^>]+>", "", text)
    text = re.sub(r"https?://\S+", "", text)
    # Pad inline code with spaces. Removing the backticks bare glued words to
    # what followed -- "a small `.NET` consumer" became "small.NET", which the
    # pronunciation map then rendered as "smalldot NET". Surrounding whitespace
    # is collapsed later, so the padding is free.
    text = re.sub(r"`{1,3}([^`]*)`{1,3}", r" \1 ", text)
    text = re.sub(r"\*\*\*([^*]+)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)                        # stray html
    return text


# Phrases that only make sense to a reader looking at a page. In audio they
# point at nothing, so they are the main thing that makes narration feel like
# a document being read out rather than someone explaining.
DEICTIC = [
    (re.compile(r",?\s*\bas (?:shown|illustrated|described) (?:above|below|here)\b", re.I), ""),
    (re.compile(r",?\s*\bsee the (?:table|diagram|figure|code|example) (?:above|below)\b", re.I), ""),
    (re.compile(r",?\s*\bin the (?:table|diagram|figure) (?:above|below)\b", re.I), ""),
    (re.compile(r"\bthe (?:table|diagram|figure|code sample|snippet) (?:above|below)\b", re.I), "this"),
    (re.compile(r"\b(?:above|below)\b(?=[,.\s])", re.I), ""),
    (re.compile(r"\bClick to expand\b.*", re.I), ""),
    (re.compile(r"\bthis file\b", re.I), "this session"),
    (re.compile(r"\bread (?:on|this section)\b", re.I), "listen on"),
]


@dataclass
class Stripped:
    title: str
    text: str
    words: int
    outline: list[str]


def strip_markdown(md: str, source: Path) -> Stripped:
    lines = md.replace("\r\n", "\n").split("\n")
    title = ""
    out: list[str] = []

    in_fence = False
    fence_marker = ""
    in_nav_footer = False
    skipping_section = False
    table_buffer: list[str] = []
    outline: list[str] = []
    section_no = 0
    in_core_concepts = False

    def flush_table():
        nonlocal table_buffer
        if table_buffer:
            out.extend(render_table(table_buffer))
            table_buffer = []

    for raw in lines:
        line = raw.rstrip()

        # Fenced blocks: code, mermaid, ASCII diagrams. Dropped wholesale.
        fence = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            marker = fence.group(1)[:3]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence = False
                out.append("")  # a beat of silence where the diagram was
            continue
        if in_fence:
            continue

        # Nav footer region
        if "nav-footer-start" in line:
            in_nav_footer = True
            continue
        if "nav-footer-end" in line:
            in_nav_footer = False
            continue
        if in_nav_footer:
            continue

        if line.strip().startswith("<!--"):
            continue

        # Headings drive section skipping and spoken structure.
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_table()
            level, htext = len(heading.group(1)), inline_clean(heading.group(2)).strip()
            # Strip trailing decoration only. Stripping leading '.' turned the
            # ".NET consumer template" heading into "NET consumer template" --
            # the pronunciation map handles ".NET" correctly if we leave it be.
            htext = strip_emoji(htext).rstrip(" .-–—").lstrip(" -–—")
            if level == 1:
                title = htext
                continue
            key = re.sub(r"[^a-z ]", "", htext.lower()).strip().replace(" ", "-")
            # "Walkthrough — Replaying a topic" -> match on the leading word too
            first_word = htext.lower().split()[0].strip(":—-") if htext else ""
            if key in SKIP_SECTIONS or first_word in SKIP_SECTIONS:
                skipping_section = True
                continue
            skipping_section = False
            if not htext:
                continue

            if level == 2:
                in_core_concepts = htext.lower().startswith("core concept")
                section_no += 1
                outline.append(htext)
                # A spoken "Section N" beats a bare heading -- in audio there
                # is no visual cue that a new part has started.
                out.extend(["", SECTION_MARK, f"Section {section_no}. {htext}.", ""])
            else:
                # H3s under Core concepts are the actual lesson content, so they
                # earn a place in the spoken contents; drill/other H3s do not.
                if in_core_concepts:
                    outline.append(f"    {htext}")
                # Tagged so hollow ones can be dropped later -- a heading whose
                # body was entirely a code block announces nothing.
                out.extend(["", SECTION_MARK, f"{HEADING_MARK}{htext}.", ""])
            continue

        # Anything before the first H2 is front matter -- breadcrumb, status
        # table, cross-link banner. None of it belongs after "Let's begin."
        if section_no == 0:
            continue

        if skipping_section:
            continue

        # <details>/<summary>: unwrap the block, drop the teaser line.
        low = line.strip().lower()
        if low.startswith("<details") or low.startswith("</details"):
            continue
        if low.startswith("<summary"):
            continue

        # Tables accumulate so we can decide 2-col vs wide.
        if line.strip().startswith("|"):
            table_buffer.append(line)
            continue
        flush_table()

        # Breadcrumb
        if line.strip().startswith("> [") and "Mastery Guide" in line:
            continue

        # Horizontal rules
        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            out.append("")
            continue

        if is_ascii_art(line):
            continue

        # Blockquote and list markers: drop the marker, keep the words.
        body = re.sub(r"^\s*>\s?", "", line)
        body = re.sub(r"^\s*[-*+]\s+", "", body)
        body = re.sub(r"^\s*\d+[.)]\s+", "", body)
        body = re.sub(r"^\s*\[[ xX]\]\s*", "", body)

        body = inline_clean(body)
        body = strip_emoji(body)
        body = body.strip()

        if not body:
            out.append("")
            continue

        # Give every fragment terminal punctuation so the voice stops -- but
        # look past a closing quote or bracket so we don't produce '?".'
        if body.rstrip('"\')') and body.rstrip('"\')')[-1] not in ".!?:;,":
            body += "."

        # A drill question must be followed by thinking time. Reading the answer
        # straight afterwards defeats the entire point of a drill -- the guide
        # itself says "cover the answers, write them cold".
        if QUESTION_LINE.match(body):
            body = QUESTION_MARK + body
        out.append(body)

    flush_table()

    out = drop_hollow_headings(out)
    out, outline = drop_hollow_sections(out, outline)
    out = [l.replace(HEADING_MARK, "") for l in out]

    text = "\n".join(out)
    for pattern, replacement in DEICTIC:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"[ \t]+([,;:])", r"\1", text)
    # Only close up space before a full stop that actually ends a sentence.
    # Matching every '.' glued "For .NET" into "For.NET", which the pronunciation
    # map then read as "Fordot NET".
    text = re.sub(r"[ \t]+\.(?![A-Za-z])", ".", text)
    text = split_long_lines(text)
    text = text.strip()

    if not title:
        title = source.stem.replace("-", " ").title()

    words = len([w for w in text.split() if w != SECTION_MARK])
    return Stripped(title=title, text=text, words=words, outline=outline)


# --------------------------------------------------------------------------
# Pronunciation
# --------------------------------------------------------------------------

META_KEYS = {"_comment", "_caseInsensitive"}


def load_pronunciation():
    if not PRONUNCIATION_FILE.exists():
        return [], [], [], []
    data = json.loads(PRONUNCIATION_FILE.read_text(encoding="utf-8"))
    ci_keys = {k.lower() for k in data.get("_caseInsensitive", [])}
    # Only the two known meta keys are excluded -- real entries such as
    # __cluster_metadata also start with an underscore.
    entries = [(k, v) for k, v in data.items() if k not in META_KEYS]
    # Longest first so ASP.NET beats .NET.
    entries.sort(key=lambda kv: len(kv[0]), reverse=True)

    # "Log end offset (LEO)" should not become "log end offset (log end offset)".
    # Where an abbreviation expands to words the text has just said, drop the
    # parenthetical gloss before expansion happens.
    gloss = []
    for key, val in entries:
        if key.isupper() and len(key) > 1 and " " in val:
            gloss.append(re.compile(
                rf"(\b{re.escape(val)})\s*\(\s*{re.escape(key)}\s*\)", re.IGNORECASE))

    def compile_rule(key: str, insensitive: bool) -> re.Pattern:
        esc = re.escape(key)
        # Word boundaries only where the edge char is word-ish; otherwise the
        # boundary can never match (e.g. ".NET" starts with a non-word char).
        left = r"\b" if key[0].isalnum() else ""
        right = r"\b" if key[-1].isalnum() else ""
        flags = re.IGNORECASE if insensitive else 0
        return re.compile(left + esc + right, flags)

    sensitive, insensitive, slashed = [], [], []
    for key, val in entries:
        # Entries containing '/' must be applied before the generic slash rule,
        # or "msgs/min" is turned into "msgs or min" and this entry can never
        # match. Kept in their own list purely for ordering.
        if "/" in key:
            slashed.append((compile_rule(key, key.lower() in ci_keys), val))
        elif key.lower() in ci_keys:
            insensitive.append((compile_rule(key, True), val))
        else:
            sensitive.append((compile_rule(key, False), val))
    return sensitive, insensitive, gloss, slashed


# Dotted config identifiers -- unclean.leader.election.enable, EnableRetryOnFailure
# style keys -- are read as one run-on word or as literal "dot"s. Spacing them
# out fixes every Kafka/EF/ASP.NET setting at once, no dictionary entry needed.
# Every segment must be alphabetic, which leaves version numbers (4.0, 3.9, 11.5)
# and decimals alone.
DOTTED_KEY = re.compile(r"\b([a-z][a-z_]*(?:\.[a-z][a-z_]*){2,})\b")

# Longest line measured in the generated text was 1,885 characters -- roughly two
# minutes of unbroken speech. edge-tts has no SSML, so a pause can only come from
# a sentence boundary, and a line that long simply never gives the voice one.
MAX_LINE = 300
# Urdu terminates sentences with '۔'; English with . ! ? -- handle both, since
# splitting Urdu on '.' finds nothing (it contains zero Latin full stops).
SENTENCE_END = re.compile(r"(?<=[.!?۔])\s+")
# Fallbacks for a single sentence that is still too long. Semicolons and colons
# first (a real structural break), commas only as a last resort.
CLAUSE_STRONG = re.compile(r"(?<=[;:؛])\s+")
CLAUSE_SOFT = re.compile(r"(?<=[,،])\s+")

# Drill questions, in the guide's Q / Cross-Q / Cross-Q² format, and numbered
# self-test items. These get thinking time spliced in after them.
QUESTION_LINE = re.compile(r"^(Q:|Cross-Q[²2]?:|Second follow-up:|First follow-up:)", re.I)

# camelCase identifiers in prose ("customerId") are read as one mashed word.
CAMEL_CASE = re.compile(r"\b([a-z]+)([A-Z][a-z]+)\b")

# Assignments lose the '=' entirely: "enable.idempotence=true" is spoken as
# "enable idempotence true", which inverts the meaning of a config example.
ASSIGNMENT = re.compile(r"(?<=[A-Za-z0-9.\]])=(?=[A-Za-z0-9])")

# Slashes glue words together. Must run BEFORE the pronunciation map, or "S3/Blob"
# has already become "S three/Blob" and the seam is invisible.
SLASH_PAIR = re.compile(r"(?<=[A-Za-z0-9])/(?=[A-Za-z0-9])")

# The dictionary expands "GB" to "gigabytes" regardless of count, so "1 GB"
# became "1 gigabytes". Applied after the dictionary, not before.
SINGULAR_UNIT = re.compile(
    r"\b1 (millisecond|second|minute|hour|day|week|byte|kilobyte|megabyte"
    r"|gigabyte|terabyte|partition|replica|broker|consumer|producer|time)s\b")


def _greedy_join(pieces: list[str], limit: int, min_piece: int = 60) -> list[str]:
    """Pack pieces into lines under the limit, avoiding stranded fragments."""
    out: list[str] = []
    current = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if current and len(current) + len(piece) + 1 > limit:
            out.append(current)
            current = piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        # A tiny tail reads as an abrupt stub, so fold it back -- but never past
        # the limit, which is what left one line at 303 characters.
        if out and len(current) < min_piece and len(out[-1]) + len(current) + 1 <= limit:
            out[-1] = f"{out[-1]} {current}"
        else:
            out.append(current)
    return out


def split_long_lines(text: str, limit: int = MAX_LINE) -> str:
    """
    Break over-long lines so the voice can breathe.

    Three passes, weakest cut last. Sentence boundaries are always preferred;
    only a single sentence that is still too long falls through to clause
    boundaries. A comma or semicolon already implies a pause, so promoting one
    to a line break lengthens a pause that belongs there rather than inventing
    one mid-thought.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if len(line) <= limit or line.strip() == SECTION_MARK:
            out.append(line)
            continue

        for chunk in _greedy_join(SENTENCE_END.split(line), limit):
            if len(chunk) <= limit:
                out.append(chunk)
                continue
            # Still too long: one very long sentence. Try strong clause marks.
            strong = _greedy_join(CLAUSE_STRONG.split(chunk), limit)
            if all(len(c) <= limit for c in strong):
                out.extend(strong)
                continue
            # Last resort: commas. Beyond this the run is genuinely unbreakable
            # and mangling it would be worse than a long breath.
            out.extend(_greedy_join(CLAUSE_SOFT.split(chunk), limit))
    return "\n".join(out)

# "30s" / "500ms" / "7d" attached to a number -- expanded before the dictionary
# runs, since a bare "s" or "d" entry would wreck ordinary words.
NUMERIC_UNITS = [
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*ms\b"), "millisecond"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*s\b"), "second"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*h\b"), "hour"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*d\b"), "day"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*x\b", re.IGNORECASE), "time"),
]


def _unit_sub(unit: str):
    """Pluralise only when the count is not exactly 1 -- '1 gigabytes' was wrong."""
    def repl(m):
        n = m.group(1)
        return f"{n} {unit}" if n in ("1", "1.0") else f"{n} {unit}s"
    return repl


def apply_pronunciation(text: str, rules) -> str:
    sensitive, insensitive, gloss, slashed = rules
    # Symbols run here rather than in the stripper so the spoken intro, which
    # is assembled later from heading text, gets the same treatment.
    for sym, word in SYMBOL_WORDS.items():
        text = text.replace(sym, word)

    # Slash-bearing dictionary entries first ("msgs/min" -> "messages per
    # minute"), then the generic slash rule for everything left over.
    for pattern, replacement in slashed:
        text = pattern.sub(replacement.replace("\\", r"\\"), text)
    text = text.replace("I/O", "I O")
    text = SLASH_PAIR.sub(" or ", text)
    text = ASSIGNMENT.sub(" set to ", text)
    text = CAMEL_CASE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)

    for pattern in gloss:
        text = pattern.sub(r"\1", text)
    for pattern, unit in NUMERIC_UNITS:
        text = pattern.sub(_unit_sub(unit), text)
    text = DOTTED_KEY.sub(lambda m: m.group(1).replace(".", " ").replace("_", " "), text)
    for pattern, replacement in sensitive:
        text = pattern.sub(replacement.replace("\\", r"\\"), text)
    for pattern, replacement in insensitive:
        text = pattern.sub(replacement.replace("\\", r"\\"), text)

    # Tidy up after substitution: " — " becomes " ,  " without this, and two
    # adjacent section markers would stack into a two-second dead spot.
    text = SINGULAR_UNIT.sub(r"1 \1", text)
    text = re.sub(rf"(?:{re.escape(SECTION_MARK)}\s*){{2,}}", SECTION_MARK + "\n", text)
    # Only close up space before punctuation that ENDS a clause. '?' also opens
    # a query string, and stripping the space there produced "pagination.?page".
    text = re.sub(r"[ \t]+([,;:])", r"\1", text)
    text = re.sub(r"[ \t]+([!?])(?=\s|$)", r"\1", text)
    # Same trap as in the stripper: only close up space before a sentence-ending
    # full stop, never before a leading-dot identifier like .index or .NET.
    text = re.sub(r"[ \t]+\.(?![A-Za-z])", ".", text)
    text = re.sub(r"([,;:])\s*\1+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

SMALL_WORDS = {"and", "or", "the", "a", "an", "of", "in", "on", "to", "for", "with", "vs"}


def smart_title(text: str) -> str:
    words = text.split()
    return " ".join(
        w.lower() if i and w.lower() in SMALL_WORDS else w[:1].upper() + w[1:]
        for i, w in enumerate(words)
    )


def chapter_label(path: Path) -> str:
    if not path.is_relative_to(GUIDE_ROOT):
        return "Mastery Guide"
    rel = path.relative_to(GUIDE_ROOT)
    top = rel.parts[0] if len(rel.parts) > 1 else "Mastery Guide"
    return smart_title(re.sub(r"^\d+-", "", top).replace("-", " "))


def collect_files(args) -> list[Path]:
    if args.file:
        p = Path(args.file)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if not p.exists():
            sys.exit(f"No such file: {p}")
        return [p]

    if args.index_only:
        return [GUIDE_ROOT / "INTERVIEW_INDEX.md"]

    root = GUIDE_ROOT
    if args.chapter:
        matches = sorted(d for d in GUIDE_ROOT.iterdir()
                         if d.is_dir() and d.name.startswith(args.chapter))
        if not matches:
            sys.exit(f"No chapter directory starting with {args.chapter!r}")
        root = matches[0]

    files = []
    for p in sorted(root.rglob("*.md")):
        if any(part in EXCLUDED_DIR_PARTS for part in p.parts):
            continue
        if p.name in EXCLUDED_NAMES:
            continue
        files.append(p)
    return files


def output_paths(src: Path) -> tuple[Path, Path]:
    # Language at the top level (audio/en, audio/ur) so each one is a single
    # self-contained folder to copy to a phone or point a player at.
    root = AUDIO_ROOT / "en"
    if src.name == "INTERVIEW_INDEX.md":
        base = root / "INTERVIEW_INDEX"
    else:
        base = root / src.relative_to(GUIDE_ROOT).with_suffix("")
    return base.with_suffix(".mp3"), base.with_suffix(".txt")


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------

# A silent MPEG-2 Layer III frame matching edge-tts output (24 kHz, 48 kbps,
# mono). edge_tts exposes only rate/volume/pitch -- no SSML, so <break> is not
# available and real pauses have to be spliced in as audio. All-zero main data
# decodes to silence, and since we already concatenate frames this drops in
# cleanly without ffmpeg.
#   byte0 FF          sync
#   byte1 F3          sync + MPEG-2 + Layer III + no CRC
#   byte2 64          bitrate index 6 (48 kbps), sample-rate index 1 (24 kHz)
#   byte3 C0          mono
_SILENT_FRAME = bytes([0xFF, 0xF3, 0x64, 0xC0]) + bytes(140)
_FRAMES_PER_SEC = 24000 / 576  # MPEG-2 LSF Layer III: 576 samples per frame

# Measured from generated output: 48 kbps CBR exactly. Because it is constant,
# byte length and duration are interchangeable, which is what lets the size cap
# and the spoken timestamps both be exact.
BYTES_PER_SEC = 6006
SIZE_CAP = 15_000_000          # 15 MB, decimal reading -- ~41 min per part
# The spoken contents is prepended AFTER packing, so its size has to be held
# back or a part lands over the cap -- part 1 came out at 15.64 MB before this.
# Part 1's intro is the longest: every sub-topic plus a spoken timestamp each.
#
# It has to be a constant rather than a measurement, because packing decides
# the groups and the intro cannot be built until the groups exist. So the
# figure must exceed the largest intro any file will produce. 1.5 MB was not
# enough -- 14-bff-and-aggregation, 17 sections across 5 parts, produced a
# ~1.52 MB intro and landed 21 KB over. 2 MB covers that with headroom; the
# cost is ~1.4 min of packing efficiency per part, which is invisible.
#
# A breach is still reported at the end of a run, so if a future chapter
# overruns this too, it shows up rather than shipping quietly.
INTRO_RESERVE = 2_000_000
SECTION_PAUSE = 0.9            # beat between sections
QUESTION_PAUSE = 5.0           # thinking time after a drill question
TRAIL_SILENCE = 1.0            # players and BT codecs clip the final moment


def silence(seconds: float) -> bytes:
    return _SILENT_FRAME * max(1, round(seconds * _FRAMES_PER_SEC))


# Section headings are emitted by the stripper surrounded by blank lines, which
# edge-tts collapses. This marker survives chunking so we know where to splice.
# Plain ASCII rather than a control character, so the .txt sidecar stays a text
# file that grep and an editor will handle.
SECTION_MARK = "@@SECTION@@"
# Tags a sub-heading so a post-pass can drop it if nothing speakable follows.
HEADING_MARK = "@@HEAD@@"
# Marks a drill question, after which a long silence is spliced so the listener
# can actually attempt an answer instead of being handed one.
QUESTION_MARK = "@@Q@@"


SECTION_LINE = re.compile(r"^Section (\d+)\. (.*)$")


def drop_hollow_sections(lines: list[str], outline: list[str]) -> tuple[list[str], list[str]]:
    """
    Drop top-level sections that announce themselves and then say nothing, and
    renumber what survives.

    "Code & diagrams" is the usual culprit: its body is entirely code blocks and
    mermaid, all of which the stripper removes, so the listener hears "Section 3.
    Code and diagrams." followed immediately by Section 4. Sub-headings are
    handled by drop_hollow_headings; this is the H2 case, which also has to fix
    up numbering and the spoken contents so they stay in step.
    """
    keep = [True] * len(lines)
    dropped: set[str] = set()

    for i, line in enumerate(lines):
        m = SECTION_LINE.match(line.strip())
        if not m:
            continue
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt or nxt == SECTION_MARK:
                continue
            if SECTION_LINE.match(nxt):      # next real content is another section
                keep[i] = False
                dropped.add(m.group(2).rstrip("."))
            break
        else:
            keep[i] = False
            dropped.add(m.group(2).rstrip("."))

    if not dropped:
        return lines, outline

    kept = [l for i, l in enumerate(lines) if keep[i]]
    renumbered, n = [], 0
    for l in kept:
        m = SECTION_LINE.match(l.strip())
        if m:
            n += 1
            renumbered.append(f"Section {n}. {m.group(2)}")
        else:
            renumbered.append(l)

    # The spoken contents is built from the outline, so it has to lose the same
    # entries or it promises sections the listener never reaches.
    new_outline = [h for h in outline
                   if h.startswith("    ") or h.rstrip(".") not in dropped]
    return renumbered, new_outline


def drop_hollow_headings(lines: list[str]) -> list[str]:
    """
    Remove sub-headings with no spoken body.

    "Topic + partitions + offsets visualized." announced a section whose entire
    content was an ASCII diagram, so the listener hears a title followed by
    silence. Cleans up most of the Code & diagrams section without special-casing.
    """
    keep = [True] * len(lines)
    for i, line in enumerate(lines):
        if not line.startswith(HEADING_MARK):
            continue
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt or nxt == SECTION_MARK:
                continue
            # Next real content is another heading -> this one is hollow.
            if nxt.startswith(HEADING_MARK) or nxt.startswith("Section "):
                keep[i] = False
            break
        else:
            keep[i] = False  # nothing at all after it
    return [l for i, l in enumerate(lines) if keep[i]]


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """
    Split into synthesis-sized pieces. SECTION_MARK always forces a boundary
    so a pause can be spliced there; it is returned as its own chunk and never
    sent to the service.
    """
    chunks, current = [], ""

    def flush():
        nonlocal current
        if current.strip():
            chunks.append(current)
        current = ""

    for para in text.split("\n"):
        if para.strip() == SECTION_MARK:
            flush()
            chunks.append(SECTION_MARK)
            continue
        if len(current) + len(para) + 1 > limit and current:
            flush()
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    flush()
    return [c for c in chunks if c.strip()]


async def tts_bytes(text: str, voice: str, rate: str) -> bytes:
    """Synthesize one chunk, retrying through the free endpoint's rate limits."""
    import edge_tts

    for attempt in range(4):
        try:
            buf = bytearray()
            comm = edge_tts.Communicate(text, voice, rate=rate)
            async for packet in comm.stream():
                if packet["type"] == "audio":
                    buf.extend(packet["data"])
            return bytes(buf)
        except Exception as exc:  # rate limit / transient network
            if attempt == 3:
                raise
            wait = 2 ** attempt
            print(f"      retry in {wait}s ({exc.__class__.__name__})", flush=True)
            await asyncio.sleep(wait)
    return b""


# Pronunciation spellings are for the voice, not the eye. "SASL" is deliberately
# written "sassle" so it isn't spelled out letter by letter, but a chapter title
# reading "Security (sassle + ACLs + T L S)" just looks broken in the player.
DISPLAY_FIXES = [
    (re.compile(r"\bsassle\b"), "SASL"),
    (re.compile(r"\bI S R\b"), "ISR"),
    (re.compile(r"\bD L Q\b"), "DLQ"),
    (re.compile(r"\bT L S\b"), "TLS"),
    (re.compile(r"\bA P I\b"), "API"),
    (re.compile(r"\bC P U\b"), "CPU"),
    (re.compile(r"\bK raft\b"), "KRaft"),
    (re.compile(r"\bk sequel D B\b"), "ksqlDB"),
    (re.compile(r"\bdot NET\b"), ".NET"),
    (re.compile(r"\bsequel\b"), "SQL"),
]


def display_title(text: str) -> str:
    """Undo speech spellings for text a player will show rather than speak."""
    for pattern, replacement in DISPLAY_FIXES:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class Segment:
    """One section's audio, measured. Bitrate is constant CBR, so len(audio)
    is an exact duration -- that is what makes size-capped packing and spoken
    timestamps precise rather than estimated."""
    title: str
    audio: bytes

    @property
    def seconds(self) -> float:
        return len(self.audio) / BYTES_PER_SEC


async def synthesize_segments(text: str, voice: str, rate: str) -> list[Segment]:
    """
    Synthesize section by section, keeping each one measured and separate.

    Everything downstream -- the 15 MB cap, part boundaries that never cut mid
    concept, and accurate spoken timestamps -- depends on knowing exact sizes
    before assembly. MP3 frames concatenate cleanly, so segments join later
    without ffmpeg and without re-synthesis.
    """
    segments: list[Segment] = []
    current = bytearray()
    title = ""

    for chunk in chunk_text(text):
        stripped = chunk.strip()
        if stripped == SECTION_MARK:
            if current:
                segments.append(Segment(title, bytes(current)))
                current = bytearray()
            current.extend(silence(SECTION_PAUSE))
            title = ""
            continue

        # Thinking time after a drill question, before its answer.
        pieces = chunk.split(QUESTION_MARK)
        for i, piece in enumerate(pieces):
            if i:
                current.extend(silence(QUESTION_PAUSE))
            if piece.strip():
                current.extend(await tts_bytes(piece, voice, rate))

        if not title:
            first = stripped.replace(QUESTION_MARK, "").lstrip().split("\n")[0]
            title = display_title(first.rstrip(".").strip())

    if current:
        segments.append(Segment(title, bytes(current)))
    return segments


async def synthesize(text: str, dest: Path, voice: str, rate: str) -> None:
    """Single-file synthesis, used by --speak-file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    segments = await synthesize_segments(text, voice, rate)
    tmp = dest.with_suffix(".part")
    with tmp.open("wb") as fh:
        for seg in segments:
            fh.write(seg.audio)
        fh.write(silence(TRAIL_SILENCE))
    tmp.replace(dest)


def pack_parts(segments: list[Segment], cap: int = SIZE_CAP) -> list[list[Segment]]:
    """
    Greedy-pack sections into parts under the size cap, breaking only at a
    section start -- a part never cuts through the middle of a concept.

    A single section larger than the cap gets its own part and exceeds it;
    splitting mid-explanation would be worse than a slightly large file, and
    the caller reports it.
    """
    parts: list[list[Segment]] = []
    current: list[Segment] = []
    running = 0
    for seg in segments:
        size = len(seg.audio)
        if current and running + size > cap:
            parts.append(current)
            current, running = [], 0
        current.append(seg)
        running += size
    if current:
        parts.append(current)
    return parts


def write_chapters(dest: Path, marks: list[tuple[str, float, float]]) -> None:
    """
    Embed ID3 chapter markers so the player offers a tappable list -- strictly
    better than scrubbing to a spoken timestamp. Voice and AntennaPod both read
    these; players that don't simply ignore them.
    """
    try:
        from mutagen.id3 import ID3, CHAP, CTOC, TIT2, CTOCFlags
    except ImportError:
        return
    if not marks:
        return
    try:
        tags = ID3(dest)
    except Exception:
        return
    ids = []
    for i, (title, start, end) in enumerate(marks):
        cid = f"ch{i}"
        ids.append(cid)
        tags.add(CHAP(element_id=cid, start_time=int(start * 1000),
                      end_time=int(end * 1000),
                      sub_frames=[TIT2(encoding=3, text=title)]))
    tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                  child_element_ids=ids,
                  sub_frames=[TIT2(encoding=3, text="Contents")]))
    tags.save(dest, v2_version=3)


def tag(dest: Path, title: str, album: str, track: int) -> None:
    """
    Write ID3v2.3 tags. edge-tts emits a bare MP3 stream with no tag header,
    so we always build the frames from scratch rather than trying to load
    existing ones. v2.3 rather than v2.4 -- markedly better support across
    Android players including AntennaPod.
    """
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TALB, TPE1, TPE2, TRCK
    except ImportError:
        return
    try:
        tags = ID3(dest)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=title)])
    tags.setall("TALB", [TALB(encoding=3, text=album)])
    tags.setall("TPE1", [TPE1(encoding=3, text=".NET Mastery Guide")])
    tags.setall("TPE2", [TPE2(encoding=3, text=".NET Mastery Guide")])
    tags.setall("TRCK", [TRCK(encoding=3, text=str(track))])
    tags.save(dest, v2_version=3)


ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth",
            "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh", "Twelfth"]

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
                12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}


# Spoken scaffolding per language. The Urdu tracks must not narrate their
# structure in English -- a listener gets "Part one of three" in a different
# language from everything around it, which is jarring and defeats the point.
INTRO_L10N = {
    "en": {
        "part_of":  "Part {part} of {total}.",
        "from":     "From the chapter on {album}.",
        "continue": "Continuing on from {prev}.",
        "runs":     "This part runs about {mins} minutes.",
        "cover":    "Here is what we are going to cover.",
        "core":     "The core concepts section covers {n} topics, in order.",
        "begin":    "Let's begin.",
        "start":    "the start",
        "min":      "{n} minute", "mins": "{n} minutes",
        "sec":      "{n} seconds in", "min_sec": "{m} minutes {s} seconds in",
    },
    "ur": {
        "part_of":  "حصہ {part} از {total}۔",
        "from":     "{album} کے باب سے۔",
        "continue": "{prev} سے آگے۔",
        "runs":     "یہ حصہ تقریباً {mins} منٹ کا ہے۔",
        "cover":    "آئیے دیکھتے ہیں کہ ہم کیا کیا کور کریں گے۔",
        "core":     "بنیادی تصورات کا سیکشن {n} موضوعات پر مشتمل ہے۔",
        "begin":    "تو آغاز کرتے ہیں۔",
        "start":    "شروع سے",
        "min":      "{n} منٹ پر", "mins": "{n} منٹ پر",
        "sec":      "{n} سیکنڈ پر", "min_sec": "{m} منٹ {s} سیکنڈ پر",
    },
}

URDU_ORDINALS = ["پہلا", "دوسرا", "تیسرا", "چوتھا", "پانچواں", "چھٹا",
                 "ساتواں", "آٹھواں", "نواں", "دسواں", "گیارہواں", "بارہواں"]


def lang_of(voice: str) -> str:
    return "ur" if voice.startswith("ur-") else "en"


def spoken_time(seconds: float, lang: str = "en") -> str:
    """'4 minutes 12 seconds in', or 'the start' -- spoken, not displayed."""
    L = INTRO_L10N[lang]
    s = int(round(seconds))
    if s < 5:
        return L["start"]
    m, sec = divmod(s, 60)
    if not m:
        return L["sec"].format(n=sec)
    if not sec:
        return (L["min"] if m == 1 else L["mins"]).format(n=m)
    return L["min_sec"].format(m=m, s=sec)


def build_intro(title: str, album: str, tops: list[str], subs: list[str],
                minutes: float, part: int = 1, parts: int = 1,
                offsets: dict[str, float] | None = None,
                prev_section: str | None = None, lang: str = "en") -> str:
    """
    The spoken contents. Without it the audio is a document read aloud -- no map
    of where you are or what is coming.

    Each entry goes on its own line ending in a full stop, which is the only way
    to get a pause between them: edge-tts has no SSML, so punctuation is the
    sole prosody control. Joining them with semicolons produced one unbroken
    run of eleven topics.

    `offsets` maps section title -> seconds from the start of THIS part, so the
    listener can skip straight to a concept.
    """
    L = INTRO_L10N[lang]
    ords = URDU_ORDINALS if lang == "ur" else ORDINALS

    lines = [f"{title}."]
    if parts > 1:
        lines.append(L["part_of"].format(
            part=NUMBER_WORDS.get(part, part) if lang == "en" else part,
            total=NUMBER_WORDS.get(parts, parts) if lang == "en" else parts))
    lines.append(L["from"].format(album=album))
    if prev_section:
        lines.append(L["continue"].format(prev=prev_section))
    lines.append(L["runs"].format(mins=round(minutes)))

    if tops:
        lines.append("")
        lines.append(L["cover"])
        for i, head in enumerate(tops):
            prefix = ords[i] if i < len(ords) else f"{i + 1}"
            when = ""
            if offsets is not None and head in offsets:
                when = f", {spoken_time(offsets[head], lang)}"
            lines.append(f"{prefix}, {head}{when}.")

    if subs:
        lines.append("")
        lines.append(L["core"].format(n=len(subs)))
        # One per line, numbered -- the run-on semicolon list was unlistenable.
        for i, sub in enumerate(subs, start=1):
            word = (URDU_ORDINALS[i - 1] if lang == "ur" and i <= len(URDU_ORDINALS)
                    else NUMBER_WORDS.get(i, str(i)).capitalize())
            lines.append(f"{word}. {sub.rstrip('.۔')}.")

    lines.append("")
    lines.append(L["begin"])
    return "\n".join(lines)


def duration_estimate(words: int, rate: str) -> float:
    """Minutes, accounting for the rate adjustment."""
    factor = 1.0
    m = re.fullmatch(r"([+-]\d+)%", rate.strip())
    if m:
        factor = 1 + int(m.group(1)) / 100
    return words / (WPM * factor)


# --------------------------------------------------------------------------

async def render_parts(*, body: str, stripped: Stripped, album: str, mp3: Path,
                       voice: str, rate: str, rules, cap: int
                       ) -> list[tuple[Path, float, int]]:
    """
    Synthesize the body once, pack it into size-capped parts, then give each
    part its own spoken contents with real timestamps.

    The body is synthesized before any intro exists, because the intro has to
    state where each section starts and that is unknowable until the sections
    have been measured.
    """
    segments = await synthesize_segments(body, voice, rate)
    if not segments:
        return []

    # Pack the body against a reduced cap so the spoken contents, prepended
    # later, still fits inside the real limit.
    groups = pack_parts(segments, max(cap - INTRO_RESERVE, cap // 2))
    total = len(groups)
    subs = [h.strip() for h in stripped.outline if h.startswith("    ")]
    written: list[tuple[Path, float, int]] = []
    prev_tail: str | None = None

    for idx, group in enumerate(groups, start=1):
        tops = [s.title for s in group if s.title]

        # The intro's own length shifts every timestamp inside it, so measure
        # it, recompute against the real length, and re-measure. Only the
        # numbers change size, so this converges immediately.
        intro_secs = 0.0
        intro_audio = b""
        for _ in range(3):
            offsets, running = {}, intro_secs
            for seg in group:
                if seg.title:
                    offsets[seg.title] = running
                running += seg.seconds
            text = build_intro(
                stripped.title, album, tops, subs if idx == 1 else [],
                minutes=running / 60, part=idx, parts=total,
                offsets=offsets, prev_section=prev_tail, lang=lang_of(voice))
            intro_audio = await tts_bytes(apply_pronunciation(text, rules), voice, rate)
            new_secs = len(intro_audio) / BYTES_PER_SEC
            if abs(new_secs - intro_secs) < 1.0:
                intro_secs = new_secs
                break
            intro_secs = new_secs

        # Timestamp in the filename so regenerations are distinguishable on the
        # phone at a glance, and an old copy is never silently mistaken for new.
        part_tag = "" if total == 1 else f"-part{idx}"
        dest = mp3.with_name(f"{mp3.stem}{part_tag}_{RUN_STAMP}{mp3.suffix}")
        dest.parent.mkdir(parents=True, exist_ok=True)

        marks, running = [], intro_secs
        with dest.open("wb") as fh:
            fh.write(intro_audio)
            fh.write(silence(SECTION_PAUSE))
            running += SECTION_PAUSE
            for seg in group:
                if seg.title:
                    marks.append((seg.title, running, running + seg.seconds))
                fh.write(seg.audio)
                running += seg.seconds
            fh.write(silence(TRAIL_SILENCE))
            running += TRAIL_SILENCE

        # Plain hyphen, not an em dash: ID3v2.3 mangles non-Latin-1 characters
        # in text frames and the title rendered as "Kafka <?> Part 1 of 3".
        title = stripped.title if total == 1 else f"{stripped.title} - Part {idx} of {total}"
        tag(dest, title, album, idx)
        write_chapters(dest, marks)
        written.append((dest, running, dest.stat().st_size))
        prev_tail = tops[-1] if tops else prev_tail

    return written


async def run_samples(voice_rate: str) -> None:
    dest_dir = AUDIO_ROOT / "_samples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    rules = load_pronunciation()
    text = apply_pronunciation(SAMPLE_TEXT, rules)

    print(f"Sample text ({len(text.split())} words)\n")

    print("Voices (at default rate):")
    for voice in SAMPLE_VOICES:
        print(f"  {voice} ...", flush=True)
        await synthesize(text, dest_dir / f"voice-{voice}.mp3", voice, voice_rate)

    # Slower is not automatically clearer -- past a point it drags and attention
    # drifts, which is worse for comprehension than a brisk delivery.
    print(f"\nRates (on {DEFAULT_VOICE}):")
    for rate in ("+0%", "-5%", "-10%"):
        label = rate.replace("+", "plus").replace("-", "minus").replace("%", "")
        print(f"  {rate} ...", flush=True)
        await synthesize(text, dest_dir / f"rate-{label}.mp3", DEFAULT_VOICE, rate)

    print(f"\nWritten to {dest_dir}")
    print("Pick a voice and a rate, then pass --voice / --rate.")


async def run_urdu_pilot() -> None:
    dest_dir = AUDIO_ROOT / "_samples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    rules = load_pronunciation()

    print("Urdu pilot -- same passage, three approaches:\n")
    notes = {
        "urdu-a-english-text": "Urdu voice reading the untranslated English",
        "urdu-b-full-urdu":    "translated to Urdu, Urdu script",
        "urdu-c-codeswitched": "Urdu structure, English technical terms",
    }
    for name, (text, voice) in URDU_SAMPLES.items():
        # Only variant A is English, so only A wants the pronunciation map.
        payload = apply_pronunciation(text, rules) if name.endswith("english-text") else text
        print(f"  {name:24} {notes[name]} ...", flush=True)
        await synthesize(payload, dest_dir / f"{name}.mp3", voice, "+0%")

    print(f"\nWritten to {dest_dir}")
    print("Judge on: could I follow 100 minutes of this and understand it")
    print("better than the English version?")


GLOSSARY_FILE = Path(__file__).resolve().parent / "urdu-glossary.json"


def load_glossary() -> dict:
    if not GLOSSARY_FILE.exists():
        sys.exit(f"Missing {GLOSSARY_FILE.name} -- needed for the Urdu pipeline.")
    return json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))


def plan_chunks(src: Path, target_lines: int = 60) -> list[dict]:
    """
    Work out translation chunk ranges from section boundaries.

    Hand-computing these was the first thing that would have gone wrong on a
    new chapter -- the ranges are chapter-specific and there is no way to eyeball
    them correctly. Boundaries land on 'Section N.' lines where possible so a
    chunk never splits an explanation across two translators.
    """
    lines = src.read_text(encoding="utf-8").split("\n")
    bounds = [i for i, l in enumerate(lines, start=1)
              if re.match(r"^Section \d+\.", l.strip())]
    bounds.append(len(lines) + 1)

    chunks, start, label = [], 1, "opening"
    for i, b in enumerate(bounds):
        if b - start >= target_lines and b > start:
            chunks.append({"from": start, "to": b - 1, "what": label})
            start = b
        if i < len(bounds) - 1:
            label = lines[b - 1].strip().rstrip(".")
    if start <= len(lines):
        chunks.append({"from": start, "to": len(lines), "what": label})

    # A section longer than the target still needs splitting, or one translator
    # is handed 300 lines while the rest get 40.
    out = []
    for c in chunks:
        span = c["to"] - c["from"] + 1
        if span <= target_lines * 1.8:
            out.append(c)
            continue
        pieces = max(2, round(span / target_lines))
        step = span // pieces
        for p in range(pieces):
            lo = c["from"] + p * step
            hi = c["to"] if p == pieces - 1 else lo + step - 1
            out.append({"from": lo, "to": hi, "what": f"{c['what']} (part {p + 1})"})
    for n, c in enumerate(out, start=1):
        c["n"] = n
    return out


def normalise_urdu_headings(text: str, gloss: dict) -> tuple[str, int]:
    """Force one spelling for Section/Drill headings and Urdu numerals throughout."""
    W = gloss["numerals"]
    w2n = {w: i for i, w in enumerate(W) if w}
    h = gloss["headings"]

    def num(tok):
        tok = tok.strip()
        return int(tok) if tok.isdigit() else w2n.get(tok, 0)

    def word(n, fallback):
        return W[n] if 0 < n < len(W) else fallback

    count = 0

    def sec(m):
        nonlocal count
        count += 1
        return f"{h['section']} {word(num(m.group(2)), m.group(2))}۔"

    def drill(m):
        nonlocal count
        count += 1
        return f"{h['drill']} {word(num(m.group(2)), m.group(2))}،"

    sec_alt = "|".join(re.escape(a) for a in h["sectionAliases"])
    dri_alt = "|".join(re.escape(a) for a in h["drillAliases"])
    text = re.sub(rf"\b({sec_alt})\s+([0-9]+|[؀-ۿ]+)\s*[.۔]", sec, text)
    text = re.sub(rf"\b({dri_alt})\s+([0-9]+|[؀-ۿ]+)\s*[,،]", drill, text)
    return text, count


def find_transliterated(text: str, gloss: dict) -> list[tuple[str, str, int]]:
    """
    Find English words spelled phonetically in Urdu letters.

    Returns (urdu_spelling, intended_english, count), longest key first so a
    compound like the two-word rendering of "timeout" is counted before its
    parts and not double-reported.

    A real Urdu word is NOT a violation -- translating "document" to the actual
    Urdu noun reads correctly. Only phonetic renderings of English are wrong,
    because the voice pronounces Urdu letters and the listener needs to hear
    the English term they will use in the interview.
    """
    table = gloss.get("transliterated") or {}
    found, seen = [], ""
    for urdu in sorted(table, key=len, reverse=True):
        n = text.count(urdu)
        if not n:
            continue
        # Skip anything already accounted for inside a longer match.
        if urdu in seen:
            continue
        seen += urdu + "|"
        found.append((urdu, table[urdu], n))
    return sorted(found, key=lambda x: -x[2])


def assemble_urdu(chunk_dir: Path, dest: Path, english: Path | None) -> int:
    """
    Concatenate translated chunks, normalise, split, and check parity.

    The parity check is the point. Marker counts matching the English is what
    proves the drill structure and section boundaries survived translation --
    it caught a real problem once, and as a manual step it would eventually be
    skipped. A mismatch now fails the build rather than shipping quietly.
    """
    gloss = load_glossary()
    parts = sorted(chunk_dir.glob("chunk-*.txt"))
    if not parts:
        sys.exit(f"No chunk-*.txt found in {chunk_dir}")

    text = "\n\n".join(p.read_text(encoding="utf-8").strip() for p in parts)
    text, fixed = normalise_urdu_headings(text, gloss)
    text = split_long_lines(text)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")

    lines = text.split("\n")
    over = sum(1 for l in lines if len(l) > MAX_LINE)
    print(f"assembled {len(parts)} chunks -> {dest}")
    print(f"  {len(text.split()):,} words | {len(lines)} lines | "
          f"{over} over {MAX_LINE} chars | {fixed} headings normalised")

    bad = False

    # English spelled in Urdu letters. The voice reads Urdu letters, so it
    # cannot say "document" from a phonetic rendering of it -- the exact bug
    # this pipeline exists to fix. Checked mechanically because self-reporting
    # does not work: a trial translation reported zero violations while writing
    # "dot" in Urdu script, so the repair stage never fired.
    hits = find_transliterated(text, gloss)
    if hits:
        total = sum(n for _, _, n in hits)
        print(f"\n  {total} transliterated English word(s), {len(hits)} distinct:")
        for urdu, english, n in hits:
            print(f"    {n:3}x  {urdu}  -> should be Latin: {english}")
        bad = True
    else:
        print("  transliteration  none found   ok")

    if english and english.exists():
        en = english.read_text(encoding="utf-8")
        for marker in gloss["markers"]:
            a, b = en.count(marker), text.count(marker)
            state = "ok" if a == b else "MISMATCH"
            print(f"  {marker:15} english {a:3}  urdu {b:3}   {state}")
            bad |= a != b

    if bad:
        print("\nFAILED: fix the chunks and re-assemble before generating audio.\n"
              "  - marker mismatch means the translation dropped or invented structure\n"
              "  - transliteration means a word will be mispronounced; it must be\n"
              "    written in Latin script to be spoken as the English word")
        return 1
    return 0


async def run_speak_file(args) -> int:
    """
    Synthesize an already-prepared text file verbatim.

    This is how the translated tracks work: the English run already emits a
    .txt sidecar of exactly what gets spoken, so a translation of that file is
    the whole Urdu pipeline -- no parallel markdown to maintain, no second
    stripper, and code blocks are already gone.
    """
    src = Path(args.speak_file)
    if not src.is_absolute():
        src = (REPO_ROOT / src).resolve()
    if not src.exists():
        sys.exit(f"No such file: {src}")

    dest = Path(args.out) if args.out else src.with_suffix(".mp3")
    if not dest.is_absolute():
        dest = (REPO_ROOT / dest).resolve()

    text = src.read_text(encoding="utf-8")
    # The sidecar writes markers in readable form; restore the internal ones so
    # section pauses and question thinking-time are spliced back as real silence.
    text = text.replace("-- pause --", SECTION_MARK).replace("-- think --", QUESTION_MARK)
    # The markdown path splits long lines inside the stripper, which this path
    # skips entirely -- so a translated file arrived with 156 lines over 300
    # characters (longest 580) and no room to breathe. Apply it here too.
    text = split_long_lines(text)

    words = len([w for w in text.split() if w not in (SECTION_MARK, QUESTION_MARK)])
    print(f"{src.name} -- {words:,} words | voice {args.voice} | rate {args.rate}")

    # Routed through the same renderer as the markdown path, so a translated
    # track gets identical treatment: size-capped parts, spoken timestamps and
    # chapter markers, with the scaffolding spoken in its own language.
    stub = Stripped(title=args.title or dest.stem, text=text, words=words, outline=[])
    written = await render_parts(
        body=text, stripped=stub, album=args.album or "Mastery Guide",
        mp3=dest, voice=args.voice, rate=args.rate,
        rules=load_pronunciation() if lang_of(args.voice) == "en" else ([], [], [], []),
        cap=args.cap)

    for path, secs, size in written:
        flag = "  ** OVER CAP **" if size > args.cap else ""
        print(f"  {path.name:40} {secs/60:5.1f} min  {size/1_000_000:4.1f} MB{flag}")
    return 0


async def main_async(args) -> int:
    if args.samples:
        await run_samples(args.rate)
        return 0
    if args.urdu_pilot:
        await run_urdu_pilot()
        return 0
    if args.speak_file:
        return await run_speak_file(args)

    files = collect_files(args)
    if not files:
        print("Nothing to do.")
        return 0

    rules = load_pronunciation()
    total_words = 0
    generated = skipped = failed = 0

    print(f"{len(files)} file(s) | voice {args.voice} | rate {args.rate}"
          f"{' | DRY RUN' if args.dry_run else ''}\n")

    for i, src in enumerate(files, start=1):
        mp3, txt = output_paths(src)
        label = src.relative_to(GUIDE_ROOT) if src.is_relative_to(GUIDE_ROOT) else src.name

        stripped = strip_markdown(src.read_text(encoding="utf-8"), src)
        if not stripped.text.strip():
            print(f"[{i}/{len(files)}] {label} -- nothing speakable, skipped")
            skipped += 1
            continue

        album = chapter_label(src)
        mins = duration_estimate(stripped.words, args.rate)
        # Split AFTER pronunciation, not before. The map expands text -- "RBAC"
        # becomes "R B A C" -- so splitting first let expanded lines drift back
        # over the limit (five ended up at 301-312 characters).
        body = split_long_lines(apply_pronunciation(stripped.text, rules))
        total_words += stripped.words

        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_text(
            body.replace(SECTION_MARK, "-- pause --").replace(QUESTION_MARK, "-- think --"),
            encoding="utf-8")

        if args.dry_run:
            longest = max((len(l) for l in body.split("\n")), default=0)
            print(f"[{i}/{len(files)}] {label} -- {stripped.words:,} words, "
                  f"~{mins:.1f} min, longest line {longest}")
            continue

        # Outputs carry a run stamp and a part suffix, so the plain mp3 path
        # never exists and this check silently never fired -- every run
        # regenerated everything and left duplicate timestamped sets behind.
        # Match the actual shape instead: <stem>[-partN]_<stamp>.mp3
        existing = sorted(mp3.parent.glob(f"{mp3.stem}*_[0-9]*{mp3.suffix}"))
        if existing and not args.force:
            newest = max(p.stat().st_mtime for p in existing)
            if newest >= src.stat().st_mtime:
                print(f"[{i}/{len(files)}] {label} -- up to date "
                      f"({len(existing)} part(s)), skipped")
                skipped += 1
                continue

        print(f"[{i}/{len(files)}] {label} -- {stripped.words:,} words, "
              f"~{mins:.1f} min", flush=True)
        try:
            written = await render_parts(
                body=body, stripped=stripped, album=album, mp3=mp3,
                voice=args.voice, rate=args.rate, rules=rules, cap=args.cap)
            generated += len(written)
            for path, secs, size in written:
                flag = "  ** OVER CAP **" if size > args.cap else ""
                print(f"      {path.name:38} {secs/60:5.1f} min  "
                      f"{size/1_000_000:4.1f} MB{flag}")
        except Exception as exc:
            print(f"      FAILED: {exc}")
            failed += 1

    total_hours = duration_estimate(total_words, args.rate) / 60
    print(f"\n{total_words:,} speakable words | ~{total_hours:.1f} h of audio")
    if args.dry_run:
        print(f"Dry run -- .txt sidecars written under {AUDIO_ROOT}. No audio generated.")
    else:
        print(f"generated {generated} | skipped {skipped} | failed {failed}")
        print(f"Output: {AUDIO_ROOT}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--file", help="single markdown file")
    src.add_argument("--chapter", help="chapter number prefix, e.g. 05")
    src.add_argument("--index-only", action="store_true", help="INTERVIEW_INDEX.md only")
    src.add_argument("--all", action="store_true", help="every topic file (~104 h)")
    ap.add_argument("--samples", action="store_true", help="generate voice + rate samples and exit")
    ap.add_argument("--urdu-pilot", action="store_true",
                    help="three Urdu approaches on one passage, then exit")
    ap.add_argument("--speak-file", help="synthesize a prepared .txt verbatim "
                                         "(used for translated tracks)")
    ap.add_argument("--plan-chunks", metavar="TXT",
                    help="emit translation chunk ranges for a sidecar, then exit")
    ap.add_argument("--assemble-urdu", metavar="DIR",
                    help="join translated chunk-NN.txt, normalise, verify, then exit")
    ap.add_argument("--english", metavar="TXT",
                    help="English sidecar to check marker parity against, "
                         "with --assemble-urdu")
    ap.add_argument("--out", help="output mp3 path, with --speak-file")
    ap.add_argument("--title", help="ID3 title, with --speak-file")
    ap.add_argument("--album", help="ID3 album, with --speak-file")
    ap.add_argument("--track", type=int, default=1, help="ID3 track number")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=DEFAULT_RATE)
    ap.add_argument("--cap", type=int, default=SIZE_CAP,
                    help=f"max bytes per part, split at section boundaries "
                         f"(default {SIZE_CAP:,} = ~41 min)")
    ap.add_argument("--dry-run", action="store_true", help="write .txt only, no TTS")
    ap.add_argument("--force", action="store_true", help="regenerate even if up to date")
    args = ap.parse_args()

    # These two are synchronous helpers for the Urdu pipeline, not synthesis.
    if args.plan_chunks:
        src = Path(args.plan_chunks)
        if not src.is_absolute():
            src = (REPO_ROOT / src).resolve()
        chunks = plan_chunks(src)
        print(f"// {len(chunks)} chunks for {src.name}\nconst CHUNKS = [")
        for c in chunks:
            print(f"  {{ n: {c['n']:2}, from: {c['from']:4}, to: {c['to']:4}, "
                  f"what: {json.dumps(c['what'])} }},")
        print("]")
        return 0

    if args.assemble_urdu:
        d = Path(args.assemble_urdu)
        if not d.is_absolute():
            d = (REPO_ROOT / d).resolve()
        if not args.out:
            ap.error("--assemble-urdu needs --out")
        dest = Path(args.out)
        if not dest.is_absolute():
            dest = (REPO_ROOT / dest).resolve()
        eng = Path(args.english) if args.english else None
        if eng and not eng.is_absolute():
            eng = (REPO_ROOT / eng).resolve()
        return assemble_urdu(d, dest, eng)

    if not any([args.file, args.chapter, args.index_only, args.all,
                args.samples, args.urdu_pilot, args.speak_file]):
        ap.error("pick one of --file / --chapter / --index-only / --all / "
                 "--samples / --urdu-pilot / --speak-file / --plan-chunks / "
                 "--assemble-urdu")

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
