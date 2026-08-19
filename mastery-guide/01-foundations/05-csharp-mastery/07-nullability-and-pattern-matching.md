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
  - [How nullability is stored in metadata](#how-nullability-is-stored-in-metadata)
  - [The nullable context has two flags, not one](#the-nullable-context-has-two-flags-not-one)
  - [Where null-state analysis is unsound](#where-null-state-analysis-is-unsound)
  - [The nullable attribute vocabulary in full](#the-nullable-attribute-vocabulary-in-full)
  - [NRT at the boundary — EF Core, model binding, JSON](#nrt-at-the-boundary--ef-core-model-binding-json)
  - [Generic nullability — what `T?` really means](#generic-nullability--what-t-really-means)
  - [Exhaustiveness, precisely](#exhaustiveness-precisely)
  - [Subpattern evaluation order is unspecified](#subpattern-evaluation-order-is-unspecified)
  - [Pattern precedence traps](#pattern-precedence-traps)
  - [What a pattern will and will not convert](#what-a-pattern-will-and-will-not-convert)
  - [List patterns — countable, indexable, sliceable](#list-patterns--countable-indexable-sliceable)
  - [Closed hierarchies and unions — C# 15 preview](#closed-hierarchies-and-unions--c-15-preview)
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

> 🌍 **In the real world**: during an NRT migration a team fixed a `CS8602` on `settings.Database.ConnectionString` by adding one `?.` at the front — `settings?.Database.ConnectionString` — and the warning went away, which everyone read as the bug being fixed. It wasn't: `?.` short-circuits only on the receiver it is attached to. If `settings` is non-null, the expression evaluates `.Database` and then `.ConnectionString` unconditionally, and a null `Database` throws exactly as before. The warning disappeared because the *expression's* result type became nullable, not because the dereference became safe. What made it hard to spot in review is that the diff looked like the canonical fix, and the crash rate barely moved because `settings` was almost never null and `Database` almost always was populated — so the residual NREs read as an unrelated flake for a month. **The rule is per-link, not per-chain: every member in a chain that can be null needs its own `?.`.** The deeper habit worth building is to distrust a null-safety fix that only makes a warning go away — ask which dereference it protects, and if the answer isn't a specific one, the fix is cosmetic.

### Null-conditional assignment (C# 14)

C# 14 introduced **null-conditional assignment** — `?.` and `?[]` on the left side of an assignment:

```csharp
order?.Total = 100;
// If 'order' is null, the assignment is skipped (no NRE).
// If non-null, executes order.Total = 100.

list?[0] = "first";
// Indexer-form null-conditional assignment.
```

**Why it matters:** removes the boilerplate `if (order != null) order.Total = 100;` for property/indexer setters on potentially-null objects.

**The rule that surprises people — the right-hand side is *not* evaluated when the receiver is null.** The feature specification is explicit: *"The right side of the assignment is only evaluated when the receiver of the conditional access is non-null."* So `customer?.Order = GetCurrentOrder();` does not call `GetCurrentOrder()` when `customer` is null. This is the same short-circuit you already get from `obj?.Method(args)`, not an exception to it. As a statement, `P?.A = B` is specified as *"equivalent to `if (P is not null) P.A = B;`, except that `P` is only evaluated once."*

**What is and isn't allowed** (from the C# 14 specification):

| Form | Allowed? |
|---|---|
| `a?.b = x` / `a?[i] = x` | ✓ |
| `a?.b += x`, `-=`, and all other compound assignments | ✓ — "all forms of compound assignment are allowed" |
| `a?.E += handler` (event accessor) | ✓ — a stated motivation was attaching handlers in UI code |
| `a?.b ??= x` | ✓ — lowers to a nested "if non-null, and if `b` is null, assign" |
| `a?.b++`, `--a?.b` | ✗ — increment/decrement are not supported |
| `M(ref a?.b)` | ✗ — a conditional access is still not an lvalue |
| `a?.b = ref x` | ✗ — no ref-assignment through a conditional access |
| `(a?.b, c?.d) = (x, y)` | ✗ — no deconstruction assignment |
| `a?.b = c` where `a` is a value type | ✗ — `?.` needs a nullable receiver, and `a.Value` isn't a variable |

If you *use* the result rather than discarding it, the expression's type must be known to be a reference type or a value type — an unconstrained `T` gives `CS8978: 'T' cannot be made nullable`, because `(c?.field = t)` needs to produce `T?`:

```csharp
class C<T> { public T? field; }

void M<T>(C<T>? c, T t)
{
    (c?.field = t).ToString();  // ⚠ CS8978 — 'T' cannot be made nullable
    c?.field = t;               // ✓ as a statement, nothing needs to be nullable
}
```

> 🌍 **In the real world**: a WPF team upgraded to C# 14 and collapsed a block of handler wiring from `if (_vm is not null) { _vm.Changed += OnChanged; _vm.HandlerGeneration = ++_attached; }` down to two null-conditional lines: `_vm?.Changed += OnChanged;` and `_vm?.HandlerGeneration = ++_attached;`. The wiring worked — that is what the feature is for. The instrumentation didn't: `_attached` was a process-wide counter feeding a leak-detection dashboard, and on every code path where the view model had already been torn down, `_vm` was null, the right-hand side was never evaluated, and the increment silently didn't happen. The dashboard therefore reported *fewer* live handler registrations than existed, which is precisely the direction that makes a leak invisible. Nobody suspected the counter in review, because the reviewer's mental model — shared by a great deal of what was written about the feature at the time — was "only the assignment is skipped, the right side still runs". The specification says the opposite, and the specified behaviour is the more useful one: `?.` short-circuits everything to its right, on both sides of an `=`. **The transferable rule: a null-conditional access is a short-circuit, never a conditional store. A side effect that must happen whether or not the receiver is null does not belong anywhere inside the conditional access expression** — hoist it to its own statement, where its execution is unconditional and obvious.

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

// 'input' is not null when the method returns true — this is what makes
// string.IsNullOrEmpty work: bool IsNullOrEmpty([NotNullWhen(false)] string? value)
public bool IsValid([NotNullWhen(true)] string? input) { ... }

// The type says null is possible, but callers must not pass null
public void Use([DisallowNull] string? value) { ... }
```

**Common attributes:**
- `[NotNull]` / `[MaybeNull]` — postconditions. `[MaybeNull]` says a *non-nullable* return/parameter/field might be null; `[NotNull]` says a *nullable* one never is once the method returns.
- `[AllowNull]` / `[DisallowNull]` — preconditions on arguments only (they never affect a property's `get`). `[AllowNull]` says a *non-nullable* slot may be assigned null; `[DisallowNull]` says a *nullable* slot must not be.
- `[NotNullWhen(true|false)]` / `[MaybeNullWhen(...)]` — conditional postconditions keyed on the `bool` return.
- `[NotNullIfNotNull("paramName")]` — return non-null if named param is non-null.
- `[MemberNotNull("field")]` / `[MemberNotNullWhen(true, "field")]` — after this method returns (or returns the given `bool`), the named members are non-null.
- `[DoesNotReturn]` — method never returns normally (throws / `Environment.Exit`). The analyzer treats code after the call as unreachable.
- `[DoesNotReturnIf(false)]` — never returns when the annotated `bool` argument has that value.

These are most useful in framework / library code. App code can usually get by with just `?` and `!` — but see [The nullable attribute vocabulary in full](#the-nullable-attribute-vocabulary-in-full) below for the cases where an attribute deletes dozens of `!`s.

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

One entry deserves a footnote: **C# 11 also let you match a `Span<char>` or `ReadOnlySpan<char>` against a constant string** (`span is "GET"`). That is not a list pattern — it is a constant pattern with a special rule, and the specification says it lowers to `MemoryExtensions.SequenceEqual(e, MemoryExtensions.AsSpan(v))` rather than to `object.Equals`. It is the reason a zero-allocation parser can dispatch on tokens without materialising a `string`.

The grammar on C# 14 is mature, and the long-standing gap — compile-time exhaustiveness over a closed set of types — is being closed in **C# 15**, which is in preview with .NET 11 as of this writing. See [Closed hierarchies and unions](#closed-hierarchies-and-unions--c-15-preview) at the end of this section for what shipped, what hasn't, and what to say about it in an interview today.

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

The dotted form (`Customer.Tier: "Gold"`) is the **extended property pattern** (C# 10) — drills into nested objects without intermediate `is` checks. The standard defines it as pure sugar: `{ Prop1.Prop2: pattern }` is *"exactly equivalent to `{ Prop1: { Prop2: pattern } }`"*, and since a property pattern requires its input to be non-null, every level of the chain carries an implicit null check.

> 🌍 **In the real world**: a pricing service classified orders with `o switch { { Customer.Tier: "Gold" } => WhiteGlove(o), { Total: > 1000 } => Review(o), _ => Standard(o) }`, replacing a nested `if` chain that had thrown `NullReferenceException` twice in the preceding year. The NREs stopped, which was the point. What nobody registered is *how* they stopped: a property pattern requires non-null at every level, so when `Customer` was null the arm simply didn't match and the order fell through to `Standard(o)`. Some months later a change to the query dropped an `.Include(o => o.Customer)` on one code path, and every Gold customer on that path was silently priced as Standard. There was no exception, no log line and no alert — the pattern did exactly what it is specified to do. The revenue discrepancy was found by finance, not by engineering. The fix was to make absence explicit rather than implicit: an arm `{ Customer: null }` that throws, placed above the tier arms, so an unloaded navigation is a loud failure instead of a silent reclassification. **The transferable insight is that pattern matching converts a crash into a non-match, and a non-match into whatever your fallback arm does** — which is an unambiguous improvement in robustness and an unambiguous *regression* in observability. When "this data should always be here" is genuinely an invariant, give it its own arm and throw; a `_` catch-all will otherwise absorb your bugs at full speed.

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

**Precedence is `not`, then `and`, then `or`** — three levels, not two. The `&&`/`||` analogy is the trap, because it makes people forget the `not` level. See [Pattern precedence traps](#pattern-precedence-traps) for the two ways this bites.

**And unlike `&&` / `||`, the pattern combinators are not short-circuiting.** The C# specification states it plainly: *"Unlike their language operator counterparts, `&&` and `||`, `and` and `or` are **not** short-circuiting operators."* You cannot use `and` to order a cheap test before an expensive one and rely on the second not running.

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

List patterns work on any type that is *countable* and *indexable* — so `string`, `List<T>`, `Span<T>`, `ReadOnlySpan<T>`, `T[]`, and custom types with the right shape. The exact requirements, and the fact that a bare `..` needs less from the type than `.. var x` does, are worked through in [List patterns — countable, indexable, sliceable](#list-patterns--countable-indexable-sliceable) below.

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

**Discriminated-union-style code:** combine `abstract record` for the closed hierarchy + `switch` expression with type patterns. On C# 14 the compiler does **not** derive exhaustiveness from a closed hierarchy — marking the base `sealed` changes nothing (and an `abstract` base can't be `sealed` anyway). You still need the `_ => throw new UnreachableException()` arm. The gap is being closed by the `closed` modifier in C# 15; see [Closed hierarchies and unions](#closed-hierarchies-and-unions--c-15-preview).

For the broader Result/discriminated-union pattern in production code, see [Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md).

### How nullability is stored in metadata

"NRT is compile-time only" is the right headline, but a senior answer should be able to say *where the information goes*, because that is what makes it survive across assembly boundaries and what lets EF Core and System.Text.Json read it at runtime.

The compiler emits two synthesized attributes into your assembly, both in `System.Runtime.CompilerServices`:

- **`NullableAttribute`** — carries a `byte` (or `byte[]` for a constructed type like `Dictionary<string, List<string?>>`, one entry per reference-type position).
- **`NullableContextAttribute`** — carries a single `byte` that sets the default for an enclosing scope (type or method), so that only *exceptions* to the default need their own `NullableAttribute`. This is a size optimisation: annotating every member individually would bloat metadata and slow the IDE's cross-assembly analysis.

The byte has three values:

| Value | Meaning | Source form |
|---|---|---|
| `0` | **Oblivious** — pre-C# 8 behaviour; the analyzer neither trusts nor complains | compiled with `<Nullable>disable</Nullable>` |
| `1` | **Not annotated** — non-nullable | `string` |
| `2` | **Annotated** — nullable | `string?` |

Three consequences worth being able to state:

1. **You cannot write `NullableAttribute` yourself.** `CS8623: Explicit application of 'System.Runtime.CompilerServices.NullableAttribute' is not allowed.` The `?` is the only supported input.
2. **`?` is an annotation, not a type**, so it is rejected everywhere the language wants a real type: `typeof(string?)` is `CS8639`, `obj is string?` is `CS8650` ("use the underlying type instead"), `obj as string?` is `CS8651`, and `new object?()` is `CS8628`. Add a designation and you get the *pattern* diagnostic instead — `obj is string? s` is `CS8116`, *"It is not legal to use nullable type 'string?' in a pattern."*
3. **`0` — oblivious — is a third state, not "nullable".** A value that arrives from an oblivious assembly is neither trusted nor challenged: assigning it to a non-nullable produces no warning, and dereferencing it produces no warning. You get *silence*, which is exactly what a wall of green warnings-as-errors will look like when the bug is in a dependency.

> 🌍 **In the real world**: a platform team turned on `<Nullable>enable</Nullable>` solution-wide, promoted `CS8600;CS8602;CS8603;CS8604` to errors in CI, drained a four-thousand-warning backlog over a quarter, and shipped. Production `NullReferenceException` counts fell, then flattened at a stubborn residue that all traced through one internal NuGet package — a decade-old identity/claims helper that nobody had rebuilt, still compiled null-oblivious. Every reference type it returned carried nullable byte `0`, so the analyzer had nothing to say about any of it, and the team read the resulting silence as safety. The diagnosis came from a build-time script that reflected over every referenced assembly looking for a `NullableContextAttribute` on the module; the packages that had none were the ones still producing NREs. The fix was not to annotate the old package (nobody could rebuild it safely) but to route every call through a small internal facade whose signatures were honest — `Claim?` where it really could be absent — so the analyzer got something to reason about at the seam. **The transferable point is that enabling NRT gives you a guarantee about code the compiler can see, and "no warnings" over an oblivious dependency is not evidence of anything.** Audit the nullable state of your dependency graph before you trust a clean build.

### The nullable context has two flags, not one

`<Nullable>` looks like an on/off switch. It is two independent flags — an **annotation** flag and a **warning** flag — and the four project-level values are just the four combinations. Knowing this is what turns "we can't enable nullable, we'd get eight thousand warnings" into a staged plan.

| `<Nullable>` | Dereference warnings | Assignment warnings | Reference types | `?` suffix | `!` operator |
|---|---|---|---|---|---|
| `disable` | off | off | all nullable | produces a warning | has **no effect** |
| `enable` | on | on | non-nullable unless `?` | declares nullable | suppresses warnings |
| `warnings` | on | n/a | all nullable, but members are *not-null* at the opening brace of methods | produces a warning | suppresses warnings |
| `annotations` | off | off | non-nullable unless `?` | declares nullable | has **no effect** |

Read the two "has no effect" cells carefully: under `disable` and `annotations`, a `!` you wrote to silence something is doing nothing at all — it is not suppressing a warning, because there is no warning to suppress. That is why `annotations` is the right first step for a library: you publish an honest, annotated API surface for your consumers *before* you have fixed a single one of your own warnings.

The same two flags exist as pragmas, and they can be moved independently, which gives nine per-file combinations:

```csharp
#nullable enable                 // both flags on
#nullable disable                // both flags off
#nullable restore                // both flags back to the project setting
#nullable enable warnings        // warning flag only
#nullable disable annotations    // annotation flag only
#nullable restore annotations    // annotation flag back to project setting
```

The useful ones in a migration: `#nullable disable warnings` on a file you have annotated but not yet fixed, and `#nullable enable annotations` on a file you want to annotate before you are ready to see its warnings.

**The exemption nobody remembers: the project-level nullable context does not apply to generated code.** The compiler treats a file as generated — and therefore *nullable-disabled* — if any of these hold: `generated_code = true` for it in `.editorconfig`; an `<auto-generated>` comment as the first element of the file; a filename starting with `TemporaryGeneratedFile_`; or a filename ending in `.designer.cs`, `.generated.cs`, `.g.cs`, or `.g.i.cs`. A generator that wants annotations has to emit `#nullable enable` itself.

> 🌍 **In the real world**: a team put `<Nullable>enable</Nullable>` in `Directory.Build.props`, treated `CS8602` as an error, and considered the API layer covered. Their request/response contracts, however, were produced by a protobuf tool into `.g.cs` files, and the generator did not emit `#nullable enable`. Every generated message type was therefore compiled oblivious: `string Email` on a generated contract carried nullable byte `0`, the mapping layer that read `dto.Email.Trim()` got no warning, and a client that omitted the field produced an NRE in a code path that had been reviewed as "null-safe by construction". Two things came out of the postmortem. First, generated contracts are a boundary, not internal code, and the mapping layer should treat them the way it treats any external payload — a real check, not an annotation. Second, they added a CI step that greps generated output for a `#nullable` directive and fails if it is missing, because the generator version could regress that at any upgrade. **The rule to keep: `<Nullable>enable</Nullable>` is a statement about hand-written source. Anything with `.g.cs` in its name opted out of your null-safety policy before you enabled it.**

### Where null-state analysis is unsound

The compiler tracks exactly two states per expression — *not-null* and *maybe-null* — and updates them on assignments and null checks. It does not attempt a proof. Microsoft documents two patterns that *"can leave a non-nullable reference holding `null` without a warning"*, and describes both as limitations of the static analysis rather than bugs in your code.

**1. Default structs.** A struct can be brought into existence without any of its fields being assigned:

```csharp
public struct Student
{
    public string FirstName;      // non-nullable
    public string? MiddleName;
    public string LastName;       // non-nullable
}

Student s = default;              // no warning; FirstName and LastName are null
Console.WriteLine(s.FirstName?.Length ?? -1);
```

`default` and `new()` both do this, and the same applies to a struct reached through `default(T)` in a generic method. The documented mitigations are `required` members or a parameterised constructor — but note that neither *closes* the hole, because `default(T)` bypasses both.

**Be precise about where the silence actually is**, because this is a detail an interviewer can push on. The *creation* never warns, and the fields really are `null`. But Roslyn does track the member slots of a local it watched you initialise, so a direct dereference in the same method — `Slot s = default; s.Key.Length;` — **does** produce `CS8602`. (That is why Microsoft's own example writes `?.` on the next line.) The warning disappears the moment the value reaches you any other way, and those are the cases that ship:

```csharp
struct Slot { public string Key; }        // non-nullable reference field
static Slot Make() => default;

void Flush(Slot[] batch)
{
    var fresh = new Slot[8];
    _ = fresh[0].Key.Length;              // no warning — array element
    foreach (var s in batch)
        _ = s.Key.Length;                 // no warning — foreach over an array of structs
    _ = Make().Key.Length;                // no warning — method return
}
void Take(Slot s) => _ = s.Key.Length;    // no warning — parameter
```

**2. Arrays.** A new array of a non-nullable reference type is a block of nulls:

```csharp
string[] values = new string[3];   // no warning; all three elements are null
Console.WriteLine(values[0].Length);   // no warning — NullReferenceException

string[] ok = ["a", "b", "c"];     // collection expression fills every slot
```

Arrays of structs inherit the first hole through the second: every element starts at the struct's default value, so every non-nullable reference field in every element starts as `null`.

**3. The analysis stops at method boundaries.** Microsoft states it directly: *"The analysis doesn't trace into the bodies of methods."* Your `if (Validator.IsPresent(x)) x.Length;` warns, no matter how obviously `IsPresent` is a null check, until you put `[NotNullWhen(true)]` on its parameter. This is a deliberate design decision — cross-method inference would be unstable and slow — and the attribute vocabulary exists precisely to bridge it.

**4. Member paths are tracked as if they were variables.** `if (o.Config is not null) Use(o.Config);` does not warn, because the compiler gives the *path* `o.Config` a null-state slot and narrows it. That is correct for a field and for the overwhelming majority of properties. It is wrong for a property whose getter can return a different value on each call.

> 🌍 **In the real world**: a service read its downstream endpoint through `IOptionsMonitor<GatewayOptions>.CurrentValue`, which re-reads the current snapshot on every access. The guard was written the obvious way — `if (_options.CurrentValue.Endpoint is not null) Connect(_options.CurrentValue.Endpoint);` — and the analyzer was perfectly happy, because it had narrowed the path `_options.CurrentValue.Endpoint` to *not-null* on the first read and carried that state into the second. During a config reload that briefly published a snapshot with the endpoint missing, the two reads returned different objects, and the NRE landed inside `Connect`. Nothing about the code was unusual; the whole point of `CurrentValue` is that it changes. The fix was one line — `if (_options.CurrentValue.Endpoint is { } endpoint) Connect(endpoint);` — which reads the property once and binds the result. **The habit worth building: read a maybe-null member exactly once, into a local, and check the local.** The empty property pattern `is { } x` does the read, the null test and the binding in a single step, which is why it reads better than `!= null` in exactly this situation.

> 🌍 **In the real world**: an ingestion pipeline preallocated its batch buffer as `var slots = new Slot[BatchSize];` over `struct Slot { public string Key; public ReadOnlyMemory<byte> Payload; }`, then filled it in a loop that `continue`d past rows that failed schema validation. A partially-filled batch therefore had holes: `Slot` instances at their default value, with a non-nullable `string Key` field holding `null`. The flush loop iterated the whole buffer and called `slot.Key.Length`, and on a batch where every row was valid — which was every batch in every test, and most batches in production — nothing happened. The failures arrived in a burst on the day an upstream producer shipped a bad schema, which is the worst possible time. The compiler had warned about none of it: both halves of the hole (arrays of non-nullable references, and default structs with non-nullable reference fields) are documented gaps in the analysis. The fix was to track the fill count and slice the buffer to it before flushing. **The lesson to carry into a review: `new T[n]` and `default(T)` are the two places where the type system's promise about non-nullability is not backed by anything, and the compiler will not remind you.**

### The nullable attribute vocabulary in full

There are eleven attributes in `System.Diagnostics.CodeAnalysis`, and they sort cleanly into four groups. The framing that makes them memorable: **the `?` describes the *type*; the attributes describe the *contract*, for the cases where the contract and the type disagree.**

| Attribute | Category | Meaning |
|---|---|---|
| `[AllowNull]` | Precondition | A **non-nullable** parameter, field, or property might be null |
| `[DisallowNull]` | Precondition | A **nullable** parameter, field, or property should never be null |
| `[MaybeNull]` | Postcondition | A **non-nullable** parameter, field, property, or return value might be null |
| `[NotNull]` | Postcondition | A **nullable** parameter, field, property, or return value is never null |
| `[MaybeNullWhen(bool)]` | Conditional postcondition | A non-nullable argument might be null when the method returns that value |
| `[NotNullWhen(bool)]` | Conditional postcondition | A nullable argument isn't null when the method returns that value |
| `[NotNullIfNotNull(nameof(p))]` | Conditional postcondition | Return value / property / argument isn't null if `p` isn't null |
| `[MemberNotNull(...)]` | Helper method | The listed members aren't null when the method returns |
| `[MemberNotNullWhen(bool, ...)]` | Helper method | The listed members aren't null when the method returns that value |
| `[DoesNotReturn]` | Unreachable code | The method never returns — it always throws |
| `[DoesNotReturnIf(bool)]` | Unreachable code | Never returns if the annotated `bool` argument has that value |

Every row follows the same shape: **preconditions relax or tighten what a *caller* may pass; postconditions describe what the caller may *assume* afterwards.** Note the asymmetry in the first four — each attribute is only meaningful on the *opposite* annotation. `[AllowNull]` on a `string?` is redundant; `[NotNull]` on a `string` is redundant.

The canonical `[AllowNull]` case is a property with a defaulting setter — the getter never returns null, but callers may assign null to mean "reset":

```csharp
[AllowNull]
public string ScreenName
{
    get => _screenName;
    set => _screenName = value ?? GenerateRandomScreenName();
}
private string _screenName = GenerateRandomScreenName();
```

`[DisallowNull]` is its mirror — the property may *read* null (it starts that way) but must never be *set* to null:

```csharp
[DisallowNull]
public string? ReviewComment
{
    get => _comment;
    set => _comment = value ?? throw new ArgumentNullException(nameof(value));
}
```

Because these are preconditions, they apply only to the `set` accessor. That is why the attribute goes on the property, not on an accessor.

`[MemberNotNull]` is the answer to the `CS8618` flood that every constructor-heavy class produces when you enable NRT. The compiler analyses constructors and field initializers, but it does not follow assignments through a shared helper:

```csharp
public class Container
{
    private string _uniqueIdentifier;   // must be initialized
    private string? _optionalMessage;

    public Container() => Helper();
    public Container(string message) { Helper(); _optionalMessage = message; }

    [MemberNotNull(nameof(_uniqueIdentifier))]
    private void Helper() => _uniqueIdentifier = DateTime.Now.Ticks.ToString();
}
```

`[MemberNotNullWhen]` is the same idea for a `bool`-returning initializer (`if (TryInitialize()) { _field.Use(); }`).

**`[DoesNotReturnIf]` is the one with a production sting in the tail.** It is what makes `Debug.Assert` teach the analyzer anything. The declaration in `dotnet/runtime` is:

```csharp
[Conditional("DEBUG")]
[OverloadResolutionPriority(-1)]
public static void Assert([DoesNotReturnIf(false)] bool condition)
```

Both attributes matter, and they pull in opposite directions. `[DoesNotReturnIf(false)]` is why `Debug.Assert(order.Customer is not null);` clears the warning on the next line — without it the compiler would learn nothing from the call, exactly as with any other method. `[Conditional("DEBUG")]` means the compiler **omits the call entirely when `DEBUG` is not defined**, which is every Release build you ship. So the construct you reached for to make the analyzer stop complaining is, in production, not there.

> 🌍 **In the real world**: a team hitting a wall of `CS8602` in a legacy order pipeline settled on `Debug.Assert(x is not null)` as the house style for "I know this is set" — it read better than `!`, it was greppable, and unlike `!` it actually did something. In Debug and in CI it did: an assert fired within a week and caught a genuine ordering bug. What nobody articulated is that `[Conditional("DEBUG")]` deletes the call from the Release build, so the production binary had the same protection as a bare `!` — none — while the source looked defensive. The eventual incident was a null customer on a partially-materialised order, and the stack trace pointed several frames past the assert, at a mapper. The team's revised rule was a two-way split that is worth stealing: `Debug.Assert` for invariants you want to catch *in development*, and `ArgumentNullException.ThrowIfNull` (unconditional, and it fills in the parameter name via `[CallerArgumentExpression]`) for anything whose violation should be visible in production. **The general point: an assertion's null-state narrowing is a compile-time effect and its runtime check is a build-configuration effect, and those two are not the same guarantee.**

> 🌍 **In the real world**: a validation library exposed `Guard.HasValue(string? s)` returning `bool`, used at the top of roughly two hundred methods. After NRT was enabled, every one of those methods warned on the very next line, and the team's first pass added `!` at each dereference — two hundred suppressions, each of which was individually correct and collectively meant the analyzer had been switched off for the most null-sensitive code in the product. The second pass replaced all of it with a single character change to the library: `public static bool HasValue([NotNullWhen(true)] string? s)`. Every suppression came out, and the *real* violations — three places where the guard was checked on one variable and a different one was dereferenced — surfaced as fresh warnings the moment the noise was gone. **The heuristic: when the same `!` appears at more than a handful of call sites, the bug is in a signature, not at the call sites.** One attribute on the API is worth two hundred suppressions in the callers, and it is the only version of the fix that keeps finding bugs afterwards.

### NRT at the boundary — EF Core, model binding, JSON

Microsoft's own documentation carries a caveat that is easy to skim past: *"Nullable reference annotations don't introduce behavior changes, but other libraries might use reflection to produce different runtime behavior for nullable and non-nullable reference types."* Three of those libraries are ones you use every day, and in each case the `?` you type changes something outside the compiler.

**Entity Framework Core reads the annotations and maps them to required/optional.** From the same source: *"Notably, Entity Framework Core reads nullable attributes. It interprets a nullable reference as an optional value, and a non-nullable reference as a required value."* Adding or removing a `?` on an entity property is a **schema change**, and the next migration will contain it.

**ASP.NET Core MVC infers `[Required]` from non-nullability.** With a nullable context enabled, MVC treats every non-nullable reference type property or parameter on a bound model as though it carried `[Required(AllowEmptyStrings = true)]`. The opt-out is a single option:

```csharp
builder.Services.AddControllers(options =>
    options.SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true);
```

Its documented semantics: `false` (the default) means all non-nullable reference types behave as if `[Required]` were applied; `true` makes nullable and non-nullable behave identically for validation.

**System.Text.Json ignores annotations unless you opt in — and .NET 9 added the opt-in.** `JsonSerializerOptions.RespectNullableAnnotations` *"configures the serializer to throw an exception when trying to serialize a `null` value from a non-nullable property getter, or when deserializing a `null` value into a non-nullable property setter or constructor parameter."* It also honours `[NotNull]`, `[MaybeNull]`, `[AllowNull]` and `[DisallowNull]`. Two things to know about it:

- The documented recommendation is that *"new applications always set this property to `true`, in combination with the closely related `RespectRequiredConstructorParameters` property"* — and the application-wide default can be flipped through the `System.Text.Json.Serialization.RespectNullableAnnotationsDefault` feature switch.
- It does **not** cover everything. Per the docs: *"this setting only governs nullability annotations of non-generic properties, fields, and constructor parameters. It cannot be used to enforce nullability annotations of root-level types, collection elements, or generic parameters."* A `List<string>` can still come back with null elements — which is the array/collection hole from the previous section arriving through a different door.

> 🌍 **In the real world**: a developer tidying an EF Core entity changed `public string? MiddleName { get; set; }` to `public string MiddleName { get; set; } = string.Empty;` because "every user has a middle name field, it's just empty". The diff read as a null-safety improvement and was approved in under a minute. The generated migration contained `ALTER COLUMN [MiddleName] nvarchar(max) NOT NULL`, which applied cleanly to the seeded staging database — where every row had been created by the current code and had an empty string — and failed on production, where two million rows predating the column had `NULL`. The deploy rolled back mid-migration at 6am. The team had reviewed the C# and not the migration, on the reasonable-sounding basis that nullable reference types have no runtime effect. **They do not have a runtime effect in *your* process; they have a schema effect in EF Core's, because EF reads the annotation to decide required versus optional.** The rule adopted afterwards was that any diff touching a `?` on an entity type must show the generated migration in the pull request.

> 🌍 **In the real world**: a team enabled NRT across an existing MVC application and immediately broke every `PATCH` endpoint. The binding models were reused for both create and partial-update, and their properties were plain `string`, `string`, `string` — which under a nullable context makes MVC infer `[Required(AllowEmptyStrings = true)]` on all of them. A partial update that sent one field now failed validation on the other eleven. The fast fix was `SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true`, and they used it to unblock the release; the fix they kept was to stop sharing one model between create and patch, and to declare the patch model's properties `string?`, which is what they actually meant. **The reframing worth internalising: on a bound model, `?` is not a compiler hint — it is your validation rule.** A DTO whose annotations are dishonest produces a validation contract you did not design.

> 🌍 **In the real world**: an integration team spent two days on a bug where `order.CustomerReference.Trim()` threw an NRE on a DTO whose property was declared `public string CustomerReference { get; set; }` — non-nullable, no `!` anywhere, and the analyzer clean end to end. `System.Text.Json` had happily deserialised a payload with `"customerReference": null` into it, because on .NET 8 the serializer did not look at nullability annotations at all. Moving to .NET 9 and setting `RespectNullableAnnotations = true` (plus `RespectRequiredConstructorParameters = true`) turned the silent null into a deserialization exception at the boundary, which is where they wanted it. What the change did *not* fix, and the docs say so, is collection elements: `List<string> Tags` could still arrive with nulls inside it, because the setting only governs non-generic properties, fields and constructor parameters. **The durable lesson is a boundary rule: a deserializer constructs your object without running your constructor or your invariants, so a `?`-free DTO is a claim about your intent, not a guarantee about the bytes on the wire** — and it only becomes a guarantee when you configure something to enforce it, and only as far as that something reaches.

### Generic nullability — what `T?` really means

`T?` is one syntax with three different resolutions, and which one you get depends on the type argument and the constraint. Microsoft's rules for an **unconstrained** `T`:

| Type argument | `T` is | `T?` is |
|---|---|---|
| non-nullable reference type — `Box<string>` | `string` | `string?` |
| **value type — `Box<int>`** | `int` | **`int` — the annotation has no effect** |
| already-nullable reference type — `Box<string?>` | `string?` | `string?` (no "doubly nullable") |

The middle row is the one people get wrong. On an unconstrained `T`, `T?` does **not** become `Nullable<int>`. It becomes `int`, and the `?` is purely a signal to the *analyzer* that this slot may hold `default(T)`. `T?` only means `Nullable<T>` when the type parameter carries the `struct` constraint.

Constraints then narrow what is allowed and what `T?` means inside:

| Constraint | Accepts | Notes |
|---|---|---|
| `where T : class` | non-nullable reference types | `Box<string?>` warns |
| `where T : class?` | nullable **or** non-nullable reference types | both allowed |
| `where T : struct` | non-nullable value types | `Box<int?>` rejected; inside, `T?` **is** `Nullable<T>` |
| `where T : notnull` | non-nullable reference **or** value types | `Box<string?>` warns |
| `where T : BaseType` | non-nullable types deriving from `BaseType` | use `BaseType?` to allow nullable |

This is exactly why `[MaybeNull]` and `[NotNull]` exist as *postconditions on a return*. A generic `Find<T>` that returns `default` when nothing matches cannot express itself with `?` alone, because on `T = int` the `?` evaporates:

```csharp
[return: MaybeNull]
public T Find<T>(IEnumerable<T> sequence, Func<T, bool> predicate)
```

And `[NotNull]` on a parameter is what lets a throwing helper hand its caller a narrowed state:

```csharp
public static void ThrowWhenNull([NotNull] object? value, string valueExpression = "")
    => _ = value ?? throw new ArgumentNullException(nameof(value), valueExpression);
```

The contract that reads out of that signature is precise: callers may pass null, and if the method returns at all, the argument is not null.

> 🌍 **In the real world**: a caching layer exposed `bool TryGet<T>(string key, out T? value)`, written with `T?` on the out parameter because `?` is how you say "might be absent" everywhere else and the shape looked like `TryGetValue`. (It isn't: `Dictionary<TKey, TValue>.TryGetValue` is declared `bool TryGetValue(TKey key, [MaybeNullWhen(false)] out TValue value)` — an attribute, not a `?`.) Here `T` was unconstrained, so on `TryGet<int>("hits", out var v)` the `T?` collapsed to plain `int`, the miss path produced `default(int)` — zero — and callers doing `if (!cache.TryGet(key, out var v)) v = 0;` could not distinguish a cache miss from a cached zero. The counters they were caching were legitimately zero much of the time, so the bug read as "the cache never seems to warm up" and was chased in the eviction policy for a week. The correct signature turned out to be the one the BCL actually uses for this shape: `bool TryGet<T>(string key, [MaybeNullWhen(false)] out T value)` — an attribute, not an annotation, because only the attribute can say "maybe-default on the false branch" for a `T` that might be a struct. **The transferable rule: `?` on an unconstrained type parameter is a hint to the analyzer, not a wrapper; if you need the *value* space to include an absent case for both classes and structs, you need `Nullable<T>` explicitly, a sentinel, or a `MaybeNullWhen` contract — the `?` alone will silently do nothing on the struct instantiations.**

### Exhaustiveness, precisely

"The `switch` expression is exhaustiveness-checked" is true and too coarse. There are four distinct warnings, and each one names a different way the value space is not covered. Being able to name them is the difference between "I add `_` when the compiler tells me to" and "I know what the compiler is telling me."

| Code | Message | Fires when |
|---|---|---|
| **CS8509** | *The switch expression does not handle all possible values of its input type (it is not exhaustive). For example, the pattern '…' is not covered.* | the general case |
| **CS8524** | *…does not handle some values of its input type (it is not exhaustive) **involving an unnamed enum value**.* | every declared enum member is handled, but the enum's underlying type has other values |
| **CS8655** | *The switch expression does not handle some **null inputs** (it is not exhaustive).* | the value space includes `null` and no arm matches it |
| **CS8846** / **CS8847** | *…However, a pattern with a `when` clause might successfully match this value.* | the only arm that could match is guarded, so the compiler can't prove coverage |

**CS8524 is the enum one.** A `switch` over `Status` that handles `Pending`, `Shipped` and `Cancelled` with no `_` is still not exhaustive, because `(Status)7` is a legal value of the type — an enum is a named set of constants over an integral type, not a closed set of values. This is why "I handled every member, why is it still warning?" has a real answer.

**CS8655 is the null one, and it is subtler than it looks.** Microsoft's own example:

```csharp
int AsScale(string status) => status switch
{
    "Red" => 0,
    "Yellow" => 5,
    "Green" => 10,
    { } => -1          // ⚠ CS8655 — matches every non-null value, but not null
};
```

The parameter is `string`, not `string?`, and the compiler *still* warns. The reason is the empty property pattern: `{ }` means "non-null", so it does not cover `null`. Swap it for `_` — which matches everything, null included — and the warning goes. **`{ }` and `_` are not interchangeable catch-alls.** `{ }` is a null check; `_` is the real discard.

**When nothing matches at runtime**, the switch expression throws — and the type is worth memorising because it appears in stack traces with no useful message: `System.Runtime.CompilerServices.SwitchExpressionException` on .NET Core 3.0 and later, and `InvalidOperationException` on .NET Framework.

**And there is one construct the compiler does not check at all.** Per the documentation: *"List patterns don't generate a warning when all possible inputs aren't handled."* A `switch` expression whose arms are all list patterns gets no exhaustiveness analysis, so a length you didn't think of becomes a `SwitchExpressionException` with nothing at compile time to warn you.

> 🌍 **In the real world**: an order service dispatched on a `Status` enum with a `switch` expression covering all five declared members and no discard arm — a deliberate choice, and a good one, because the team wanted CI to fail the day somebody added a sixth member without handling it. To make that work they had promoted the exhaustiveness warning to an error; what they had actually promoted was CS8509. The build was green, because with all five members handled the compiler was emitting **CS8524** instead — the unnamed-enum-value variant — which was still just a warning and was lost in the build log. Months later a bulk data fix wrote `Status = 7` into a few hundred rows, and those orders produced `SwitchExpressionException` with a message that named no order and no status. The two-line fix was to add CS8524 to the error list and add a `_ => throw new InvalidOperationException($"Unhandled status {s}")` arm carrying the offending value. **The design tension is real and worth being able to argue: a discard arm buys you a good runtime error and costs you the compile-time check that a new enum member is unhandled.** You get both only by treating the *warning* as the compile-time check and using the discard arm purely to produce a diagnosable exception — and by knowing that there are two warning numbers to promote, not one.

### Subpattern evaluation order is unspecified

This is the most commonly mis-stated fact about pattern matching, and the C# standard is unambiguous about it in three separate places:

> *"The order of evaluation of operations and side effects during pattern-matching (calls to `Deconstruct`, property accesses, and invocations of members of `System.Runtime.CompilerServices.ITuple`) is not specified."* — §11.2.1
>
> *"The order in which subpatterns are matched is not specified, and a failed match may not test all subpatterns at runtime."* — §11.2.6, property pattern
>
> *"The order in which subpatterns are matched at runtime is unspecified, and a failed match might not attempt to match all subpatterns."* — §11.2.5, positional pattern

So in `o is { Status: "Cancelled", Total: > 1000 }`, **you may not assume `Status` is read before `Total`, and you may not assume `Total` is not read when `Status` fails to match.** The `switch` *arms* are ordered — the specification says "the `switch` expression arms are evaluated in text order" and the first matching arm wins — but the tests *inside* a pattern are not.

The reason is that the compiler does not lower a pattern into a chain of `&&`. It builds a decision structure over the whole set of arms and shares the common tests between them, which is what makes a large `switch` cheap. The standard even points at this: *"As repeated member paths are allowed, the compilation of pattern matching can take advantage of common parts of patterns."* Two arms that both test `{ Customer.Tier: ... }` do not read `Customer` twice.

Three practical consequences:

1. **Never put a side-effecting or expensive property getter in a pattern.** Lazy loading, memoised computation, an `IOptionsMonitor` snapshot, a counter — all of them become order-dependent behaviour that the language does not promise to keep stable.
2. **The `and`/`or` combinators are not short-circuiting either** (§11.2.10), so `x is not null and { Length: > 0 }` is not a guarantee that the null check runs first — the *pattern semantics* still make the whole thing safe, but the reasoning "I ordered the cheap test first" is not sound.
3. **A `when` clause *is* ordered relative to its own pattern**: the arm runs only if the pattern matches *and* the guard returns true, so the guard runs after the pattern for that arm. If you genuinely need ordered, side-effecting logic, a `when` clause is the supported place for it — which is also why an expensive `when` clause is a real cost, evaluated arm by arm.

> 🌍 **In the real world**: a pricing engine matched on `order is { Customer.Tier: "Gold", LineCount: > 20 }`, where `Customer` was a lazy-loading navigation property that issued a query on first access. The team knew this and had ordered the arms so that the cheap `LineCount` test appeared first in the *earlier* arms, reasoning that most orders would be rejected before `Customer` was ever touched. Query counts on the database agreed with them, for two years. Then a toolchain upgrade changed how the decision structure was built, `Customer` began to be read on paths that previously short-circuited past it, and the endpoint's database calls roughly doubled overnight with no change to the pricing code in the diff. There was no bug to fix, because there had been no promise to break: the standard says subpattern evaluation order is unspecified, and the team had built a performance characteristic on an implementation detail. The rewrite hoisted the load out of the pattern — fetch the tier once into a local, match on the local. **The general shape: a pattern is a question about a value, not a script.** Anything whose *timing* matters — a query, a log line, a counter, a lazily-materialised property — has to happen before the pattern, not inside it.

### Pattern precedence traps

Precedence is three levels: **`not` binds first, then `and`, then `or`.** The `&&`/`||` analogy only covers the bottom two, and the missing level is where the bug lives.

**Trap one — `not` binds to the immediately following pattern, not to the conjunction:**

```csharp
// Intent: "any character that is NOT a lowercase letter"
static bool IsNotLowerCaseLetter(char c) => c is not >= 'a' and <= 'z';

// What it actually means:
static bool Parsed(char c) => c is ((not >= 'a') and <= 'z');

// What you meant:
static bool Correct(char c) => c is not (>= 'a' and <= 'z');
```

**Trap two — `not X or Y` distributes the way the grammar says, not the way it reads.** Microsoft's documented example, with its actual output:

```csharp
object msg = "msg";
bool result = msg is not int or string;   // parsed as: msg is (not int) or string
// => True
```

Read aloud, "is not int or string" sounds like "is neither an int nor a string". It parses as "is (not an int), or is a string" — which is true for every value that isn't an int, and also true for every string. As a guard clause, that is the opposite of what the author wanted for exactly one of the two types they were trying to exclude.

**Trap three — you cannot declare a pattern variable under `not` or `or`** (`CS8780`). The standard's rationale: *"Because neither `not` nor `or` can produce a definite assignment for a pattern variable, it is an error to declare one in those positions."* So `x is not null and { } v` binds `v`; `x is null or { } v` does not compile.

**Trap four — `==` and `!=` are not pattern syntax.** `x is == 5` is `CS9344` and `x is != 5` is `CS9345` ("use `not` to represent a negated pattern"). The constant pattern *is* the equality test.

**Trap five — the discard is not universally available.** `_` cannot be the entire pattern of an `is` expression or a `switch` *statement* case label; write `var _` there. (`CS8523` is the diagnostic for the case-label form; the exact code you see varies with what `_` binds to.) It can be the arm of a `switch` *expression*. And if a constant or a type named `_` is in scope, `_` silently stops being a discard and becomes a reference to that declaration.

> 🌍 **In the real world**: a message router guarded its handler with `if (envelope.Payload is not string or byte[]) throw new NotSupportedException();`, meaning "reject anything that isn't one of my two supported payload shapes". It parses as `(not string) or byte[]`. Work the three cases: a `string` gives `false or false` → no throw, correct; anything unsupported gives `true or false` → throw, correct; and a **`byte[]` gives `true or true` → throw**, because a `byte[]` genuinely is "not a string" and the first alternative already matched. The guard rejected one of the two payload types it existed to permit. Every test used string payloads, so the suite was green, and the failure surfaced on the first binary message in production. The fix was one pair of parentheses — `is not (string or byte[])` — and the rule the team adopted afterwards was blunt and effective: **any `is` expression containing `not` gets explicit parentheses, always, even when they are redundant.** Microsoft's documentation gives the same advice in gentler words ("use parentheses to clarify your patterns"); a team that has been bitten writes it as a lint rule. The tell in review is that the buggy form is the one that reads *most* like English — "is not string or byte array" is exactly how you would say the correct intent out loud, and exactly not what it means.

### What a pattern will and will not convert

A pattern is a type test, not a conversion. The declaration/type pattern matches when the runtime type of the value satisfies one of a fixed list of conditions — identity conversion, derivation, interface implementation, another implicit reference conversion, a `Nullable<T>` with `HasValue`, or a boxing/unboxing conversion. The specification adds the exclusion that catches people: **"Declaration patterns don't consider user-defined conversions or implicit span conversions."**

The consequence that shows up in real code:

```csharp
object boxed = 5;              // a boxed Int32

if (boxed is long l) { }       // false — no unboxing conversion Int32 -> Int64
if (boxed is 5L) { }           // false — same reason
if (boxed is int i) { }        // true
```

There is no widening. `int` implicitly converts to `long` *as a value*; a boxed `int` does not unbox as a `long`. Numeric promotion is a compile-time conversion, and by the time the value is in an `object` there is nothing left to promote.

Nullable value types do unwrap, which is the one place the pattern is more forgiving than a cast:

```csharp
int? maybe = 7;
if (maybe is int v) { }        // true — matches when HasValue
if (maybe is int? x) { }       // ⚠ CS8116 — "use the underlying type instead"
```

`object o = (int?)null;` boxes to a plain `null` reference, so `o is null` is `true` and `o is int` is `false` — consistent, once you know that `Nullable<T>` never survives boxing.

**Constant patterns use `object.Equals`, not `==`.** The specification defines three cases: integral and enum inputs compare with `e == v`; a `Span<char>` or `ReadOnlySpan<char>` against a constant string uses `MemoryExtensions.SequenceEqual`; and *everything else* matches when `object.Equals(e, v)` returns `true`. Two things fall out of this:

- **`x is double.NaN` matches NaN**, even though `x == double.NaN` is always false, because `Equals` treats NaN as equal to itself. Microsoft's example prints `Unknown` for `Classify(double.NaN)` from the arm `double.NaN => "Unknown"`.
- Meanwhile a *relational* pattern against NaN is a compile-time error — `CS8782: Relational patterns may not be used for a floating-point NaN` — because every relational comparison with NaN is false and the compiler refuses to let you write something that can never match.

Two more type-level rejections worth knowing by number:

- **`CS8781`** — *Relational patterns may not be used for a value of this type.* The standard lists the built-in supported set exhaustively: `sbyte`, `byte`, `short`, `ushort`, `int`, `uint`, `long`, `ulong`, `char`, `float`, `double`, `decimal`, `nint`, `nuint`, and enums. `s is > "a"` on a `string` does not compile. Note the trap in the other direction: `o is > 5` on an `object` **does** compile, because when the input type has no built-in relational operator the standard falls back to *"an explicit nullable or unboxing conversion"* to the constant's type — and `object` → `int` unboxes. It is a type test plus a comparison, not an error.
- **`CS9060`** — *Cannot use a numeric constant or relational pattern on '…' because it inherits from or extends `INumberBase<T>`.* In generic-math code, `where T : INumber<T>` plus `t is > 0` is rejected: the compiler doesn't know which numeric type's comparison to use. Narrow with a type pattern first.

> 🌍 **In the real world**: an event bus carried payloads as `object` and dispatched with `payload switch { long id => HandleById(id), string s => HandleByKey(s), _ => Dead(payload) }`. It worked in every test and against the two internal producers, both of which wrote `long` into the envelope from C#. It failed silently — everything to the dead-letter queue — for a third producer whose messages arrived through `System.Text.Json`, because the deserializer materialises a JSON number that fits into an `Int32` as a boxed `int`, and a boxed `int` does not match `long`. Nothing threw; the discard arm did exactly what it was written to do, and the symptom was "producer three's messages just don't arrive". The permanent fix was to stop round-tripping identifiers through `object` at all and give the envelope a typed discriminator, but the immediate one was an arm per boxed numeric type. **The rule to carry: once a value is boxed, pattern matching tests its exact runtime type and nothing more — the implicit numeric conversions you rely on in ordinary code do not exist across a boxing boundary**, and a `_` arm will absorb the mismatch without a sound.

### List patterns — countable, indexable, sliceable

The requirements are stricter and more interesting than "has `Length` and an indexer", and they differ between a bare `..` and a `.. subpattern`.

A **list pattern** requires the type to be *countable* (an accessible `Length` or `Count` property returning `int`) and *indexable* — and the specification is specific about which indexer: *"an accessible indexer that takes an `Index` as an argument, or an accessible indexer with a single `int` parameter. If both indexers are present, the former is preferred."*

A **slice pattern with no subpattern** (`[1, .., 9]`) requires nothing beyond that. It is a pure discard — the standard says *"a slice pattern acts like a proper discard; that is, no tests shall be made for such pattern"* — and it only affects the length test and which indices the other subpatterns read.

A **slice pattern with a subpattern** (`[1, .. var mid, 9]`) additionally requires the type to be *sliceable*: *"an accessible indexer that takes a `Range` as an argument, or an accessible `Slice` method with two `int` parameters. If both are present, the former is preferred."*

**Arrays and `string` have neither a `Range` indexer nor a `Slice` method** — the compiler special-cases them. From the standard: *"The input type for a slice pattern is the return type of the underlying `this[Range]` or `Slice` method with two exceptions: For `string`s and arrays, `string.Substring` and `RuntimeHelpers.GetSubArray`, respectively, shall be used."* Both of those **allocate a copy**. `Span<T>` and `ReadOnlySpan<T>` have no `Range` indexer either — their only indexer is `this[int]` — but they *do* satisfy the second half of the rule with `Slice(int, int)`, which returns a span over the same memory. Nothing is allocated.

The lowering, from the specification, makes the cost model obvious:

```csharp
// expr is [1, 2, 3]  is equivalent to:
expr.Length is 3
&& expr[new Index(0, fromEnd: false)] is 1
&& expr[new Index(1, fromEnd: false)] is 2
&& expr[new Index(2, fromEnd: false)] is 3

// expr is [1, .. var s, 3]  is equivalent to:
expr.Length is >= 2
&& expr[new Index(0, fromEnd: false)] is 1
&& expr[new Range(new Index(1, fromEnd: false), new Index(1, fromEnd: true))] is var s
&& expr[new Index(1, fromEnd: true)] is 3
```

Read the second one and the two rules fall out for free: the minimum length is the count of non-slice subpatterns (so `[_, .., _]` needs **two** elements, not one), and `.. var s` is the only line that costs anything beyond an index.

> 🌍 **In the real world**: a device-telemetry gateway parsed a binary framing protocol with `frame is [SOH, .. var body, var checksum]` over the `byte[]` it got from the socket, which read beautifully and passed review on those grounds. At a few hundred messages per second per connection it was invisible. When the fleet grew, an allocation profile showed `byte[]` dominating gen-0 with no obvious allocation site in the parser — the copies were coming from `RuntimeHelpers.GetSubArray`, which is what the compiler emits for a slice-with-subpattern on an array, once per message. The parser was allocating a full copy of every payload purely to give it a name. Changing the parameter type from `byte[]` to `ReadOnlySpan<byte>` kept the pattern character-for-character and made the slice a view over the original buffer, because a span satisfies the sliceable requirement through `Slice(int, int)`, which returns a span over the same memory. **The generalisable point: `..` on its own is free, and `.. var x` is a slice — and whether that slice is a view or a copy is decided entirely by the receiver's type**, which is a property of the method signature, not of the pattern you wrote.

### Closed hierarchies and unions — C# 15 preview

The honest state of play, version-gated, because this is a live area and an interviewer may be testing whether you version-gate.

**On C# 14 / .NET 10 — what you actually ship today** — there is no compile-time exhaustiveness over a closed set of types. The compiler treats every reference type as open: another assembly could derive from your base, and `null` is always a possible value. So the DU-by-convention shape still needs its catch-all:

```csharp
public abstract record Shape;
public sealed record Circle(double R) : Shape;
public sealed record Square(double S) : Shape;

double Area(Shape s) => s switch
{
    Circle c => Math.PI * c.R * c.R,
    Square q => q.S * q.S,
    _ => throw new UnreachableException()   // still required
};
```

**In C# 15, in preview with .NET 11** (GA targeted for November 2026), two features close the gap, and they solve different problems:

- **`closed` hierarchies.** Marking a base type `closed` makes a `switch` over it exhaustive once every *direct* descendant is handled, with no discard arm and no warning. Three details a careful reader should have: the descendants must all be *visible at the switch site* (a `public closed` base with an `internal` descendant is exhaustive inside the assembly and warns outside it); `null` is still an extra value, so a switch over `PaymentMethod?` must handle it; and closure is **not transitive** — only direct descendants form the exhaustive set, and an indirect descendant is covered because its parent's arm covers it, not because it was enumerated. Marking a class `closed` also makes it implicitly `abstract`.
- **`union` types.** `public union Pet(Cat, Dog);` composes existing types into a closed set with no shared base class or interface. Patterns *unwrap* the union — a pattern applies to the union's `Value`, not to the union value itself — with three documented exceptions that apply to the union value: `_`, `var`, and `not`.

Interview posture: describe the C# 14 pattern as what you write, name `closed` and `union` as the C# 15 direction, and be explicit that they are in preview. Claiming a preview feature as shipped is a version-gating error an interviewer will notice; not knowing the direction exists reads as not following the language.

> 🌍 **In the real world**: a team modelled payment outcomes as `abstract record PaymentResult` with four sealed records under it, switched on them exhaustively, and ended every switch with `_ => throw new UnreachableException()` — the correct pattern, applied consistently, reviewed and approved. Eighteen months later a second team added a fifth case, `PartiallyRefunded`, in *their own* assembly, because the base record was `public` and nothing stopped them. Every switch in the original service began throwing `UnreachableException` in production, from a line whose entire purpose was to be impossible, and the exception type made the on-call engineer's first hypothesis "memory corruption" rather than "someone added a subtype". Nothing in the original service's build had changed. The two mitigations they adopted were both about *closing the set the compiler cannot close*: an internal-only constructor on the base record (so derivation outside the assembly fails to compile) and an architecture test asserting that the set of `PaymentResult` subtypes across all loaded assemblies matches an expected list. **The lesson to carry into the C# 15 conversation is why `closed` is a language feature rather than a convention: "closed hierarchy" is a claim the compiler has to be able to check, and until it can, `sealed` on the leaves buys you nothing about the base** — anyone with a reference to your assembly can extend it, and your `UnreachableException` is a comment, not a guarantee.

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

**The nullable context is a 2×2, not a switch** — this is the diagram that makes a staged migration obvious:

```
                       ANNOTATION FLAG
                  off                     on
              ┌────────────────────┬────────────────────┐
              │   disable          │   annotations      │
              │                    │                    │
        off   │ pre-C#8 behaviour  │ 'T?' declares      │
              │ every ref nullable │ nullable; NO       │
WARNING       │ '?' warns          │ warnings emitted   │
 FLAG         │ '!' does nothing   │ '!' does nothing   │
              ├────────────────────┼────────────────────┤
              │   warnings         │   enable           │
              │                    │                    │
        on    │ all refs nullable, │ full feature:      │
              │ members not-null   │ 'T' non-nullable,  │
              │ at method entry;   │ 'T?' nullable,     │
              │ '?' warns          │ warnings on        │
              └────────────────────┴────────────────────┘

  Migration path for a large codebase, left to right then down:
      disable  ──▶  annotations  ──▶  enable
                    (publish an          (fix your own
                     honest API           warnings)
                     surface first)
```

**What the compiler actually emits for a list pattern** — the specification's own lowering, which is where the cost model comes from:

```
  expr is [1, .. var s, 3]
        │
        ▼
  expr.Length is >= 2                      ← min length = count of NON-slice subpatterns
    && expr[Index(0, fromEnd:false)] is 1  ← indices from the front
    && expr[Range(Index(1,false),          ← the ONLY line that can allocate:
                  Index(1,true))] is var s     array  -> RuntimeHelpers.GetSubArray (copy)
    && expr[Index(1, fromEnd:true)] is 3       string -> string.Substring          (copy)
                                               Span   -> Slice(int, int)           (view)

  Drop the 'var s' and the Range line disappears entirely — a bare '..'
  is a pure discard that only moves the other indices.
```

**Shape of the benchmark** to settle the slice-allocation question yourself. No numbers here on purpose — run it on your own runtime and read *your* `Allocated` column, because that is the one that decides the design:

```csharp
[MemoryDiagnoser]              // the point of this benchmark is Allocated, not Mean
public class SlicePatternBench
{
    private byte[] _frame = null!;

    [Params(64, 1024, 16384)]  // sweep payload size: a copy scales with it, a view doesn't
    public int Size;

    [GlobalSetup] public void Setup() => _frame = new byte[Size];

    [Benchmark(Baseline = true)]
    public int BareSlice() => _frame is [0x01, .., var last] ? last : -1;   // no subpattern on '..'

    [Benchmark]
    public int ArraySliceBinding() =>                                        // GetSubArray -> copy
        _frame is [0x01, .. var body, _] ? body.Length : -1;

    [Benchmark]
    public int SpanSliceBinding()                                            // Slice(int,int) -> view
    {
        ReadOnlySpan<byte> s = _frame;
        return s is [0x01, .. var body, _] ? body.Length : -1;
    }
}
```

The prediction the mechanism gives you before you run it: `BareSlice` and `SpanSliceBinding` should be flat in `Allocated` across every `Size`, and `ArraySliceBinding` should grow with `Size`. If your run disagrees, the mechanism is wrong or the benchmark is — and either is worth knowing.

</details>
## Common pitfalls

1. **Treating `string?` like `Nullable<string>`.** It's a compile-time hint, not a runtime wrapper. There's no `.HasValue` or `.Value` — just check for `null` and use the variable.
2. **Overusing `!`.** Each `!` is a `// trust me, bro` to the compiler. Prefer fixing the actual nullness reasoning with `?? throw`, `if (x is null) return`, or `[NotNullWhen]`.
3. **Forgetting that NRT is per-project.** A library compiled with NRT off has signatures with no nullness info. Consumers see "null oblivious" warnings — set `<NullableContextOptions>` carefully when consuming such libraries.
4. **`is null` vs `== null`.** Almost always identical, but `is null` is preferred (it can't be overridden via `==` operator overloads, so it's safer for value-equal types and structurally-equal records).
5. **Using `as` for type tests.** `var s = obj as string; if (s != null) ...` is the old way. Modern: `if (obj is string s) ...`.
6. **`switch` expression without a discard arm + non-exhaustive types.** When the type is `string`, `int`, or any open-ended primitive, you almost always need `_ => ...`. Note that even a *non-nullable* `string` parameter needs it: the value space still includes `null`, and a `{ }` arm won't cover it (`CS8655`).
7. **Overlapping switch arms.** The first match wins, but the compiler warns when arms are unreachable (`CS8510` for expressions, `CS8120` for statements) — e.g. `> 0 => ...` followed by `> 5 => ...`.
8. **`is` with explicit non-pattern syntax.** `obj is List<int> { Count: > 0 }` — the property pattern works on the matched type. People forget this and reach for nested `is` checks.
9. **List patterns on non-indexable types.** `IEnumerable<T>` doesn't support list patterns — the type must be *countable* (`Length`/`Count`) and *indexable* (an `Index` indexer, or an indexer taking a single `int`). `T[]`, `List<T>`, `string`, `Span<T>`, `ReadOnlySpan<T>` qualify; `IEnumerable<T>` doesn't (`CS8979`/`CS8985` — the latter is specifically "no suitable `Length` or `Count` property was found").
10. **`.. var rest` allocating.** A bare `..` costs nothing. A slice *with a subpattern* needs the type to be sliceable, and for arrays and `string` the compiler special-cases it to `RuntimeHelpers.GetSubArray` and `string.Substring` — both of which **copy**. `Span<T>`/`ReadOnlySpan<T>` qualify via `Slice(int, int)`, which returns a view.
11. **Assuming subpatterns evaluate left to right.** They don't — the C# standard says the order is *unspecified* and a failed match *may not test all subpatterns*. Never put a lazily-loading property, a counter, or anything else side-effecting inside a pattern.
12. **Assuming `and`/`or` short-circuit.** They don't. The standard: *"Unlike their language operator counterparts, `&&` and `||`, `and` and `or` are not short-circuiting operators."*
13. **`is not X or Y`.** Parses as `(not X) or Y`, which is almost never the intent. Parenthesize every `not` in a compound pattern.
14. **Handling every enum member and thinking you're done.** You get `CS8524` instead of `CS8509` — an enum can hold any value of its underlying type. Promote *both* codes if you're using the warning as your exhaustiveness check.
15. **`{ }` used as a catch-all.** `{ }` means "non-null". `_` means "anything". Only `_` covers `null`.
16. **Believing `new string[10]` and `default(MyStruct)` are checked.** They are the two documented holes in null-state analysis: both produce non-nullable references holding `null`. Array elements are silent everywhere; the default struct is silent everywhere *except* a direct dereference off a local you initialised with `default`/`new()` in the same method, which does give `CS8602`.
17. **`Debug.Assert` as a production null guard.** `[DoesNotReturnIf(false)]` narrows the analyzer; `[Conditional("DEBUG")]` removes the call from Release. Use `ArgumentNullException.ThrowIfNull` when the check must survive the build.
18. **Boxed numerics in patterns.** `object o = 5; o is long` is `false`. Patterns don't apply implicit numeric conversions across a boxing boundary.
19. **`x is int? i` / `typeof(string?)` / `obj as string?`.** All compile errors (`CS8116`, `CS8639`, `CS8651`) — `?` is an annotation, not a type. Use the underlying type.
20. **Forgetting that generated files opt out.** `.g.cs`, `.designer.cs`, `.generated.cs` and `<auto-generated>` files are nullable-*disabled* regardless of your project setting.

## Interview-ready summary

- **NRT is compile-time only** — no runtime null check, no type-system change. The analyzer warns based on `?` annotations and flow analysis. `!` suppresses warnings without runtime effect.
- **Operators**: `?.` (conditional access), `??` (coalesce), `??=` (coalesce-assign), `!` (forgive), `?` (annotation). C# 14 adds `?.` on the LHS of assignment.
- **Attributes** like `[NotNullWhen]`, `[MemberNotNull]`, `[NotNullIfNotNull]` teach the analyzer about your method's null contract — most useful in libraries.
- **Pattern matching is now mature** — type, constant, declaration, property (extended), tuple, relational, logical, list patterns. The `switch` expression replaces most `if/else` chains.
- **`switch` expression is exhaustiveness-checked** — the compiler warns when the type space isn't fully covered. Add a `_ => ...` arm or handle the missing type.
- **Property patterns drill into objects**: `{ Customer.Tier: "Gold" }`. **List patterns** match shapes: `[var first, .. var rest]`.
- **Modern domain modeling**: `abstract record` hierarchy + exhaustive `switch` on type patterns ≈ discriminated unions. On C# 14 you still need the `_ => throw` arm; C# 15 adds real `closed` hierarchies and `union` types, in preview with .NET 11.
- **Nullability lives in metadata**: `NullableAttribute` / `NullableContextAttribute` carrying `0` = oblivious, `1` = not annotated, `2` = annotated. That is how the information crosses assembly boundaries and how EF Core reads it.
- **The nullable context is two flags** — annotation and warning. `annotations` publishes an honest API surface before you fix a single warning; `warnings` finds bugs before you commit to annotations.
- **The analysis is not sound, by design.** `new string[10]` and `default(MyStruct)` both produce non-nullable references holding `null` — unwarned once the value arrives via an array element, a parameter, a field or a return. The analysis also stops at method boundaries — that is what the attributes are for.
- **Four exhaustiveness warnings, not one**: `CS8509` (general), `CS8524` (unnamed enum value), `CS8655` (null inputs), `CS8846`/`CS8847` (a `when` clause might have matched). At runtime a miss throws `SwitchExpressionException`.
- **Subpattern evaluation order is unspecified** and `and`/`or` do not short-circuit. Patterns are questions, not scripts.
- **`?` changes runtime behaviour outside your process**: EF Core maps it to required/optional columns, MVC infers `[Required]` from non-nullability, and .NET 9's `RespectNullableAnnotations` makes System.Text.Json enforce it.
- **Precedence is `not`, then `and`, then `or`** — three levels. `is not string or byte[]` means `(not string) or byte[]`.

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
> **A**: `obj?.Method(args)` short-circuits — if `obj` is null, **neither `Method` nor `args` is evaluated.** This matters if `args` has side effects: `obj?.Process(LogAndCompute())` — `LogAndCompute()` only runs when `obj` is non-null. **C# 14's null-conditional assignment behaves the same way**, which is the point people get backwards: in `obj?.Total = ComputeTotal();` the right-hand side is *not* evaluated when `obj` is null. The specification is explicit — *"The right side of the assignment is only evaluated when the receiver of the conditional access is non-null"* — and as a statement `P?.A = B` is defined as `if (P is not null) P.A = B;`, with `P` evaluated once. The consequence for real code: a logger, a counter or an audit call sitting in the right-hand side silently doesn't run on the null path. `?.` short-circuits everything to its right, on both sides of the `=`.

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
> **A**: Roughly: `o is not null && o.Status == "active"`. The pattern combines a null check (because `{...}` matches non-null) with property access and equality. For value types, the null check is elided. The equality is not `==`: the C# standard defines a constant pattern as matching when **`object.Equals(e, v)`** returns `true`, except for integral/enum inputs (which use `e == v`) and `Span<char>`/`ReadOnlySpan<char>` against a constant string (which uses `MemoryExtensions.SequenceEqual`). `object.Equals` handles a null `Status` safely, and — a consequence worth remembering — it also makes `x is double.NaN` **match**, where `x == double.NaN` never would.
>
> **Cross-Q**: How would `o is { Status: "active", Total: > 100 }` differ?
>
> **A**: All listed properties must match; the value set is the same as `o is not null && o.Status == "active" && o.Total > 100`. The `>` is a **relational pattern** (C# 9). But the *evaluation* is not the same: the standard says *"the order in which subpatterns are matched is not specified, and a failed match may not test all subpatterns at runtime."* You may not assume `Status` is read first, and you may not assume `Total` goes unread when `Status` fails. The compiler builds a decision structure over all the arms and shares common tests between them rather than lowering each pattern to a `&&` chain — which is what makes a large `switch` cheap, and what makes side effects in a pattern unsafe.
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
> **A**: There isn't one warning, there are four, and naming them is the senior answer. **CS8509** is the general case — *"does not handle all possible values of its input type… For example, the pattern '…' is not covered."* **CS8524** fires when every *declared* enum member is handled but the enum's underlying type can still hold other values ("involving an unnamed enum value"). **CS8655** fires when `null` isn't covered — and it fires even on a non-nullable `string` parameter if your catch-all is `{ }`, because `{ }` means "non-null" and only `_` matches null. **CS8846**/**CS8847** fire when the only candidate arm is guarded: *"However, a pattern with a `when` clause might successfully match this value."* One construct escapes checking entirely — per the docs, *"list patterns don't generate a warning when all possible inputs aren't handled."*
>
> **Cross-Q²**: Why doesn't the switch expression on `abstract record Animal` with arms `Dog`, `Cat` warn me if I'm missing one?
>
> **A**: Because on C# 14 the compiler does **no** closed-hierarchy analysis: it treats every reference type as open — another assembly can derive from your base — and `null` is always a possible value on top of that. Marking the base `sealed` changes nothing (and an `abstract` base can't be `sealed`). So the shape you write today ends with `_ => throw new UnreachableException()`, and "did somebody add a subtype without adding an arm?" stays a code-review and test concern. **C# 15, in preview with .NET 11, closes this** with the `closed` modifier: a `switch` over a `closed` base is exhaustive once every *direct* descendant is handled, with no discard arm. Three caveats to state if you raise it: every descendant must be *visible at the switch site* (a `public closed` base with an `internal` descendant is exhaustive in-assembly and warns out-of-assembly), `null` is still a separate value for a nullable governing type, and closure is not transitive — only direct descendants form the exhaustive set. Say "preview", not "shipped."

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
> **A**: It depends on `T`, and the answer most people give is wrong for the value-type case. For an **unconstrained** `T`, Microsoft's rules are: with `T = string`, `T?` is `string?`; with `T = string?`, `T?` is still `string?` (there is no "doubly nullable"); and with **`T = int`, `T?` is just `int`** — *"the annotation has no effect on value types unless the type parameter has the `struct` constraint."* It does **not** become `Nullable<int>`. On an unconstrained `T`, `?` is a signal to the analyzer that the slot may hold `default(T)`, not a wrapper. `T?` means `Nullable<T>` only under `where T : struct`.
>
> That asymmetry is exactly why `[MaybeNull]` and `[NotNull]` exist: a generic `[return: MaybeNull] T Find<T>(...)` can say "may be absent" for both classes and structs, and `?` alone cannot. The constraint vocabulary is the other half of the answer: `where T : class` (non-nullable reference), `where T : class?` (either), `where T : struct` (non-nullable value type, and `T?` becomes `Nullable<T>` inside), `where T : notnull` (non-nullable reference *or* value type), and `where T : BaseType?` to allow a nullable derived type.

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
> **A**: It's a representation constraint, not a preference. `Span<T>` holds a **managed reference** (a `ref T`, a byref) plus a length. The CLR's object model does not permit a byref-typed field on a heap object — a byref may point into the middle of an object, into a stack frame, or into unmanaged memory, and the runtime only reports those from stack frames. So a type containing one has to be a `ref struct`, which the compiler then restricts to the stack (and to fields of other `ref struct`s). Everything else follows: no boxing, no heap fields, no `Span<T>?`, no `async` capture. `Memory<T>` pays for heap-safety with an indirection — it stores an `object` owner plus offset and length, and `.Span` re-derives the byref on demand — which is what lets it be a field and cross an `await`.
>
> Note what this answer does *not* claim. "Span is faster than Memory" is the sort of thing people repeat with a multiplier attached; the honest version is mechanical: slicing a `Span<T>` adjusts a pointer and a length with no allocation and no indirection, while every access through a `Memory<T>` goes through `.Span` first. Whether that is measurable in *your* loop is a question for `[MemoryDiagnoser]`, not for folklore. The NRT and null restrictions in this drill fall out of the ref-struct rules, not from a separate design choice.

### Drill 16 — Where does the nullability information live?

> **Q**: You said `string` and `string?` are the same type at runtime. So how does a *consumer* of my compiled library know which parameters accept null?
>
> **A**: Through metadata. The compiler emits two synthesized attributes in `System.Runtime.CompilerServices`: **`NullableAttribute`**, carrying a `byte` (or a `byte[]` for a constructed type like `Dictionary<string, List<string?>>`, one entry per reference-type position), and **`NullableContextAttribute`**, carrying one `byte` that sets a default for an enclosing type or method so only exceptions need their own attribute. The byte values are `0` = oblivious, `1` = not annotated (non-nullable), `2` = annotated (nullable). This is metadata the compiler reads back on the consuming side — it is not a type and it generates no IL.
>
> **Cross-Q**: Can I apply `NullableAttribute` myself, say from a source generator?
>
> **A**: No — `CS8623: Explicit application of 'System.Runtime.CompilerServices.NullableAttribute' is not allowed.` The `?` is the only supported input, which is the compiler protecting the invariant that the annotation and the emitted metadata always agree. The same "it's an annotation, not a type" rule shows up as `CS8639` (`typeof(string?)`), `CS8650` (`obj is string?`), `CS8651` (`obj as string?`), `CS8628` (`new object?()`) and — once you add a designation, so it's a pattern rather than an is-type test — `CS8116` (`obj is string? s`). If you are generating code and want annotations, emit a `#nullable enable` directive and write `?` in the generated source.
>
> **Cross-Q²**: What is the practical difference between byte `0` and byte `2` at a call site?
>
> **A**: Byte `2` (annotated) makes the analyzer *challenge* you: dereference without a check and you get `CS8602`. Byte `0` (oblivious) makes the analyzer *silent* — it will neither warn you for treating the value as non-null nor promise that it is. That third state is the one people forget, and it is why a solution that is clean under warnings-as-errors can still be shipping NREs: the holes are in the dependencies that were compiled `<Nullable>disable</Nullable>`, and obliviousness looks exactly like safety from the outside.

### Drill 17 — The nullable context is two flags

> **Q**: A 400-file legacy project produces 6,000 warnings when you set `<Nullable>enable</Nullable>`. What do you do?
>
> **A**: Split the two flags. `<Nullable>` isn't a switch, it's four combinations of an **annotation** flag and a **warning** flag. The staged path is `disable` → `annotations` → `enable`. Under `annotations` you get to *declare* nullability (`?` works, `T` means non-nullable) with **all warnings off**, so you can publish an honest API surface to consumers and to your own downstream projects before fixing a single warning in your implementation. Then flip files to `enable` as you drain them, via `#nullable enable` per file.
>
> **Cross-Q**: What does the `warnings` setting do that `enable` doesn't?
>
> **A**: `warnings` runs the full null analysis and emits every dereference warning, but leaves all reference types nullable and makes `?` itself a warning. Its distinctive rule: *members are considered not-null at the opening brace of methods*. It is a **discovery** mode — "show me where this code could throw" — without asking you to commit to any annotation yet. The pairing that matters: `warnings` finds bugs, `annotations` documents intent, and they are genuinely independent, which is why there are nine per-file pragma combinations (`#nullable enable warnings`, `#nullable disable annotations`, `#nullable restore`, and so on).
>
> **Cross-Q²**: Your project sets `enable` and treats `CS8602` as an error. Name a category of file in that project where nullable is still off.
>
> **A**: Generated code. The global nullable context does **not** apply to files the compiler considers generated, and it decides that four ways: `generated_code = true` in `.editorconfig`; an `<auto-generated>` comment as the first element in the file; a filename beginning `TemporaryGeneratedFile_`; or a filename ending `.designer.cs`, `.generated.cs`, `.g.cs`, or `.g.i.cs`. Everything in those files is compiled nullable-*disabled*, so its public surface is oblivious to consumers. Generators have to opt in by emitting `#nullable` themselves. In practice this means your protobuf contracts, scaffolded EF models and designer files are outside the policy you think you enabled — treat them as an external boundary and validate at the mapping layer.

### Drill 18 — Two places the analysis is simply wrong

> **Q**: Give me a case where a non-nullable reference holds `null` and the compiler says nothing.
>
> **A**: Two, both documented by Microsoft as known limitations. **Arrays**: `string[] values = new string[3];` produces three nulls, and `values[0].Length` warns about nothing. **Default structs**: for `struct S { public string Name; }`, `S s = default;` leaves `Name` null and the creation never warns — and `new S()` and `default(T)` inside a generic do the same. Arrays of structs compose the two: every element starts at the struct's default, so every non-nullable reference field in every element starts null.
>
> One refinement worth volunteering, because it shows you've actually tried it: the struct hole isn't *uniformly* silent. Roslyn tracks the member slots of a local it watched you initialise, so `S s = default; s.Name.Length;` in the same method **does** give `CS8602`. It goes quiet as soon as the value arrives some other way — an element of an `S[]`, a `foreach` variable, a parameter, a field, a method return. That is exactly the set of paths real code uses, which is why the hole matters despite the local-variable case being caught.
>
> **Cross-Q**: Do `required` members fix the struct case?
>
> **A**: Partly, and it's worth being precise. `required` forces a caller who writes `new S { ... }` to initialize the member, which closes the constructor path. It does not close `default(S)`, and it cannot — `default` is a zeroed value by definition and bypasses every constructor and initializer you have. Same for `new S[n]`. So `required` is a real improvement on the paths where somebody is constructing the value, and no help at all on the paths where the runtime is producing it. If a struct has a non-nullable reference field, the honest position is that the field is `string?` and the reads are checked.
>
> **Cross-Q²**: The compiler happily accepts `if (o.Config is not null) Use(o.Config);`. When is that unsafe?
>
> **A**: When `Config` is a property whose getter can return a different value on each call. The compiler assigns the member *path* `o.Config` a null-state slot and narrows it on the check, exactly as it would for a local — which is correct for fields and for the vast majority of properties, and wrong for anything that re-reads live state: `IOptionsMonitor<T>.CurrentValue`, a lazily-materialising navigation property, a snapshot accessor, a property backed by a `ConcurrentDictionary` lookup. Two reads, two different values, and the analyzer silently believed the first one. The fix is a habit rather than a rule: read once into a local and check the local — `if (o.Config is { } config) Use(config);` does the read, the null test and the binding in one step.

### Drill 19 — Which attribute, and why not just `?`

> **Q**: When is `[NotNullWhen(true)]` not enough, and you reach for something else?
>
> **A**: The eleven attributes divide into four jobs. **Preconditions** (`[AllowNull]`, `[DisallowNull]`) describe what a caller may *pass*, and each is only meaningful on the *opposite* annotation — `[AllowNull]` on a non-nullable slot, `[DisallowNull]` on a nullable one. **Postconditions** (`[MaybeNull]`, `[NotNull]`) describe what the caller may *assume* afterwards. **Conditional postconditions** (`[NotNullWhen]`, `[MaybeNullWhen]`, `[NotNullIfNotNull]`) key that assumption on the return value or on another argument. **Helpers** (`[MemberNotNull]`, `[MemberNotNullWhen]`) tell the compiler which fields a shared initializer assigns, which is the standard answer to a `CS8618` flood in a class with several constructors. `[DoesNotReturn]` / `[DoesNotReturnIf]` stop the analysis dead.
>
> **Cross-Q**: Show me the case for `[AllowNull]` on a property.
>
> **A**: A property that never *returns* null but accepts null on the way in as "reset to default":
>
> ```csharp
> [AllowNull]
> public string ScreenName
> {
>     get => _screenName;
>     set => _screenName = value ?? GenerateRandomScreenName();
> }
> private string _screenName = GenerateRandomScreenName();
> ```
>
> `string?` would be wrong — it would force every reader to null-check something that is never null. `string` alone would be wrong — it would warn every caller who assigns null deliberately. `[AllowNull] string` says exactly the two things that are true. Note it goes on the property, not the accessor: preconditions apply only to arguments, and the only argument is the setter's `value`. `[DisallowNull] string?` is the mirror — reads may be null, writes may not.
>
> **Cross-Q²**: `Debug.Assert(x is not null);` silences `CS8602`. Is that a good null guard?
>
> **A**: It's a good *development* check and not a guard at all. The declaration in `dotnet/runtime` is `[Conditional("DEBUG")] [OverloadResolutionPriority(-1)] public static void Assert([DoesNotReturnIf(false)] bool condition)`. `[DoesNotReturnIf(false)]` is what makes the analyzer narrow after the call — without it the compiler would learn nothing, since the analysis doesn't trace into method bodies. But `[Conditional("DEBUG")]` means the compiler **omits the call entirely** when `DEBUG` isn't defined, which is the build you ship. So the Release binary has the protection of a bare `!` while the source reads as defensive. If the invariant matters in production, `ArgumentNullException.ThrowIfNull(x)` — unconditional, and it fills the parameter name in from `[CallerArgumentExpression]`.

### Drill 20 — Where `?` stops being compile-time only

> **Q**: You keep saying NRT has no runtime effect. Microsoft's own docs carry a caveat. What is it?
>
> **A**: *"Nullable reference annotations don't introduce behavior changes, but other libraries might use reflection to produce different runtime behavior for nullable and non-nullable reference types."* The `?` has no effect in *your* process; it has plenty of effect in libraries that reflect over it. Three you use every day: **EF Core** — the docs say it *"interprets a nullable reference as an optional value, and a non-nullable reference as a required value"*, so adding or removing a `?` on an entity property is a schema change that lands in your next migration. **ASP.NET Core MVC** — with a nullable context enabled, every non-nullable reference type on a bound model behaves as if it carried `[Required(AllowEmptyStrings = true)]`, controlled by `MvcOptions.SuppressImplicitRequiredAttributeForNonNullableReferenceTypes`. **System.Text.Json** — historically ignored annotations entirely; .NET 9 added `JsonSerializerOptions.RespectNullableAnnotations` to opt in.
>
> **Cross-Q**: What exactly does `RespectNullableAnnotations` enforce, and what does it not?
>
> **A**: It makes the serializer *"throw an exception when trying to serialize a `null` value from a non-nullable property getter, or when deserializing a `null` value into a non-nullable property setter or constructor parameter"*, and it honours `[NotNull]`, `[MaybeNull]`, `[AllowNull]` and `[DisallowNull]` too. What it does not do is stated just as plainly: *"this setting only governs nullability annotations of non-generic properties, fields, and constructor parameters. It cannot be used to enforce nullability annotations of root-level types, collection elements, or generic parameters."* So `List<string> Tags` can still deserialize with null elements. It's off by default; the recommendation is to set it — along with `RespectRequiredConstructorParameters` — in new applications, and the app-wide default can be moved with the `System.Text.Json.Serialization.RespectNullableAnnotationsDefault` feature switch.
>
> **Cross-Q²**: Why is that limitation the *same* limitation as one of the two known pitfalls in the analysis?
>
> **A**: Because both are the collection-element hole. The compiler can't stop `new string[3]` from being three nulls, and the serializer can't stop `["a", null, "c"]` from filling a `List<string>` with one — the runtime has no representation of "non-nullable element" to check against, only metadata the compiler wrote for the compiler's benefit. Same root cause, two different tools failing at it. Which is the real lesson about NRT at a boundary: the annotation is a claim about your intent, and it only becomes a guarantee where something specific is enforcing it, and only as far as that thing reaches.

### Drill 21 — Reading a pattern's cost

> **Q**: What does `frame is [0x01, .. var body, var checksum]` compile to, and what does it cost?
>
> **A**: The specification gives the lowering directly: `frame.Length is >= 2 && frame[Index(0)] is 0x01 && frame[Range(Index(1,false), Index(1,true))] is var body && frame[Index(1, fromEnd:true)] is var checksum`. Two things fall out. The **minimum length is the number of non-slice subpatterns** — so `[_, .., _]` requires two elements, not one. And the **only line that can allocate is the `Range` access**. For a `T[]` the compiler special-cases that to `RuntimeHelpers.GetSubArray`, for a `string` to `string.Substring` — both **copy**. A `Span<T>`/`ReadOnlySpan<T>` has no `Range` indexer, but it satisfies the sliceable requirement with `Slice(int, int)`, which returns a **view** and allocates nothing.
>
> **Cross-Q**: So is `..` expensive?
>
> **A**: A bare `..` is free. The standard calls it *"a proper discard; that is, no tests shall be made for such pattern"* — it only changes the length test and which indices the other subpatterns read. The requirements differ accordingly: a list pattern needs the type to be *countable* (`Length`/`Count`) and *indexable* (an `Index` indexer, or an indexer taking one `int`, with the former preferred). Only a slice *with a subpattern* additionally needs the type to be *sliceable* (a `Range` indexer, or `Slice(int, int)`). So `[1, .., 9]` and `[1, .. var mid, 9]` have genuinely different type requirements and genuinely different costs, and the difference is three characters.
>
> **Cross-Q²**: How would you make that parser allocation-free without changing the pattern?
>
> **A**: Change the receiver's type, not the pattern. `ReadOnlySpan<byte> frame` instead of `byte[] frame` keeps the pattern character-for-character and turns the slice from a copy into a view, because a span meets the sliceable requirement with `Slice(int, int)`, which returns a span over the same memory rather than a copy. This is the general shape of span refactoring: the call sites and the logic stay put, and the cost model changes because the *signature* changed. Verify it with `[MemoryDiagnoser]` and a `[Params]` sweep over payload size — a copy scales with the payload, a view is flat, and that difference is visible in the `Allocated` column without needing to trust anybody's multiplier.

### Drill 22 — Precedence and parenthesization

> **Q**: What does `c is not >= 'a' and <= 'z'` mean?
>
> **A**: Not what it looks like. Precedence is **`not`, then `and`, then `or`** — three levels, and `not` binds tightest. So it parses as `c is ((not >= 'a') and <= 'z')`, which is "less than `a`, and also `<= 'z'`" — the set of characters below `'a'`. The intent, "not a lowercase letter", needs the parentheses: `c is not (>= 'a' and <= 'z')`.
>
> **Cross-Q**: Same question for `x is not string or byte[]`.
>
> **A**: It parses as `(not string) or byte[]`. Walk the cases and the bug is obvious: a `string` gives `false or false` (no match), an unsupported type gives `true or false` (match), and a **`byte[]` gives `true or true` (match)** — because a `byte[]` really is "not a string", and the first alternative has already succeeded. Used as `if (x is not string or byte[]) throw;`, it rejects one of the two types it was written to permit. Tests that only cover the first type stay green. The fix is `is not (string or byte[])`, and the durable rule is to parenthesize every `not` in a compound pattern unconditionally.
>
> **Cross-Q²**: Why can't I write `x is null or { } v`?
>
> **A**: `CS8780` — a variable may not be declared beneath a `not` or `or` pattern. The standard's reason is definite assignment: *"neither `not` nor `or` can produce a definite assignment for a pattern variable"* — on the `null` branch of that `or`, `v` would be in scope and unassigned. `and` is fine (`x is not null and { } v` binds `v`), because both sides must have matched. Two related syntax rules from the same family: `==` and `!=` are not pattern operators (`CS9344`/`CS9345` — the constant pattern *is* the equality test, and `not` is the negation), and a bare `_` can't be the whole pattern of an `is` expression or a `switch` *statement* label — write `var _` (`CS8523` is the diagnostic that names the case-label form; depending on what `_` binds to you may instead see `CS0103`/`CS0246`, or `CS8512`/`CS8513` when a constant or type named `_` is in scope) — though it can be a `switch` *expression* arm.

### Drill 23 — Patterns and conversions

> **Q**: `object o = 5; if (o is long l) { ... }`. Does it match?
>
> **A**: **No.** A declaration pattern matches on identity, derivation, interface implementation, another implicit reference conversion, `Nullable<T>` with `HasValue`, or a boxing/unboxing conversion — and the spec explicitly excludes user-defined conversions and implicit span conversions. There is no unboxing conversion from a boxed `Int32` to `Int64`. The implicit `int` → `long` widening you rely on everywhere else is a *compile-time* conversion on a value; once the value is boxed, the pattern tests the exact runtime type and nothing more. `o is 5L` fails for the same reason. This bites hardest at deserialization boundaries, where a JSON number that fits in an `Int32` comes back boxed as `int` and a `long` arm silently falls through to the discard.
>
> **Cross-Q**: What about `int? x = 7; x is int v`?
>
> **A**: That one **does** match — a `Nullable<T>` matches a type pattern `T` when `HasValue` is true, and `v` is bound to the unwrapped value. The pattern is more forgiving here than a cast. What you can't write is `x is int? v` — `CS8116: It is not legal to use nullable type in a pattern; use the underlying type instead.` And note that a `Nullable<T>` with no value boxes to a plain `null` reference, so `object o = (int?)null;` gives `o is null` → true and `o is int` → false. Consistent, once you know `Nullable<T>` never survives boxing.
>
> **Cross-Q²**: `x is double.NaN` — does it match a NaN? And `x is > double.NaN`?
>
> **A**: The first matches; the second doesn't compile. A **constant pattern** matches when `object.Equals(e, v)` returns true (except for integral/enum inputs, which use `e == v`, and `Span<char>` against a constant string, which uses `MemoryExtensions.SequenceEqual`), and `Equals` treats NaN as equal to itself — so `double.NaN => "Unknown"` is a working switch arm, even though `x == double.NaN` is always false. A **relational** pattern against NaN is `CS8782: Relational patterns may not be used for a floating-point NaN`, because every relational comparison with NaN is false and the compiler refuses to let you write an arm that can never match. Two neighbours worth knowing by number: `CS8781` (relational patterns aren't defined for this type — `s is > "a"` on a `string`; note that `o is > 5` on an `object` is *fine*, because the standard falls back to an unboxing conversion to `int`) and `CS9060` (you can't use a numeric constant or relational pattern on a `T` constrained to `INumberBase<T>`; narrow with a type pattern first).

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
- **DU shape**: `abstract record` base + sealed records + exhaustive switch ≈ discriminated union. `_ => throw` still required on C# 14; `closed` / `union` land in C# 15 (preview, .NET 11).
- **C# 14 RHS rule**: `a?.b = M()` does **not** call `M()` when `a` is null. Compound assignment ✓, `++`/`--` ✗.
- **Metadata**: `NullableAttribute` / `NullableContextAttribute`, byte `0` oblivious · `1` non-nullable · `2` nullable.
- **`<Nullable>` = 2 flags**: `disable` · `warnings` (find bugs) · `annotations` (declare intent) · `enable`.
- **Generated files** (`.g.cs`, `.designer.cs`, `<auto-generated>`) are nullable-**disabled** whatever the project says.
- **Two documented holes**: `new string[n]` and `default(MyStruct)` — non-nullable references holding null. Silent via array element / parameter / field / return; a local you wrote `= default` on still gets `CS8602`.
- **Exhaustiveness codes**: `CS8509` general · `CS8524` unnamed enum value · `CS8655` null inputs · `CS8846`/`CS8847` `when`-guarded. Runtime miss → `SwitchExpressionException`.
- **`{ }` ≠ `_`**: `{ }` means non-null; only `_` covers `null`.
- **Subpattern order is unspecified**, and `and`/`or` do **not** short-circuit. No side effects inside patterns.
- **Precedence**: `not` → `and` → `or`. `is not X or Y` means `(not X) or Y`. Parenthesize every `not`.
- **Boxing kills widening**: `object o = 5; o is long` is `false`.
- **Unconstrained `T?` on a value type is just `T`** — not `Nullable<T>`. Use `[MaybeNull]` / `[MaybeNullWhen]`.
- **Slice cost**: bare `..` is free; `.. var x` copies on `T[]` (`GetSubArray`) and `string` (`Substring`), views on `Span<T>`.
- **`?` at the boundary**: EF Core → required/optional column · MVC → implicit `[Required]` · STJ → `RespectNullableAnnotations` (.NET 9, opt-in).

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

<details>
<summary>6. A colleague deletes the `?` from `public string? MiddleName { get; set; }` on an EF Core entity, arguing it's "just a compile-time hint." Critique.</summary>

The premise is false for this specific library. Microsoft's documentation states that EF Core reads the nullable attributes and *"interprets a nullable reference as an optional value, and a non-nullable reference as a required value."* Removing the `?` therefore changes the model from optional to required, and the next `dotnet ef migrations add` will emit an `ALTER COLUMN … NOT NULL`. That migration succeeds against any database whose existing rows all have values — which is typically a freshly-seeded dev or staging database — and fails against production data containing `NULL`s, at deploy time.

Two review rules follow. First, a diff that touches a `?` on an entity type is a schema diff, and the generated migration belongs in the pull request. Second, the general principle: NRT has no runtime effect *in your process*, and that is a much narrower claim than "no runtime effect". Any library that reflects over nullability metadata — EF Core for required/optional, ASP.NET Core MVC for implicit `[Required]`, System.Text.Json when `RespectNullableAnnotations` is on — turns your annotation into behaviour.
</details>

<details>
<summary>7. Analyze: `int AsScale(string status) => status switch { "Red" => 0, "Yellow" => 5, { } => -1 };` — the parameter is non-nullable and there's a catch-all. Why does this warn?</summary>

`CS8655: The switch expression does not handle some null inputs (it is not exhaustive).` The catch-all isn't one. `{ }` is the **empty property pattern**, and a property pattern *"checks that the input value is not `null`"* — so `{ }` matches every non-null value and nothing else. The discard `_` is the real catch-all: it matches any value including `null`.

The parameter being declared `string` rather than `string?` doesn't rescue it. Non-nullability is an annotation the compiler enforces where it can see the callers; the value space of `System.String` still contains `null`, and the value can arrive from an oblivious assembly, from reflection, from a deserializer, or through a `!` in some caller. The compiler is right to insist.

The fix is `_ => -1`. Keep `{ }` for what it's genuinely good at — `if (GetThing() is { } thing)` reads better than a null check plus an assignment, and it binds a variable the analyzer treats as non-null. Just never reach for it as a default arm.
</details>

<details>
<summary>8. Trade-off: your `switch` over an enum should fail the build if someone adds a member without handling it. Discard arm or no discard arm?</summary>

They're in genuine tension and you have to pick, but the framing most people use is wrong because it assumes one warning code.

**No discard arm** gives you the compile-time check: add an enum member, get a warning, promote it to an error in CI, build fails. The cost is that an unnamed value at runtime — `(Status)7` from a bulk data fix, a legacy row, or a bad integration — throws `SwitchExpressionException`, whose message names neither the value nor the switch, so the incident starts with a useless stack trace.

**A discard arm** with `_ => throw new InvalidOperationException($"Unhandled status {s}")` gives you an excellent runtime error and destroys the compile-time check, because the switch is now exhaustive forever.

The resolution: keep the discard arm for diagnosability, and make the compile-time check come from the *warnings* rather than from the absence of an arm — which means knowing there are two codes to promote, not one. With all declared members handled you get **CS8524** (*"involving an unnamed enum value"*), not CS8509, so a `<WarningsAsErrors>CS8509</WarningsAsErrors>` that looks like it's guarding you is guarding nothing. Promote both. Add `CS8655` (null inputs) if the governing type is a reference type.
</details>

<details>
<summary>9. A parser does `if (payload is [0x02, .. var body, 0x03]) Process(body);` over a `byte[]`, once per message, at high throughput. What's the problem and what's the one-line fix?</summary>

`.. var body` is a **slice with a subpattern**, which requires the type to be sliceable and lowers to a `Range` access. Arrays have no `Range` indexer and no `Slice` method, so the compiler special-cases them: the standard says *"for `string`s and arrays, `string.Substring` and `RuntimeHelpers.GetSubArray`, respectively, shall be used."* `GetSubArray` **allocates a new array** and copies. So this parser allocates a full copy of every payload, purely to give it a name, once per message — which shows up in a memory profile as `byte[]` dominating gen-0 with no obvious allocation site in the parser code.

The one-line fix is to change the parameter type to `ReadOnlySpan<byte>`. The pattern text doesn't change at all; a span meets the sliceable requirement with `Slice(int, int)`, which returns a span over the same memory, so the slice becomes a view over the original buffer.

Worth also knowing what *isn't* the problem: a bare `..` costs nothing. `payload is [0x02, .., 0x03]` needs only countability and indexability, makes no slice, and allocates nothing — the standard describes it as *"a proper discard; that is, no tests shall be made for such pattern."* The three characters `var body` are the entire cost.
</details>

<details>
<summary>10. Apply: a helper `static bool IsValidId(string? s)` is used in ~150 methods, each of which then dereferences `s` and warns. Two engineers propose `s!` at every call site vs. one attribute. Argue it out.</summary>

The attribute wins, and the reason is not brevity.

`[NotNullWhen(true)] string? s` on the helper's parameter is a single change that removes all 150 warnings, because it tells the compiler the one thing it cannot work out for itself — the docs are explicit that *"the analysis doesn't trace into the bodies of methods"*, no matter how obviously the body is a null check.

150 `!`s remove the same 150 warnings and look equivalent on the day of the change. They differ afterwards. Each `!` is a permanent, unconditional suppression at that expression: it will keep suppressing when the surrounding code is refactored, when the guard is moved, when someone checks `IsValidId(a)` and dereferences `b`. The attribute is conditional — it only narrows on the `true` branch of an actual call — so those mistakes surface as fresh warnings. In practice, replacing a wall of suppressions with one attribute reliably *uncovers* real bugs that the suppressions were hiding, which is the strongest argument available: the two options aren't equally safe, they're opposite in kind.

The reviewable heuristic to take away: **when the same `!` appears at more than a handful of call sites, the defect is in a signature, not at the call sites.** A `!` should be rare enough that each one can carry a comment explaining why the analyzer is wrong.
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

**Added in this pass** — the specific pages backing the claims above:

- C# standard — [Patterns and pattern matching (§11)](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/language-specification/patterns). Source for: unspecified subpattern evaluation order (§11.2.1, §11.2.5, §11.2.6); `and`/`or` are not short-circuiting (§11.2.10); constant patterns use `object.Equals` (§11.2.3); list-pattern countable/indexable and slice-pattern sliceable requirements plus the `GetSubArray` / `Substring` special-case (§11.2.11, §11.2.12).
- Microsoft Learn — [Nullable reference types (language reference)](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/builtin-types/nullable-reference-types). Source for: the four nullable contexts and their table; the nine pragma combinations; the generated-code exemption; the generic `T?` resolution rules and constraint table; the EF Core reflection caveat.
- Microsoft Learn — [Nullable reference types (fundamentals) — "Known pitfalls"](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/null-safety/nullable-reference-types#known-pitfalls). Source for: default structs and arrays as the two documented holes; "the analysis doesn't trace into the bodies of methods."
- Microsoft Learn — [Nullable static analysis attributes](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/attributes/nullable-analysis). Source for: the eleven-attribute table, the `AllowNull`/`DisallowNull` property examples, `MemberNotNull`, `DoesNotReturnIf`.
- Microsoft Learn — [Nullable reference type warnings](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/compiler-messages/nullable-warnings) and [pattern matching warnings](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/compiler-messages/pattern-matching-warnings). Source for every `CS####` in this file, including CS8509 / CS8524 / CS8655 / CS8846 and the `{ }`-vs-`_` example.
- Microsoft Learn — [`switch` expression](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/switch-expression). Source for: `System.Runtime.CompilerServices.SwitchExpressionException` (.NET Core 3.0+) vs `InvalidOperationException` (.NET Framework); arms evaluated in text order; list patterns exempt from exhaustiveness warnings.
- C# 14 feature specification — [Null conditional assignment](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/proposals/csharp-14.0/null-conditional-assignment). Source for: "the right side of the assignment is only evaluated when the receiver of the conditional access is non-null", compound assignment allowed, increment/decrement and ref-assignment not.
- dotnet/runtime — [`Debug.cs`](https://github.com/dotnet/runtime/blob/main/src/libraries/System.Private.CoreLib/src/System/Diagnostics/Debug.cs). Source for `Debug.Assert([DoesNotReturnIf(false)] bool condition)` under `[Conditional("DEBUG")]`.
- Microsoft Learn — [`JsonSerializerOptions.RespectNullableAnnotations`](https://learn.microsoft.com/en-us/dotnet/api/system.text.json.jsonserializeroptions.respectnullableannotations) (.NET 9+) and [`MvcOptions.SuppressImplicitRequiredAttributeForNonNullableReferenceTypes`](https://learn.microsoft.com/en-us/dotnet/api/microsoft.aspnetcore.mvc.mvcoptions.suppressimplicitrequiredattributefornonnullablereferencetypes).
- Microsoft Learn — [C# version history](https://learn.microsoft.com/en-us/dotnet/csharp/whats-new/csharp-version-history) and [What's new in C# 14](https://learn.microsoft.com/en-us/dotnet/csharp/whats-new/csharp-14). Source for version gating: C# 14 released November 2025 with .NET 10; `closed` hierarchies and `union` types are documented as C# 15, in preview with .NET 11.

</details>
<!-- nav-footer-start -->

---

[← Previous: LINQ — Language Deep Dive](06-linq-language-deep-dive.md) · [↑ Back to top](#nullability--pattern-matching) · [Next: Reflection, Attributes & Source Generators →](08-reflection-attributes-and-source-gen.md)

<!-- nav-footer-end -->
