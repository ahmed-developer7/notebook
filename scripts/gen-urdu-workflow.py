"""
Generate a whole-chapter Urdu translation workflow.

Replaces the retarget-one-file-at-a-time loop. `retarget-urdu.py` rewrote SRC,
OUT and CHUNKS in translate-to-urdu.js for a single topic, so a 17-topic chapter
meant 17 manual retargets, each an opportunity to run a full fan-out against the
wrong file. This emits one script covering every topic in a chapter.

    py scripts/gen-urdu-workflow.py 02-api-development
    py scripts/gen-urdu-workflow.py 02-api-development --model sonnet

Why the chunk plan is baked into the generated script: workflow scripts have no
filesystem access, so they cannot read a chunk manifest at run time, and `args`
arrives as a JSON *string* rather than an object -- passing the plan that way
silently yields undefined and the run proceeds against stale defaults.

Writes in binary with LF endings on purpose: a CRLF file is rejected by the
Workflow permission dialog as "contains control characters". The generated
script must also contain no Arabic-script literals, for the same reason -- so
the term policy describes examples rather than showing them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from md_to_audio import plan_chunks  # noqa: E402

POLICY = """
TERM POLICY - this is the single most important rule:

KEEP IN LATIN SCRIPT, spelled exactly as in the English source:
  ALL technical vocabulary, whatever the topic: service, endpoint, middleware,
  gateway, header, payload, schema, contract, client, route, policy, token,
  claim, scope, cache, queue, stream, socket, handshake, retry, timeout,
  throttle, quota, versioning, deprecation, migration, and every config key,
  attribute or API name verbatim.
  Product names stay as written: ASP.NET Core, OpenAPI, Swagger, GraphQL,
  Azure, Kestrel, Polly, NuGet, Redis, Kafka, RabbitMQ, SignalR.
  Acronyms get SPACES between letters so the voice reads them as letters and
  not as a word: A P I, H T T P, U R L, J S O N, J W T, S S E, M Q T T,
  dot NET.

  If a term is the name of a concept an interviewer would say in English, it
  stays in English. When in doubt, keep it Latin.

  The word "dot" in "dot NET" is part of the term and stays Latin. A trial run
  produced it written in Urdu script, which the voice then mispronounces - and
  the agent that did it reported zero violations, so do not rely on your own
  sense of having complied. Re-read your output for this specific case before
  reporting.

TRANSLATE INTO URDU SCRIPT:
  Everything else - all connecting prose, verbs, explanations, reasoning.

The result is how a Pakistani senior engineer actually talks: Urdu sentence
structure carrying English technical terms. Do NOT transliterate technical
terms into Urdu script - that is precisely the bug being fixed. A transliterated
"acks" is read aloud as the letter X.
"""

RULES = """
RULES:
1. This is AUDIO for someone studying on a commute. Natural spoken Urdu, not
   stiff literary translation.
2. Keep these marker lines EXACTLY as they are, alone on their own line, never
   translated, never removed:
       -- pause --
       -- think --
   "-- think --" marks a gap where the listener attempts a drill question. It
   is essential; dropping it destroys the exercise.
3. Keep the line structure. One source line becomes one output line. Do NOT
   merge lines - long unbroken lines are unlistenable, and the line breaks are
   what give the voice somewhere to breathe.
4. Preserve meaning exactly. This is interview prep; a wrong technical claim
   is worse than clumsy phrasing.
5. WATCH DIRECTION AND AGENCY. Who does what to whom survives translation
   badly. A model trial found BOTH candidate models turning "the API is
   consumed by libraries that already set Accept" into "the API uses those
   libraries" - reversing which side sets the header. Before writing a sentence
   with two actors, check you have not swapped them. The same care applies to
   which side reads and which writes, which version is old and which is new,
   and whether a limit is being loosened or tightened.
6. DO NOT TURN A DESCRIPTION INTO AN INSTRUCTION. "SDKs ignore unknown
   properties by default" is a claim about how SDKs behave; rendering it as
   "SDKs should ignore unknown properties" changes it into advice. Keep
   statements as statements.
7. KEEP MODAL STRENGTH. "must" is not "should" and "breaks" is not "affects".
   These carry the weight of the claim in an interview answer.
8. End every Urdu sentence with the Urdu full stop (U+06D4), not a period.
9. Translate only. No commentary or notes of your own.
"""

TEMPLATE = """export const meta = {{
  // meta must be a pure literal, so the chapter cannot be interpolated here.
  name: 'translate-chapter-to-urdu',
  description: 'Translate a whole chapter of spoken-text sidecars to Urdu, keeping technical terms in Latin script',
  phases: [
    {{ title: 'Translate', detail: 'every chunk of every topic, pipelined' }},
    {{ title: 'Verify', detail: 'repair any chunk that transliterated technical terms' }},
  ],
}}

// GENERATED by scripts/gen-urdu-workflow.py -- edit that, not this.
// Chapter: {chapter}   Topics: {n_topics}   Chunks: {n_chunks}
//
// The chunk plan is baked in because workflow scripts have no filesystem
// access, and `args` arrives as a JSON string rather than an object, so
// passing it that way silently falls back to stale defaults.
//
// This CANNOT run in plan mode: subagents lose write access there and every
// agent reports success having written nothing. The tell is chunks: 0.

const MODEL = {model}
const EN = 'd:/projects/whenthenonboarding/audio/en/{chapter}'
const WORK = 'd:/projects/whenthenonboarding/audio/_work/ur-{chapter}'

const POLICY = `{policy}`

const RULES = `{rules}`

const TOPICS = {topics}

const RESULT = {{
  type: 'object',
  properties: {{
    topic: {{ type: 'string' }},
    chunk: {{ type: 'number' }},
    urduLines: {{ type: 'number' }},
    sourceLines: {{ type: 'number' }},
    pauseMarkers: {{ type: 'number' }},
    thinkMarkers: {{ type: 'number' }},
    transliteratedTerms: {{
      type: 'array', items: {{ type: 'string' }},
      description: 'technical terms wrongly written in Urdu script instead of Latin; empty if none',
    }},
  }},
  required: ['topic', 'chunk', 'urduLines', 'sourceLines', 'pauseMarkers', 'thinkMarkers', 'transliteratedTerms'],
  additionalProperties: false,
}}

const pad = n => String(n).padStart(2, '0')

// Flatten to one task per chunk so every topic's chunks interleave. A barrier
// per topic would idle the whole pool behind whichever topic is slowest.
const TASKS = TOPICS.flatMap(t => t.chunks.map(c => ({{ ...c, topic: t.topic, lines: t.lines }})))

const results = await pipeline(
  TASKS,

  t => agent(
    `Translate part of a spoken .NET interview-prep study script into Urdu for
text-to-speech.

Read lines ${{t.from}} to ${{t.to}} of: ${{EN}}/${{t.topic}}.txt
This part covers: ${{t.what}}

${{POLICY}}
${{RULES}}

Write ONLY the translation to: ${{WORK}}/${{t.topic}}/chunk-${{pad(t.n)}}.txt
(create the directory if needed)

Then report the topic, chunk number, how many lines you wrote, how many source
lines there were, how many "-- pause --" and "-- think --" markers you
preserved, and honestly list any technical terms you ended up writing in Urdu
script rather than Latin. The next stage checks, so do not under-report.`,
    {{ label: `${{t.topic.slice(0, 2)}}:${{pad(t.n)}}`, phase: 'Translate', schema: RESULT, model: MODEL }}
  ),

  (res, t) => {{
    if (!res) return null
    if (!res.transliteratedTerms.length) return {{ ...res, repaired: false }}
    return agent(
      `A chunk of Urdu text-to-speech script wrongly transliterated some
technical terms into Urdu script. The Urdu voice mispronounces those badly - a
transliterated "acks" is read aloud as the letter X, which is the exact bug
being fixed.

File: ${{WORK}}/${{t.topic}}/chunk-${{pad(t.n)}}.txt
Terms reported as transliterated: ${{JSON.stringify(res.transliteratedTerms)}}

${{POLICY}}

Fix the file IN PLACE: rewrite every transliterated technical term back into
Latin script. Leave the surrounding Urdu prose alone. Keep "-- pause --" and
"-- think --" lines exactly as they are. Then report the final counts.`,
      {{ label: `fix:${{t.topic.slice(0, 2)}}:${{pad(t.n)}}`, phase: 'Verify', schema: RESULT, model: MODEL }}
    ).then(r => ({{ ...(r || res), repaired: true }}))
  }}
)

const ok = results.filter(Boolean)
const byTopic = {{}}
for (const r of ok) {{
  const b = byTopic[r.topic] || (byTopic[r.topic] = {{ chunks: 0, pause: 0, think: 0, bad: 0, repaired: 0 }})
  b.chunks++; b.pause += r.pauseMarkers || 0; b.think += r.thinkMarkers || 0
  b.bad += r.transliteratedTerms?.length || 0; b.repaired += r.repaired ? 1 : 0
}}

const expected = {{}}
for (const t of TOPICS) expected[t.topic] = t.chunks.length
const incomplete = Object.keys(expected).filter(k => (byTopic[k]?.chunks || 0) !== expected[k])

log(`${{ok.length}}/${{TASKS.length}} chunks across ${{Object.keys(byTopic).length}} topics | ${{incomplete.length}} topics incomplete`)

return {{
  model: MODEL,
  chunks: ok.length,
  expected: TASKS.length,
  topics: byTopic,
  incomplete,
  stillTransliterated: ok.reduce((s, r) => s + (r.transliteratedTerms?.length || 0), 0),
  dir: WORK,
}}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", help="e.g. 02-api-development")
    ap.add_argument("--model", default=None,
                    help="model override for every agent; omit to inherit the session model")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    en = ROOT / "audio" / "en" / args.chapter
    if not en.is_dir():
        sys.exit(f"No English sidecars at {en}\nGenerate the English audio first.")

    sidecars = sorted(en.glob("*.txt"))
    if not sidecars:
        sys.exit(f"No .txt sidecars in {en}")

    topics, total = [], 0
    for p in sidecars:
        chunks = plan_chunks(p)
        total += len(chunks)
        topics.append({
            "topic": p.stem,
            "lines": len(p.read_text(encoding="utf-8").split("\n")),
            "chunks": [{"n": c["n"], "from": c["from"], "to": c["to"], "what": c["what"]}
                       for c in chunks],
        })

    body = TEMPLATE.format(
        chapter=args.chapter,
        n_topics=len(topics),
        n_chunks=total,
        model=f"'{args.model}'" if args.model else "undefined",
        policy=POLICY.strip("\n"),
        rules=RULES.strip("\n"),
        topics=json.dumps(topics, ensure_ascii=True, indent=2),
    )

    # A stray backtick or ${ in the generated literals would break the template
    # strings silently, so fail loudly instead.
    for bad in ("`", "${"):
        if bad in POLICY or bad in RULES:
            sys.exit(f"Term policy contains {bad!r}, which breaks the JS template literal.")

    dest = Path(args.out) if args.out else ROOT / "scripts" / "workflows" / f"translate-{args.chapter}-urdu.js"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body.encode("utf-8"))   # binary: keeps LF

    cr = body.count("\r")
    non_ascii = [ch for ch in body if ord(ch) > 127]
    print(f"wrote {dest.relative_to(ROOT)}")
    print(f"  topics : {len(topics)}")
    print(f"  chunks : {total}")
    print(f"  model  : {args.model or '(inherit session model)'}")
    print(f"  CR     : {cr} (must be 0)")
    print(f"  non-ASCII chars: {len(non_ascii)} (must be 0 - the permission dialog rejects them)")
    if cr or non_ascii:
        return 1
    print(f"\nnext: run the workflow, then per topic:")
    print(f"  py scripts/md_to_audio.py --assemble-urdu audio/_work/ur-{args.chapter}/<topic> \\")
    print(f"       --out audio/ur/{args.chapter}/<topic>.txt --english audio/en/{args.chapter}/<topic>.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
