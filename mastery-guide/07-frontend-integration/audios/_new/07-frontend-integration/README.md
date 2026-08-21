# Chapter 07 — regenerated audio (Angular, RxJS)

**Generated 2026-08-20. Does NOT replace anything.** The existing tracks under
`audio/en/07-frontend-integration/` and `audio/en-drills/07-frontend-integration/`
are untouched and still playable. Compare, then decide.

## Why these were regenerated

The reader listened to the Angular chapter and its drills on 2026-08-19 and
rated them **2 out of 10**, naming three faults: *"not audible / wrong
pronunciations"*, *"direct code reading"*, and *"too much basic audio"*.

Measuring the old spoken text confirmed all three. In `01-angular` alone, out
of 18,588 spoken words:

| Defect | Count | Example of what you heard |
|---|---|---|
| Flattened table rows | 174 | *"v14, Jun 2022, Standalone A P Is (developer preview); inject() usable in field initialisers; typed reactive forms…"* — a nine-row version table recited as prose |
| Split identifiers | 207 | `toSignal()` → *"to Signal"* ×15, `httpResource` → *"http Resource"* ×15, `setInput()` → *"set Input"* ×10 |
| Spelled-out acronyms | 105 | *"A P I"* ×29, *"A P Is"* ×17 (the plural read as "Is"), *"D I"* ×14 |
| Slash corruption | 13 | `@angular/forms/signals` → *"@angular **or** forms **or** signals"*; `guards/resolvers/interceptors` → *"guards **or** resolvers…"*, inverting "and" to "or" |

The splitting was also **inconsistent**: the regex required exactly two camel
humps, so `ngOnInit` survived intact while `toSignal` was split, and you heard
both spellings in the same sentence.

## The actual cause

Not a stripper bug. **The pipeline narrated the page.** A page is written to be
scanned — tables, code blocks, identifiers — and none of that survives contact
with an ear. No amount of pronunciation patching fixes a nine-row table being
read aloud.

## What changed

Audio now has its own artifact: a **lecture script**, generated from the page
by an agent briefed to teach rather than recite, then narrated instead of the
page. The page remains the reference; these are separate documents, kept under
`audio/_scripts/07-frontend-integration/` and tracked in git.

Four rules were enforced on the scripts: never read code, never read a table,
say identifiers as a person says them, and signpost constantly because the
listener cannot see structure.

The version table became four named eras with one landmark each. Code blocks
became explanations of what the code does and why. A deterministic pass
(`scripts/speakify.py`) then applied the pronunciation conventions the reader
chose after a 60-item A/B listening test:

- **ng-prefixed names spell the NG** — `ngOnInit` → "N G on init"
- **at-syntax drops the at** — `@if` → "the if block"
- **camelCase splits into words** — `toSignal` → "to Signal"
- **acronyms are words where real, letters otherwise** — `CORS` → "corse",
  `LINQ` → "link", `SQL` → "sequel"; `API`, `DI`, `HTTP`, `CQRS` stay as letters

Product names are protected from the split rule, so `TypeScript` and
`WebSocket` stay whole.

## Result, same source page

| | Old (page read aloud) | New (lecture script) |
|---|---|---|
| Spoken words | 18,588 | 11,006 |
| Listening time | 172 min | 101 min |
| Flattened table rows | 174 | 10 |
| Raw `ngOnInit`-style names | many | 0 |
| `A P Is` mispronounced plural | 17 | 0 |
| `@` symbols spoken | present | 0 |
| Slash-as-"or" | 13 | 1 |

Shorter because code and tables became explanation instead of recitation — not
because material was dropped. Every technical claim, version number and
stability label was carried across unchanged; the scripts were told they were
changing delivery, not facts.

## What is here

| File | Parts | Length |
|---|---|---|
| `01-angular` | 4 | 102 min |
| `01-angular-interview-drills` | 3 | 95 min |
| `02-rxjs-reactive-programming` | 5 | 157 min |
| `02-rxjs-reactive-programming-interview-drills` | 3 | 97 min |

Total ~7.5 hours, replacing ~11 hours of the old format.

**Only Angular and RxJS.** Chapter 07's other four topics — NgRx, service
worker/PWA, testing, SSR — were deliberately left in the old format at the
reader's instruction, pending judgement on these two.

## Known open questions

- **Voice and pace** are unchanged: `en-IN-PrabhatNeural` at −10%. Six
  comparison clips (`VOICE-A` … `VOICE-F`) sit in `audio/_samples/`. Switching
  costs a regeneration, which is free apart from machine time.
- **Part length** is the default 41-minute cap, which produced a 6-minute stub
  as the tail of both lectures. ~20 minutes per part would suit a commute
  better and is a one-flag change.
- **RxJS ran long.** Its lecture script came out at 16,993 words from 13,436
  source words — an expansion, where Angular compressed to roughly half. The
  agent judged that operator choice is a set of scenes to be told rather than a
  table to be read. If it feels padded, that ratio is the dial to turn.

## To adopt these

Nothing is automatic. Move the files over `audio/en/07-frontend-integration/`
and `audio/en-drills/07-frontend-integration/`, deleting the old parts for
those two topics only. Until then both versions coexist and the old one is
what a player will find.
