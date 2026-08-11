"""
Point translate-to-urdu.js at a different topic.

The workflow script cannot take its target through `args` (the value arrives as
a JSON string, so the script silently falls back to its previous target and
fans out against the wrong file). It also has no filesystem access, so a config
file is not an option. Editing the constants is the only reliable way to
retarget -- this does that edit, and computes CHUNKS at the same time.

    py scripts/retarget-urdu.py 05-microservices-and-messaging/03-grpc

Writes in binary with LF endings on purpose: a CRLF file is rejected by the
Workflow permission dialog as "contains control characters".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "workflows" / "translate-to-urdu.js"

sys.path.insert(0, str(ROOT / "scripts"))
from md_to_audio import plan_chunks  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit("usage: retarget-urdu.py <chapter>/<topic>   (no extension)")

    rel = sys.argv[1].removesuffix(".md").removesuffix(".txt")
    sidecar = ROOT / "audio" / "en" / f"{rel}.txt"
    if not sidecar.exists():
        sys.exit(f"No English sidecar at {sidecar}\nRun a --dry-run for it first.")

    topic = Path(rel).name
    out_dir = f"d:/projects/whenthenonboarding/audio/_work/ur-{topic}"
    src = sidecar.as_posix().replace(str(ROOT.as_posix()), "d:/projects/whenthenonboarding")

    chunks = plan_chunks(sidecar)
    body = "const CHUNKS = [\n" + "\n".join(
        f'  {{ n: {c["n"]:2}, from: {c["from"]:4}, to: {c["to"]:4}, '
        f'what: "{c["what"]}" }},' for c in chunks) + "\n]"

    text = SCRIPT.read_bytes().decode("utf-8")
    text = re.sub(r"const SRC = '[^']*'", f"const SRC = '{src}'", text)
    text = re.sub(r"const OUT = '[^']*'", f"const OUT = '{out_dir}'", text)
    text = re.sub(r"const CHUNKS = \[.*?\n\]", body, text, flags=re.S)
    SCRIPT.write_bytes(text.encode("utf-8"))   # binary: keeps LF

    print(f"retargeted -> {topic}")
    print(f"  src    : {src}")
    print(f"  out    : {out_dir}")
    print(f"  chunks : {len(chunks)}")
    print(f"  CR     : {text.count(chr(13))} (must be 0)")
    print(f"\nnext: py scripts/md_to_audio.py --assemble-urdu {out_dir} \\")
    print(f"        --out audio/ur/{rel}.txt --english audio/en/{rel}.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
