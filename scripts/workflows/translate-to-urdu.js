export const meta = {
  // meta must be a pure literal, so it cannot name the file being translated
  // -- that comes from the SRC constant below.
  name: 'translate-to-urdu',
  description: 'Translate a spoken-text sidecar to Urdu, keeping technical terms in Latin script',
  phases: [
    { title: 'Translate', detail: 'parallel chunks, shared term policy' },
    { title: 'Verify', detail: 'check terms stayed Latin and structure survived' },
  ],
}

// ---------------------------------------------------------------------------
// EDIT SRC, OUT AND CHUNKS FOR EACH FILE, then run with no args.
//
// `args` is deliberately unused: the value arrives as a JSON *string*, so
// args.src comes back undefined and the run silently proceeds against the old
// defaults -- a full fan-out against the wrong file, reported as success.
// Workflow scripts have no filesystem access, so a config file is not an
// option either. Editing these constants is the only reliable way to retarget.
//
// Also: this CANNOT run in plan mode. Subagents lose write access, every agent
// reports success having written nothing.
//
// Get CHUNKS from:  py scripts/md_to_audio.py --plan-chunks <english sidecar>
// ---------------------------------------------------------------------------
const SRC = 'd:/projects/whenthenonboarding/audio/en/02-api-development/01-rest-and-web-api.txt'
const OUT = 'd:/projects/whenthenonboarding/audio/_work/ur-01-rest-and-web-api'

// The reversal of v1, which transliterated everything into Urdu script and
// mispronounced badly: "acks" came out as the letter X. Technical vocabulary
// now stays in Latin script.
//
// No Arabic-script literals in this file -- the Workflow permission dialog
// rejects a script containing them, so such examples are described instead.
const POLICY = `
TERM POLICY - this is the single most important rule:

KEEP IN LATIN SCRIPT, spelled exactly as in the English source:
  ALL technical vocabulary, whatever the topic. Examples across this guide:
  service, microservice, endpoint, middleware, container, cluster, queue,
  topic, partition, consumer, producer, offset, broker, replica, commit,
  transaction, schema, retention, rebalance, acks, batch, throughput,
  latency, key, value, header, index, segment, timeout, idempotence, saga,
  gateway, circuit breaker, retry, backpressure, hub, sidecar, actor, stream,
  session, lock, DLQ -- and every config key or API name verbatim.
  Product names: Kafka, RabbitMQ, SignalR, Dapr, gRPC, Service Bus, Redis,
  Kubernetes, Postgres, Confluent.
  Acronyms with SPACES between letters so they are read as letters, not words:
  I S R, D L Q, A P I, H T T P, S3, K Raft, k sequel D B, dot NET.

  If a term is the name of a concept an interviewer would say in English, it
  stays in English. When in doubt, keep it Latin.

TRANSLATE INTO URDU SCRIPT:
  Everything else - all connecting prose, verbs, explanations, reasoning.

The result is how a Pakistani senior engineer actually talks: Urdu sentence
structure carrying English technical terms. Do NOT transliterate technical
terms into Urdu script - that is precisely the bug being fixed.
`

const RULES = `
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
   merge lines together - long unbroken lines are unlistenable and line breaks
   are what give the voice somewhere to breathe.
4. Preserve meaning exactly. This is interview prep; a wrong technical claim
   is worse than clumsy phrasing.
5. End every Urdu sentence with the Urdu full stop (U+06D4), not a period.
6. Translate only. No commentary or notes of your own.
`

const CHUNKS = [
  { n:  1, from:    1, to:   61, what: "Section 2. Core concepts (chapter extensions)" },
  { n:  2, from:   62, to:  124, what: "Section 6. Interview Cross-Questioning Drill (part 1)" },
  { n:  3, from:  125, to:  187, what: "Section 6. Interview Cross-Questioning Drill (part 2)" },
  { n:  4, from:  188, to:  250, what: "Section 6. Interview Cross-Questioning Drill (part 3)" },
  { n:  5, from:  251, to:  313, what: "Section 6. Interview Cross-Questioning Drill (part 4)" },
  { n:  6, from:  314, to:  379, what: "Section 6. Interview Cross-Questioning Drill (part 5)" },
  { n:  7, from:  380, to:  424, what: "Section 9. Self-test" },
]

const RESULT = {
  type: 'object',
  properties: {
    chunk: { type: 'number' },
    urduLines: { type: 'number' },
    pauseMarkers: { type: 'number' },
    thinkMarkers: { type: 'number' },
    transliteratedTerms: {
      type: 'array', items: { type: 'string' },
      description: 'technical terms you wrongly wrote in Urdu script instead of Latin; empty if none',
    },
  },
  required: ['chunk', 'urduLines', 'pauseMarkers', 'thinkMarkers', 'transliteratedTerms'],
  additionalProperties: false,
}

const pad = n => String(n).padStart(2, '0')

const results = await pipeline(
  CHUNKS,

  c => agent(
    `Translate part of a spoken .NET interview-prep study script into Urdu for
text-to-speech.

Read lines ${c.from} to ${c.to} of: ${SRC}
This part covers: ${c.what}

${POLICY}
${RULES}

Write ONLY the translation to: ${OUT}/chunk-${pad(c.n)}.txt
(create the directory if needed)

Then report: the chunk number, how many lines you wrote, how many "-- pause --"
and "-- think --" markers you preserved, and honestly list any technical terms
you ended up writing in Urdu script rather than Latin (empty array if none -
the next stage checks, so do not under-report).`,
    { label: `ur:${pad(c.n)}`, phase: 'Translate', schema: RESULT }
  ),

  (res, c) => {
    if (!res) return null
    if (!res.transliteratedTerms.length) return { ...res, fixed: false }
    return agent(
      `A chunk of Urdu text-to-speech script wrongly transliterated some technical
terms into Urdu script. The Urdu voice mispronounces those badly - "acks"
transliterated into Urdu script is read as the letter X -- the exact bug
being fixed.

File: ${OUT}/chunk-${pad(c.n)}.txt
Terms reported as transliterated: ${JSON.stringify(res.transliteratedTerms)}

${POLICY}

Fix the file IN PLACE: rewrite every transliterated technical term back into
Latin script. Leave the surrounding Urdu prose alone. Keep "-- pause --" and
"-- think --" lines exactly as they are. Then report the final counts.`,
      { label: `fix:${pad(c.n)}`, phase: 'Verify', schema: RESULT }
    ).then(r => ({ ...(r || res), fixed: true }))
  }
)

const ok = results.filter(Boolean)
const pauses = ok.reduce((s, r) => s + (r.pauseMarkers || 0), 0)
const thinks = ok.reduce((s, r) => s + (r.thinkMarkers || 0), 0)
const stillBad = ok.reduce((s, r) => s + (r.transliteratedTerms?.length || 0), 0)

log(`${ok.length}/${CHUNKS.length} chunks | ${pauses} pause, ${thinks} think markers | ${stillBad} terms still transliterated`)

return {
  chunks: ok.length,
  expected: CHUNKS.length,
  pauseMarkers: pauses,
  thinkMarkers: thinks,
  stillTransliterated: stillBad,
  missing: CHUNKS.map(c => c.n).filter(n => !ok.some(r => r.chunk === n)),
  dir: OUT,
}
