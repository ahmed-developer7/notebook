# Audio pipeline

Turns mastery-guide markdown into study audio, English and Urdu.

Most of what was learned building this is **in the code**, and applies to a new
chapter automatically. This file covers only what the code cannot tell you: the
procedure, why the settings are what they are, the ordering traps, and what is
still unverified.

---

## Quick reference

| | |
|---|---|
| English voice | `en-IN-PrabhatNeural` at `-10%` |
| Urdu voice | `ur-PK-AsadNeural` at `-5%` |
| Size cap | 15,000,000 bytes → ~41 min (bitrate is 6006 B/s CBR exactly) |
| Split rule | Greedy pack, break only at a section start, never mid-concept |
| Output | `audio/en/<chapter>/<topic>-partN_<stamp>.mp3` + `.txt` sidecar |
| Player | **Voice** (`de.ph1b.audiobook`), folder per language |

`audio/` is gitignored. Nothing here commits or pushes.

---

## Procedure — one new chapter

### English (fully automatic)

```powershell
# 1. Read what will be spoken BEFORE spending synthesis time
pwsh scripts/build-audio.ps1 -File mastery-guide/<chapter>/<topic>.md -DryRun

# 2. Generate
pwsh scripts/build-audio.ps1 -File mastery-guide/<chapter>/<topic>.md
```

Optional first: add real-world examples to the guide itself.

```
grep -n '^### ' mastery-guide/<chapter>/<topic>.md      # get the headings
```
Then run `scripts/workflows/add-real-world-examples.js` with `args: { file, concepts }`.

> ⚠️ **These workflows cannot run in plan mode.** Subagents have no Edit access
> there, so every agent composes its example, returns `inserted: false`, and
> writes nothing — while the run reports *completed, 0 errors*. The tell is
> `added: 0`. Their text is recoverable from `journal.jsonl` in the run's
> transcript directory, so a failed run does not have to be repeated: extract
> the `text` field per result and apply it directly.
>
> ⚠️ **Retarget by editing `FILE` and `CONCEPTS` in the script, not via `args`.**
> `args` arrives as a JSON *string*, so `args.file` comes back `undefined` and
> the script silently falls back to whatever the defaults were — a full fan-out
> against the wrong chapter. Workflow scripts have no filesystem access either,
> so a config file is not an alternative.
It writes into the markdown, so the guide improves permanently and the audio
inherits it. A second agent fact-checks any named company or statistic — that
guard exists because a fabricated figure repeated in an interview is worse than
no example at all.

### Urdu (three steps, each mechanical)

```powershell
# 1. Chunk ranges, computed from section boundaries - do NOT hand-compute
py scripts/md_to_audio.py --plan-chunks audio/en/<chapter>/<topic>.txt
```

Paste that output as `args.chunks` and run `scripts/workflows/translate-to-urdu.js`
with `args: { src, out, chunks }`. The term policy lives in
[urdu-glossary.json](urdu-glossary.json) — keep it and the workflow prompt in step.

```powershell
# 2. Join, normalise headings, split lines, and VERIFY against the English
py scripts/md_to_audio.py --assemble-urdu <scratch dir> `
   --out audio/ur/<chapter>/<topic>.txt `
   --english audio/en/<chapter>/<topic>.txt

# 3. Generate
pwsh scripts/build-audio.ps1 -SpeakFile audio/ur/<chapter>/<topic>.txt `
     -Out audio/ur/<chapter>/<topic>.mp3 `
     -Voice ur-PK-AsadNeural -Rate "-5%" `
     -Title "<Topic> (Urdu)" -Album "<Chapter> (Urdu)"
```

**Step 2 will fail the build** if `-- pause --` or `-- think --` counts differ
from the English. Do not work around it — a mismatch means the translation
dropped or invented structure, and `-- think --` in particular is the gap where
you attempt a drill question. Fix the chunk and re-assemble.

---

## Why the settings are what they are

**Voices, by ear from samples** (`-Samples` regenerates them). Prabhat beat
Ryan, Sonia and Andrew. Urdu runs `-5%` against English's `-10%` because
syllable density differs and the first Urdu build dragged.

**15 MB cap, not 20.** At 20 MB, Kafka sat exactly on the 2-vs-3 parts boundary,
so an edit could renumber every file between regenerations. 15 MB keeps it
stably at 3 parts, and ~40 min is a better commute unit.

**Latin technical terms in Urdu.** The first translation transliterated
everything into Urdu script; `acks` became `ایکس`, which the voice reads as the
letter *X*. Terms now stay Latin, and acronyms are spaced (`I S R`, not `ISR`)
so they are read as letters rather than attempted as words.

**5-second drill gap.** Questions used to be followed straight by their answer,
which defeats a drill entirely. This is a starting guess — tune by ear.

**300-character line limit.** edge-tts exposes no SSML, so punctuation is the
only prosody control and a long line has nowhere to breathe. Urdu once had a
1,885-character line, about two minutes of unbroken speech.

**Timestamps in filenames** so regenerations are distinguishable on the phone
and an old copy is never mistaken for new.

---

## Ordering traps

These caused real bugs. A rewrite would hit them again.

| Rule | What happens otherwise |
|---|---|
| Slash handling runs **before** the pronunciation map | `S3/Blob` is already `S three/Blob`; the seam is gone |
| Dictionary entries containing `/` run **before** the generic slash rule | `msgs/min` becomes "msgs or min" instead of "messages per minute" |
| Line splitting runs **after** the map | The map expands text (`RBAC` → `R B A C`) and pushes lines back over |
| Only close up whitespace before a full stop **not** followed by a letter | `For .NET` collapses to `For.NET`, spoken as "Fordot NET" |
| Inline code is padded with spaces when backticks are removed | `a \`.index\` file` glues into `a.index` |
| Display titles reverse speech spellings | Chapter list shows `Security (sassle + ACLs + T L S)` |
| Pack the body against `cap - INTRO_RESERVE` | The intro is prepended after packing; part 1 came out at 15.64 MB |

---

## Known limitations

**The Urdu has never been checked for technical accuracy.** Structure was
verified — marker parity, script purity, no dropped sections — but nobody who
reads Urdu *and* knows Kafka has confirmed the concepts survived translation.
For interview prep that is a real risk: confidently learning a mistranslated
concept is worse than not learning it. Spot-check drill answers against the
English.

**It is synthetic speech.** No emphasis on the word that matters, no slowing for
something hard. A human reading this would be better, and no amount of text
processing closes that gap.

**`edge-tts` is a free unofficial endpoint.** No SLA. It rate-limits on long
runs; the code retries with backoff.

**Cost per chapter:** ~12 min synthesis per language, plus ~450k tokens to
translate. Urdu is the expensive half by a wide margin — worth reserving for
chapters you genuinely find hard.

**Kafka's current build** has five English lines at 301–312 chars. The
ordering fix is in the code; that build predates it. Inaudible, not worth a
regeneration on its own.

---

## Verification

```powershell
# Every file must be under 15 MB - this is enforced from measured segment
# sizes, so a breach is a packing bug, not rounding
Get-ChildItem audio -Recurse -Filter *.mp3 |
  Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}} |
  Sort-Object MB -Descending
```

Zero lines over 300 **characters**, both languages:

```powershell
.\.venv\Scripts\python.exe -c @"
import glob
for lang in ('en','ur'):
    worst = over = 0
    for p in glob.glob(f'audio/{lang}/**/*.txt', recursive=True):
        for l in open(p, encoding='utf-8').read().split('\n'):
            worst = max(worst, len(l)); over += len(l) > 300
    print(lang, 'over:', over, 'longest:', worst)
"@
```

> ⚠️ **Do not use `awk 'length($0)>300'` for this.** awk counts *bytes*, and
> Urdu is multi-byte UTF-8 — a clean 300-character Urdu line measures ~600
> bytes, so awk reports hundreds of false failures. It happens to be right for
> English and wrong for Urdu, which is the worst kind of wrong.

Read the `.txt` sidecar before generating — it is exactly what will be spoken,
and reading is far cheaper than listening. Then play the first minute of each
part: a clear beat between contents items, a usable gap after each drill
question, and every technical term recognisable as the English word you would
use in an interview.
