# Nullability & Pattern Matching

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Nullable reference types — compile-time, not runtime](#nullable-reference-types--compile-time-not-runtime)
  - [The `?` `!` `?.` `??` `??=` operators](#the------operators)
  - [Null-conditional assignment (C# 14)](#null-conditional-assignment-c-14)
  - [NRT attributes — annotating "may be null"](#nrt-attributes--annotating-may-be-null)
  - [Pattern matching evolution C# 7 → C# 14](#pattern-matching-evolution-c-7--c-14)
  - [Type, declaration, and constant patterns](#type-declaration-and-constant-patterns)
  - [Property and tuple patterns](#property-and-tuple-patterns)
  - [Relational and logical patterns](#relational-and-logical-patterns)
  - [List patterns (C# 11)](#list-patterns-c-11)
  - [`switch` expression — exhaustiveness and the catch-all](#switch-expression--exhaustiveness-and-the-catch-all)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--enabling-nullable-on-a-legacy-project)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Two of the most-evolved areas of C# in the last five years. Nullable reference types (NRTs, C# 8) reshape how teams write defensive code — done well, NPEs effectively disappear from a codebase. Pattern matching grew from a one-trick `is` check (C# 7) into a full discriminated-union-style language feature (C# 11+) that makes domain modeling expressive without inheritance ceremony.

These two features deeply intersect: NRTs use flow analysis to track "is this null right now," and patterns are the cleanest way to *establish* non-null in flow analysis. Senior code reviews ask "why is this `!`?" — knowing when the nullable suppression is hiding a real bug vs. a real "I know better than the analyzer" is a judgment call worth understanding precisely.

## Core concepts

### Nullable reference types — compile-time, not runtime

Before C# 8, every reference type could be null silently. NRTs add **compile-time annotations** that say "this can be null" (with `?`) or "this can't" (without). The analyzer then warns when:
- You assign `null` to a non-nullable.
- You dereference a possibly-null without checking first.
- You return a possibly-null from a non-nullable signature.

**Crucially, the runtime is unchanged.** `string` and `string?` are the same type in IL. There is no automatic null check. NRT is a stricter type-system layer the compiler reasons about; it has zero runtime cost and can be wrong (you can `!`-suppress warnings).

```csharp
#nullable enable

string nonNull = "alice";
string? maybe = null;

// Warnings
nonNull = null;            // ⚠ CS8625
maybe.Length;              // ⚠ CS8602: dereference of possibly null

// Flow analysis tracks state
if (maybe is not null)
{
    Console.WriteLine(maybe.Length);   // ✓ — analyzer knows it's non-null in this branch
}

// After this line, the analyzer assumes maybe is non-null
ArgumentNullException.ThrowIfNull(maybe);
Console.WriteLine(maybe.Length);   // ✓
```

**Enable per-project** via `<Nullable>enable</Nullable>` in `.csproj`, or **per-file** with `#nullable enable`. Modern templates enable it by default.

**Migration patterns for existing codebases:** turn it on, expect a flood of warnings, fix systematically. Use `#nullable disable` on troublesome legacy files as a holding pattern, but don't leave them disabled forever — the goal is project-wide enablement.

### The `?` `!` `?.` `??` `??=` operators

A small operator family covers most null-handling patterns.

```csharp
// ?. — null-conditional access (chained safely)
string? city = order?.Customer?.Address?.City;

// ??  — null-coalescing (use 'b' if 'a' is null)
string display = name ?? "(unknown)";

// ??= — null-coalescing assignment (assign only if null)
_cache ??= LoadFromDisk();

// ! — null-forgiving (post-fix; tells analyzer "trust me")
string definitelyNonNull = maybeNull!;

// ?[ ] — null-conditional indexer
T? item = list?[0];

// ?. with method call (chains)
int? count = items?.Count();
```

**The `!` operator has zero runtime effect.** It's just a hint to the analyzer: "I know this is non-null; suppress the warning." If you're wrong, you get a `NullReferenceException` at runtime. Use sparingly and with a comment explaining why you know better.

**`??` chains:** `a ?? b ?? c` returns the first non-null. Useful for fallback chains:

```csharp
var endpoint = config["Endpoint"] ?? Environment.GetEnvironmentVariable("ENDPOINT") ?? "http://localhost";
```

### Null-conditional assignment (C# 14)

C# 14 introduced **null-conditional assignment** — `?.` on the left side of an assignment:

```csharp
order?.Total = 100;
// If 'order' is null, the assignment is skipped (no NRE).
// If non-null, executes order.Total = 100.

list?[0] = "first";
// Indexer-form null-conditional assignment.
```

**Why it matters:** removes the boilerplate `if (order != null) order.Total = 100;` for property/indexer setters on potentially-null objects.

**Limitations:**
- Only on properties/fields/indexers, not method calls (you'd need `?.SetTotal(100)` which already works pre-C# 14).
- The right-hand side **is still evaluated** even if the left is null (it's the assignment that's skipped). If RHS has side effects, factor them out.

### NRT attributes — annotating "may be null"

The `?` syntax handles 90% of cases. The remaining 10% — patterns where a method's return depends on inputs, or where ref/out parameters have conditional nullness — uses a small set of attributes from `System.Diagnostics.CodeAnalysis`:

```csharp
using System.Diagnostics.CodeAnalysis;

// Returns null only when input is null
[return: NotNullIfNotNull(nameof(input))]
public string? Format(string? input) => input?.Trim();

// 'TryParse' style — out param is non-null when method returns true
public bool TryParse([NotNullWhen(true)] out User? user)
{
    user = null;
    if (/* parse fails */) return false;
    user = new User(...);
    return true;
}

// 'this' is not null when method returns true
public bool IsValid([NotNullWhen(true)] string? input) { ... }

// Argument was checked for null and proven non-null
public void Use([DisallowNull] string? value) { ... }
```

**Common attributes:**
- `[NotNull]` / `[MaybeNull]` — output position.
- `[AllowNull]` / `[DisallowNull]` — input position.
- `[NotNullWhen(true|false)]` — out param non-null based on return.
- `[NotNullIfNotNull("paramName")]` — return non-null if named param is non-null.
- `[MemberNotNull("field")]` — after this method returns, the named field is non-null.
- `[DoesNotReturn]` — method never returns normally (throws / `Environment.Exit`). The analyzer treats code after the call as unreachable.

These are most useful in framework / library code. App code can usually get by with just `?` and `!`.

### Pattern matching evolution C# 7 → C# 14

C# 7 added the `is` type pattern. Each subsequent version expanded the pattern grammar.

| Version | Addition |
|---|---|
| C# 7 (2017) | `is Type variable` (declaration pattern) |
| C# 8 (2019) | `switch` expression; type, constant, var, discard patterns; property pattern |
| C# 9 (2020) | Relational (`>`, `<=`), logical (`and`, `or`, `not`) patterns |
| C# 10 (2021) | Extended property patterns (`a.b.c is X`) |
| C# 11 (2022) | List patterns (`[1, 2, 3]`, `[_, var x, ..]`) |
| C# 12 (2023) | (no major pattern additions) |
| C# 13 (2024) | (no major pattern additions) |
| C# 14 (2025) | (no major pattern additions; null-conditional assignment is separate) |

By 2026, the pattern grammar is mature. The remaining gaps (true discriminated unions) are still in language design, not yet shipped.

### Type, declaration, and constant patterns

```csharp
object x = ...;

// Type pattern (no variable)
if (x is string)
    Console.WriteLine("it's a string");

// Declaration pattern (binds variable)
if (x is string s)
    Console.WriteLine(s.Length);

// Constant pattern
if (x is null)
    Console.WriteLine("null");
if (x is 42)
    Console.WriteLine("the answer");

// Negation
if (x is not null)
    Console.WriteLine("non-null");
```

The declaration pattern (`is T t`) is the most common; it both type-tests and unwraps in one step. Useful inside `if`, `while`, `?:`, and `switch`.

### Property and tuple patterns

**Property pattern** matches against an object's properties:

```csharp
public record Order(decimal Total, string Status, Customer Customer);
public record Customer(string Country, string Tier);

string Process(Order o) => o switch
{
    { Status: "Cancelled" }                                  => "skip",
    { Total: > 1000, Customer.Tier: "Gold" }                 => "white-glove",
    { Total: > 1000 }                                        => "review",
    { Customer.Country: "US" or "CA" }                       => "domestic",
    _                                                        => "default"
};
```

The dotted form (`Customer.Tier: "Gold"`) is the **extended property pattern** (C# 10) — drills into nested objects without intermediate `is` checks.

**Tuple pattern** matches against tuple shapes:

```csharp
(int x, int y) p = (3, 5);
string Quadrant(int x, int y) => (x, y) switch
{
    (> 0, > 0) => "I",
    (< 0, > 0) => "II",
    (< 0, < 0) => "III",
    (> 0, < 0) => "IV",
    (0, _) or (_, 0) => "axis",
    _ => "origin"
};
```

### Relational and logical patterns

**Relational** patterns: `>`, `>=`, `<`, `<=` (C# 9):

```csharp
string Describe(int n) => n switch
{
    < 0     => "negative",
    0       => "zero",
    > 0 and < 10 => "small positive",
    >= 10 and <= 100 => "medium",
    > 100   => "large"
};
```

**Logical** patterns: `and`, `or`, `not` (C# 9):

```csharp
bool IsLetter(char c) => c is (>= 'a' and <= 'z') or (>= 'A' and <= 'Z');

if (status is not null and not "")
    Process(status);
```

`and` has higher precedence than `or`, like `&&` and `||`. Parenthesize when in doubt.

### List patterns (C# 11)

Match against the shape of an array, list, or any indexable + countable type:

```csharp
int[] arr = ...;

// Exact match
if (arr is [1, 2, 3])
    Console.WriteLine("exactly [1, 2, 3]");

// Match elements + bind
if (arr is [var first, var second, ..])
    Console.WriteLine($"starts with {first}, {second}");

// Match length pattern
if (arr is [_, _])
    Console.WriteLine("two elements");

// Slice pattern with binding
if (arr is [1, .. var middle, 9])
    Console.WriteLine($"between: {string.Join(',', middle)}");

// Match against last
if (arr is [.., 0])
    Console.WriteLine("ends with zero");
```

List patterns work on any type with `Length`/`Count` and an indexer (`int -> T`) — so they work on `string`, `List<T>`, `Span<T>`, `T[]`, custom indexable types. The slice (`..`) requires a `Slice(int, int)` method (built into arrays, `Span`, `string`).

### `switch` expression — exhaustiveness and the catch-all

The modern `switch` expression (C# 8) is *exhaustiveness-checked*: the compiler warns when there's a possible input value not handled.

```csharp
public abstract record Shape;
public record Circle(double R) : Shape;
public record Square(double S) : Shape;
public record Triangle(double Base, double Height) : Shape;

double Area(Shape s) => s switch
{
    Circle c => Math.PI * c.R * c.R,
    Square q => q.S * q.S,
    // ⚠ CS8509: switch expression doesn't handle all values — Triangle missing
};
```

Add `Triangle` (or a discard arm `_ => ...`) to silence the warning:

```csharp
double Area(Shape s) => s switch
{
    Circle c => Math.PI * c.R * c.R,
    Square q => q.S * q.S,
    Triangle t => 0.5 * t.Base * t.Height,
    _ => throw new ArgumentException(nameof(s))
};
```

**Discriminated-union-style code:** combine `abstract record` for the closed hierarchy + `switch` expression with type patterns. The compiler enforces exhaustiveness if you mark the base `sealed` or use a finite `enum` — though true DUs (with compile-time exhaustiveness on a closed hierarchy) are still proposed for a future C# version.

For the broader Result/discriminated-union pattern in production code, see [Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md).

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌──────────────────────────────────────────────────────────────┐
│   NRT flow analysis — what the analyzer tracks                │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   string? name = GetName();   ← state: {name: maybe-null}     │
│                                                               │
│   if (name is null) return;   ← state: {name: maybe-null}     │
│                                  In branch (null): early ret. │
│                                  After branch: {name: not null}│
│                                                               │
│   Console.WriteLine(name.Length);  ← ✓ analyzer happy         │
│                                                               │
│   if (Random.Next() == 0)                                     │
│       name = null;            ← state: {name: maybe-null}     │
│                                                               │
│   Console.WriteLine(name.Length);  ← ⚠ warning back            │
└──────────────────────────────────────────────────────────────┘
```

**Pattern decision tree (which pattern to reach for):**

```
Need to test type?              → 'is T t' / 'switch { T t => ... }'
Need to compare to a value?     → 'is 42' / 'is "abc"'
Test multiple properties?       → '{ Prop1: x, Prop2: y }'
Test nested property?           → '{ Outer.Inner: x }' (C# 10+)
Test tuple shape?               → '(x, y)' patterns
Range comparison?               → 'is > 0 and < 10' (relational + logical)
List shape / element binding?   → 'is [a, b, ..]' (C# 11+)
Negate any of the above?        → 'is not <pattern>'
Combine?                        → 'and' / 'or' between patterns
Catch-all in switch expression? → '_ => ...'
```

**NRT mental model:** the compiler tracks each variable's "may-be-null" state through control flow. After a check that proves non-null (`is not null`, `?? throw`, an `ArgumentNullException.ThrowIfNull`, etc.), state flips. Reassignment can flip it back. `[NotNullWhen]` and friends teach the analyzer about your method's contract.

</details>
## Common pitfalls

1. **Treating `string?` like `Nullable<string>`.** It's a compile-time hint, not a runtime wrapper. There's no `.HasValue` or `.Value` — just check for `null` and use the variable.
2. **Overusing `!`.** Each `!` is a `// trust me, bro` to the compiler. Prefer fixing the actual nullness reasoning with `?? throw`, `if (x is null) return`, or `[NotNullWhen]`.
3. **Forgetting that NRT is per-project.** A library compiled with NRT off has signatures with no nullness info. Consumers see "null oblivious" warnings — set `<NullableContextOptions>` carefully when consuming such libraries.
4. **`is null` vs `== null`.** Almost always identical, but `is null` is preferred (it can't be overridden via `==` operator overloads, so it's safer for value-equal types and structurally-equal records).
5. **Using `as` for type tests.** `var s = obj as string; if (s != null) ...` is the old way. Modern: `if (obj is string s) ...`.
6. **`switch` expression without a discard arm + non-exhaustive types.** When the type is `string`, `int`, or any open-ended primitive, you almost always need `_ => ...`.
7. **Overlapping switch arms.** The first match wins, but the compiler warns when arms are unreachable (e.g., you have `> 0 => ...` then `> 5 => ...` after it — the second is unreachable).
8. **`is` with explicit non-pattern syntax.** `obj is List<int> { Count: > 0 }` — the property pattern works on the matched type. People forget this and reach for nested `is` checks.
9. **List patterns on non-indexable types.** `IEnumerable<T>` doesn't support list patterns directly — you need `Length`/`Count` + indexer (so `T[]`, `List<T>`, `string`, `Span<T>` are fine; `IEnumerable<T>` isn't).
10. **`.. var rest` allocating.** On `T[]`, the slice creates a new array. On `Span<T>`, it's a view (free). Profile if it matters.

## Interview-ready summary

- **NRT is compile-time only** — no runtime null check, no type-system change. The analyzer warns based on `?` annotations and flow analysis. `!` suppresses warnings without runtime effect.
- **Operators**: `?.` (conditional access), `??` (coalesce), `??=` (coalesce-assign), `!` (forgive), `?` (annotation). C# 14 adds `?.` on the LHS of assignment.
- **Attributes** like `[NotNullWhen]`, `[MemberNotNull]`, `[NotNullIfNotNull]` teach the analyzer about your method's null contract — most useful in libraries.
- **Pattern matching is now mature** — type, constant, declaration, property (extended), tuple, relational, logical, list patterns. The `switch` expression replaces most `if/else` chains.
- **`switch` expression is exhaustiveness-checked** — the compiler warns when the type space isn't fully covered. Add a `_ => ...` arm or handle the missing type.
- **Property patterns drill into objects**: `{ Customer.Tier: "Gold" }`. **List patterns** match shapes: `[var first, .. var rest]`.
- **Modern domain modeling**: `abstract record` hierarchy + exhaustive `switch` on type patterns ≈ discriminated unions. Real DUs are still proposed.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — NRT is compile-time only

> **Q**: At runtime, what's the difference between `string` and `string?`?
>
> **A**: **None.** Both are emitted as the same `System.String` in IL. NRT is purely a **compile-time annotation** layered on top of the type system — the `?` becomes a `[Nullable(2)]` metadata flag, not a wrapper type. There is no `Nullable<string>`, no `.HasValue`, no runtime null check generated.
>
> **Cross-Q**: If NRT is compile-time only, why does turning it on still catch real bugs?
>
> **A**: The compiler performs **flow analysis** — it tracks every variable's "may-be-null" state through control flow (`if` checks, early returns, `?? throw`, `[NotNullWhen]` attributes). Bugs surface as `CS8602` ("dereference of a possibly null reference") at every site where you'd otherwise hit `NullReferenceException`. The analysis runs in the IDE in real time and in CI when warnings are errors. Even though no runtime check exists, the wall of warnings forces defensive code at the right places.
>
> **Cross-Q²**: A library was compiled without NRT and exposes `public string GetName()`. I consume it with NRT enabled. What does the analyzer think?
>
> **A**: It treats the return as **"null-oblivious"** — neither annotated nullable nor annotated non-nullable. The analyzer suppresses warnings on this value (won't yell at you for treating it as non-null), but also doesn't promise non-null. You get partial safety: better than nothing, worse than a fully-annotated library. Modern .NET BCL is fully annotated; older NuGet packages may not be. The `<Nullable>annotations</Nullable>` mode is for libraries that want to expose annotations without enforcing them on their own code.

### Drill 2 — When NRT lies — EF Core navigations

> **Q**: An EF Core entity has `public Customer Customer { get; set; } = null!;` — why the `null!`?
>
> **A**: EF Core populates navigation properties at materialization time (after the constructor runs), via reflection. From NRT's point of view, the property is non-nullable but is initialized to `null` — `null!` is the **escape hatch** that says "I know this is null right now; trust me, the runtime will fix it before anyone reads it."
>
> **Cross-Q**: When does that lie blow up in production?
>
> **A**: When the navigation isn't loaded — you query `_db.Orders.FirstOrDefault(o => o.Id == 42)` without an `.Include(o => o.Customer)`, and the property is `null` at runtime. NRT promised non-null; you get `NullReferenceException`. EF Core ≥ 6 ships an analyzer warning for required-but-not-included navigations, and `[Required]` on the navigation throws on save if missing, but **the runtime can still hand you a `null` on a "non-nullable" property** — NRT's promise depends on disciplined `.Include` calls, lazy loading config, or explicit projection.
>
> **Cross-Q²**: What's the safest pattern then?
>
> **A**: Three options, in order of preference. (1) Use **explicit projection** with `Select` into a DTO with real NRT annotations: `_db.Orders.Select(o => new OrderDto(o.Id, o.Customer!.Name))` — the projection forces you to think about each accessed property. (2) For collection navigations, initialize to `new()`: `public List<LineItem> Items { get; set; } = new();` — empty list is null-safe and works in both materialized and constructed states. (3) For reference navigations that *might* be absent, declare them **nullable**: `public Customer? Customer { get; set; }` — then the call sites force you to handle null. The `null!` pattern is a stopgap when you know loading is enforced elsewhere; the safer pattern is honesty about lifecycle.

### Drill 3 — The null-forgiving operator `!`

> **Q**: What does `someValue!` do at runtime?
>
> **A**: **Nothing.** It's a compile-time suppression — the compiler emits the same IL as if the `!` weren't there. No null check is generated, no exception is thrown. The operator only tells the analyzer "suppress the nullable warning on this expression."
>
> **Cross-Q**: When is `!` the right tool — and when is it a bug deferred?
>
> **A**: **Right tool**: when you have invariant knowledge the analyzer can't see — e.g., a `Dictionary<string, T>.TryGetValue` pattern in legacy code, a value just validated by a custom helper, an out-of-process invariant. **Bug deferred**: when used to silence warnings without proving non-null — the most common form is `user.Profile!.Name` when `Profile` is sometimes null. The `!` doesn't fix anything; it just hides the warning that was telling you the truth. A code review heuristic: every `!` in a PR should have a comment explaining why the analyzer is wrong.
>
> **Cross-Q²**: How would you replace `user.Profile!.Name` safely?
>
> **A**: Pick based on intent. (1) If null is a real possibility and you want a fallback: `user.Profile?.Name ?? "Unknown"`. (2) If null is a contract violation that should crash: `user.Profile?.Name ?? throw new InvalidOperationException("Profile required")`. (3) If null means "skip this user": `if (user.Profile is null) continue;`. (4) If you want a typed precondition check at the top of a method: `ArgumentNullException.ThrowIfNull(user.Profile);`. Each generates real runtime behavior; `!` generates none.

### Drill 4 — `?.` chains and short-circuit

> **Q**: Walk me through `order?.Customer?.Address?.City`.
>
> **A**: The chain is **short-circuit evaluating** — if any link is `null`, the entire expression returns `null` without evaluating the rest. So if `order` is null, neither `Customer` nor `Address` nor `City` is accessed. If `order` is non-null but `Customer` is null, the same — no `Address` access. The return type is `string?` (always nullable, because the chain can yield null).
>
> **Cross-Q**: What's the difference between `a?.b.c` and `a?.b?.c`?
>
> **A**: `a?.b.c` short-circuits only on `a` — if `a` is non-null, it then accesses `.b` and then `.c` unconditionally. If `b` is null, `b.c` throws `NullReferenceException`. `a?.b?.c` short-circuits on both. **The mistake**: assuming one `?.` covers the chain. Each member in the chain that can be null needs its own `?.`. This is one of the most common subtle bugs after enabling NRT in a partially-annotated codebase.
>
> **Cross-Q²**: How does `?.` interact with method invocation and side effects?
>
> **A**: `obj?.Method(args)` short-circuits — if `obj` is null, **neither `Method` nor `args` is evaluated.** This matters if `args` has side effects: `obj?.Process(LogAndCompute())` — `LogAndCompute()` only runs when `obj` is non-null. Contrast with `?.` on the left side of assignment (C# 14): `obj?.Total = ComputeTotal();` — here the RHS **is still evaluated** even when `obj` is null; only the assignment is skipped. Subtle but real for code with logging or counters in the RHS.

### Drill 5 — `??` vs `??=`

> **Q**: Difference between `a ?? b` and `a ??= b`?
>
> **A**: `a ?? b` is an **expression** — returns `a` if non-null, else `b`. Doesn't mutate. `a ??= b` is a **statement** that assigns `b` to `a` only if `a` is currently null. Equivalent to `if (a is null) a = b;`. Most common use case: lazy initialization — `_cache ??= LoadFromDisk();`.
>
> **Cross-Q**: Why is `??=` not equivalent to `a = a ?? b`?
>
> **A**: They're *almost* equivalent but `??=` **avoids re-assigning when `a` is non-null** — important when `a` is a property with a setter that has side effects (raises `INotifyPropertyChanged`, triggers validation, writes through to a backing store). `a = a ?? b` always invokes the setter; `a ??= b` invokes it only when needed. For plain field assignments it doesn't matter, but for properties on UI models it can.
>
> **Cross-Q²**: Can you `??` between different types?
>
> **A**: Only if one is implicitly convertible to the other or they share a common base. `int? x = null; int y = x ?? 0;` works — `int?` and `int` are compatible. `string? a = null; object b = a ?? "default";` works — string is object. But `string? a = null; int b = a ?? 0;` is a compile error — `string` doesn't convert to `int`. The result type is the **best-common-type** of both operands; the compiler must find a single type that holds both.

### Drill 6 — Property patterns

> **Q**: What does `o is { Status: "active" }` translate to under the hood?
>
> **A**: Roughly: `o is not null && o.Status == "active"`. The pattern combines a null check (because `{...}` matches non-null) with property access and equality. For value types, the null check is elided. The compiler also handles `Status` being potentially `null` — the comparison uses `EqualityComparer<T>.Default.Equals(o.Status, "active")` semantics (works for null safely).
>
> **Cross-Q**: How would `o is { Status: "active", Total: > 100 }` differ?
>
> **A**: All listed properties must match. Equivalent to `o is not null && o.Status == "active" && o.Total > 100`. The `>` is a **relational pattern** (C# 9). The order of evaluation is left-to-right, short-circuit — if `Status` doesn't match, `Total` is not accessed. Pattern matching gives you the conjunction for free, without nested `if`s or `&&` chains.
>
> **Cross-Q²**: How do extended property patterns (`{ Customer.Name: "Ahmed" }`) handle null along the chain?
>
> **A**: They **propagate null safely** — the pattern silently fails (no match) if any intermediate property is null. `o is { Customer.Name: "Ahmed" }` matches only if `o` is non-null, `o.Customer` is non-null, and `o.Customer.Name == "Ahmed"`. No `NullReferenceException`. This is the killer feature of extended property patterns (C# 10): you get safe deep-property tests in one line, no need for `o?.Customer?.Name == "Ahmed"` (which still works but reads less naturally inside a `switch`).

### Drill 7 — List patterns

> **Q**: When were list patterns introduced and what shapes do they cover?
>
> **A**: **C# 11 (2022)**. They match against any type with `Length`/`Count` and an `int`-indexer (so `T[]`, `List<T>`, `string`, `Span<T>`, `ReadOnlySpan<T>`, plus custom types with the right shape). The slice pattern `..` requires a `Slice(int, int)` method. They cover exact-shape (`[1, 2, 3]`), partial (`[var first, .., var last]`), length-only (`[_, _]` for "exactly two"), and combined with property/constant patterns (`[> 0, .., 0]`).
>
> **Cross-Q**: Does `arr is [_, .., _]` match a single-element array?
>
> **A**: **No.** The slice `..` matches **zero or more**, but the two `_` patterns each match exactly one element. Total minimum length is 2. So `[1]` doesn't match; `[1, 2]` does (slice matches empty); `[1, 2, 3, 4]` matches (slice matches `[2, 3]`). The mental model: count the non-slice patterns to get the minimum length.
>
> **Cross-Q²**: Why don't list patterns work on `IEnumerable<T>`?
>
> **A**: `IEnumerable<T>` is forward-only — no `Count`, no indexer. List patterns require **random access** (`Length`/`Count` + `[int]`) to be efficient. If the compiler emitted `Count()` + repeated enumeration, you'd silently quadratic-blow-up on long enumerables. The shape-based requirement forces you to materialize (`ToList()`/`ToArray()`) or use a concrete type first — explicit cost. For streams, you typically pattern-match on the first few elements via `.Take(2).ToArray() is [_, _]` or use LINQ.

### Drill 8 — `when` clauses

> **Q**: What does the `when` clause add to a pattern?
>
> **A**: An **arbitrary boolean predicate** evaluated after the pattern matches. The arm runs only if both the pattern matches AND the `when` returns true. Syntax: `case Customer { Tier: "Gold" } c when c.AccountAgeDays > 365: ...`. Useful when the matching condition isn't structural.
>
> **Cross-Q**: When does `when` hurt performance or readability?
>
> **A**: **Performance**: `when` can disable the compiler's switch-table optimization — for `int` switches the compiler emits a jump table (O(1) dispatch); with `when`, it falls back to sequential evaluation (O(n) over arms). For type-pattern switches the impact is smaller (already sequential), but expensive `when` predicates (database calls, regex, allocations) inside a switch make the whole switch slow. **Readability**: complex `when` clauses hide logic that would be clearer as a method call or as a separate `if` after the switch. Heuristic: if your `when` clause is longer than the pattern, refactor.
>
> **Cross-Q²**: Can `when` reference variables captured by the pattern?
>
> **A**: Yes — that's its main use. `case Order o when o.Total > o.Customer.CreditLimit: ...` uses the captured `o`. Variables bound by `is` patterns (`var x`, declaration patterns) are in scope for the `when` clause. **Gotcha**: in switch *statements* with fall-through arms, the captured variable is scoped per-arm, not across arms. Switch *expressions* don't have fall-through, so each arm is independent.

### Drill 9 — Switch expression vs switch statement

> **Q**: When would you choose a switch *expression* over a switch *statement*?
>
> **A**: When the switch **produces a value** — assignment, return, or argument expression. The switch expression is exhaustiveness-checked, returns a value, doesn't allow side effects in arms (you can call methods but the arm result IS the value). The switch *statement* is for side effects — multiple statements per case, fall-through, `break`/`return`/`throw` per case. **Modern guidance**: prefer switch expression for `value = x switch { ... }` patterns; use switch statement for "do different things, no value to compute."
>
> **Cross-Q**: What does exhaustiveness-checking actually warn on?
>
> **A**: The compiler warns (CS8509) when it can prove a switch expression doesn't cover every possible input value. For `bool`, it requires both `true` and `false` (or a `_`). For closed enums, all defined members (or `_`). For sealed hierarchies, all derived types reachable — but **only within the same assembly** (cross-assembly sealing isn't tracked). For open-ended types (`int`, `string`, unsealed classes), it always wants a `_ => ...` arm. The warning helps catch "I added a new enum value, forgot to handle it in the switch."
>
> **Cross-Q²**: Why doesn't the switch expression on `sealed record Animal` with cases `Dog`, `Cat` warn me if I'm missing one?
>
> **A**: Compiler limitation. **Sealed-hierarchy exhaustiveness** isn't (yet) part of the C# spec — the analyzer treats reference types as open. You get the warning only if you use `_` or if the input is `bool` or `enum`. The workaround: always end your sealed-hierarchy switches with `_ => throw new UnreachableException()` and rely on integration tests to catch missing arms. **Discriminated unions** (proposed language feature) will close this gap when they ship; until then, treat closed hierarchies as a code-review concern.

### Drill 10 — `is var x` 

> **Q**: What does `obj is var x` do?
>
> **A**: It **always matches** and binds `obj` to `x`. The result is `true` regardless of what `obj` is — including `null`. Equivalent to `var x = obj; if (true) ...`. Useful inside a `switch` expression as a default arm with a name, or inside an expression to introduce a local binding.
>
> **Cross-Q**: When is `is var x` actually useful versus just declaring a variable?
>
> **A**: Two scenarios. (1) Inside a `switch` expression where you need to **name** the discard for use in the arm body: `_ => Compute(unknown)` doesn't bind a name; `var u => Compute(u)` binds. (2) In **side-effecting expressions** where you want to capture a result for `when` clauses: `case var x when ComputeHash(x) % 7 == 0: ...`. Outside those, prefer plain assignment — `is var` reads like a pattern but is actually unconditional.
>
> **Cross-Q²**: Difference between `is var x` and `is { } x`?
>
> **A**: `is var x` matches **anything including null**; `is { } x` matches **non-null only** (the empty property pattern `{}` requires non-null). So `obj is { } o` is a tighter check — guarantees `o` is non-null. `obj is var o` doesn't. For NRT flow analysis, prefer `{ }` when you want the compiler to treat the binding as non-null in the downstream code.

### Drill 11 — Records and deconstruction in patterns

> **Q**: How does pattern matching interact with records?
>
> **A**: Records auto-generate a **`Deconstruct`** method matching the positional parameters. This enables **positional patterns**: `o is Order(decimal total, _, _) when total > 100` deconstructs in the pattern. Records also work well with property patterns (the auto-generated init-only properties are matchable) and with `with` for non-destructive testing variants.
>
> **Cross-Q**: Can I deconstruct a non-record class in a positional pattern?
>
> **A**: Yes — any type with a `Deconstruct` method (instance or extension) works. `class Point { public int X, Y; public void Deconstruct(out int x, out int y) => (x, y) = (X, Y); }` enables `p is (1, 2)`. The compiler invokes `Deconstruct`, then matches each output against the corresponding sub-pattern. Records get this for free; classes need an explicit `Deconstruct`.
>
> **Cross-Q²**: With `record Order(int Id, Customer Cust)`, what's the difference between `o is Order(_, { Name: "X" })` and `o is Order { Cust.Name: "X" }`?
>
> **A**: Both match the same set of objects. **`Order(_, { Name: "X" })`** is a **positional pattern** — invokes `Deconstruct`, then sub-pattern matches the second output. **`Order { Cust.Name: "X" }`** is a **property pattern** with extended access — invokes the `Cust` getter, then `.Name`. Trade-offs: positional ties to declaration order (refactoring-fragile); property ties to property names (declaration-order independent but verbose). For records with stable shape, positional reads cleaner. For records likely to grow new params, property patterns are safer.

### Drill 12 — NRT with collections

> **Q**: What's the difference between `List<string?>`, `List<string>?`, and `List<string?>?`?
>
> **A**: All three are different. (1) `List<string?>` — non-null list, but elements *may* be null. (2) `List<string>?` — the list reference itself may be null; elements are non-null. (3) `List<string?>?` — both may be null: the list reference, and each element. The `?` placement matters — the analyzer flows the right state to each access site.
>
> **Cross-Q**: Why does `List<string> list = new(); list.Add(null);` warn?
>
> **A**: `List<string>` (element type without `?`) declares "this list holds non-null strings." `Add` takes `string` (non-nullable). Passing `null` triggers `CS8625` ("cannot convert null literal"). To allow null elements: declare `List<string?>`. To allow the whole list to be null but elements non-null: declare `List<string>? list = null;`. The annotation precisely matches the intent.
>
> **Cross-Q²**: What does `T?` mean for unconstrained generics like `Func<T, T?>`?
>
> **A**: It depends on `T`. For `T = string` (reference type), `T?` is `string?` (nullable annotation). For `T = int` (value type), `T?` is `int?` (a.k.a. `Nullable<int>` — a wrapper struct). The `?` is **uniform syntax** with different semantics. Pre-C# 9, this caused ambiguity errors; the language now resolves it via `[Nullable]` metadata, which encodes both cases. For libraries authoring generic APIs, the rule is: declare `T?` consistently to mean "this slot may hold the default value of T" — and constrain with `where T : notnull` or `where T : class` to remove the ambiguity if you need to.

### Drill 13 — `null!` and `default!` in DTOs

> **Q**: When is `public string Name { get; set; } = null!;` the right pattern?

> **A**: For **frameworks that materialize objects without calling user constructors** — JSON deserialization (`System.Text.Json` uses reflection unless source-gen'd), EF Core navigation properties, ASP.NET Core model binding, mocking libraries. The runtime guarantees the property will be set before any user code reads it, but the analyzer can't see that promise. `null!` is the "I know better than the analyzer" marker.
>
> **Cross-Q**: When is it the *wrong* pattern?
>
> **A**: (1) When the property genuinely might not be set — JSON deserialization with missing fields, optional bindings. Use `string?` instead. (2) When you control the construction path — make it `required` (C# 11): `public required string Name { get; init; }` — the compiler now enforces that callers set it in the object initializer. (3) When the type has a real default — `public string Name { get; set; } = string.Empty;` — empty string beats `null!` for safety. The `null!` should be reserved for the framework-materialized case; for normal DTOs, `required` or default-initialization is cleaner.
>
> **Cross-Q²**: How does `default!` compare to `null!`?
>
> **A**: Same role, generic-safe. `null!` is specifically `null` cast as non-null; works for reference types. `default!` is `default(T)` cast as non-null; works for any `T` including generics. In a generic method, `T result = default!;` is correct (you don't know if `T` is a reference or value type); `T result = null!;` only compiles for reference-type-constrained `T`. For non-generic code, prefer `null!` for readability.

### Drill 14 — Recursive (extended) property patterns

> **Q**: Walk me through `order is { Customer.Address.Country: "US" or "CA" }`.
>
> **A**: The pattern matches if `order` is non-null, `order.Customer` is non-null, `order.Customer.Address` is non-null, and `order.Customer.Address.Country` is either `"US"` or `"CA"`. The dotted access is the **extended property pattern** (C# 10). The `or` inside the constant slot is a **logical pattern** (C# 9). All null checks along the chain are implicit.
>
> **Cross-Q**: Compare this to the nested form `{ Customer: { Address: { Country: "US" or "CA" } } }`.
>
> **A**: Semantically identical. The nested form makes the structure explicit (clear at a glance that `Customer` and `Address` are separate types), at the cost of vertical noise. The extended form (`Customer.Address.Country`) is denser and reads naturally for short chains. **Style heuristic**: prefer extended for 2-3 level shallow access; prefer nested when each level has multiple property tests (`{ Customer: { Tier: "Gold", Address.Country: "US" } }` — mixed, drills deeply only at the leaves).
>
> **Cross-Q²**: How does pattern matching choose between `==` and `Equals` for `Country: "US"`?
>
> **A**: Constant patterns use the equivalent of **`object.Equals`** (or specifically `pattern matches if EqualityComparer<T>.Default.Equals(actual, "US")`). For `string`, this is ordinal case-sensitive equality. For records, this invokes the record's auto-generated `Equals`. For value types, it boxes only if necessary. **Gotcha**: case sensitivity — `Country: "us"` won't match `"US"`. For case-insensitive matching, you need a `when` clause: `{ Country: var c } when c.Equals("us", StringComparison.OrdinalIgnoreCase)`.

### Drill 15 — `Span<T>` and NRT

> **Q**: What's special about `Span<T>` and nullability?
>
> **A**: `Span<T>` is a **`ref struct`** — cannot be boxed, cannot live on the heap, cannot be a field of a non-ref-struct, cannot be `null`. The whole concept of "null Span" doesn't exist; instead, you have `Span<T>.Empty` (zero-length span with valid pointer). NRT annotations on `Span<T>` are restricted accordingly: you can have `Span<string?>` (elements may be null) but not `Span<T>?` (the span itself can't be null-annotated as a struct).
>
> **Cross-Q**: How do you check "no data" on a Span then?
>
> **A**: `span.IsEmpty` — checks `Length == 0`. **Don't** use `span == default` — that's a value comparison and works but is non-idiomatic. **Don't** try `span is null` — won't compile (value types can't match `null` patterns unless wrapped in `Nullable<T>`, which `ref struct` types can't be). The empty span is the equivalent of "null reference" in the Span world.
>
> **Cross-Q²**: Why does `Span<T>` exist with these restrictions when `Memory<T>` is more flexible?
>
> **A**: **Performance.** `Span<T>` is stack-only because it stores a managed pointer (a `ref`) — letting it escape to the heap would mean GC has to track those pointers across collections, which destroys the perf benefit. `Memory<T>` wraps the same data in a heap-safe form (via an internal `object owner + offset + length`); it can be async-passable and field-storable, but introduces an indirection. For tight loops over arrays/strings/buffers, `Span<T>` is 10-100x faster than `Memory<T>` slicing. The NRT and null restrictions fall out of the ref-struct rules, not from a separate design choice.

</details>
## Cheat Sheet

- **NRT is compile-time only**: `string?` and `string` are the same runtime type — flow analysis only.
- **`!`** is a suppressor, *not* an assertion — runtime null still passes through unchecked.
- **`?.`** short-circuits chain to `null`; **`??`** coalesces; **`??=`** assigns if null.
- **C# 14**: `obj?.Prop = value` — null-conditional assignment skips when receiver is null.
- **`is null`** > `== null` — can't be overloaded; safer with custom `==` operators.
- **Property pattern**: `obj is { Customer.Tier: "Gold" }` drills nested members.
- **List pattern** (C# 11): `[first, .. rest]`, `[_, _, last]`; works on indexable types only.
- **`switch` expression**: exhaustiveness-checked — add `_ => ...` for open-ended primitives.
- **NRT attributes**: `[NotNullWhen(true)]`, `[MemberNotNull]`, `[NotNullIfNotNull]` — teach the analyzer.
- **DU shape**: `abstract record` base + sealed records + exhaustive switch ≈ discriminated union.

## Walkthrough — Enabling `<Nullable>` on a legacy project

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A 200K-LoC service has 18 `NullReferenceException`s per day in production. The team enables `<Nullable>enable</Nullable>` and gets 4,200 warnings. They mass-suppress with `!` to ship. NREs continue.

**Diagnosis**: The mass-suppression turned the analyzer off — `!` is a `// trust me, bro`, not a fix. Audit one NRE: stack trace points at `var name = user.Profile.DisplayName;` where `Profile` is loaded lazily from EF and is `null` for users with no profile row. Search the codebase: `git grep '!\.' | wc -l` = 800+ — most are masking real holes. Run Roslyn analyzer `CS8602` (Dereference of a possibly null reference) with warnings-as-errors in CI to enforce no new violations.

**Fix**: Stage the migration. (1) Set `<Nullable>annotations</Nullable>` first — annotations enabled, warnings off — so callers see the API surface but you don't fail builds. (2) Annotate APIs file-by-file with `?` and `[NotNullWhen]`. (3) Switch each file to `<Nullable>enable</Nullable>` only after fixing its warnings. (4) Add `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>` for `CS8600;CS8601;CS8602;CS8603;CS8604` once a project is clean. (5) Replace `user.Profile!.DisplayName` with `user.Profile?.DisplayName ?? "Unknown"` or `?? throw new InvalidOperationException("Profile required")`.

```xml
<PropertyGroup>
  <Nullable>enable</Nullable>
  <WarningsAsErrors>CS8602;CS8604</WarningsAsErrors>
</PropertyGroup>
```

**Why it works**: NRT is a *flow-analysis* tool — it works only when you let warnings drive real fixes. Phasing avoids the "8000-warning wall" that pushes teams to suppress everything. Treating dereference warnings as errors stops new bugs from entering while the backlog drains.

</details>
## Self-test

<details>
<summary>1. What does `[NotNullWhen(true)]` on a `bool TryParse(string s, out int x)`-style method tell the analyzer?</summary>

It says: "when this method returns `true`, the `out` parameter is guaranteed non-null." Combined with NRT, the analyzer can flow that knowledge: `if (TryGetUser(id, out var user)) { user.DoSomething(); }` — the analyzer no longer warns on `user.DoSomething()` because returning `true` means `user` is non-null. Without the attribute, the analyzer would conservatively assume `user` could be null on either branch. Critical for `TryGet`/`TryParse` patterns and for libraries that want callers to write idiomatic code without `!`.
</details>

<details>
<summary>2. Apply: design a `Result<T>` discriminated-union analog using records and pattern matching.</summary>

```csharp
public abstract record Result<T>;
public sealed record Success<T>(T Value) : Result<T>;
public sealed record Failure<T>(string Error) : Result<T>;

string Describe<T>(Result<T> r) => r switch {
    Success<T> { Value: var v } => $"OK: {v}",
    Failure<T> { Error: var e } => $"Fail: {e}",
    _ => throw new UnreachableException()
};
```

The `abstract record` base + `sealed` cases + exhaustive switch gives DU-like ergonomics. The `_ => throw` arm is a safety net the compiler insists on (it can't prove sealed-derived exhaustion across assemblies). True discriminated-union syntax is in the C# language proposal pipeline but not yet shipped.
</details>

<details>
<summary>3. Trade-off: when does `?? throw` beat a manual `if (x is null) throw`?</summary>

`?? throw` is shorter and inline-compatible: `var u = repo.Get(id) ?? throw new NotFoundException(id);` — idiomatic for fluent code. `if (x is null) throw` reads better when you want a *named* contract check at the top of a method (`ArgumentNullException.ThrowIfNull(x);` is the modern one-liner). Trade-offs: `?? throw` couples value-fetching with null-policy in one expression; `ArgumentNullException.ThrowIfNull` adds the parameter name to the exception automatically (uses `[CallerArgumentExpression]`). For public-API guard clauses, prefer `ThrowIfNull`; for inline value extraction, prefer `?? throw`.
</details>

<details>
<summary>4. Analyze: a colleague writes `if (obj is List<int> { Count: > 0 } list && list[0] == 1) ...`. What does this match, and is it equivalent to checking three conditions separately?</summary>

It matches: `obj` is non-null, is a `List<int>` (not e.g., `int[]`), has at least one element, and the first element is `1`. The pattern combines type, property, and indexer access. Equivalent to: `if (obj is List<int> list && list.Count > 0 && list[0] == 1)`. The pattern form is preferred because (a) the `Count > 0` guard prevents the `list[0]` from throwing — pattern matching short-circuits left to right; (b) `list` is in scope only in the matched branch; (c) the analyzer treats `list` as non-null inside the block. Modern equivalent with list patterns: `if (obj is List<int> [1, ..])`.
</details>

<details>
<summary>5. You enable NRT and the EF Core navigation property `public List<Order> Orders { get; set; } = null!;` warns "non-nullable initialized to null." Critique the `null!`.</summary>

This is the canonical EF Core idiom: navigation properties are populated by the runtime when the entity is loaded, never by user code. The `null!` says "I know this is null at construction but EF will fix it before I read it." Acceptable, but better alternatives in modern EF Core: (1) declare with `default!` and document; (2) use a constructor that the EF materializer can invoke (with mapped fields); (3) for required navigations, declare `Orders { get; set; } = new();` so empty list is the default — works for collection navs but not for reference navs. Trade-off: `null!` is honest about the EF lifecycle but defeats null-safety for that property; `new()` is null-safe but might cause confusion if EF doesn't overwrite empty collections.
</details>

## Cross-references

- **Previous: [LINQ — Language Deep Dive](./06-linq-language-deep-dive.md)** — patterns inside `Where` lambdas.
- **Next: [Reflection, Attributes & Source Generators](./08-reflection-attributes-and-source-gen.md)** — NRT attributes are reflection metadata.
- **[Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md)** — applied pattern matching for error handling.
- **[Modern C# Features](../01-net-core-deep-dive/12-modern-csharp.md)** — the broader feature reference (records, init, etc.).
- **[Type System Deep Dive](./02-type-system.md)** — `Nullable<T>` (the value-type sibling).

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [Nullable reference types](https://learn.microsoft.com/en-us/dotnet/csharp/nullable-references).
- Microsoft Learn — [Patterns and pattern matching](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/patterns).
- Microsoft Learn — [Nullability attributes (System.Diagnostics.CodeAnalysis)](https://learn.microsoft.com/en-us/dotnet/csharp/nullable-attributes).
- Mads Torgersen — Roslyn pattern-matching design notes on [GitHub: dotnet/csharplang](https://github.com/dotnet/csharplang).
- Eric Lippert — *"Pattern matching in C#"* — historical write-up.

</details>
<!-- nav-footer-start -->

---

[← Previous: LINQ — Language Deep Dive](06-linq-language-deep-dive.md) · [↑ Back to top](#nullability--pattern-matching) · [Next: Reflection, Attributes & Source Generators →](08-reflection-attributes-and-source-gen.md)

<!-- nav-footer-end -->
