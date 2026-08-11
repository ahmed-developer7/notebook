export const meta = {
  // meta must be a pure literal, so it cannot name the chapter being processed
  // -- the target comes from args.file at run time.
  name: 'add-real-world-examples',
  description: 'Add one real-world example per core concept, then fact-check for invented claims',
  phases: [
    { title: 'Write', detail: 'one agent per concept, house style enforced' },
    { title: 'Fact-check', detail: 'adversarial pass for invented statistics' },
  ],
}

// ---------------------------------------------------------------------------
// EDIT THESE TWO CONSTANTS FOR EACH CHAPTER, then run with no args.
//
// `args` is deliberately NOT used: the value arrives as a JSON *string* rather
// than an object, so args.file / args.concepts come back undefined and the run
// silently proceeds against whatever the defaults were -- a full agent fan-out
// against the wrong chapter, reported as a success. Workflow scripts also have
// no filesystem access, so a config file is not an option either. Editing the
// constants is the only reliable way to retarget this.
//
// Get the headings with:  grep -n '^### ' <file>
// ---------------------------------------------------------------------------
const FILE = 'd:/projects/whenthenonboarding/mastery-guide/05-microservices-and-messaging/01-microservices.md'

const STYLE = `
HOUSE STYLE - follow exactly:
- Insert ONE blockquote, formatted exactly:  > 🌍 **In the real world**: ...
- Place it AFTER the mechanism is explained, at the END of that ### subsection,
  immediately before the next ### heading. It illustrates; it must not replace
  or duplicate the explanation above it.
- 2-4 sentences. This becomes AUDIO for someone studying on a commute, so it
  must be picturable WITHOUT a diagram. Concrete scenario, not abstract.
- Match the file's existing voice: direct, British spelling, no hype, no
  "imagine that..." throat-clearing. Read the surrounding prose and blend in.
- Do NOT use bullet lists, code blocks, or headings inside the blockquote.
`

const ACCURACY = `
ACCURACY - this is interview preparation, so a confidently-stated wrong fact is
worse than no fact at all:
- Use ONLY widely-documented, verifiable facts. "LinkedIn originally built Kafka
  and open-sourced it" is fine.
- NEVER invent statistics, throughput figures, cluster sizes, dates or company
  specifics. No "Uber processes 4 trillion messages a day" unless you are
  certain it is a well-known published figure - and if in doubt, leave the
  number out entirely and describe the shape of the problem instead.
- Generic industry scenarios ("a ride-hailing app", "an e-commerce checkout")
  need no citation and are PREFERRED over named-company claims.
- Do not claim a specific company uses a specific Kafka feature unless it is
  genuinely well known.
`

// One entry per '### ' heading in the Core concepts section. `idea` is a
// starting angle; agents adapt it to what the section actually says.
const CONCEPTS = [
  { h: 'Service boundaries — bounded contexts', idea: 'the word Order means three different things to checkout, warehouse and support - the boundary follows the meaning, not the noun' },
  { h: 'Sync vs async communication', idea: 'checkout must confirm payment before the page returns, but the receipt email and loyalty points can happen later - same request, opposite choices' },
  { h: 'Data ownership and the database-per-service rule', idea: 'two teams sharing one orders table; one adds a NOT NULL column on Friday and the other teams service starts failing' },
  { h: 'Saga pattern for distributed transactions', idea: 'booking a flight, hotel and hire car where the car fails and the first two must be compensated - there is no ROLLBACK across services' },
  { h: 'Service discovery and API gateway', idea: 'a mobile app that would otherwise need to know twelve hostnames, and pods getting fresh IPs on every deploy' },
  { h: 'Resilience patterns', idea: 'one slow downstream dependency exhausting the callers connection pool and taking down services that never depended on it' },
  { h: 'Deployment topology — containers, orchestration', idea: 'scaling only the checkout service during a sale instead of every copy of a monolith' },
  { h: 'When NOT to use microservices', idea: 'a small team running more services than engineers, spending their week on infrastructure rather than features' },
]

const WROTE = {
  type: 'object',
  properties: {
    heading: { type: 'string' },
    inserted: { type: 'boolean' },
    text: { type: 'string', description: 'the blockquote line exactly as written into the file' },
    namedCompanies: { type: 'array', items: { type: 'string' }, description: 'any real company named' },
    statistics: { type: 'array', items: { type: 'string' }, description: 'any numeric claim made about the real world' },
  },
  required: ['heading', 'inserted', 'text', 'namedCompanies', 'statistics'],
  additionalProperties: false,
}

const VERDICT = {
  type: 'object',
  properties: {
    heading: { type: 'string' },
    problem: { type: 'boolean', description: 'true if an unverifiable or invented claim survives' },
    action: { type: 'string', description: 'what was changed, or "none needed"' },
  },
  required: ['heading', 'problem', 'action'],
  additionalProperties: false,
}

const results = await pipeline(
  CONCEPTS,

  c => agent(
    `Add a real-world example to one section of a .NET interview-prep guide.

File: ${FILE}
Section: the "### ${c.h}" subsection.

Read that whole subsection first so your example fits what is already explained.

Suggested angle (adapt freely if a better one fits the section's actual content):
${c.idea}

${STYLE}
${ACCURACY}

Edit the file to insert your blockquote. Change nothing else - no rewording of
existing prose, no reformatting.

Report the heading, whether you inserted it, the exact text, and honestly list
any real companies named and any numeric real-world claims you made (empty
arrays if none - do not under-report, the next stage checks).`,
    { label: `write:${c.h.slice(0, 22)}`, phase: 'Write', schema: WROTE }
  ),

  (res, c) => {
    if (!res || !res.inserted) return null
    // Only pay for a fact-check where there is something checkable. A generic
    // scenario with no company and no numbers cannot contain a fabricated fact.
    if (!res.namedCompanies.length && !res.statistics.length) {
      return { heading: c.h, problem: false, action: 'no checkable claims', checked: false }
    }
    return agent(
      `Fact-check one blockquote in a .NET interview-prep guide. The reader may
repeat this in an interview, so an invented statistic is a real harm.

File: ${FILE}
Section: "### ${c.h}"

The blockquote begins "> 🌍 **In the real world**".

It claims these companies: ${JSON.stringify(res.namedCompanies)}
It makes these numeric claims: ${JSON.stringify(res.statistics)}

For each: is it widely-documented public knowledge, or plausible-sounding
invention? Be strict - "probably true" is not good enough.

If anything fails, EDIT THE FILE to remove that specific claim, rewriting the
sentence to describe the shape of the problem generically instead. Keep the
blockquote otherwise intact and keep the house style. If everything checks out,
change nothing.

Report honestly whether you found a problem and what you did.`,
      { label: `check:${c.h.slice(0, 22)}`, phase: 'Fact-check', schema: VERDICT }
    ).then(v => ({ ...(v || { heading: c.h, problem: false, action: 'check failed' }), checked: true }))
  }
)

const ok = results.filter(Boolean)
const corrected = ok.filter(r => r.problem)
log(`${ok.length}/${CONCEPTS.length} examples added; ${ok.filter(r => r.checked).length} fact-checked; ${corrected.length} corrected`)

return {
  added: ok.length,
  expected: CONCEPTS.length,
  factChecked: ok.filter(r => r.checked).length,
  corrected: corrected.map(r => ({ heading: r.heading, action: r.action })),
  missing: CONCEPTS.map(c => c.h).filter(h => !ok.some(r => r.heading && r.heading.includes(h.slice(0, 15)))),
}
