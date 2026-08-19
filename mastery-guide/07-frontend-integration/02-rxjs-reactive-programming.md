# RxJS / Reactive Programming

> [Mastery Guide](../README.md) › [Frontend Integration](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 10 — Frontend (parallel) | 2026-08-19 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Observable, Observer, Subscription](#observable-observer-subscription)
  - [Cold vs hot Observables](#cold-vs-hot-observables)
  - [Subjects — the bridge between imperative and reactive](#subjects--the-bridge-between-imperative-and-reactive)
  - [Multicasting in RxJS 7 — share, connectable, and the deprecated operators](#multicasting-in-rxjs-7--share-connectable-and-the-deprecated-operators)
  - [The operator catalog](#the-operator-catalog)
  - [Higher-order mapping — switchMap, mergeMap, concatMap, exhaustMap](#higher-order-mapping--switchmap-mergemap-concatmap-exhaustmap)
  - [Combination operators](#combination-operators)
  - [Error handling](#error-handling)
  - [Promise interop — toPromise, firstValueFrom, lastValueFrom](#promise-interop--topromise-firstvaluefrom-lastvaluefrom)
  - [Memory leak prevention](#memory-leak-prevention)
  - [Marble testing with TestScheduler](#marble-testing-with-testscheduler)
  - [RxJS in the signals era](#rxjs-in-the-signals-era)
  - [The .NET seam — interceptors, token refresh, CORS, SSR](#the-net-seam--interceptors-token-refresh-cors-ssr)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--leaking-subscriptions-in-a-spa)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

**RxJS** is the JavaScript port of ReactiveX — a library for composing asynchronous, event-based programs using *observable streams*. Angular has used RxJS as its primary async model since the beginning (HttpClient returns Observables, Router events are streams, forms expose `valueChanges`). Even with the rise of signals, RxJS isn't going anywhere — for **streams of values over time** (typing in a search box, websocket messages, polling, multi-step async pipelines), Observables are still the right shape.

The mental model: Promises are one-shot async results; Observables are async sequences. A click handler can produce many events; an HTTP polling loop emits many responses; a websocket emits messages forever. Promises can't model these naturally; Observables can.

Why interviewers ask: RxJS is the most-asked Angular topic and the biggest junior→senior gap. Knowing the difference between `mergeMap` and `switchMap`, when to use `BehaviorSubject` vs `ReplaySubject`, and how to avoid memory leaks separates engineers who copy patterns from Stack Overflow from those who can design reactive flows.

When NOT to use: simple one-shot async (use Promise / `async/await` / `firstValueFrom`). Pure state values that don't change over time (use signals). Computational pipelines on arrays (use plain JS / lodash; RxJS is for streams over time).

**Where the versions actually stand.** Angular **v22** shipped **3 June 2026** and still declares a peer dependency of `rxjs@^6.5.3 || ^7.4.0` — RxJS is not being removed from Angular, and no RxJS 6 code has been locked out either. The latest *published stable* RxJS is **7.8.2** (February 2025). The next major was renumbered along the way: the `8.0.0-alpha` line stopped at `8.0.0-alpha.14` (January 2024), and the work resurfaced as **`9.0.0-beta.0`, published 4 August 2026** (its changelog diffs against `8.0.0-alpha.14`). Two consequences worth having straight before an interview: every `@deprecated … will be removed in v8` note in the RxJS source means "removed in the next major", and that major is now numbered **9**; and nothing has actually been removed from the version you are shipping today.

**The question this page exists to answer.** Signals have been stable since v17, `toSignal`/`toObservable` since **v20**, and `resource`/`rxResource`/`httpResource` since **v22**. So the senior-level question is no longer "what does `mergeMap` do" — it is *when do you still reach for RxJS at all*. The answer worth being able to defend in one sentence: **signals model a value that has a current state; Observables model events that happen in time.** Anything where *when* matters — debouncing, cancelling work already in flight, retry with backoff, resolving a race, guaranteeing order, replaying history, a socket that pushes — is an Observable problem, and no amount of `computed()` turns it into a signal problem. Anything that is "the current thing on screen" is a signal problem, and expressing it as a `BehaviorSubject` in 2026 is a habit rather than a design.

> 🌍 **In the real world**: a team migrating a v13 app to signals did a service-by-service pass turning every `BehaviorSubject` into a `signal()`. The state services converted cleanly and the diff looked like a win. Then the typeahead broke. The old pipeline was `searchTerm$.pipe(debounceTime(300), distinctUntilChanged(), switchMap(term => api.search(term)))`; the signal rewrite was `effect(() => this.search(this.term()))`, which fired a request per keystroke and rendered whichever response happened to land last. It looked fine on a laptop against localhost and produced visibly wrong results over conference Wi-Fi. They put search back on RxJS and converted only at the edge with `toSignal`. The sentence to carry into an interview: **`effect()` is not `subscribe()`** — it has no debounce and no cancel-the-previous semantics, so everywhere you were relying on `switchMap` to discard stale work, a naive effect races instead.

> 🌍 **In the real world**: an architecture review deferred an RxJS cleanup with "we'll do it when we move to RxJS 8, it's nearly out." That was 2023. The last v8 alpha shipped in January 2024, the major was later renumbered, and `9.0.0-beta.0` did not appear until August 2026 — roughly three years of a migration plan pinned to a release that never arrived. Meanwhile every one of the deprecations they were waiting on (`toPromise`, `multicast`, `publish*`, `refCount`, `retryWhen`) was replaceable *inside 7.x*, one small PR at a time, with no version bump at all. **A deprecation is a thing you can retire today; the major release is only the day the compiler stops being polite about it.**

## Core concepts

### Observable, Observer, Subscription

```typescript
import { Observable } from 'rxjs';

// Create an Observable — describes a stream of values
const numbers$ = new Observable<number>(subscriber => {
  subscriber.next(1);                      // emit value 1
  subscriber.next(2);
  subscriber.next(3);
  subscriber.complete();                    // signal done
});

// Subscribe — actually run the producer
const subscription = numbers$.subscribe({
  next: n => console.log(n),                // 1, 2, 3
  error: e => console.error(e),
  complete: () => console.log('done')
});

// Cancel before completion if needed
subscription.unsubscribe();
```

Three callbacks: `next` (each emitted value), `error` (terminates the stream with an error), `complete` (terminates cleanly). After `error` or `complete`, no more values.

The convention: Observables end with a `$` suffix. `users$`, `searchTerm$`, `clicks$`. Reading code is much easier with the convention.

### Cold vs hot Observables

**Cold Observables** are unicast — each subscriber gets its own execution. The producer code (the `(subscriber) => { ... }`) runs from scratch per subscribe.

```typescript
const cold$ = new Observable<number>(s => {
  console.log('producer running');
  s.next(Math.random());
  s.complete();
});

cold$.subscribe(v => console.log('A:', v));   // "producer running", "A: 0.123..."
cold$.subscribe(v => console.log('B:', v));   // "producer running", "B: 0.456..." (DIFFERENT!)
```

`HttpClient.get()` returns cold Observables — every subscribe issues a new HTTP request. This is why you sometimes see "my service is being called twice."

**Hot Observables** are multicast — one shared execution; all subscribers see the same values.

```typescript
import { Subject } from 'rxjs';

const hot$ = new Subject<number>();

hot$.subscribe(v => console.log('A:', v));
hot$.subscribe(v => console.log('B:', v));

hot$.next(42);   // both A and B see 42
```

DOM events (clicks, websocket messages) are inherently hot — they happen whether you're listening or not.

**`shareReplay`** turns cold into hot:

```typescript
const shared$ = http.get<User[]>('/api/users').pipe(shareReplay(1));

shared$.subscribe(...);   // HTTP fires
shared$.subscribe(...);   // gets cached value; no new HTTP
```

`shareReplay(1)` keeps the last 1 emitted value and replays to new subscribers — common for caching API responses.

Know what `shareReplay` actually expands to, because the interview follow-up is always about its resets. In RxJS 7 it is implemented in terms of `share`:

```typescript
// shareReplay(bufferSize) === share({ ... }) with these exact settings:
share({
  connector: () => new ReplaySubject(bufferSize, windowTime, scheduler),
  resetOnError: true,        // a failed source goes cold again — the next subscriber retries
  resetOnComplete: false,    // a completed source keeps replaying its buffer forever
  resetOnRefCountZero: refCount   // false unless you asked for refCount: true
})
```

So `shareReplay(1)` is `shareReplay({ bufferSize: 1, refCount: false })`, and `refCount: false` is the setting most codebases pick up by accident. It means the operator subscribes to the source once and **never unsubscribes**. On a finite source (one HTTP response) that costs one retained value and no invalidation. On an infinite source (`interval`, a socket, `fromEvent(window, 'resize')`) it is a permanent subscription that no component teardown can ever reach — the classic "the app gets slower the longer it runs" leak.

> 🌍 **In the real world**: a dashboard cached its "current tenant" lookup with `shareReplay(1)` in a `providedIn: 'root'` service. Correct, cheap, and a support ticket six months later: an admin who switched tenants kept seeing the previous tenant's numbers until a hard refresh, because `refCount: false` gives a cache with no invalidation story at all — it holds the first response for the lifetime of the tab. The fix was not a different operator. It was to stop pretending an operator was a cache: hold the value in something they owned (a signal, or a `BehaviorSubject`) written by an explicit `loadTenant()`, so "invalidate" became a line of code instead of an emergent property of an operator's defaults. The reviewable rule they wrote down: **`shareReplay` is a de-duplicator for concurrent subscribers, not a cache with a lifecycle.**

### Subjects — the bridge between imperative and reactive

A **Subject** is both an Observable AND an Observer — you can `next()` values into it AND subscribe to it. Used to bridge imperative code (button click handler) with reactive (downstream Observable chain).

Four flavors:

| Subject | Behavior |
|---|---|
| **`Subject`** | No initial value; subscribers get only values emitted after they subscribe |
| **`BehaviorSubject<T>`** | Has a current value; new subscribers immediately get the latest |
| **`ReplaySubject(n)`** | Replays the last N values to new subscribers |
| **`AsyncSubject`** | Emits only the last value, only on complete (rare) |

`BehaviorSubject` is the workhorse for "current state":

```typescript
@Injectable({ providedIn: 'root' })
export class CartService {
  private items$ = new BehaviorSubject<Item[]>([]);
  readonly items = this.items$.asObservable();   // expose readonly

  add(item: Item) {
    this.items$.next([...this.items$.value, item]);
  }

  remove(id: string) {
    this.items$.next(this.items$.value.filter(i => i.id !== id));
  }
}

// Component
this.cartService.items.subscribe(items => this.cartCount = items.length);
```

In modern Angular, signals (`signal<Item[]>([])`) replace this pattern — but tons of existing code uses BehaviorSubject. Both are valid.

Two Subject behaviours that decide production incidents, and that interviewers use to separate "I've used a Subject" from "I've debugged one":

- **A Subject that errors is dead permanently — for everyone.** `error()` terminates the Subject itself, not just the current subscribers. Every later `subscribe()` receives that same error immediately, and every later `next()` is dropped silently. A `BehaviorSubject`-backed store that lets an HTTP failure reach its error channel takes the whole feature down until the page is reloaded, and the stack trace points at the store rather than at the request that killed it. Keep errors out of your state Subject: catch at the edge and push an error-shaped **value** (`{ status: 'error', message }`) instead.
- **`.value` is a synchronous peek, not a subscription.** Reading `subject.value` inside a handler that is itself running during that Subject's emission is a re-entrancy trap — you are reading state mid-update, and the read order becomes dependent on subscription order. It is the same class of bug as reading a signal you are also writing inside an `effect`.

### Multicasting in RxJS 7 — share, connectable, and the deprecated operators

RxJS 7 (April 2021) replaced the entire `multicast` family with two things: a fully configurable `share()`, and `connectable()` for the case where you need to decide *when* the shared subscription starts. If your codebase still contains `publishReplay(1), refCount()`, that is a v6 idiom and the interviewer will notice.

**`share(config)`** — the configuration object landed in 7.0; notifier factories for the resets landed in 7.1. The defaults, straight from the source:

```typescript
share({
  connector: () => new Subject(),   // default. Use () => new ReplaySubject(1) to replay
  resetOnError: true,               // default — go cold again after an error, so the next subscriber retries
  resetOnComplete: true,            // default — go cold again after completion
  resetOnRefCountZero: true         // default — tear down when the last subscriber leaves
})
```

All three reset options also accept a **notifier factory** (`() => ObservableInput<any>`) instead of a boolean, which is the feature almost nobody knows and which solves a real problem:

```typescript
// Keep the shared subscription alive for 5s after the last subscriber leaves.
// Route away and straight back and you get the live stream, not a fresh connection.
socket$.pipe(share({
  connector: () => new ReplaySubject(1),
  resetOnRefCountZero: () => timer(5_000)
}))
```

**`connectable(source, config)`** — the v7 replacement for `multicast` + `ConnectableObservable`. The source stays dormant until you call `connect()`, which hands you back the `Subscription` that owns the shared connection:

```typescript
import { connectable, ReplaySubject } from 'rxjs';

const prices = connectable(this.socket.prices$, {
  connector: () => new ReplaySubject<Price>(1),
  resetOnDisconnect: true              // default true
});

const connection = prices.connect();   // one subscription to the socket, on your schedule
// ... later, deterministically:
connection.unsubscribe();
```

Use it when the lifetime of the shared subscription must be owned by something other than "whether anyone is currently subscribed" — an app-level service that connects on login and disconnects on logout, for instance. For everything else `share`/`shareReplay` is the right tool. The related `connect(selector)` operator (also new in 7.0) multicasts a source *within a single pipeline* so you can fan it out and recombine it without a second subscription to the source.

**What is deprecated, and what the annotations literally say** (RxJS 7.8.2 source):

| API | Annotation | Replacement |
|---|---|---|
| `multicast(...)` | "Will be removed in v8. To create a connectable observable, use `connectable`." | `connectable()` or `connect()` |
| `publish()`, `publish(selector)` | "Will be removed in v8." | `connectable()` / `connect()` |
| `publishReplay`, `publishBehavior`, `publishLast` | same family | `share({ connector })` with the matching Subject |
| `refCount()` | "Replaced with the `share` operator." | `share()` |
| `retryWhen(notifier)` | "Will be removed in **v9 or v10**, use `retry`'s `delay` option instead." | `retry({ count, delay })` |
| `toPromise()` | "Replaced with `firstValueFrom` and `lastValueFrom`. Will be removed in v8." | see the Promise-interop section below |
| `mergeMap(project, resultSelector)` | "The `resultSelector` parameter will be removed in v8." | inner `map` |
| `throwError(errorValue)` | "Support for passing an error value will be removed in v8." | `throwError(() => new Error(...))` |

Note the asymmetry in the `retryWhen` note — it is the one deprecation explicitly scheduled *later* than the others, because the migration is non-mechanical. Everything else in that table can be migrated on 7.8.2 today.

**What the next major has already removed** (landed in the `8.0.0-alpha` line that became v9): the `Symbol.observable` export, the deprecated `Subject.create` static, and `WebSocketSubject` no longer extends `Subject`. If you wrote a wrapper that subclasses `WebSocketSubject` or leans on `Subject.create`, that is the code the upgrade will break — not your operators.

> 🌍 **In the real world**: a trading UI kept a socket alive with `publishReplay(1), refCount()` and had a bug nobody could reproduce: navigating from the watchlist to the detail view and back occasionally dropped the price feed for a few seconds. `refCount()` tears down when the count hits zero, and Angular destroys the old component *before* creating the new one, so the count really did touch zero on every navigation — a reconnect on each route change, and a visible gap whenever the reconnect was slow. Migrating to `share({ connector: () => new ReplaySubject(1), resetOnRefCountZero: () => timer(3000) })` fixed it in one line, because the grace-period notifier is exactly the missing concept. The lesson is not "use the new API": it is that **`refCount` encodes a policy — "nobody is watching, so stop" — and route transitions momentarily satisfy that policy even when the user never left.**

### The operator catalog

Operators are functions that transform Observables. Used inside `.pipe()`:

```typescript
source$.pipe(
  filter(x => x > 10),
  map(x => x * 2),
  take(5),
  debounceTime(300)
).subscribe(...);
```

The most-used operators:

**Filtering:**
- `filter(predicate)` — keep matching values.
- `take(n)` — first N values, then complete.
- `takeUntil(notifier$)` — stop when notifier emits.
- `takeWhile(predicate)` — keep while predicate is true.
- `skip(n)` — drop first N.
- `distinctUntilChanged()` — drop consecutive duplicates.
- `debounceTime(ms)` — emit only after silence of `ms` (typing in search).
- `throttleTime(ms)` — emit at most once per `ms` window.

**Transformation:**
- `map(fn)` — transform each value.
- `scan(reducer, seed)` — Redux-like running accumulator (emits each step).
- `reduce(reducer, seed)` — final accumulator on complete.
- `pairwise()` — emit `[previous, current]`.
- `bufferTime(ms)` — collect values into arrays per time window.

**Combination:**
- `combineLatest([a$, b$])` — emits when ANY source emits, with the latest of each.
- `forkJoin([a$, b$])` — emits ONCE when all sources complete.
- `merge(a$, b$)` — interleaves emissions from all.
- `concat(a$, b$)` — emits a$ fully, then b$.
- `zip(a$, b$)` — pairs up values 1:1.
- `withLatestFrom(other$)` — use other$'s latest with each value of source.

**Flattening (higher-order):** see next section.

**Side effects:**
- `tap(fn)` — run side effect; pass values through. Like console.log without breaking the chain.

**Error handling:**
- `catchError(fn)` — replace the error with a fallback Observable.
- `retry(n)` / `retry({ count: n, delay: ... })` — re-subscribe on error.

**The ones that separate ten years from three**, because they only show up once you have hit the problem they solve:

- `finalize(fn)` — runs on complete, error **and** unsubscribe. The only correct place to clear a `loading` flag, because `catchError` misses cancellation and `complete` misses errors.
- `timeout({ each: 10_000 })` — errors with `TimeoutError` if the gap between emissions exceeds the budget. The missing half of every retry policy: without it, a request that hangs forever never reaches your `retry`.
- `defaultIfEmpty(x)` — the antidote to a filtered stream that completes empty and silently produces nothing downstream (and to `EmptyError` from `firstValueFrom`).
- `groupBy(keyFn)` + `mergeMap` — per-key sequencing. `concatMap` globally serialises; `groupBy(o => o.customerId), mergeMap(g => g.pipe(concatMap(save)))` serialises *per customer* and runs customers in parallel. This is the answer to "how do you keep order without giving up throughput".
- `mergeMap(project, concurrency)` — the second parameter is a concurrency cap. `mergeMap(upload, 3)` is a three-lane queue; `mergeMap(x, 1)` is `concatMap`.
- `audit`/`auditTime` and `sample`/`sampleTime` — "latest value, on my clock" rather than "every value" or "the first one".
- `startWith` / `pairwise` / `distinctUntilKeyChanged` — the small ones that remove a surprising amount of stateful component code.
- `EMPTY`, `NEVER`, `of()`, `defer(() => …)` — `defer` in particular: it re-evaluates its factory per subscription, which is how you make an Observable that reads a *current* token or timestamp instead of the one that existed when the pipeline was built.

### Higher-order mapping — switchMap, mergeMap, concatMap, exhaustMap

These four are the most-asked RxJS interview question. Each handles "I have an Observable; for each value, I want to call another async function."

```typescript
searchTerms$.pipe(
  someFlatteningOperator(term => this.api.search(term))
).subscribe(results => ...);
```

| Operator | Behavior on new outer value | Use case |
|---|---|---|
| **`switchMap`** | Cancel any in-flight inner; start new | Search-as-you-type, latest-wins |
| **`mergeMap`** (`flatMap`) | Run all inners in parallel | Independent operations, fan-out |
| **`concatMap`** | Queue inner; run sequentially | Order-sensitive operations |
| **`exhaustMap`** | Ignore new outer values until inner completes | Login button, prevent double-submit |

```typescript
// switchMap — search box; only the latest term matters
searchTerm$.pipe(
  debounceTime(300),
  distinctUntilChanged(),
  switchMap(term => this.api.search(term))     // cancel previous if new term arrives
).subscribe(results => this.results = results);

// mergeMap — process each click in parallel
clicks$.pipe(
  mergeMap(click => this.api.trackClick(click))   // all run concurrently
).subscribe();

// concatMap — save edits in order
edits$.pipe(
  concatMap(edit => this.api.saveEdit(edit))   // wait for previous save
).subscribe();

// exhaustMap — login button; ignore additional clicks during request
loginClicks$.pipe(
  exhaustMap(() => this.api.login(this.form.value))   // ignore clicks during in-flight
).subscribe();
```

The mental model: outer Observable emits ⇒ for each value, project to inner Observable ⇒ flatten to a single output stream. The four operators differ in how they handle **concurrent inners**.

#### Choose by failure mode, not by definition

Anyone can recite the four definitions. What an interviewer is actually probing is whether you pick them from the *symptom*, because that is how the choice arrives in real work — as a bug report, not as a design question.

| The bug you are handed | What is happening | Operator |
|---|---|---|
| "Search results flicker and sometimes show the wrong list" | Slow response for `"ma"` lands after the fast one for `"mars"` | **`switchMap`** — kill the stale request |
| "The customer was charged twice" / "two orders with the same lines" | Double-clicked submit; two POSTs in flight | **`exhaustMap`** — ignore clicks while one is running |
| "The audit log shows the edits out of order" / "last-write-wins picked the wrong write" | Parallel PATCHes resolved by arrival time | **`concatMap`** — queue them |
| "We hammered the downstream API and got 429s" | Unbounded fan-out | **`mergeMap(fn, n)`** — cap the lanes |
| "Order is only required per customer, and the queue is too slow" | Global serialisation used where per-key would do | **`groupBy` + `concatMap` inside `mergeMap`** |

The one-line versions worth memorising: **`switchMap` for reads, `exhaustMap` for writes, `concatMap` when order is load-bearing, `mergeMap` when nothing about order or duplication matters.** The default should be `switchMap` for GETs and `exhaustMap` for anything that mutates.

#### Why switchMap on a POST is a bug

`switchMap` cancels the inner subscription when a new outer value arrives. For a GET that is exactly right — you no longer want the answer. For a POST it is the wrong mental model twice over:

1. **You cancel your knowledge of the write, not the write.** Unsubscribing aborts the client's side of the request. The server has already received the bytes; if the handler is past the point of no return, the order is created, the payment is captured, the email is queued. What you discarded is the *response* — including the id of the thing you just created.
2. **The retry then duplicates it.** Because the caller saw "cancelled", the UI shows an error or an idle button, the user clicks again, and now there are two.

The fix is a pair, not a single operator. On the client, `exhaustMap` (plus a disabled button bound to a `loading` signal). On the server, an **idempotency key** the client generates once per user intent and sends as a header, so a genuine duplicate is recognised and answered with the original result. In .NET, that is typically a de-duplication table or a distributed-cache entry keyed on that header inside the command handler — and it is the answer interviewers want when they ask "what if the client retries anyway?"

#### What `unsubscribe` actually cancels

This is where the Angular and .NET halves of the interview meet.

- **In the browser (Angular v22 and later):** `HttpClient` uses the **fetch backend by default**. The v22 release notes deprecate `withFetch()` with "it can be safely removed", and flag the corresponding breaking change: use `provideHttpClient(withXhr())` if you still need upload-progress reports, which the fetch backend does not provide. The fetch backend creates an `AbortController` per request and calls `abort()` in the Observable's teardown, so unsubscribing genuinely aborts the in-flight request. On the older XHR backend the teardown calls `xhr.abort()` — same observable behaviour, different plumbing.
- **On the wire:** an aborted fetch closes the request stream. Whether the server ever notices depends on how far it got.
- **In ASP.NET Core:** it *can* notice. A `CancellationToken` parameter on a controller action or minimal-API handler is bound to `HttpContext.RequestAborted`, which fires when the client disconnects. If you pass that token down into EF Core and `HttpClient` calls, an abandoned request stops doing work; if you ignore it (the common case), the handler runs to completion and commits, and the client-side "cancellation" was cosmetic.

So the honest interview answer to "does `switchMap` cancel the server call?" is: *it cancels the browser's request and surfaces as `RequestAborted` on the server; whether that stops the work depends entirely on whether the .NET handler threads the cancellation token through. Which is why you do not use it for writes.*

> 🌍 **In the real world**: an internal ops tool let staff reassign a ticket from a dropdown, wired as `selection$.pipe(switchMap(id => api.reassign(ticket, id)))`. QA found nothing. In production, a user who picked the wrong person and immediately picked the right one produced tickets assigned to the *first* person about one time in twenty — the second request was faster than the first, the first landed later and won, and the cancelled-looking request had committed anyway. The fix was two lines: `exhaustMap` plus disabling the control while the mutation was pending. The general form is worth stating out loud in an interview: **cancellation in RxJS is a statement about what the client is still interested in, never a statement about what the server has already done.**

#### Nested `switchMap` and cancellation cascades

Cancellation propagates inward, never outward. In `outer$.pipe(switchMap(a => inner$(a).pipe(switchMap(b => leaf$(b)))))`, a new outer value tears down the inner chain *and* every leaf below it, while a new inner value tears down only the leaves. That is exactly what a dependent-dropdown screen (country → region → city) needs, and it is also why a leaked subscription at the leaf is so hard to see: the teardown looks automatic until someone converts one link in the chain to a manual `subscribe()` inside a callback, at which point the chain stops propagating and the leaves outlive the page.

### Combination operators

For combining multiple streams:

```typescript
// combineLatest — reactive form: name + email
combineLatest([
  nameControl.valueChanges,
  emailControl.valueChanges
]).pipe(
  map(([name, email]) => ({ name, email }))
).subscribe(form => /* ... */);

// forkJoin — multiple HTTP calls; wait for all
forkJoin({
  user: this.http.get<User>('/api/me'),
  orders: this.http.get<Order[]>('/api/orders'),
  notifications: this.http.get<Notif[]>('/api/notifications')
}).subscribe(({ user, orders, notifications }) => {
  // all three completed; use them
});

// merge — multiple sources of the same kind of event
merge(
  socket.messages$,
  pollInterval$.pipe(switchMap(() => this.api.getUpdates()))
).subscribe(update => this.handle(update));
```

`combineLatest` is the workhorse — "I want to react when any of these change." Common in reactive forms.

### Error handling

Default behavior: an error in the source terminates the stream — subsequent emissions stop. Two patterns:

**`catchError` to recover:**

```typescript
this.http.get<User>('/api/me').pipe(
  catchError(err => {
    console.error('Failed to load user', err);
    return of({ name: 'Anonymous' } as User);   // fallback Observable
  })
).subscribe(user => /* always fires, with fallback on error */);
```

**`retry` for transient failures:**

```typescript
this.http.get('/api/orders').pipe(
  retry({ count: 3, delay: 1000 })   // 3 retries, 1s apart
).subscribe(...);

// Or with exponential backoff.
// NOTE: retryCount is 1-based — the first retry is called with 1, not 0.
// So this schedules 2s, 4s, 8s, not 1s, 2s, 4s.
this.http.get('/api/orders').pipe(
  retry({
    count: 3,
    delay: (err, retryCount) => timer(Math.pow(2, retryCount) * 1000)
  })
).subscribe(...);
```

`retry` also takes `resetOnSuccess` (default `false`): with it set, the counter resets whenever the resubscribed source emits a value, which is what you want for a long-lived stream that reconnects — three failures *in a row* should fail, three failures over a day should not.

**Catching to keep the stream alive in higher-order:**

```typescript
searchTerm$.pipe(
  switchMap(term => this.api.search(term).pipe(
    catchError(err => of([]))   // inner caught; outer stream continues
  ))
).subscribe(results => /* ... */);
```

If the catchError were on the outer, one search failure would kill the search stream forever. Catch close to the source.

#### An unhandled error terminates the stream permanently

This is the single most consequential fact about RxJS error handling, and the one that produces the "the page just stops working until you refresh" bug class. `error` is a **terminal notification**, exactly like `complete`. Once it fires:

- no further values are delivered, ever, on that subscription;
- the teardown runs (so timers, sockets and requests are cleaned up — the stream is not leaking, it is *gone*);
- the source is not re-subscribed. There is no automatic recovery.

The pathological case is a long-lived stream that feeds the UI — form `valueChanges` piped into a save pipeline, a router-events pipeline, a websocket, a polling loop. One failed inner request without a `catchError` and the whole feature is silently inert for the rest of the session. The user's report will be "the save button stopped doing anything", and nothing in the console after the first error.

Where the error goes if you never catch it depends on how you subscribed:

- **`.subscribe({ next })` with no `error` callback** — RxJS reports it as an unhandled error, asynchronously, via `config.onUnhandledError` (default: rethrow on a fresh call stack, so it surfaces as a global `window.onerror`, not at your subscribe site).
- **`async` pipe** — the error is routed to Angular's application `ErrorHandler`. The binding keeps its last value and the subscription is finished; the pipe does **not** quietly render `null` and carry on.
- **`toSignal`** — the error is stored and **rethrown every time the signal is read**, which means it surfaces during template evaluation, at the consumer, not at the subscription.
- **`firstValueFrom` / `lastValueFrom`** — a rejected Promise, so `try`/`catch` around your `await` works normally.

#### Placement: inside the inner pipe, or outside?

The rule is mechanical once you see it as "which stream do I want to survive?":

```typescript
// ❌ Outer catch — the FIRST failure ends searching for the lifetime of the component
searchTerm$.pipe(
  switchMap(t => this.api.search(t)),
  catchError(() => of([]))
)

// ✅ Inner catch — each failed search is contained; the outer stream never sees an error
searchTerm$.pipe(
  switchMap(t => this.api.search(t).pipe(catchError(() => of([]))))
)
```

Both compile, both pass the happy-path test, and only one of them survives a 500. Two refinements a senior is expected to add:

- **`catchError` must return an Observable or rethrow.** To rethrow, use the factory form: `catchError(err => throwError(() => err))` — passing the value directly (`throwError(err)`) is deprecated in RxJS 7.
- **Do not let the fallback lie about its shape.** `catchError(() => of([]))` on a search is honest (no results). `catchError(() => of(null))` on a "load user" stream pushes `null` into code that has been told it has a `User`, and the failure resurfaces three components away as a property access on null. Prefer a discriminated result (`{ status: 'error', error }`) whenever the consumer needs to distinguish empty from broken — and note that `httpResource`/`rxResource` give you that distinction for free via `status()` and `error()`.

#### A retry policy that survives review

```typescript
this.http.get<Order[]>('/api/orders').pipe(
  timeout({ each: 10_000 }),                     // a hung request must fail before it can be retried
  retry({
    count: 3,
    delay: (err: unknown, retryCount: number) => {
      // Only retry what is worth retrying. 4xx will fail identically three more times.
      const status = err instanceof HttpErrorResponse ? err.status : 0;
      const retriable = status === 0 || status === 408 || status === 429 || status >= 500;
      if (!retriable) return throwError(() => err);

      const base = Math.min(2 ** retryCount * 1000, 30_000);   // retryCount starts at 1
      const jitter = Math.random() * base * 0.3;                // spread the herd
      return timer(base + jitter);
    }
  }),
  catchError(err => { this.notify.error('Could not load orders.'); return of([]); }),
  finalize(() => this.loading.set(false))        // runs on success, error AND unsubscribe
)
```

Four things that are load-bearing and usually missing: a **timeout** (a request that never answers is never retried), a **retriable-status filter** (retrying a 400 three times is three guaranteed failures plus 3× the latency before the user sees the error), **jitter** (without it, every client that failed during the same outage retries in lockstep and re-creates the outage the moment the service comes back — the thundering-herd problem your .NET side knows from Polly), and **`finalize`** rather than a `complete` handler, because cancellation is not completion.

> 🌍 **In the real world**: a team added `retry({ count: 3, delay: 1000 })` to a shared HTTP interceptor after a flaky-network sprint. Two months later a bad deploy started returning 401s from one endpoint. Every client turned each 401 into four requests, the auth service saturated, and the incident channel filled with "the login service is down" — the retry policy had turned a small failure into a self-inflicted load test, and the *actual* fault (an expired signing key) took an extra forty minutes to find under the noise. The retry was reinstated with a status filter and jitter. The generalisable line: **a retry without a predicate is an amplifier, and the thing it amplifies most reliably is your own outage.**

### Promise interop — toPromise, firstValueFrom, lastValueFrom

`toPromise()` is deprecated in RxJS 7 with the note "Replaced with `firstValueFrom` and `lastValueFrom`. Will be removed in v8" — i.e. in the next major. The reason it had to go is a design flaw, not a style preference, and the flaw is the interview question:

```typescript
const value = await someObservable$.toPromise();   // Promise<T | undefined>
```

`toPromise` resolves with the **last** value the source emitted, and with **`undefined`** if the source completed without emitting anything. Those two outcomes are indistinguishable when `T` itself can be `undefined`, and the `undefined` case is silent — the caller carries on with a value that never existed. The typings say `Promise<T | undefined>` for every source, which is why every `toPromise()` call site in a strict codebase either has a `!` on it or a defensive `if`.

The v7 replacements are explicit about both dimensions — *which* value, and *what happens on empty*:

| | Resolves with | Empty completion | Unsubscribes |
|---|---|---|---|
| `firstValueFrom(source$)` | the **first** emission | rejects with `EmptyError` | immediately after the first value |
| `lastValueFrom(source$)` | the **last** emission, on complete | rejects with `EmptyError` | on complete |
| `firstValueFrom(source$, { defaultValue: x })` | first emission, else `x` | resolves with `x` | — |
| `lastValueFrom(source$, { defaultValue: x })` | last emission, else `x` | resolves with `x` | — |

Consequences worth stating precisely:

- **`firstValueFrom` cancels.** It unsubscribes as soon as it has a value, which on an HTTP call is harmless (the response has arrived) but on a hot stream means the rest of the stream is never observed. That is the intended semantic, and it is what makes `firstValueFrom` the right bridge for one-shot requests.
- **`lastValueFrom` on an infinite source never settles.** No `EmptyError`, no timeout, no warning — just a Promise that hangs, and an `await` that never returns. Pair it with `take(n)`, `takeUntil`, or `timeout`.
- **`EmptyError` is a feature.** `firstValueFrom(this.http.get<User>(...))` on an endpoint returning `204 No Content` rejects rather than silently handing you `undefined`, which is exactly the distinction `toPromise` could not make.
- **In Angular, prefer staying in Observables** at the boundary — guards, resolvers, interceptors and `HttpClient` all accept them — and convert with `firstValueFrom` only where you genuinely want `async`/`await` ergonomics (test setup, a sequential script, an `APP_INITIALIZER`-style bootstrap step).

For a .NET reader, the sharpest contrast: `await someTask` does not cancel the work if the awaiting code goes away, whereas unsubscribing from an Observable does tear it down. `firstValueFrom` is where you give that up — once it is a Promise, cancellation is no longer part of the contract.

### Memory leak prevention

Subscriptions hold references. Forgotten subscriptions leak memory and trigger phantom callbacks. Three solutions:

**1. `async` pipe** (preferred when possible):
```html
<div *ngFor="let order of orders$ | async">
  {{ order.id }}
</div>
```
Angular subscribes when the template renders, unsubscribes when the component is destroyed. No manual cleanup.

**2. `takeUntilDestroyed()`** (shipped in Angular **v16** with `@angular/core/rxjs-interop`; promoted to **stable in v19**):
```typescript
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

constructor() {
  this.api.getOrders()
    .pipe(takeUntilDestroyed())
    .subscribe(orders => this.orders = orders);
}
```
The cleanest manual approach. Auto-completes the stream when the component is destroyed.

**3. Manual `Subject` notifier** (legacy pattern):
```typescript
private destroy$ = new Subject<void>();

ngOnInit() {
  this.api.getOrders().pipe(takeUntil(this.destroy$)).subscribe(...);
}

ngOnDestroy() {
  this.destroy$.next();
  this.destroy$.complete();
}
```
Common in older codebases; avoid in new code.

#### Every way a subscription actually leaks

"Leak" is used loosely. Precisely: a subscription keeps a reference to its observer, the observer closes over the component, and the component keeps its DI graph, its DOM references and its child components alive. So the leak is not the stream — it is everything the callback can see. The shapes, in rough order of how often they show up in a heap snapshot:

1. **`.subscribe()` in `ngOnInit` with no teardown**, on a source that never completes (`interval`, a socket, a `BehaviorSubject` in a root service, `router.events`, `form.valueChanges`). The canonical case.
2. **Nested `subscribe`.** The inner subscription is not owned by the outer one — cleaning up the outer leaves the inner running. Flatten instead.
3. **Subscribing to a root-scoped Subject from many components.** The Subject's subscriber list is the leak; it lives as long as the app. `takeUntilDestroyed` fixes the consumer side, but nothing fixes it if the components never unregister.
4. **`shareReplay({ refCount: false })` over an infinite source** — a permanent subscription by construction (see the cold/hot section).
5. **`toObservable()` or `toSignal()` created outside a destroyable injection context**, or with `manualCleanup: true` on a source that never completes. `manualCleanup` means exactly what it says: *you* own it now.
6. **`fromEvent(window, …)` / `fromEvent(document, …)`** in a component. The listener outlives the component along with everything the handler closes over.
7. **`takeUntil` placed anywhere but last.** Operators that resubscribe (`retry`, `repeat`) re-establish the upstream subscription *below* your teardown gate, so the gate stops applying. This is what the ESLint rule `no-unsafe-takeuntil` exists to catch.
8. **A pending request after destroy.** Not permanent, but real: the component stays reachable until the response arrives or the request aborts. `take(1)` does not help if the source never emits; `takeUntilDestroyed()` does, because destruction — not emission — is the trigger.

The systematic fix is not vigilance, it is removing the manual `subscribe` from components entirely: `async` pipe or `toSignal` for anything the template reads, `takeUntilDestroyed()` for genuine side effects, and a lint rule so the exceptions have to be argued in review.

#### `takeUntilDestroyed` — the mechanism, and its two sharp edges

It is a thin wrapper: it injects `DestroyRef`, builds an Observable that emits when `DestroyRef.onDestroy` fires, and pipes your source through `takeUntil` of that. Which explains both edges:

```typescript
export class OrdersComponent {
  private readonly destroyRef = inject(DestroyRef);   // field initializer = injection context

  ngOnInit() {
    // ❌ throws NG0203 — ngOnInit is not an injection context, so inject(DestroyRef) fails
    this.api.poll().pipe(takeUntilDestroyed()).subscribe();

    // ✅ pass the ref you captured earlier
    this.api.poll().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
  }
}
```

- **Edge one — injection context.** Called with no argument, `takeUntilDestroyed()` asserts it is running in an injection context (constructor, field initializer, factory, or inside `runInInjectionContext`). Outside one it throws `NG0203` ("can only be used within an injection context…"), not a warning. The explicit `takeUntilDestroyed(this.destroyRef)` overload exists precisely so you can use it in a method.
- **Edge two — it completes, it does not error.** `takeUntil` completes the stream, so your `complete` handler runs on destroy and your `error` handler does not. Also, if the `DestroyRef` has *already* been destroyed when you call it, the notifier emits synchronously and the source is never subscribed at all — a subtle but useful behaviour when you are handing observables around late in a component's life.

For services, the rule follows from ownership: a component-provided service gets the component's `DestroyRef` and behaves as you would expect; a `providedIn: 'root'` service is destroyed only when the application is, so `takeUntilDestroyed()` there is a no-op dressed as cleanup.

#### What the `async` pipe actually does

Worth knowing exactly, because "just use the async pipe" is advice, not an explanation:

- it subscribes on first `transform()` and unsubscribes in `ngOnDestroy` — the pipe instance is owned by the view;
- on each emission it stores the value and calls `markForCheck()`, which is what makes it work under `OnPush` (and under v22's OnPush-by-default);
- the subscription is created inside `untracked(...)`, so signal reads that happen as a side effect of subscribing are not captured as template dependencies;
- errors are routed to the application's `ErrorHandler`;
- **each `| async` in the template is its own subscription.** `{{ (user$ | async)?.name }}` twice means two subscriptions and, on a cold HTTP source, two requests. Bind once with `@if (user$ | async; as user)`.

> 🌍 **In the real world**: a team chased a memory report for two sprints — the JS heap climbing steadily across an hour of normal use, never coming back down — and kept finding "correctly unsubscribed" components. The actual retainer was a `providedIn: 'root'` notifications service whose `Subject` had accumulated one subscriber per visit to a dialog that never unsubscribed, each closure holding the dialog's component instance and its rendered rows. `takeUntilDestroyed()` in the dialog fixed it in one line. What made it expensive was the diagnosis, and the diagnosis was a habit rather than a tool: **take a heap snapshot, filter by your component's class name, and look at the retaining path** — the path names the leak in seconds, and every leak above shows up as a chain that ends at a subscriber list.

### Marble testing with TestScheduler

Marble testing is how you assert on *time* without waiting for it. `TestScheduler` from `rxjs/testing` runs your pipeline in virtual time, so a 300 ms debounce and a 30 s backoff both resolve instantly and deterministically.

```typescript
import { TestScheduler } from 'rxjs/testing';

let scheduler: TestScheduler;

beforeEach(() => {
  // The callback is how TestScheduler asserts — wire it to your test framework.
  scheduler = new TestScheduler((actual, expected) => expect(actual).toEqual(expected));
});

it('debounces, and cancels the in-flight search when a new term wins', () => {
  scheduler.run(({ cold, expectObservable, expectSubscriptions }) => {
    const terms  = cold('a 400ms b 900ms |', { a: 'ma', b: 'mars' });
    const search = cold('500ms r|', { r: ['Mars'] });      // a 500 ms API call

    const out$ = terms.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(() => search)
    );

    // 'ma' debounces to 300 and starts a search; 'mars' debounces to 701 and
    // replaces it, so only the second search ever produces a value (at 1201).
    expectObservable(out$).toBe('1201ms r 100ms |', { r: ['Mars'] });

    // The proof that switchMap cancelled: the first subscription is torn down at
    // 701 — before its response would have arrived at 800.
    expectSubscriptions(search.subscriptions).toBe([
      '300ms ^ 400ms !',
      '701ms ^ 500ms !',
    ]);
  });
});
```

(That test is exact — the frame arithmetic above is what RxJS 7.8.2 actually produces, including the fact that the outer `|` at 1302 is what completes the result, not the inner completion at 1202.)

**What `run()` changes.** Inside `testScheduler.run(callback)`:

- one marble frame (`-`) is **1 virtual millisecond**; outside `run()` the legacy `frameTimeFactor` of **10** applies, which is why old marble tests read so strangely;
- `maxFrames` is lifted (750 by default outside `run()`), so long backoffs are testable;
- RxJS's internal timer providers — `setInterval`, `setTimeout`, `setImmediate`, `requestAnimationFrame`, `Date.now`, `performance.now` — are delegated to the scheduler, so `delay`, `debounceTime`, `timer`, `interval`, `auditTime` all use virtual time **without being passed a scheduler**;
- the scheduler **flushes automatically when your callback returns**, which is when the assertions actually execute. Anything you assert with a plain `expect` *inside* the callback runs before the flush and will see pre-flush state.

**Reading the syntax fluently** (this is the part interviewers test by writing a marble on a whiteboard and asking what it means):

| Token | Meaning |
|---|---|
| `-` | one frame of virtual time (1 ms inside `run()`) |
| `a`–`z`, `0`–`9` | a `next()` of the value mapped in the values object |
| `\|` | `complete()` |
| `#` | `error()` |
| `^` | the subscription point — **hot observables only**; frames before it are negative time |
| `(abc)` | those notifications occur **synchronously in the same frame**; time then advances by the length of the group *including the parentheses* |
| `100ms`, `1.5s`, `2m` | time-progression syntax — only valid inside `run()`, and needs a space around it unless it starts the diagram |
| whitespace | ignored; use it to vertically align diagrams |

Two gotchas that will bite the first time:

- **An emission character consumes a frame of its own.** `'a 10ms b'` is not "b at 10 ms" — the `a` advances time by 1, so you usually write `'a 9ms b'` to land on 10. The docs call this out explicitly and it is the most common reason a marble test is off by one.
- **Promises are not virtualised.** `TestScheduler` delegates RxJS's scheduler providers, not the microtask queue. Anything that goes through a Promise — `from(promise)`, `async`/`await` in your code under test, `fetch`, an Angular `HttpClient` call that has not been mocked at the Observable level — will not respect virtual time. That, not "CI is slower", is the actual reason marble tests turn flaky.

**The assertion that earns its place is `expectSubscriptions`.** `expectObservable` proves what came out; `expectSubscriptions` proves *when the inner source was subscribed and unsubscribed* — which is the only direct way to test that `switchMap` cancelled, that `exhaustMap` ignored, or that `takeUntilDestroyed` tore down. "How would you prove your cancellation logic works?" is a standard senior follow-up, and `expectSubscriptions(inner.subscriptions).toBe([...])` — one marble string per subscription, with `^` for subscribe and `!` for unsubscribe — is the answer.

**Where marble tests do not belong.** Testing an Angular component's rendered output through marbles is usually the wrong layer — `fakeAsync`/`tick()` or the harness APIs read better there, and mixing `TestScheduler` with `fakeAsync` or a framework's fake timers gives you two competing clocks. Keep marbles for the pure pipeline: a custom operator, a service method that composes streams, an NgRx effect. The Angular CLI's default test runner is **Vitest as of v21**, but nothing above changes with the runner — `TestScheduler` brings its own clock and does not depend on Jasmine, Jest or Vitest timer mocks.

> 🌍 **In the real world**: a team's auto-save pipeline (`debounceTime(2000)` → `switchMap` → save) had a test that passed for a year and a bug that never went away: rapid edits occasionally saved an older document body. The test used `fakeAsync` + `tick(2000)` and asserted the final HTTP call, so it verified the debounce and said nothing about the *first* request being cancelled. Rewritten with `expectSubscriptions`, it failed on the first run — someone had changed `switchMap` to `mergeMap` months earlier to "fix a dropped save", and the two saves were racing. **Test the cancellation, not just the last value; a test that only asserts the final emission cannot see a race.**

### RxJS in the signals era

Signals replace many BehaviorSubject use cases. RxJS is still indispensable for **streams over time** (events, websocket, debounced search, polling, complex async chains). The two coexist via interop helpers:

```typescript
import { toSignal, toObservable } from '@angular/core/rxjs-interop';

// Observable → Signal
const orders$ = this.http.get<Order[]>('/api/orders');
orders = toSignal(orders$, { initialValue: [] });

// Signal → Observable
const search = signal('');
const search$ = toObservable(search);
search$.pipe(
  debounceTime(300),
  switchMap(term => this.http.get<Result[]>(`/api/search?q=${term}`))
).subscribe(...);
```

Modern guidance:
- **Pure state** → signal.
- **Streams of events / async sequences** → Observable.
- **HttpClient one-shot** → Observable + `firstValueFrom` or `toSignal`.
- **Complex async pipelines** → Observable; convert to signal at the end.

#### `toSignal` — the whole contract

Stability: shipped in **v16** (developer preview), **stable in v20**. The full options object as of v22:

```typescript
toSignal(source, {
  initialValue?: T,        // value returned before the first emission
  requireSync?: boolean,   // assert a synchronous first emission — no undefined in the type
  injector?: Injector,     // when you are not in an injection context
  manualCleanup?: boolean, // opt out of DestroyRef teardown entirely
  equal?: (a, b) => boolean,
  debugName?: string       // shows up in Angular DevTools
})
```

The behaviours that decide whether your code is correct:

- **It subscribes immediately, at the call site.** Not lazily on first read. So `toSignal` on a cold HTTP Observable fires the request when the field initializer runs, not when the template first reads it — that is a real difference from `| async`, which subscribes when the view renders and re-subscribes if the view is destroyed and recreated.
- **Without `initialValue` and without `requireSync`, the type is `Signal<T | undefined>` and the value is `undefined` until the first emission.** Not "the last value", not a loading sentinel — `undefined`. Every template that reads it needs to handle that state, which is exactly why so many codebases pass `{ initialValue: [] }` reflexively and then cannot distinguish "loading" from "no results".
- **`requireSync: true` removes the `undefined` from the type by asserting the source emits synchronously on subscribe.** If it does not, Angular throws **`NG0601`** — "`toSignal()` called with `requireSync` but `Observable` did not emit synchronously" — at creation time. Correct for a `BehaviorSubject`, a `startWith(...)` pipeline, or a `ReplaySubject(1)` that has already emitted. Never correct for `HttpClient`: an HTTP Observable is asynchronous by definition, so `requireSync` on it throws every single time.
- **Errors are rethrown at read.** The subscription's error is stored and thrown by the signal's getter, so it surfaces during template evaluation, at whatever consumer happens to read it — potentially far from the pipeline that failed. Catch inside the pipeline; do not rely on the signal to carry a failure gracefully. (The old `rejectErrors` option was **removed in v20** on the grounds that it "encourages uncaught exceptions" — it is not an option you can reach for.)
- **Completion is a non-event.** Signals have no notion of complete; the signal simply keeps returning the last value it saw.
- **Cleanup follows the injection context.** It takes `DestroyRef` from the current context (or the `injector` you pass) and unsubscribes on destroy. With `manualCleanup: true` there is no teardown at all — only safe for sources that complete on their own.
- **It must not be called inside a reactive context.** Calling `toSignal` inside a `computed`/`effect` throws in dev mode, because it would create a new subscription on every recomputation. This is the trap when someone "moves it closer to where it is used".

#### `toObservable` — an effect in disguise

Also **stable since v20**. Its implementation is three lines and explains every question you will be asked about it: a `ReplaySubject(1)` fed by an `effect` that reads the signal, completed when the injection context is destroyed.

That means:

- **it emits the latest value on subscribe** (ReplaySubject semantics), so it behaves like a `BehaviorSubject`, not like a plain `Subject`;
- **it emits when the signal stabilises, not on every write.** Five synchronous `set()` calls in one turn produce **one** emission of the final value. If you need every intermediate value — an analytics trail, an undo stack, a `pairwise()` diff — a signal was the wrong carrier and `toObservable` will not recover the history that was never there;
- **it completes on destroy**, which makes downstream `takeUntil`/`finalize` behave sanely;
- **it needs an injection context** (or an explicit `injector`), because it creates an `effect`.

> 🌍 **In the real world**: a team moved a filter panel from a `BehaviorSubject` to a `signal` and kept the analytics pipeline by wrapping it in `toObservable(filters).pipe(pairwise(), map(diff))`. The events went from a few hundred a day to a handful. Nothing was broken in the RxJS sense: their `applyPreset()` set four signals in a row, and where the old code had emitted four times, the effect-backed Observable coalesced them into one emission of the final state — so "user changed date range" and "user changed status" disappeared into a single combined event. They moved the analytics call to the place the *intent* lived (the preset handler) instead of inferring it from state transitions. **`toObservable` is a view of a value over time, not a log of the writes that produced it.**

#### `rxResource` — the v22 shape (and what changed since v19)

`resource()`, `rxResource()` and `httpResource()` were promoted **from experimental to stable in v22** (merged May 2026, released 3 June 2026). Their shape changed twice on the way there, which is exactly the kind of detail an interviewer uses to date your knowledge:

| Version | Status | Trigger option | Loader option |
|---|---|---|---|
| **v19.0** | `@experimental` | `request` | `loader` (returns an Observable) |
| **v19.2** | `@experimental` (`httpResource` added) | `request` | `loader` |
| **v20**, **v21** | still `@experimental` — the tag is in the source | **`params`** | **`stream`** |
| **v22** | **stable** (angular.dev says "stable since v22.0") | `params` | `stream` |

```typescript
readonly userId = signal<string | undefined>(undefined);

readonly user = rxResource({
  params: () => this.userId(),                       // reactive; undefined = don't load
  stream: ({ params, abortSignal, previous }) =>     // ResourceLoaderParams
    this.http.get<User>(`/api/users/${params}`),
  defaultValue: undefined,
  equal: (a, b) => a?.etag === b?.etag,
  // id: 'user'   // v22: key for TransferState caching across SSR → client
});

// user.value()  user.status()  user.error()  user.isLoading()  user.hasValue()  user.reload()
```

What it buys you over a hand-rolled `toSignal(pipeline)`, and what it costs:

- **Cancellation is built in.** When `params` changes or the resource is destroyed, the `abortSignal` fires and `rxResource` unsubscribes from your Observable — `switchMap` semantics, without the pipeline.
- **Status is first-class.** `status()` / `isLoading()` / `error()` / `hasValue()` replace the three parallel signals every team writes by hand, and `error()` means you no longer have to smuggle failures through the value type.
- **An Observable that completes without emitting is an error**, not an empty state: the resource fails with "Resource completed before producing a value". So `stream: () => EMPTY`, or a stream whose only value is filtered out, does not leave the resource pending — it errors. Worth knowing before you pipe `filter(...)` into one.
- **It is not a pipeline.** There is no debounce, no retry, no ordering guarantee across params changes other than last-wins. Compose that *inside* `stream`, or keep the pipeline in RxJS and convert with `toSignal` at the end. Choosing between the two is a real design decision, not a migration to be completed.

#### `debounced()` — signals grew a clock in v22 (experimental)

**Mark this as experimental if you bring it up** — angular.dev labels `debounced()` *Experimental*, available from v22.0. Say "stable" about it in an interview and you have handed the interviewer a correction. The shape: `debounced(source, wait, options?)`, where `wait` is a number of milliseconds or a function returning a Promise (a custom timer), and the return value is a **`Resource<T>`** — so you read `.value()` and can inspect `.isLoading()`:

```typescript
readonly query = signal('');
readonly debouncedQuery = debounced(() => this.query(), 300);

readonly results = rxResource({
  params: () => this.debouncedQuery.value(),
  stream: ({ params }) => this.api.search(params ?? '')
});
```

This is a genuine narrowing of RxJS's territory: the "debounce a value, then load" case — which was the poster child for `debounceTime` + `switchMap` — is now expressible in signals end to end, with cancellation supplied by the resource. What it still does not give you: retry with backoff, ordering across requests, merging several event sources, `exhaustMap`-style ignore-while-busy, buffering, or anything driven by an event that is not a value (a click, a socket frame, a router navigation). Answer the "do signals replace RxJS?" question with that boundary, not with a slogan.

#### So: when do you still reach for RxJS?

| Reach for RxJS when… | Because |
|---|---|
| the trigger is an **event**, not a value | clicks, keystrokes, socket frames, `router.events`, `valueChanges` — signals have no notion of "it happened again with the same value" |
| you need **cancellation** of in-flight work beyond a resource's last-wins | `switchMap`, `exhaustMap`, `takeUntil` |
| **time** is part of the requirement | debounce/throttle/audit/buffer/interval/timeout — the experimental `debounced()` covers one case of many |
| you need **retry, backoff, jitter, timeout** | `retry({ delay })` + `timeout` have no signal equivalent |
| **order** is load-bearing | `concatMap`, `groupBy` |
| several sources must be **coordinated** | `combineLatest`, `merge`, `race`, `zip`, `withLatestFrom` |
| the producer **pushes** | WebSocket, SSE, `BroadcastChannel`, `fromEvent` |

| Prefer signals when… | Because |
|---|---|
| it is **current state the template reads** | pull-based, glitch-free, and the template tracks it precisely |
| it is **derived** from other state | `computed()` beats `combineLatest(...).pipe(map(...))` for readability and for change detection |
| it is **async data keyed by state** | `resource`/`rxResource`/`httpResource` (stable in v22) |
| it is a **component input or model** | `input()` / `model()` are signals; converting them to Observables adds a hop |

The composite rule, and the one worth saying in an interview: **keep the pipeline in RxJS and convert once, at the edge, with `toSignal`.** Converting back and forth (`toObservable(toSignal(x$))`) is a smell — it means the ownership of that piece of state was never decided.

> 🌍 **In the real world**: a fifty-component app upgraded to v22 and a third of its screens stopped updating. Nothing in the release notes about the app's own patterns had changed — but **`OnPush` became the default change-detection strategy in v22** for any component with an undefined `changeDetection` property (`ChangeDetectionStrategy.Default` was renamed `Eager` and deprecated). Every component that had been mutating an array in place, or updating a field from inside a bare `.subscribe()` without `markForCheck()`, had been carried by `Default` for years and now failed. The upgrade migration adds `changeDetection: ChangeDetectionStrategy.Eager` where it can detect the risk, and taking that escape hatch is the correct short-term move — but the honest interview version of this story is that **the app had been depending on Angular re-checking everything on every event since v8, and every one of those components was already broken under `OnPush`; the version bump only made it visible.** They fixed the top twenty by hand (async pipe or `toSignal` for anything read by the template, immutable updates for the rest) and left `Eager` on the tail.

> 🌍 **In the real world**: a team put NgRx into a five-screen internal admin app because "we'll need it when it grows". Three years later it had eleven screens, four hundred lines of actions, and a rule that every new field needed an action, a reducer case, a selector and an effect. Half the state was server data that a `resource()` would now own for free, and the genuinely global state was a user profile and a feature-flag map — two signals in a service. The migration they eventually ran deleted the store for everything except one genuinely cross-cutting workflow. The interview-usable version is not "NgRx is bad": it is that **the cost of a store is paid per field, forever, and it is only worth paying where several distant features write the same state** — which was one slice out of eleven. Being able to say "we removed a state library and the design got better" is a senior sentence.

### The .NET seam — interceptors, token refresh, CORS, SSR

Full-stack interviews cross this boundary deliberately. Every item below is an RxJS problem *and* an ASP.NET Core problem, and the strong answers show both sides.

#### Functional interceptors and token attachment

Since v15, `provideHttpClient(withInterceptors([...]))` takes plain functions — `HttpInterceptorFn = (req, next) => Observable<HttpEvent<unknown>>` — which can use `inject()` directly. Class interceptors still work via `withInterceptorsFromDi()`, but new code has no reason to use them.

```typescript
export const SKIP_AUTH = new HttpContextToken(() => false);

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  // Requests are immutable — clone to modify.
  const token = auth.accessToken();
  const authed = token && !req.context.get(SKIP_AUTH)
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : req;

  return next(authed);
};
```

`HttpContext` is the mechanism for per-request opt-outs (skip auth, skip the retry policy, skip the loading spinner) without string-matching URLs — the request carries the flag, so the interceptor stays decoupled from your routing table.

#### The refresh race — several requests 401 at once

This is the interceptor question that separates people who have run this in production. A dashboard fires six requests on load; the access token has just expired; all six come back 401 at roughly the same moment. The naive interceptor issues **six** refresh calls. On a .NET back end that implements **refresh-token rotation** (the current OAuth BCP recommendation), the first refresh rotates the token and invalidates the one the other five are holding — and a rotated-token reuse is, correctly, treated as a possible theft signal, so the whole token family is revoked and every one of your users is logged out mid-session.

The fix is **single-flight**: one refresh, shared by everyone who needs it.

```typescript
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  readonly accessToken = signal<string | null>(null);
  private refresh$: Observable<string> | null = null;

  refreshOnce(): Observable<string> {
    // Every caller during the window gets the SAME in-flight request.
    this.refresh$ ??= this.http
      .post<{ accessToken: string }>('/auth/refresh', {}, {
        context: new HttpContext().set(SKIP_AUTH, true)   // never intercept the refresh itself
      })
      .pipe(
        map(r => r.accessToken),
        tap(t => this.accessToken.set(t)),
        finalize(() => (this.refresh$ = null)),           // reopen the gate, success or failure
        shareReplay({ bufferSize: 1, refCount: false })
      );

    return this.refresh$;
  }
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const attach = (r: HttpRequest<unknown>, token: string | null) =>
    token ? r.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : r;

  return next(attach(req, auth.accessToken())).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status !== 401 || req.context.get(SKIP_AUTH)) return throwError(() => err);

      return auth.refreshOnce().pipe(
        switchMap(fresh => next(attach(req, fresh))),   // replay this request once
        catchError(refreshErr => { auth.logout(); return throwError(() => refreshErr); })
      );
    })
  );
};
```

Points an interviewer will probe:

- **`finalize` rather than `tap`**, so the gate reopens on failure and on cancellation too — otherwise one failed refresh wedges the app into a state where nothing can ever refresh again. Note its **position**: above `shareReplay`, so it runs once when the shared upstream tears down, not once per subscriber.
- **The late-401 refinement.** A request that was already in flight with the old token can 401 *after* the refresh completed and the gate reopened — triggering a second, unnecessary refresh. The usual guard is to capture the token the request was sent with and, on 401, retry immediately if the service's current token is already newer, refreshing only when they match.
- **`SKIP_AUTH` on the refresh call itself**, or a 401 from `/auth/refresh` recurses forever.
- **Retry exactly once.** Without a guard, a permanently-401 endpoint plus a working refresh gives you an infinite request loop.
- **`switchMap` here is safe** because the retried request is your own replay of a request the server rejected — nothing was committed.
- **Distinguish 401 from 403.** 401 means "your token is stale, refresh"; 403 means "you are authenticated and not allowed", and refreshing it is a pointless round trip that hides an authorisation bug.
- **The .NET half:** short-lived access tokens, rotation with reuse detection, and clock-skew tolerance (`ClockSkew` defaults to five minutes in `TokenValidationParameters`, which is why a token can look valid to your API for minutes after the client thinks it expired).

> 🌍 **In the real world**: a team shipped refresh-on-401 without single-flighting, and it worked for a year because their dashboard made one request at a time. Then a redesign put six widgets on the landing page. Support started seeing users logged out "randomly, only in the morning" — that is, when everyone's overnight-expired token hit six parallel requests at once, six refreshes rotated over each other, and the API's reuse detection revoked the family. The mitigation someone proposed first was to disable rotation on the .NET side; the actual fix was eight lines of `shareReplay` on the client. **Concurrency the back end considers an attack is usually just a front end without a gate.**

#### CORS preflight is a per-request tax you can measure

Attaching `Authorization` makes a request non-simple, so the browser sends an `OPTIONS` preflight first. Per the CORS rules a preflight is skipped **only** when the method is GET/HEAD/POST, the headers are limited to the CORS-safelisted set (`Accept`, `Accept-Language`, `Content-Language`, `Content-Type`, `Last-Event-ID`), and `Content-Type` is one of `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`. A JSON API with bearer tokens fails that test on two counts, so essentially every call is preflighted.

What that costs, and how to reduce it:

- One extra round trip per *uncached* (origin, method, header-set) combination — on a high-latency connection that is the difference between a screen that paints and a screen that waits.
- `Access-Control-Max-Age` caches the preflight. Per MDN, the default is **5 seconds**, Firefox caps it at **24 hours**, and Chromium (since v76) caps it at **2 hours**. In ASP.NET Core: `policy.SetPreflightMaxAge(TimeSpan.FromHours(2))`.
- `AllowAnyOrigin()` together with `AllowCredentials()` is not a shortcut — Microsoft's guidance is explicit that the combination is insecure and the CORS service emits an invalid response, because the spec forbids `*` with credentials. Name your origins.
- The structural fix is to stop being cross-origin: serve the SPA and the API from the same origin (reverse proxy, or a BFF), and the preflight question disappears along with the third-party-cookie question.

#### Why SSR breaks cookie-based auth

Server-side rendering runs your components in Node. There is no browser, so there is **no cookie jar**: an `HttpClient` call made during SSR sends whatever headers you put on it and nothing else. `withCredentials: true` is a browser instruction and means nothing on the server. So a cookie-authenticated app renders as "logged out" on the server and "logged in" after hydration — a flash of the wrong UI at best, and a duplicate round trip for everything at worst.

The mechanism to fix it: read the inbound request and forward what you are allowed to forward.

```typescript
// Runs during SSR only. REQUEST is a public API in v22 and is null in the browser.
export const ssrCookieInterceptor: HttpInterceptorFn = (req, next) => {
  const request = inject(REQUEST);   // the Fetch API Request during SSR; null in the browser
  if (!request) return next(req);    // browser: the cookie jar already handles this

  const cookie = request.headers.get('cookie');
  const sameOrigin = req.url.startsWith('/') || req.url.startsWith(environment.apiOrigin);

  return next(cookie && sameOrigin
    ? req.clone({ setHeaders: { cookie } })
    : req);
};
```

Four things to say about that code, because each is a real failure mode:

- **Scope the forwarding.** Blindly attaching the user's session cookie to every outbound URL sends it to whatever third-party host a component happens to call.
- **Relative URLs do not resolve on the server.** `http.get('/api/orders')` needs an absolute base during SSR.
- **The transfer cache is where SSR leaks user data.** Angular serialises SSR HTTP responses into the HTML so the client does not re-fetch. By default, requests carrying `Authorization`, `Proxy-Authorization` or `Cookie` headers — and requests sent with credentials — are **excluded**. `withHttpTransferCacheOptions({ includeRequestsWithAuthHeaders: true })` turns that protection off, and the per-user payload is then embedded in a document that a CDN or a shared proxy may cache and serve to the next person. If you enable it, the page must be marked private end to end.
- **`pendingUntilEvent()`** (in `@angular/core/rxjs-interop`, **developer preview** since v20) makes an Observable's first emission count towards application stability, so SSR waits for it before serialising. Resources and `HttpClient` already participate via `PendingTasks`; a hand-rolled subscription does not, and that is why some SSR output renders a spinner forever.

#### When a chatty component tree forces a BFF

Signals and resources make it very easy for each component to own its own data — which is good design locally and, over a real network, a screen that issues one authenticated cross-origin request per widget, each with its own preflight, its own token attachment, and its own error path. The symptoms are recognisable: time-to-interactive dominated by request count rather than payload size, a waterfall on the network tab shaped like a staircase (because child components only mount once their parents have data), and an SSR pass that has to await all of it before it can serialise.

The **backend-for-frontend** answer is one endpoint per screen, shaped for that screen, composed server-side where the calls are cheap and local — and, in the OAuth variant of the pattern, the BFF also holds the tokens so the browser only ever carries a same-site `HttpOnly` session cookie. (The IETF's *OAuth 2.0 for Browser-Based Applications* — an Internet-Draft with intended status Best Current Practice — describes exactly this architecture.) For a .NET shop that is a small ASP.NET Core project, often with YARP in front for pass-through routes, and it collapses the preflight problem, the token-in-JS problem and the chattiness problem into one deployment unit.

The counter-argument you should also be able to make: a BFF is another service to version, deploy, monitor and keep in sync with the screens it serves, and teams that build one per team end up with an aggregation layer that duplicates domain logic. Reach for it when the round-trip count is the bottleneck or the token needs to leave the browser — not because the diagram looks tidier.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Marble diagrams (the universal RxJS visualization)

```
source$:          ──1──2──3──4──5───|→
                              │
                              ▼ map(x => x * 10)
                  ──10─20─30─40─50──|→
                              │
                              ▼ filter(x => x > 20)
                  ────────30─40─50──|→
                              │
                              ▼ take(2)
                  ────────30─40|

Time flows left to right.  | = complete.  X = error.
```

Mental model: each operator is a transformation of the timeline of values.

### Search-as-you-type — the canonical RxJS pattern

```typescript
@Component({
  template: `
    <input [formControl]="searchControl" placeholder="Search orders..." />
    @for (result of results(); track result.id) {
      <div>{{ result.title }}</div>
    }
  `
})
export class SearchComponent {
  searchControl = new FormControl('', { nonNullable: true });
  results = toSignal(
    this.searchControl.valueChanges.pipe(
      debounceTime(300),                              // wait for typing pause
      distinctUntilChanged(),                          // ignore unchanged value
      switchMap(term => term.length < 2
        ? of([])
        : this.api.search(term).pipe(
            catchError(err => {
              console.error(err);
              return of([]);
            })
          ))
    ),
    { initialValue: [] }
  );

  constructor(private api: SearchApi) {}
}
```

Five operators, four operational concerns: pause-while-typing, deduplicate, latest-wins, error-recover. Without RxJS, this is dozens of lines of state and timer management.

### The same typeahead, three ways (v22)

Worth being able to write all three and to say which you would pick and why — this is the most likely "code on the whiteboard" prompt for a senior Angular role in 2026.

```typescript
// 1. Classic RxJS. Still the most explicit about time and cancellation.
results = toSignal(
  this.searchControl.valueChanges.pipe(
    debounceTime(300),
    distinctUntilChanged(),
    switchMap(term => this.api.search(term).pipe(catchError(() => of([]))))
  ),
  { initialValue: [] as Result[] }
);

// 2. Signal in, RxJS in the middle, signal out. Use when the trigger is already a signal
//    (an input(), a linkedSignal, a form model) but the pipeline needs real operators.
query = signal('');
results2 = toSignal(
  toObservable(this.query).pipe(
    debounceTime(300),
    distinctUntilChanged(),
    switchMap(term => this.api.search(term).pipe(catchError(() => of([]))))
  ),
  { initialValue: [] as Result[] }
);

// 3. Signals end to end (v22). debounced() — EXPERIMENTAL — supplies the timer; rxResource
//    (stable) supplies cancellation, loading and error state. No pipeline, and no
//    retry/ordering control either.
debouncedQuery = debounced(() => this.query(), 300);
search = rxResource({
  params: () => this.debouncedQuery.value(),
  stream: ({ params }) => this.api.search(params),
  defaultValue: [] as Result[]
});
// template: @if (search.isLoading()) { … } @else { @for (r of search.value(); track r.id) { … } }
```

Trade-offs to state out loud: (1) is the most testable with marbles and the most portable; (2) is the bridge you will actually write during a migration, and its cost is the `effect`-based coalescing in `toObservable`; (3) is the least code and gives you `isLoading()`/`error()` free, but the moment you need retry-with-backoff, `exhaustMap` semantics, or coordination with a second stream, you are back to composing inside `stream` — which is (2) with extra steps.

### Higher-order mapping illustrated

```
Outer:    ──A──B──C──|→        (request triggers)
Inner A:    ──a1─a2─a3─|→      (response stream for A)
Inner B:       ──b1─b2─b3─|→
Inner C:          ──c1─c2─c3─|→

mergeMap (parallel; all interleave):
  result: ──a1─a2─b1─a3─b2─c1─b3─c2─c3─|→

concatMap (sequential; queue):
  result: ──a1─a2─a3─b1─b2─b3─c1─c2─c3─|→

switchMap (cancel previous):
  result: ──a1─a2─b1─b2─c1─c2─c3─|→
              ↑       ↑       ↑
        (a3 cancelled)(b3 cancelled)

exhaustMap (ignore new while inner running):
  result: ──a1─a2─a3─c1─c2─c3─|→
              ↑       ↑
        (B ignored — A still running)
        (C runs because A completed before C)
```

Pick by intent. For search-as-you-type: switchMap. For "save edits in order": concatMap. For "fan out independent jobs": mergeMap. For "ignore double-clicks": exhaustMap.

### Forms + RxJS — composing form state

```typescript
@Component({...})
export class OrderFormComponent {
  form = this.fb.group({
    customerId: [0, Validators.required],
    items: this.fb.array([]),
    notes: ['']
  });

  // Computed total stream
  total$ = this.form.get('items')!.valueChanges.pipe(
    startWith(this.form.get('items')!.value),
    map(items => items.reduce((sum, i) => sum + i.price * i.quantity, 0))
  );

  // Auto-save when form is valid and stable
  private autoSave$ = this.form.valueChanges.pipe(
    debounceTime(2000),
    filter(() => this.form.valid),
    distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
    switchMap(value => this.orderService.saveDraft(value).pipe(
      catchError(err => of({ saved: false, error: err }))
    ))
  );

  constructor(private fb: FormBuilder, private orderService: OrderService) {
    this.autoSave$.pipe(takeUntilDestroyed()).subscribe(result => {
      console.log('Auto-saved:', result);
    });
  }
}
```

The form's `valueChanges` is an Observable — debounce, validate, persist as a single declarative pipeline.

### Caching with shareReplay

```typescript
@Injectable({ providedIn: 'root' })
export class CountryService {
  // Loaded once; replayed to all subscribers
  private countries$ = this.http.get<Country[]>('/api/countries').pipe(
    shareReplay({ bufferSize: 1, refCount: false })
  );

  getCountries() {
    return this.countries$;
  }
}

// Multiple subscribers; one HTTP call
this.countryService.getCountries().subscribe(c => /* ... */);
this.countryService.getCountries().subscribe(c => /* same data, no new request */);
```

`refCount: false` keeps the cache alive even when subscribers drop to zero. `refCount: true` would teardown when last unsubs.

### Error retry with backoff

```typescript
this.http.get<Order[]>('/api/orders').pipe(
  retry({
    count: 3,
    // retryCount is 1-based: the first retry is called with 1.
    delay: (err, retryCount) => {
      const delayMs = Math.min(Math.pow(2, retryCount - 1) * 1000, 30_000);
      console.warn(`Retry ${retryCount} in ${delayMs}ms after error:`, err);
      return timer(delayMs);
    }
  }),
  catchError(err => {
    this.notify.error('Failed to load orders. Please refresh.');
    return of([]);
  })
).subscribe(orders => this.orders = orders);
```

Exponential backoff (1s, 2s, 4s) with a cap and a user-facing fallback if all retries fail. The `- 1` is not cosmetic: RxJS calls the `delay` function with the retry *count*, starting at 1, so `2 ** retryCount` would start at two seconds. In production add a retriable-status check and jitter — see the retry policy in [Error handling](#error-handling).

### Memory-safe subscription patterns

```typescript
// ✅ Best — async pipe, no manual subscribe
@Component({
  template: `
    @if (user$ | async; as user) {
      <p>Hello, {{ user.name }}</p>
    }
  `
})
export class UserComponent {
  user$ = this.http.get<User>('/api/me');
}

// ✅ Good — takeUntilDestroyed (Angular 16+)
constructor() {
  this.api.getOrders()
    .pipe(takeUntilDestroyed())
    .subscribe(orders => this.orders = orders);
}

// ⚠️ Acceptable — toSignal for one-shot data
orders = toSignal(this.api.getOrders(), { initialValue: [] });

// ❌ Bad — leaks if component destroyed
ngOnInit() {
  this.api.poll().subscribe(data => this.data = data);
  // never unsubscribed; phantom subscription survives
}
```

</details>

## Common pitfalls

1. **Not unsubscribing.** Subscriptions outlive components → leaks. Use async pipe, `takeUntilDestroyed`, or explicit unsubscribe.
2. **Subscribing inside subscribe (nested subscribes).** Code smell. Use `switchMap` / `mergeMap` / `concatMap` to flatten.
3. **`mergeMap` for everything.** Concurrent inners cause race conditions. Use `switchMap` for "latest wins," `concatMap` for ordered.
4. **Cold Observable subscribed multiple times.** HttpClient.get() fires per subscribe. Use `shareReplay` to multicast.
5. **Calling `.pipe()` without subscribing.** No subscription = no execution. Cold Observables only run when subscribed.
6. **Side effects in `map`.** `map(x => { sideEffect(); return x; })` is wrong — that's `tap`. Use `tap` for side effects, `map` for transformations.
7. **`catchError` at the wrong level.** Catching too high terminates the outer stream forever. Catch inside `switchMap` to recover one inner.
8. **`Subject` for app state.** Use `BehaviorSubject` (initial value + late subscribers see current) or signals. Plain `Subject` loses values to late subscribers.
9. **`debounceTime` without `distinctUntilChanged`.** "abc" → "abcd" → "abc" debounce-emits "abc" twice. Add distinct.
10. **Mutating values in operators.** Operators expect immutability. Mutating arrays/objects in `map` causes spooky bugs.
11. **Forgetting `startWith` for combineLatest.** combineLatest waits for ALL sources to emit at least once. With form controls or BehaviorSubjects, this is fine; with cold streams, prepend `startWith(initial)`.
12. **Over-using RxJS.** Not everything needs to be a stream. Plain Promises, signals, and arrays of values are simpler when there's no time dimension.
13. **`switchMap` on a non-idempotent request.** Cancelling a POST cancels your knowledge of the write, not the write. `exhaustMap` for submits, plus an idempotency key on the server.
14. **`retry` without a predicate, a timeout or jitter.** Retrying a 400 three times is three guaranteed failures; retrying a hung request never happens at all; retrying in lockstep with every other client re-creates the outage you are recovering from.
15. **`requireSync: true` on an HTTP Observable.** It throws `NG0601` every time — HTTP is asynchronous by definition. `requireSync` is for `BehaviorSubject`s and `startWith` pipelines.
16. **Calling `toSignal` inside a `computed` or `effect`.** It throws in dev mode, because it would resubscribe on every recomputation. Create it once, in a field initializer.
17. **Expecting `toObservable` to emit every write.** It is backed by an `effect` and a `ReplaySubject(1)`, so synchronous writes coalesce into one emission.
18. **`takeUntil` (or `takeUntilDestroyed`) that isn't last in the pipe.** Anything below it that resubscribes — `retry`, `repeat` — re-establishes the upstream subscription beneath your teardown gate.
19. **Multiple `| async` on the same source in one template.** Each occurrence is its own subscription and, on a cold source, its own HTTP request. Bind once with `@if (x$ | async; as x)`.
20. **A `catchError` fallback that lies about the shape.** `of(null)` handed to code that was promised a `User` moves the failure three components away. Return an error-shaped value, or let `rxResource`'s `error()` carry it.
21. **Letting an error reach a state `Subject`.** `error()` is terminal for the Subject itself — every future subscriber gets the error and every future `next()` is dropped. The feature is dead until reload.
22. **Assuming `shareReplay` is a cache.** With the default `refCount: false` it never invalidates and never unsubscribes; on an infinite source that is a permanent subscription.

## Interview-ready summary

- **Observable** = lazy stream of values over time. Subscribe to run; unsubscribe to stop.
- **Cold** = unicast (HTTP). **Hot** = multicast (DOM events, Subjects).
- **Subjects:** `Subject` (no initial), `BehaviorSubject` (initial + current to late subscribers), `ReplaySubject(n)` (replay last N).
- **Operators** transform via `.pipe()`. The big four flattening: `switchMap` (cancel), `mergeMap` (parallel), `concatMap` (sequential), `exhaustMap` (ignore-while-busy).
- **Combination:** `combineLatest` (any), `forkJoin` (all complete), `merge`, `concat`, `zip`.
- **Error handling:** `catchError` to recover, `retry` with backoff for transient.
- **Memory safety:** `async` pipe, `takeUntilDestroyed()`, explicit unsubscribe.
- **Modern Angular:** signals for state; RxJS for streams; interop via `toSignal()` and `toObservable()`.
- **Versions (Aug 2026):** Angular **v22** (3 June 2026) peer-depends on `rxjs@^6.5.3 || ^7.4.0`; stable RxJS is **7.8.2**; the next major is **9.0.0-beta.0** (the v8 line was renumbered), so "will be removed in v8" means "the next major".
- **Stability ladder:** `takeUntilDestroyed` stable in **v19**; `toSignal`/`toObservable` stable in **v20**; `resource`/`rxResource`/`httpResource` stable in **v22**; `pendingUntilEvent` is still **developer preview**.
- **`toSignal` contract:** subscribes immediately; `undefined` until first emission unless `initialValue`; `requireSync` asserts a synchronous emission or throws **NG0601**; errors are rethrown **at read**.
- **`toObservable` contract:** `effect` + `ReplaySubject(1)` — latest value on subscribe, one emission per stabilisation, completes on destroy.
- **Terminal means terminal:** an unhandled error ends the stream permanently; a Subject that errors is dead for every future subscriber.
- **v22 defaults that change RxJS code:** `OnPush` is the default change-detection strategy (`Default` renamed `Eager` and deprecated), and `HttpClient` uses **fetch** by default (`withFetch()` deprecated, `withXhr()` for upload progress).

**Expected interview questions:**

1. *"`switchMap` vs `mergeMap` vs `concatMap`?"* — switchMap cancels previous inner on new outer (search-as-you-type). mergeMap runs all in parallel (fan-out). concatMap queues sequentially (ordered saves). exhaustMap ignores new while inner running (login click).
2. *"What's a cold vs hot Observable?"* — Cold: producer runs per subscription; HTTP requests are cold. Hot: shared producer; DOM events are hot. `shareReplay` makes a cold one hot for caching.
3. *"`Subject` vs `BehaviorSubject` vs `ReplaySubject`?"* — Subject: no initial value, late subscribers miss old values. BehaviorSubject: has current value, late subscribers get it immediately. ReplaySubject(n): replays last N values to late subscribers.
4. *"How do you avoid memory leaks with RxJS?"* — Three options: `async` pipe in template (auto-clean), `takeUntilDestroyed()` (Angular 16+), or explicit `Subject<void>` + `takeUntil` + complete in `ngOnDestroy`.
5. *"How do you implement search-as-you-type?"* — `valueChanges.pipe(debounceTime(300), distinctUntilChanged(), switchMap(term => api.search(term)))`. Five operators handle pause, dedup, cancel-previous, error.
6. *"What's `shareReplay` and when do you use it?"* — Multicasts a cold Observable; replays last N values to new subscribers. Use for caching API responses (one HTTP call, many subscribers).
7. *"RxJS vs signals?"* — Signals: reactive primitives for state (current value). Observables: streams of values over time (events, async pipelines). Coexist via `toSignal` / `toObservable`. New apps: signals for state, RxJS for streams.
8. *"With `resource()` stable and `debounced()` (experimental) in v22, when do you still reach for RxJS?"* — Events rather than values; cancellation semantics beyond last-wins (`exhaustMap`); retry/backoff/jitter/timeout; ordering (`concatMap`, `groupBy`); coordinating several sources; anything that pushes (sockets, SSE). Signals own current state, derived state and — since v22 — keyed async loading.
9. *"What does `toSignal` return before the Observable emits, and how do you avoid it?"* — `undefined`, and the type says so. Pass `initialValue`, or `requireSync: true` if the source is synchronous (`BehaviorSubject`, `startWith`) — the latter throws `NG0601` if it is not. Never `requireSync` on `HttpClient`.
10. *"Five requests 401 at once. What happens?"* — Naively, five refresh calls; with rotation on the server, the later four present an already-rotated token, reuse detection fires and the session family is revoked. Single-flight the refresh (`shareReplay` + `finalize` to reset the gate), mark the refresh call itself to skip the interceptor, and retry the original request exactly once.
11. *"How would you prove in a test that your typeahead cancels the stale request?"* — `TestScheduler.run()` with `expectSubscriptions` on the inner cold Observable: assert the first subscription's `!` lands before its response frame. `expectObservable` alone cannot see a race.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> **Q: What is the difference between Observable, Subject, BehaviorSubject, and ReplaySubject?**
> A: `Observable` is a lazy unicast producer — each subscriber gets its own execution. `Subject` is both Observable and Observer; hot (multicast), no initial value, late subscribers miss past values. `BehaviorSubject<T>` is a Subject with a current value — late subscribers immediately receive the latest emission; use for "current state." `ReplaySubject(n)` buffers the last N emissions and replays them to any new subscriber regardless of when they subscribe.
>
> Cross-Q: You use a plain `Subject` as an event bus. A component subscribes after the first event fires. What does it receive?
> A: Nothing from before the subscription. Subject has no buffer. The component only sees events emitted after it subscribes. If the component needs the latest state, switch to `BehaviorSubject`. If it needs recent history (e.g., last 5 messages in a chat), use `ReplaySubject(5)`.
>
> Cross-Q²: A service exposes a `BehaviorSubject` directly (`public cart$ = new BehaviorSubject<Item[]>([])`). What is wrong with this, and how do you fix it?
> A: External callers can call `cart$.next([])` — bypassing the service's validation and mutation logic. Expose `cart$.asObservable()` for reading, and provide explicit mutation methods (`add()`, `remove()`) that call `next()` internally. The subject itself stays private.

### Drill 2 — Cold vs hot observables

> **Q: What makes an Observable cold vs hot, and why does it matter in practice?**
> A: Cold: the producer function runs fresh per subscriber — each subscriber gets its own execution. Every `HttpClient.get()` is cold; subscribing twice fires two HTTP requests. Hot: a shared producer; subscribers see the same emissions from the point they subscribe. DOM events, WebSocket messages, and Subjects are hot — they emit regardless of subscriber count.
>
> Cross-Q: You want multiple components to share one HTTP response. How do you turn a cold Observable hot?
> A: Pipe with `shareReplay({ bufferSize: 1, refCount: false })`. The first subscriber triggers the HTTP call; subsequent subscribers get the cached last emission immediately. `refCount: false` keeps the cache alive when subscribers drop to zero; `refCount: true` re-fetches when subscriber count drops to zero and someone subscribes again.
>
> Cross-Q²: `shareReplay` with `refCount: false` is used to cache an auth token HTTP call. The token expires. How does the cache invalidate?
> A: It doesn't automatically — `shareReplay` with `refCount: false` holds the value indefinitely. You must either switch to `refCount: true` (re-fetches on new subscription after last unsub) or build manual invalidation: hold a reference to the `Observable`, reset it to `null` on token expiry, and reassign a new `http.get(...).pipe(shareReplay(1))`. Alternatively, use a `BehaviorSubject` to hold the token and update it imperatively.

### Drill 3 — switchMap vs mergeMap vs concatMap vs exhaustMap

> **Q: Walk me through all four higher-order mapping operators and their use cases.**
> A: `switchMap` — on each outer emission, cancel the in-flight inner and start a new one. Use for search-as-you-type; only the latest request matters. `mergeMap` (`flatMap`) — run all inners concurrently; no cancellation. Use for independent parallel operations (track multiple clicks). `concatMap` — queue inners; start the next only after the previous completes. Use for order-sensitive sequential operations (save edits). `exhaustMap` — ignore new outer values while an inner is running. Use for non-idempotent actions (login button, payment submit).
>
> Cross-Q: You use `mergeMap` for a save operation. Two saves overlap. What can go wrong?
> A: Race condition — both HTTP requests are in-flight simultaneously; the server may process them out of order. The second response could overwrite the first's result, or the server could reject the concurrent write. Use `concatMap` for ordered writes or `exhaustMap` if you want to ignore additional save triggers while one is pending.
>
> Cross-Q²: `switchMap` is used for an HTTP POST (order submission). The user types quickly and triggers a cancellation. Has the cancelled request actually been cancelled on the server?
> A: RxJS cancels by unsubscribing from the inner Observable, and Angular's HTTP backend tears the request down: the fetch backend — **the default since v22**, which is why `withFetch()` is now deprecated as removable — calls `abort()` on its `AbortController`; the XHR backend (`provideHttpClient(withXhr())`, still needed for upload progress) calls `xhr.abort()`. So the browser really does abandon the request. Whether the *server* stops is a different question: in ASP.NET Core a client disconnect trips `HttpContext.RequestAborted`, which is what a `CancellationToken` parameter binds to — if the handler threads that token into EF Core and downstream calls, the work stops; if it ignores it (the common case), the write commits and you have simply thrown away the response. Which is the whole argument for `exhaustMap` on writes plus a server-side idempotency key.

### Drill 4 — combineLatest vs forkJoin vs zip

> **Q: When do you use combineLatest, forkJoin, and zip, and how do they differ in emission timing?**
> A: `combineLatest([a$, b$])` — emits whenever ANY source emits, pairing with the latest of the others. Requires all to have emitted at least once. Ideal for reactive form state, filter combinations. `forkJoin([a$, b$])` — emits exactly once when ALL sources complete, with their last values. Ideal for parallel HTTP calls where you need all results together. `zip(a$, b$)` — pairs values index-for-index: first emission of A with first of B, second with second. Rarely used except for sequential pairing.
>
> Cross-Q: `combineLatest` doesn't emit initially even though both sources are BehaviorSubjects. Why?
> A: This shouldn't happen with BehaviorSubjects — they emit their current value synchronously on subscription, satisfying `combineLatest`'s "all must have emitted once" condition. If you see this, one "source" is actually a cold Observable that hasn't emitted. Fix: `startWith(initialValue)` on cold sources before passing to `combineLatest`.
>
> Cross-Q²: You have three HTTP calls using `forkJoin`. One fails with a 404. What happens to the other two?
> A: `forkJoin` propagates the error immediately, cancelling (unsubscribing) the remaining inner Observables. The combined Observable errors; you never get results from the other two. To handle partial failures gracefully, wrap each inner with `catchError(err => of(null))` so failures produce a null value rather than terminating the join.

### Drill 5 — takeUntil vs takeUntilDestroyed

> **Q: What is the difference between takeUntil and takeUntilDestroyed for subscription cleanup?**
> A: `takeUntil(notifier$)` is a generic operator — completes the source when `notifier$` emits. Used with a `Subject<void>` destroyed in `ngOnDestroy`. Verbose: requires a destroy Subject field, `next()` + `complete()` calls. `takeUntilDestroyed()` (Angular 16+, from `@angular/core/rxjs-interop`) uses `DestroyRef` internally — automatically completes when the injection context (component, directive) is destroyed. Cleaner; no boilerplate.
>
> Cross-Q: `takeUntilDestroyed()` is called inside `ngOnInit` rather than in the constructor. What happens?
> A: It throws — this is not a warning. With no argument, `takeUntilDestroyed()` calls `assertInInjectionContext` and then `inject(DestroyRef)`; `ngOnInit` is a lifecycle hook, not an injection context, so you get **`NG0203`**: "takeUntilDestroyed() can only be used within an injection context such as a constructor, a factory function, a field initializer, or a function used with `runInInjectionContext`". The two correct shapes are (a) call it in a field initializer or the constructor, or (b) capture `private destroyRef = inject(DestroyRef)` as a field and call `takeUntilDestroyed(this.destroyRef)` wherever you like. Also worth knowing: if the `DestroyRef` has already been destroyed, the notifier emits synchronously and the source is never subscribed at all.
>
> Cross-Q²: You have a subscription in a service (not a component). Can `takeUntilDestroyed` be used there?
> A: Yes if the service is provided at component level (`providers: [MyService]` on the component). The `DestroyRef` it captures is the component's — the subscription completes when the component is destroyed. For `providedIn: 'root'` services (app lifetime), `takeUntilDestroyed` is meaningless since the service is never destroyed. Use `first()`, `take(1)`, or explicit `unsubscribe()` for one-shot operations in root services.

### Drill 6 — debounceTime vs throttleTime vs auditTime

> **Q: What is the difference between debounceTime, throttleTime, and auditTime?**
> A: `debounceTime(ms)` — waits for `ms` silence; emits the last value after no new values for `ms`. Resets timer on each emission. Use for search-as-you-type (emit only after user stops typing). `throttleTime(ms)` — emits immediately, then silences for `ms`. Use for rate-limiting scroll/resize events (emit first, ignore flood). `auditTime(ms)` — waits `ms` after the first emission in a window, then emits the latest. Similar to throttle but emits at the END of the window with the most recent value.
>
> Cross-Q: A user types "hello world" — 11 keystrokes in 500ms. debounceTime(300) is applied. How many emissions reach the downstream operator?
> A: One — the value "hello world" emitted 300ms after the last keystroke. Each keystroke resets the timer. The first 10 keystrokes are discarded because new values arrive before the timer fires.
>
> Cross-Q²: You use `throttleTime(1000)` for a scroll handler that updates a sticky header's position. The user scrolls quickly for 3 seconds, then stops. The header's final position is wrong. Why?
> A: `throttleTime` (default leading=true, trailing=false) emits at the start of each window and discards all trailing values. The last scroll position after the user stops may never emit if it falls in a silent window. Fix: `throttleTime(1000, asyncScheduler, { leading: true, trailing: true })` to also emit the final value after the window ends, or use `auditTime(100)` for a "emit latest every 100ms" pattern.

### Drill 7 — share vs shareReplay

> **Q: What is the difference between share and shareReplay?**
> A: `share()` is the RxJS 7 replacement for the old `multicast(() => new Subject()), refCount()` pairing, and it is fully configurable: `connector` (default `() => new Subject()`), `resetOnError`, `resetOnComplete` and `resetOnRefCountZero`, all defaulting to `true` and all able to take a notifier factory instead of a boolean. It multicasts to active subscribers; if all unsubscribe and a new one subscribes later, the source is re-subscribed from scratch (no replay). `shareReplay(n)` is literally `share` with a `ReplaySubject(n)` connector plus `resetOnError: true`, `resetOnComplete: **false**` and `resetOnRefCountZero: refCount` — which is why a completed source keeps replaying forever while a failed one goes cold and lets the next subscriber retry. Use `share` for hot streams where late subscribers don't need history; `shareReplay(1)` to de-duplicate concurrent subscribers to an HTTP call.
>
> Cross-Q: `shareReplay({ bufferSize: 1, refCount: true })` vs `shareReplay(1)` — what is the difference?
> A: `shareReplay(1)` is equivalent to `shareReplay({ bufferSize: 1, refCount: false })`. With `refCount: false`, the source stays subscribed even when all subscribers unsubscribe — the cache is kept forever. With `refCount: true`, the source is torn down when subscriber count drops to zero; the next subscription re-triggers the source. Prefer `refCount: true` to avoid dangling subscriptions and stale caches.
>
> Cross-Q²: Two components subscribe to the same `shareReplay(1)` HTTP Observable. Both unsubscribe (user navigates away). A third component later subscribes. Does it get the cached value or re-fetch?
> A: With `refCount: false` — gets the cached value, no re-fetch. With `refCount: true` — the source was torn down when the second subscriber left; the third subscription re-triggers the HTTP call. Choose based on whether staleness or extra HTTP calls are the greater concern.

### Drill 8 — catchError vs retry vs retryWhen

> **Q: What is the difference between catchError, retry, and retryWhen in error handling?**
> A: `catchError(fn)` — intercepts the error and replaces the stream with a fallback Observable (or re-throws). The original stream is terminated; downstream receives the fallback's emissions instead. `retry(n)` — resubscribes to the source Observable on error, up to n times; useful for transient network failures. `retryWhen` — custom retry logic driven by a notifier Observable; **deprecated**, with the source note saying it will be removed "in v9 or v10", and replaced by the `retry({ count, delay, resetOnSuccess })` config that landed in **RxJS 7.3**. Note the `delay` callback is invoked with a **1-based** retry count.
>
> Cross-Q: Where you place `catchError` matters critically. Explain the difference between catching at the outer vs inner level in a `switchMap` chain.
> A: Outer catch: `searchTerm$.pipe(switchMap(t => api.search(t)), catchError(err => of([])))` — the first search failure terminates the entire search stream; no further searches are possible. Inner catch: `searchTerm$.pipe(switchMap(t => api.search(t).pipe(catchError(err => of([])))))` — each search error is isolated; the outer stream continues; subsequent searches still work. Always catch errors at the innermost level when the outer stream must survive.
>
> Cross-Q²: `retry({ count: 3 })` retries 3 times and then errors. The caller doesn't catch the error. What happens in Angular?
> A: The error propagates to the subscriber's `error` callback. If there is none, RxJS reports it through `config.onUnhandledError`, which by default rethrows on a fresh call stack — so it surfaces as a global error, not at your `subscribe()` line. The Observable is terminated: no more values, no `complete`, and the teardown has already run. What happens in a template depends on the bridge: the **`async` pipe routes the error to Angular's application `ErrorHandler`** and keeps rendering its last value (it does not silently swap in `undefined`), while **`toSignal` stores the error and rethrows it every time the signal is read**, so it detonates during template evaluation at whichever consumer reads it. Either way the stream is finished. Always pair `retry` with a terminal `catchError` — and prefer an error-shaped value (or `rxResource`'s `error()`) over a fallback that pretends the call succeeded.

### Drill 9 — Marble testing with TestScheduler

> **Q: What is marble testing and what problem does TestScheduler solve?**
> A: Marble testing lets you write RxJS tests using ASCII timeline strings (marbles) to describe Observable behavior over virtual time. `TestScheduler` from `rxjs/testing` controls time — `debounceTime`, `delay`, `timer` all respect virtual time, so you can test time-based operators synchronously without real `setTimeout` waits.
>
> Cross-Q: Write the marble syntax for testing that debounceTime(300) on input "abc" (three quick emissions, one after 400ms silence) emits exactly once.
> A: Inside `run()` you do **not** pass the scheduler to the operator — `debounceTime(300)` picks up virtual time automatically, because `run()` delegates RxJS's internal timer providers. The test is:
>
> ```typescript
> scheduler.run(({ cold, expectObservable }) => {
>   const source = cold('abc 400ms |');           // a@0, b@1, c@2, complete@403
>   expectObservable(source.pipe(debounceTime(300))).toBe('302ms c 100ms |');
> });
> ```
>
> Read the expectation out loud: nothing for 302 frames, then `c`, then the source's completion at 403. Only `c` survives because each of `a` and `b` reset the timer one frame later. Note the frame arithmetic that trips everyone up — an emission character advances time by one frame itself, so `c` at frame 2 debounces to 302, not 300.
>
> Cross-Q²: A marble test passes locally but fails in CI where the CPU is slower. What is the cause and fix?
> A: Wall-clock speed cannot affect a `TestScheduler.run()` test — virtual time is deterministic and the whole block runs synchronously. So the failure means something in the test is *not* on virtual time. `run()` delegates RxJS's own providers (`setTimeout`, `setInterval`, `setImmediate`, `requestAnimationFrame`, `Date.now`, `performance.now`) — it does **not** virtualise the microtask queue. Anything that goes through a Promise escapes: `from(promise)`, an `async` function inside the code under test, a real `fetch`, an un-mocked `HttpClient`. The fix is to keep the unit under test Observable-all-the-way (mock at the Observable boundary, not the Promise boundary) and to test Promise-based code with `async`/`await` instead. A second, less common cause: mixing `TestScheduler` with `fakeAsync`/`tick` or a framework's fake timers, which gives you two clocks fighting over the same callbacks.

### Drill 10 — Scheduler types

> **Q: What are RxJS schedulers and when would you use asyncScheduler vs queueScheduler vs animationFrameScheduler?**
> A: Schedulers control when Observable emissions and operator callbacks are executed. `asyncScheduler` — defers work with `setTimeout(fn, delay)`; good for non-urgent background work, avoids blocking the call stack. `queueScheduler` — executes synchronously in a queue (FIFO); used for recursion prevention in synchronous pipelines. `animationFrameScheduler` — schedules work via `requestAnimationFrame`; ideal for DOM updates that should sync with the browser paint cycle (smooth animations, canvas updates).
>
> Cross-Q: `observeOn(asyncScheduler)` vs `subscribeOn(asyncScheduler)` — what is the difference?
> A: `subscribeOn` controls on which scheduler the subscription setup runs (the producer). `observeOn` controls on which scheduler values are delivered to the next operator/subscriber (the consumer). For moving work off the main thread context: `observeOn(asyncScheduler)` defers downstream processing to a `setTimeout`. For starting a slow producer asynchronously: `subscribeOn(asyncScheduler)`.
>
> Cross-Q²: You have a `scan` accumulating 10,000 values emitted synchronously. The UI freezes. How do you fix it using schedulers?
> A: Be careful with the framing first: `observeOn(asyncScheduler)` does not move work off the main thread and does not reduce the work — it schedules each downstream delivery through `setInterval`/`setTimeout`, i.e. as **macrotasks** (not microtasks), so the browser can paint and handle input between them. That converts one long block into 10,000 small ones, which fixes "the tab is frozen" but makes total wall-clock time worse and, under zone-based change detection, can trigger 10,000 change-detection passes. The better answers in order: reshape the stream so the UI never sees 10,000 emissions (`bufferTime(16)`, `auditTime(16)`, or a `scan` that accumulates and a separate throttled read for the template); only then consider `observeOn` for yielding; and if the *computation* is genuinely expensive rather than merely frequent, put it in a Web Worker and let the stream carry the results back.

### Drill 11 — scan vs reduce

> **Q: What is the difference between scan and reduce in RxJS?**
> A: `scan(reducer, seed)` — like `Array.reduce` but emits the accumulated value after **every emission**. The stream stays open; each new value triggers a new accumulated result. `reduce(reducer, seed)` — accumulates all values and emits the **final result only on `complete`**. If the source never completes, `reduce` never emits. Use `scan` for running totals, Redux-style state updates, and live aggregation. Use `reduce` for batch summarization of a finite stream.
>
> Cross-Q: Show how scan implements a simple Redux-style state store.
> A: `const state$ = actions$.pipe(scan((state, action) => reducer(state, action), initialState), startWith(initialState), shareReplay(1))`. Each action dispatched to `actions$` triggers `scan`, which applies the reducer and emits the new state. All components subscribing to `state$` get current and future states. This is conceptually what NgRx does internally.
>
> Cross-Q²: A `scan` accumulates items in an array. You push items but the template doesn't update because you mutated the array with `push()` instead of spreading. Why does this happen, and how does it relate to RxJS?
> A: RxJS itself doesn't care — `scan` emits the same array reference you returned from the reducer. Angular's change detection (or signal comparison) checks the reference. If you `push()` into an existing array and return the same reference, nothing detects a change. Always return a new array: `[...acc, newItem]`. This is the pure reducer contract; mutation in scan is the same bug as mutation in Redux reducers.

### Drill 12 — Higher-order observable flattening strategies

> **Q: What is a higher-order Observable and why do you need a flattening operator?**
> A: A higher-order Observable is an Observable that emits Observables — `Observable<Observable<T>>`. Without flattening, you'd have to subscribe inside a subscribe (nested subscribes — the anti-pattern). Flattening operators (`switchMap`, `mergeMap`, `concatMap`, `exhaustMap`) merge the inner Observables back into a single output stream. They take a projection function `(outerValue) => Observable<innerValue>` and handle the inner subscriptions automatically.
>
> Cross-Q: `mergeAll` vs `mergeMap` — what is the difference?
> A: `mergeMap(project)` is equivalent to `map(project)` + `mergeAll()`. `mergeAll()` operates on an already-higher-order Observable (you've already done the `map`); `mergeMap` combines both steps. Same relationship for `switchMap` = `map` + `switchAll`, `concatMap` = `map` + `concatAll`. The combined form (`switchMap`, etc.) is almost always preferred — cleaner and the intent is explicit.
>
> Cross-Q²: You nest `switchMap` inside `switchMap`. When does the inner-inner Observable get cancelled?
> A: When the inner `switchMap`'s source emits a new value, it cancels the inner-inner Observable. When the outer `switchMap`'s source emits a new value, it cancels the entire inner Observable chain including its inner-inner subscriptions. Cancellation cascades inward. This is useful for multi-level search (select category → select subcategory → fetch products): each level's new selection cancels the downstream request tree.

### Drill 13 — RxJS with Angular: async pipe vs manual subscribe

> **Q: Why is the async pipe preferred over manual subscribe in Angular components?**
> A: `async` pipe subscribes when the template renders and unsubscribes when the component is destroyed — automatic lifecycle management, no memory leaks. It also calls `markForCheck()` on each emission, making it compatible with `OnPush` change detection. Manual `subscribe()` requires you to hold the `Subscription`, call `unsubscribe()` in `ngOnDestroy`, and manually handle change detection if on `OnPush`. More code, more surface for mistakes.
>
> Cross-Q: A component subscribes to an Observable in `ngOnInit` and updates a local field. With OnPush, the template doesn't update. Why?
> A: OnPush only checks the component when inputs change, events occur, or `markForCheck()` / `detectChanges()` is called. A bare `.subscribe()` callback updates a field but doesn't tell Angular to check the component. Fix: inject `ChangeDetectorRef` and call `this.cdr.markForCheck()` inside the subscribe callback, or use the `async` pipe which calls `markForCheck()` automatically.
>
> Cross-Q²: The async pipe is used in a template with an Observable that emits frequently (WebSocket messages, ~100/sec). Is this a performance problem, and how do you mitigate it?
> A: At 100 emissions/sec, async pipe calls `markForCheck()` 100 times per second triggering change detection. With default CD strategy this is heavy; with OnPush it's managed at that component but still runs 100 times. Mitigate: `auditTime(16)` or `throttleTime(16)` to cap at ~60fps. For very high-frequency streams, use `observeOn(animationFrameScheduler)` to synchronize updates with browser paint cycles, or switch to a signal updated in a subscription, then let the template signal-track.

### Drill 14 — Memory leaks: common patterns

> **Q: Name three common subscription patterns that cause memory leaks in Angular.**
> A: (1) `ngOnInit() { this.service.poll$.subscribe(x => this.data = x); }` with no `ngOnDestroy` unsubscribe. (2) `combineLatest([a$, b$]).subscribe(...)` stored in a local variable that's never unsubscribed — the component is destroyed but the subscription holds a reference to the component's closure. (3) Using a `Subject` in a service as an event bus, subscribing to it in many components, and never calling `complete()` — subjects in root services live forever, and component callbacks leak via the subscriber list.
>
> Cross-Q: You add ESLint rule `rxjs/no-unsafe-takeuntil` to the project. What does it catch?
> A: (In the maintained fork the rule id is `rxjs-x/no-unsafe-takeuntil`, described as "disallow applying operators after `takeUntil`".) `takeUntil` placed before other operators that can re-subscribe (`repeat`, `repeatWhen`, `retry`, `retryWhen`) is unsafe — after `takeUntil` fires, the re-subscribe operators restart the upstream subscription, bypassing the takeUntil teardown and leaking. The rule enforces that `takeUntil` is the last operator in the pipe before `subscribe`, ensuring it's the final teardown gate.
>
> Cross-Q²: A developer argues: "I use `take(1)` so I don't need to unsubscribe." Is this always correct?
> A: Yes for one-shot Observables that complete after `take(1)` (e.g., HTTP calls, router events). No for long-lived sources where the component is destroyed before the first emission — `take(1)` is still holding a live subscription in that case. Also no if the Observable is a `BehaviorSubject` that emits synchronously — `take(1)` completes immediately, which is correct. The edge case: if the source never emits (pending HTTP, filtered-out event), `take(1)` keeps the subscription open until it does. For components, `takeUntilDestroyed()` is more robust than `take(1)` for anything that might not emit before destroy.

### Drill 15 — Custom operator creation with pipe()

> **Q: How do you create a custom RxJS operator using pipe()?**
> A: A custom operator is a function that takes an Observable and returns an Observable. The idiomatic form: `const myOp = <T>(config: Config) => (source$: Observable<T>): Observable<Result> => source$.pipe(operatorA(), operatorB())`. It's just a function returning a function — pipeable. Usage: `source$.pipe(myOp(config))`. You compose existing operators internally; no need to write a new subscriber from scratch unless you need low-level control.
>
> Cross-Q: Write a custom operator `distinctUntilChangedDeep` that uses deep equality instead of reference equality.
> A: `const distinctUntilChangedDeep = <T>() => (source$: Observable<T>) => source$.pipe(distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)))`. Use a proper deep-equality library (`fast-deep-equal`) instead of JSON.stringify for production — JSON.stringify has ordering issues and can't handle circular references. The operator is still a simple composition: `distinctUntilChanged` with a custom comparator.
>
> Cross-Q²: Your custom operator needs to accumulate state across emissions (like a ring buffer of the last N values). Is composing existing operators enough or do you need to use the `new Observable(subscriber => ...)` constructor?
> A: Composition is enough — `scan` is the right primitive: `const lastN = (n: number) => <T>(src$: Observable<T>) => src$.pipe(scan((buf, val) => [...buf.slice(-(n-1)), val], [] as T[]))`. The `new Observable` constructor is only needed for truly imperative sources (wrapping a callback API, a DOM event, a WebSocket) or for custom teardown logic that composition can't express. For transformation operators, composition with scan/bufferCount/pairwise is almost always sufficient.

### Drill 16 — toSignal: initialValue, requireSync, and errors

> **Q: What does `toSignal(source$)` return before the source emits, and what are your options?**
> A: `undefined` — and the type says `Signal<T | undefined>`, so the template has to handle it. Three ways out: pass `initialValue` (the value returned until the first emission); pass `requireSync: true`, which asserts the source emits synchronously on subscribe and removes `undefined` from the type; or accept the `undefined` and treat it as "not loaded yet". Also know that `toSignal` subscribes **immediately at the call site**, not lazily on first read, so any side effect of subscribing happens when the field initializer runs.
>
> Cross-Q: A developer writes `data = toSignal(this.http.get<Data>('/api/data'), { requireSync: true })` to avoid the `undefined`. What happens?
> A: It throws `NG0601` — "`toSignal()` called with `requireSync` but `Observable` did not emit synchronously" — every time, at creation. An HTTP Observable cannot emit synchronously. `requireSync` is for sources that are guaranteed synchronous: a `BehaviorSubject`, a `ReplaySubject(1)` that has already emitted, or any pipeline ending in `startWith(...)`. For HTTP, use `initialValue`, or better, use `httpResource`/`rxResource` so "loading" is a real state (`isLoading()`) rather than a sentinel value.
>
> Cross-Q²: The observable behind a `toSignal` errors. Where does the error surface, and how do you handle it?
> A: The error is stored and **rethrown from the signal's getter** — so it is thrown wherever the signal is read, typically during template evaluation, in a component that may be far away from the pipeline that failed. There is no `error` callback to attach and no `rejectErrors` option (it was **removed in v20** for encouraging uncaught exceptions). Handle it inside the pipeline with `catchError`, mapping failure to a value your template can render, or move to `rxResource` where `status()` and `error()` are part of the contract.

### Drill 17 — rxResource vs a hand-rolled toSignal pipeline

> **Q: `rxResource` went stable in v22. When would you use it instead of `toSignal(pipeline$)`?**
> A: When the shape is "reactive params in, async value out, and the template needs loading/error state". `rxResource({ params, stream })` re-runs the loader when `params` changes, aborts the previous one (its `abortSignal` unsubscribes your Observable), and exposes `value()`, `status()`, `isLoading()`, `error()`, `hasValue()` and `reload()`. A `toSignal(pipeline$)` gives you a value and nothing else — every team that writes one also hand-rolls three sibling signals for loading, error and reload. Use RxJS when the *pipeline* is the point: debounce, retry with backoff, `exhaustMap`, ordering, or merging several sources.
>
> Cross-Q: Your `stream` returns an Observable that completes without emitting — say `EMPTY`, or a stream where a `filter` rejected the only value. What does the resource do?
> A: It errors, with "Resource completed before producing a value". It does not sit in `loading` forever and it does not fall back to `defaultValue`. This surprises people migrating a filtered pipeline into a resource: if "no value" is a legitimate outcome, emit a value that represents it (`of(null)`, `defaultIfEmpty(...)`) rather than completing empty.
>
> Cross-Q²: Someone on your team says `rxResource` proves signals have replaced RxJS. What is the accurate version?
> A: `rxResource` *consumes* an Observable — the loader's return type is `Observable<T>`, so RxJS is still the transport. What v22 removed is the boilerplate around a very common shape: keyed async loading with cancellation and status. What it did not remove: debouncing (except the narrow case covered by the **experimental** `debounced()`), retry with backoff, `exhaustMap` semantics for writes, ordering guarantees, coordination between multiple streams, and everything push-driven. Signals own state; Observables own events. `rxResource` is the bridge for the one case that is both.

### Drill 18 — the 401 refresh race

> **Q: Six requests fire on page load, the access token has just expired, and all six return 401. What does a naive interceptor do, and what should it do?**
> A: A naive `catchError(401) → refresh → retry` interceptor issues **six** refresh calls. With refresh-token rotation on the server, the first rotates the token and the other five present one that has just been invalidated — which a correct implementation treats as possible token theft and answers by revoking the whole token family, logging the user out. The fix is single-flight: cache the in-flight refresh Observable in the service, share it with `shareReplay({ bufferSize: 1 })`, and clear it in `finalize` so the gate reopens on success *and* failure. Every 401'd request then `switchMap`s onto the same refresh and replays itself once.
>
> Cross-Q: What stops this from becoming an infinite loop?
> A: Two guards. First, the refresh call itself must bypass the interceptor — mark it with an `HttpContextToken` (`SKIP_AUTH`) rather than matching on the URL, so a 401 from `/auth/refresh` propagates instead of triggering another refresh. Second, retry the original request **exactly once**: if the replay also 401s, log out rather than looping. It is also worth distinguishing 401 from 403 — refreshing on 403 is a wasted round trip that masks an authorisation bug.
>
> Cross-Q²: Why `finalize` rather than `tap` to clear the cached refresh Observable?
> A: `tap`'s next/complete handlers do not run when the stream errors or is unsubscribed. If the refresh fails once and you only cleared the cache on success, every future 401 in the session reuses a dead, permanently-erroring Observable — `shareReplay` will replay that error to every new subscriber, so the app can never recover without a reload. `finalize` runs on complete, error and unsubscribe, which is exactly the "the flight is over, whatever happened" semantic a single-flight gate needs.

</details>

## Cheat Sheet

- **switchMap vs concatMap**: switchMap cancels previous, concatMap queues sequentially.
- **mergeMap vs exhaustMap**: mergeMap runs all in parallel, exhaustMap ignores new while busy.
- **Cold vs hot**: cold = per-subscriber execution (HTTP); hot = shared (DOM events, Subjects).
- **`shareReplay(1)`**: caches last emission and multicasts; canonical HTTP cache for one-shots.
- **`BehaviorSubject` over `Subject`**: late subscribers immediately receive the current value.
- **`takeUntilDestroyed()`**: v16, stable in v19; ties the stream to the injection context's `DestroyRef`. Outside an injection context it throws **NG0203** — pass `takeUntilDestroyed(this.destroyRef)`.
- **`debounceTime` needs `distinctUntilChanged`**: otherwise repeating values still emit twice.
- **`catchError` placement matters**: catch inside `switchMap` to keep outer stream alive.
- **`combineLatest` waits for all**: prepend `startWith()` if any source is cold/late.
- **`firstValueFrom` for Promise interop**: replaces deprecated `.toPromise()`; awaits first emission and rejects with `EmptyError` on empty completion (`toPromise` resolved with `undefined` instead).
- **`switchMap` for reads, `exhaustMap` for writes**: cancelling a POST cancels the response, not the write.
- **`retry` needs a predicate, a `timeout` and jitter**: the `delay` callback's retry count is **1-based**.
- **`finalize` over `complete`**: it is the only hook that also runs on unsubscribe.
- **`toSignal` = subscribe now, `undefined` until first emission**; `requireSync` throws **NG0601** if the source is async.
- **`toObservable` = `effect` + `ReplaySubject(1)`**: latest on subscribe, one emission per stabilisation.
- **`rxResource` (stable v22)**: `params` + `stream`, aborts on param change; completing without emitting is an **error**.
- **`TestScheduler.run()`**: 1 frame = 1 ms (10 outside `run`), auto-flush at the end, `expectSubscriptions` is how you prove cancellation.

## Walkthrough — Leaking subscriptions in a SPA

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: After 100 navigations the app's CPU climbs to 80% and memory grows by 200 MB. Component instances appear stale: typing in a search box triggers requests that update components no longer on screen.

**Diagnosis**: Open Chrome DevTools → Performance Monitor; watch JS heap and listener counts grow monotonically across navigations. Take heap snapshots before and after navigating between two routes 50 times; compare retained components — `OrderListComponent` instances accumulate, each retained by an `OrderService.orders$` subscription closure. Search the codebase for raw `.subscribe(` and find 14 components calling `service.getX().subscribe(...)` in `ngOnInit` with no teardown.

**Fix**: Three migration patterns. For one-shot HTTP, swap to `toSignal(this.api.getOrders(), { initialValue: [] })` so Angular owns the lifecycle — or, on v22, to `rxResource`/`httpResource` so loading and error state come with it. For ongoing streams (search, polling), pipe `takeUntilDestroyed()` from `@angular/core/rxjs-interop` inside an injection context, or with an explicit `DestroyRef` outside one. For templates, prefer `@if (orders$ | async; as orders)` — the async pipe auto-unsubscribes on destroy, and binding once avoids the second subscription that two `| async` occurrences would create. Then make it stick with lint: `rxjs-angular-x/prefer-takeuntil` (and `rxjs-x/no-unsafe-takeuntil`) fail PRs with bare or mis-ordered subscribes. Note the plugin names — the original `eslint-plugin-rxjs` / `eslint-plugin-rxjs-angular` are unmaintained; the actively published forks are **`eslint-plugin-rxjs-x`** (rule prefix `rxjs-x/`) and **`eslint-plugin-rxjs-angular-x`** (`rxjs-angular-x/`).

**Why it works**: Each leaked subscription pinned the component, its DI graph, and any closed-over template references. `takeUntilDestroyed()` and the async pipe both register `DestroyRef` callbacks so streams complete deterministically; heap snapshots show retained instance count drop back to 1 after navigation.

</details>

## Self-test

<details><summary>1. Why does `HttpClient.get()` sometimes fire twice for one logical call?</summary>

Cold Observables run their producer per subscription. If a service exposes the Observable directly and two consumers subscribe (e.g., template `async` pipe plus a `.subscribe()` in component code), each issues an HTTP request. Fix with `shareReplay({ bufferSize: 1, refCount: true })` to multicast the response, or read once and cache the result in a signal.
</details>

<details><summary>2. When does `combineLatest` not emit, and how do you fix it?</summary>

It waits for every source to emit at least once. If one source is a cold Observable that hasn't emitted (e.g., a route param stream that fires only on navigation), the combined stream never starts. Fix by prepending `startWith(initialValue)` to that source, or use `BehaviorSubject` (already has a current value), or restructure with `withLatestFrom` so only the trigger source must emit.
</details>

<details><summary>3. Trade-off: `switchMap` vs `exhaustMap` for a save button.</summary>

`switchMap` cancels the in-flight request when the user clicks again — fine for idempotent reads but dangerous for non-idempotent saves (you may abort the network call after the server already started writing, leaving partial state). `exhaustMap` ignores subsequent clicks while the save is running — safer for non-idempotent operations and prevents double-submission. Pair with a `loading` signal to disable the button visually.
</details>

<details><summary>4. Why does `tap` exist when `map` could do the same thing?</summary>

`tap` signals intent — side effects (logging, telemetry, mutating cached state) without changing the stream. `map` is for transformation; mutating in `map` and returning the same value technically works but obscures intent and breaks immutability assumptions in operators downstream (e.g., `distinctUntilChanged` may now see the same reference). Reviewers should reject side effects inside `map`.
</details>

<details><summary>5. Should new code use signals exclusively and abandon RxJS?</summary>

No. Signals model current values; Observables model streams of values over time. Events (clicks, websocket frames, debounced search), HTTP responses, and complex async pipelines (retry+backoff, race, sequencing) remain natural Observables. Convert at the boundary with `toSignal` so the template binds to a signal while the upstream pipeline stays declarative. Rule of thumb: state → signal; events → Observable. Note also that `rxResource` — the v22 stable API people cite as evidence signals won — takes an **Observable** loader, so RxJS is still the transport underneath it.
</details>

<details><summary>6. Your typeahead uses <code>switchMap</code>; your save button uses the same operator. Which one is a bug, and what breaks?</summary>

The save. `switchMap` unsubscribes the previous inner Observable, which aborts the browser's request (the fetch backend — default since v22 — calls `AbortController.abort()`; the XHR backend calls `xhr.abort()`). The server may already have committed: in ASP.NET Core the disconnect surfaces as `HttpContext.RequestAborted`, but only handlers that actually thread that `CancellationToken` through will stop working. So you have discarded the *response* to a write that happened — and the user, seeing nothing, clicks again. Use `exhaustMap` plus a disabled button, and make the endpoint idempotent with a client-generated key.
</details>

<details><summary>7. Why does <code>toSignal(source$, { requireSync: true })</code> exist, and when does it blow up?</summary>

It removes `undefined` from the signal's type by asserting the source emits synchronously on subscription — correct for a `BehaviorSubject`, a `ReplaySubject(1)` that has already emitted, or any pipeline ending in `startWith`. If the source does not emit synchronously, Angular throws `NG0601` at creation time. It therefore always throws on `HttpClient`, which is the mistake people make when they are trying to get rid of the `undefined` in a template. For async data, use `initialValue`, or `rxResource`/`httpResource` where "loading" is a first-class status rather than a sentinel value.
</details>

<details><summary>8. An unhandled error reaches a long-lived stream feeding your UI. What is the user-visible symptom, and where would you look?</summary>

The feature goes quietly inert: `error` is terminal, so no further values arrive, the teardown has already run, and there is no automatic resubscribe. Typical report: "the save button stopped doing anything" with nothing in the console after the first stack trace. Where the error went depends on the bridge — the `async` pipe routes it to Angular's `ErrorHandler`, `toSignal` rethrows it at read (so it detonates during template evaluation), a bare `subscribe` with no error callback goes to RxJS's unhandled-error path and surfaces as a global error. The fix is a `catchError` inside the inner pipe so a single failure cannot terminate the outer stream, plus an error-shaped value rather than a fallback that pretends success.
</details>

## Cross-references

- [Angular Fundamentals](./01-angular.md) — RxJS underpins HttpClient, Forms, Router events; the version timeline there dates every API used on this page.
- [NgRx State Management](./03-ngrx-state-management.md) — built on RxJS streams; effects die permanently on an uncaught error for exactly the reason described in [Error handling](#error-handling).
- [Angular Testing](./05-angular-testing.md) — where marble tests sit relative to `fakeAsync`, harnesses and component tests.
- [Angular SSR](./06-angular-ssr.md) — the cookie/transfer-cache problems in [The .NET seam](#the-net-seam--interceptors-token-refresh-cors-ssr) in full.
- [WebSockets](../02-api-development/10-websockets.md) — natural fit for Observable wrapping.
- [REST & Web API](../02-api-development/01-rest-and-web-api.md) — HTTP responses are Observables.
- [Async/Await (deep-dive)](../01-foundations/01-net-core-deep-dive/03-async-and-threading.md) — .NET's parallel for one-shot async.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- [rxjs.dev](https://rxjs.dev/) — official documentation; the operator catalog is exceptional.
- [Marbles diagrams](https://rxmarbles.com/) — interactive operator visualizations.
- *RxJS in Action* by Paul Daniels, Luis Atencio (Manning, 2017) — older but conceptually solid.
- Ben Lesh's blog and ng-conf talks — the RxJS lead engineer; modern direction.
- Angular's [RxJS interop docs](https://angular.dev/ecosystem/rxjs-interop) — `toSignal`, `toObservable`, `takeUntilDestroyed`, `rxResource`.
- [Marble testing guide](https://rxjs.dev/guide/testing/marble-testing) — the syntax legend, `run()` semantics and the known issues (including the Promise limitation) come from here.
- [RxJS deprecations](https://rxjs.dev/deprecations) — the authoritative list; the annotations quoted on this page are from the 7.8.2 source.
- [Angular CHANGELOG](https://github.com/angular/angular/blob/main/CHANGELOG.md) — the only reliable way to date a stability promotion; v22.0.0 (2026-06-03) is where `OnPush`-by-default, fetch-by-default and the stable resource APIs land.
- [Angular release schedule](https://angular.dev/reference/releases) — active vs LTS versions, for "what can we actually upgrade to" conversations.
- MDN, [`Access-Control-Max-Age`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Access-Control-Max-Age) — the preflight-cache caps quoted in the CORS section (default 5 s; Firefox 24 h; Chromium ≥ v76 2 h).
- Microsoft Learn, [CORS in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/security/cors) — `SetPreflightMaxAge`, and why `AllowAnyOrigin` + `AllowCredentials` produces an invalid CORS response.
- IETF, [OAuth 2.0 for Browser-Based Applications](https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/) — Internet-Draft (intended status: Best Current Practice); the source for the BFF pattern and refresh-token rotation guidance.

<!-- nav-footer-start -->

---

[← Previous: Angular Fundamentals](01-angular.md) · [↑ Back to top](#rxjs--reactive-programming) · [Next: NgRx State Management →](03-ngrx-state-management.md)

<!-- nav-footer-end -->

</details>
