# C# Fundamentals

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Statements vs expressions](#statements-vs-expressions)
  - [Primitive types and literals](#primitive-types-and-literals)
  - [`decimal` vs `double` vs `float` — picking the right real number](#decimal-vs-double-vs-float--picking-the-right-real-number)
  - [Variables, scope, and definite assignment](#variables-scope-and-definite-assignment)
  - [Scope, captures, and closures — when a local outlives its block](#scope-captures-and-closures--when-a-local-outlives-its-block)
  - [`const` vs `static readonly` — the value baked into the caller](#const-vs-static-readonly--the-value-baked-into-the-caller)
  - [Operators](#operators)
  - [`checked` / `unchecked` and integer overflow](#checked--unchecked-and-integer-overflow)
  - [Conversions — implicit, explicit, and the ones that lose data](#conversions--implicit-explicit-and-the-ones-that-lose-data)
  - [Parsing and formatting — the culture that changes under you](#parsing-and-formatting--the-culture-that-changes-under-you)
  - [Control flow](#control-flow)
  - [Methods and parameters](#methods-and-parameters)
  - [`ref` / `out` / `in` — parameter semantics at the IL level](#ref--out--in--parameter-semantics-at-the-il-level)
  - [`params` arrays and collection-expression parameters (C# 12+)](#params-arrays-and-collection-expression-parameters-c-12)
  - [Strings — the surprisingly deep type](#strings--the-surprisingly-deep-type)
  - [Text is code units, not characters — surrogate pairs, `Rune`, and comparison](#text-is-code-units-not-characters--surrogate-pairs-rune-and-comparison)
  - [String interning and reference identity](#string-interning-and-reference-identity)
  - [`nameof` and `typeof` — compile-time strings vs runtime type tokens](#nameof-and-typeof--compile-time-strings-vs-runtime-type-tokens)
  - [Namespaces and `using` directives](#namespaces-and-using-directives)
  - [Top-level statements](#top-level-statements)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--silent-int-overflow-in-billing)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

This is the "skip if you've shipped C# for two years" file — but read it anyway, because it nails down the *exact* semantics that the rest of the sub-chapter assumes. Things like definite-assignment rules, integer overflow behavior, what `params` actually generates, and why `Console.WriteLine($"{x}")` doesn't allocate the way you'd think — these are foundational, and senior interviewers ask about them precisely because they reveal whether the candidate knows the language or just the framework.

Everything beyond this file (type system, generics, LINQ, memory) builds on the vocabulary cemented here. Faster to spend 15 minutes pinning it down than to discover later that you've been hand-waving over `default(T)` semantics.

## Core concepts

### Statements vs expressions

C# is a **statement-based** language with **expression-bodied** sugar layered on top. The distinction matters when reading modern C# — most of the terseness comes from expressions, not statements.

- A **statement** *does* something (assignment, branching, looping). Ends with `;`.
- An **expression** *computes* a value. No `;` of its own; embedded inside statements.

```csharp
// Statement
int x = 5;

// Expression: 'a + b * 2' produces a value, embedded inside the statement
int y = a + b * 2;

// Statement-bodied method
public int Square(int n) { return n * n; }

// Expression-bodied method (sugar over single-return)
public int Square(int n) => n * n;

// Expression-bodied property (since C# 6)
public string FullName => $"{First} {Last}";

// Expression-bodied constructor (since C# 7)
public Point(int x, int y) => (X, Y) = (x, y);
```

`switch` and `throw` exist in both forms (statement and expression) — modern code prefers the expression forms for terseness:

```csharp
// switch expression (C# 8+)
string Describe(int n) => n switch
{
    < 0 => "negative",
    0   => "zero",
    > 0 => "positive"
};

// throw expression (C# 7+)
public string Name
{
    get => _name ?? throw new InvalidOperationException("Name not set");
    set => _name = value ?? throw new ArgumentNullException(nameof(value));
}
```

### Primitive types and literals

C# has **15 built-in types** that map directly to CLR types in `System`. The shorthand keyword and the full type are interchangeable; `int` and `System.Int32` are literally the same type.

| Keyword | CLR type | Size | Range / notes |
|---|---|---|---|
| `bool` | `System.Boolean` | 1 byte | `true` / `false` |
| `byte` | `System.Byte` | 1 byte | 0 – 255 (unsigned) |
| `sbyte` | `System.SByte` | 1 byte | -128 – 127 |
| `short` | `System.Int16` | 2 bytes | ~ ±32k |
| `ushort` | `System.UInt16` | 2 bytes | 0 – 65k |
| `int` | `System.Int32` | 4 bytes | ~ ±2.1B (default integer literal) |
| `uint` | `System.UInt32` | 4 bytes | 0 – 4.3B |
| `long` | `System.Int64` | 8 bytes | ~ ±9.2 × 10¹⁸ |
| `ulong` | `System.UInt64` | 8 bytes | 0 – 1.8 × 10¹⁹ |
| `float` | `System.Single` | 4 bytes | IEEE-754 single-precision |
| `double` | `System.Double` | 8 bytes | IEEE-754 double-precision (default real literal) |
| `decimal` | `System.Decimal` | 16 bytes | Base-10 fixed-point — for money |
| `char` | `System.Char` | 2 bytes | UTF-16 code unit |
| `string` | `System.String` | reference | immutable UTF-16 sequence |
| `object` | `System.Object` | reference | root of all types |

Three more keywords belong on that list even though they aren't fixed-size: `nint` and `nuint` — pointer-sized integers, introduced in C# 9 and, since C# 11, plain aliases for `System.IntPtr` / `System.UIntPtr` — and `dynamic`, which is `System.Object` plus a compiler instruction to defer binding to the DLR.

**Numeric literal suffixes:** untyped numeric literals default to `int` (integers) and `double` (real). Use suffixes when you need a different type:

```csharp
var a = 5;          // int
var b = 5L;         // long
var c = 5U;         // uint
var d = 5UL;        // ulong
var e = 5.0;        // double
var f = 5.0f;       // float
var g = 5.0m;       // decimal — always use 'm' for money
var h = 0x1F;       // hex int (31)
var i = 0b1010;     // binary int (10)
var j = 1_000_000;  // digit separators — between digits, never leading or trailing
var k = 0x_FF_FF;   // C# 7.2+: a separator may also follow the 0x / 0b prefix
```

**Decimal vs double for money:** `decimal` is base-10, `double` is base-2. `0.1 + 0.2 == 0.3` is `false` in `double` but `true` in `decimal`. Always `decimal` for currency, never `double`. The next section walks through why.

> 🌍 **In the real world**: a device-telemetry ingest service stored a sensor reading as `int milliVolts` because that was the wire format, then computed `long microVolts = milliVolts * 1000` for the analytics table. It worked for two years on 3.3 V hardware. A new industrial sensor reported readings above 2,147,483 millivolts — `int.MaxValue / 1000` — and the column started showing negative microvolts — `int` multiplication wrapping, silently, exactly as the language specifies. The literal `1000` was the tell: an untyped integer literal is `int`, so the whole expression is evaluated in 32-bit space and only *then* widened to whatever the target is. The fix was one character, `1000L`, plus a lint rule banning bare integer multiplication on any column named `*_raw`.

**`var` is not dynamic.** `var` is *implicit static typing* — the compiler infers the type at compile time. Once inferred, it's locked in. `var x = 5;` is identical to `int x = 5;`. If you want runtime typing (which you almost never do), that's `dynamic`.

### `decimal` vs `double` vs `float` — picking the right real number

The three real-number types in C# look interchangeable in toy code. They are not. Choosing wrong silently corrupts financial reports, breaks tax math by a cent per million transactions, and burns afternoons on "why is the total off by 0.00000000000004?"

**The fundamental split: base-2 vs base-10.**

```
┌──────────────────────────────────────────────────────────────────────┐
│  float   (System.Single)   4 bytes   IEEE-754 binary32               │
│  double  (System.Double)   8 bytes   IEEE-754 binary64               │
│  decimal (System.Decimal) 16 bytes   96-bit integer + sign + scale   │
│                                      (Microsoft format, NOT IEEE-754)│
└──────────────────────────────────────────────────────────────────────┘
```

`float` and `double` are **binary** floating point — they store numbers as `mantissa × 2^exponent`. Most "nice" decimal fractions (`0.1`, `0.2`, `0.3`) **cannot be represented exactly** in binary, the same way `1/3` cannot be represented exactly in base-10 (`0.333...`).

`decimal` is **not** IEEE-754 decimal128, a confusion worth killing before an interviewer does it for you. Microsoft Learn describes the layout precisely: 128 bits made of a **96-bit integer**, a sign, and a **scaling factor — a power of ten from 0 to 28**. So the value is `±(96-bit integer) / 10^scale`. Every base-10 fraction a human writes down inside 28–29 significant digits is representable exactly; anything needing a 29th digit, or a non-terminating base-10 expansion, is not:

```csharp
decimal third = 1 / 3.0m;
Console.WriteLine(third * 3 == 1.0m);   // False
Console.WriteLine(third * 3);           // 0.9999999999999999999999999999
```

`decimal` buys you *exact representation of the numbers people write down*, not exact arithmetic. Division still rounds. That distinction is what separates a candidate who has read the type from one who has repeated the slogan.

**The scale is part of the value.** `decimal` preserves trailing zeros, because the scale is stored rather than normalised away:

```csharp
decimal a = 1.0m, b = 1.00m;
Console.WriteLine(a == b);                       // True  — arithmetic ignores the scale
Console.WriteLine(a.GetHashCode() == b.GetHashCode());  // True
Console.WriteLine($"'{a}' vs '{b}'");            // '1.0' vs '1.00'  — ToString does not
```

Equality and hashing agree; string formatting does not. Anything that round-trips a `decimal` through text — a cache key, an idempotency fingerprint, a signed request body, a JSON diff — can therefore see two "equal" amounts as different. Normalise deliberately at the boundary rather than hoping every producer used the same scale — and note that rounding is *not* the tool for this: `decimal.Round` only ever reduces scale, so `decimal.Round(1.0m, 2)` is still `1.0` and formats as `"1.0"` while `1.00m` formats as `"1.00"`. What fixes it is an explicit format string, `x.ToString("F2", CultureInfo.InvariantCulture)`, which pins the digit count regardless of the incoming scale.

**The canonical demo every interviewer expects:**

```csharp
double a = 0.1, b = 0.2;
Console.WriteLine(a + b);             // 0.30000000000000004
Console.WriteLine(a + b == 0.3);      // False

decimal c = 0.1m, d = 0.2m;
Console.WriteLine(c + d);             // 0.3
Console.WriteLine(c + d == 0.3m);     // True
```

The `double` result is *not a bug* — it's the closest binary representation of 0.3 differing from `0.1 + 0.2` (also each "the closest binary"). Two things follow, and only the second one is the reason to care. First, the per-operation error is tiny and *bounded*; nobody loses a fortune to one rounding. Second, and fatally, the error is **not reproducible across different orders of operation** — summing a batch of `double` line items in a different order can produce a different total, so the invoice, the ledger and the reconciliation job disagree by a fraction of a cent and no two of them can be made to agree by rounding. Auditors do not care how small the discrepancy is; they care that it exists.

**Comparison matrix:**

| | `float` | `double` | `decimal` |
|---|---|---|---|
| Size | 4 bytes | 8 bytes | 16 bytes |
| Precision | ~7 decimal digits | ~15-17 decimal digits | 28-29 decimal digits |
| Range | ±3.4 × 10³⁸ | ±1.7 × 10³⁰⁸ | ±7.9 × 10²⁸ |
| Exact `0.1` | ✗ | ✗ | ✓ |
| Hardware-accelerated | ✓ FPU/SIMD instructions | ✓ FPU/SIMD instructions | ✗ software routines over the integer unit |
| Overflow behaviour | `Infinity`, never throws | `Infinity`, never throws | `OverflowException` |
| Default literal suffix | `f` (required) | (none) | `m` (required) |
| Use for | Graphics, ML, sensors | Scientific, statistics | Money, percentages, anything counted in base-10 |

On speed, prefer the mechanism to a multiplier: `double` addition is a single CPU instruction and vectorises across a SIMD register; `decimal` addition is a call into a software routine that has to align two scales before it can add two 96-bit integers, and it is twice the width in memory and cache. That is a real and large gap in a numerical inner loop, and invisible next to a single database round-trip in a business app. Measure your own case with BenchmarkDotNet before quoting a number to anyone.

> 🌍 **In the real world**: an insurance quoting engine held premiums in `double` because the actuarial library it wrapped was `double`-based, and rounded to two places only at the very end. Quotes matched the finance system to the cent for years. Then a "split the premium across instalments" feature landed, and support started getting tickets where twelve instalments summed to one cent more or less than the annual premium — but only for some policies. The engine was rounding each instalment independently from a `double` that was already a hair off. The fix was structural rather than clever: keep `decimal` end to end for anything that will be *charged*, keep `double` for the actuarial model that *predicts*, and convert once at the boundary with an explicit, documented rounding rule. The reusable lesson: the bug is almost never a wrong-looking number on screen, it is two systems that each rounded correctly and now disagree.

**Decision rules:**

- **Money, ever?** → `decimal`. Non-negotiable. If a financial auditor would ask "did the math reconcile to the cent?", use `decimal`.
- **Physics / graphics / ML / signal processing?** → `double`. Speed dominates, the underlying domain is continuous, rounding errors are part of the model.
- **Memory-constrained sensor / shader data?** → `float`. Only if you've measured that the smaller size wins (cache hits, vectorization width).
- **Default for "a number with decimals"?** → `double` — it's the unsuffixed literal type. But the moment that number represents *currency*, *tax*, *interest*, *commission*, or *anything an accountant tracks*, switch to `decimal`.

**Common pitfalls:**

1. **Storing money as `double` "because it's faster"** — the speed advantage doesn't help when QA reports drift on the year-end statement. `decimal` for money is the engineering equivalent of brushing your teeth: non-optional. Watch for it leaking in sideways too: a `double` column in the reporting database, a JSON number deserialised into `double` because the DTO used `object`, an Excel export.
2. **Mixing `decimal` and `double` arithmetic** — there's no implicit conversion (compile error). Forces you to pick a side; that's a feature, not a bug.
3. **`double.NaN == double.NaN` is `false`.** IEEE-754 says NaN is unordered. Use `double.IsNaN(x)`.
4. **Forgetting the `m` suffix:** `decimal d = 0.1;` won't compile — `0.1` is `double`, no implicit conversion. Write `0.1m`.
5. **`float`-as-currency in legacy systems** — when migrating, the cleanest path is decimal-typed APIs at the boundary, with documented rounding rules at the conversion point.

### Variables, scope, and definite assignment

C# enforces **definite assignment**: a local variable must be assigned before it's read. This is a compile-time check, not runtime.

```csharp
int x;
Console.WriteLine(x);  // ❌ CS0165: Use of unassigned local variable 'x'

int y;
y = 5;
Console.WriteLine(y);  // ✓
```

Fields (class members) get **default values** automatically: `0` / `false` / `null` / `default(T)`. Only locals require explicit assignment.

**Scope** in C#:
- **Block scope** — `{ ... }`. A variable declared inside a block is invisible outside it.
- **Method scope** — parameters and locals.
- **Class scope** — fields and members.

The precise rule is worth knowing because "C# has no hoisting" is a half-truth that falls apart under one cross-question. **The scope of a local is the entire enclosing block**, including the lines above its declaration — exactly like JavaScript's `let`, and unlike `var`. What C# forbids is *using* the name before the declaration point. So the name is reserved the whole way down, and touching it early is an error rather than a silent read of something else:

```csharp
class Report
{
    int total = 1;

    void Print()
    {
        Console.WriteLine(total);  // ❌ CS0844: cannot use local variable 'total' before it is
                                   //    declared. The declaration of the local variable hides
                                   //    the field 'Report.total'.
        int total = 2;             // ← this declaration governs the whole method body
    }
}
```

Without a same-named field in play the error is `CS0841` instead, but the principle is identical: the block owns the name from its first line. And two locals with the same name in *nested* scopes is a separate error, `CS0136`, unlike C++ where the inner one silently shadows:

```csharp
void Demo()
{
    int x = 1;
    if (true)
    {
        int x = 2;  // ❌ CS0136: a local or parameter named 'x' cannot be declared in this scope...
    }
}
```

**Scope and definite assignment are two different rules**, and mixing them up is a reliable interview stumble. Pattern variables and `out var` declarations *escape* into the enclosing scope — but whether they are readable there depends on flow analysis:

```csharp
if (o is not string s) return;
Console.WriteLine(s.Length);       // ✓ in scope AND definitely assigned on this path

if (o is string t) { }
Console.WriteLine(t.Length);       // ❌ CS0165: use of unassigned local 't'
                                   //    — 't' IS in scope; it is simply not proven assigned
```

Note the error code: `CS0165` (unassigned), not `CS0103` (does not exist). The variable is visible; the compiler just cannot prove a value reached it. This is why the `is not ... return` guard shape reads so cleanly and the `if (x is T y) { }` shape does not.

> 🌍 **In the real world**: a code review flagged `if (!dict.TryGetValue(key, out var cached)) { cached = Load(key); }` as "confusing scope" and the author rewrote it as `dict.TryGetValue(key, out var cached); if (cached is null) cached = Load(key);` — which compiles, because `out` guarantees assignment regardless of the return value, and which quietly changed the semantics for a cache that legitimately stored nulls. The first form asks "was there an entry?"; the second asks "is the value null?". They differ exactly when a null was cached deliberately, which was the negative-caching case the service had added the month before. The reviewable rule that came out of it: never discard the `bool` from a `Try*` method — it is answering a different question from the `out` value.

### Scope, captures, and closures — when a local outlives its block

Everything above assumed a local dies when its block ends. A lambda, a local function, or an `async` method body can break that assumption: if the code inside refers to a local from the enclosing scope, the compiler **captures** it, and the variable's lifetime stretches to match the delegate's.

**The mechanism.** The compiler rewrites the method. Captured locals stop being stack slots and become fields of a generated class — a *display class* — allocated on the heap. Every reference to the variable, inside the lambda *and* in the original method body, is rewritten to touch that field. There is exactly one field, so both sides see the same storage. Understanding that single fact predicts every closure behaviour below.

```csharp
// What you write
void Register(int id)
{
    _handlers.Add(() => Console.WriteLine(id));
}

// Roughly what the compiler emits
sealed class <>c__DisplayClass0 { public int id; public void Body() => Console.WriteLine(id); }

void Register(int id)
{
    var c = new <>c__DisplayClass0();   // heap allocation
    c.id = id;                          // the parameter is copied into the field...
    _handlers.Add(c.Body);              // ...and the delegate points at the field, not the stack
}
```

**The loop-variable trap, and why `for` and `foreach` differ.** A `for` loop declares its variable *once*, so every lambda created inside the loop captures the same field and all of them observe the final value. A `foreach` iteration variable is a **fresh variable per iteration** (changed in C# 5 precisely because the old behaviour was a permanent bug factory), so each lambda gets its own display class:

```csharp
var fromFor = new List<Func<int>>();
for (int i = 0; i < 3; i++) fromFor.Add(() => i);
Console.WriteLine(string.Join(",", fromFor.Select(f => f())));      // 3,3,3

var fromForeach = new List<Func<int>>();
foreach (var i in new[] { 0, 1, 2 }) fromForeach.Add(() => i);
Console.WriteLine(string.Join(",", fromForeach.Select(f => f())));  // 0,1,2
```

The fix for the `for` case is one line — copy into a per-iteration local, which forces a per-iteration display class:

```csharp
for (int i = 0; i < 3; i++)
{
    int captured = i;              // new variable each iteration
    fromFor.Add(() => captured);   // 0,1,2
}
```

**Proving you did not capture.** Two modifiers turn accidental capture into a compile error rather than a production incident:

- `static` lambdas (C# 9): `static () => DoWork()` — cannot reference any enclosing local, parameter or `this`.
- `static` local functions (C# 8): same guarantee, and a non-capturing local function needs no display class at all.

**Capturing `this` by accident.** Referring to any instance field or method inside a lambda captures `this`, which keeps the *whole object* alive for as long as the delegate does. That is the standard mechanism behind "my scoped service is still in memory an hour later": an event handler or a cached `Func<>` rooted an object graph nobody meant to keep.

> 🌍 **In the real world**: a background worker fanned out per-tenant refresh jobs with `for (int i = 0; i < tenants.Count; i++) tasks.Add(Task.Run(() => Refresh(tenants[i])));`. In development, with three tenants and a fast loop, it usually refreshed tenant 0, 1 and 2 — because the tasks happened to start before the loop advanced. In production it refreshed the *last* tenant three times and threw `ArgumentOutOfRangeException` on the run where the loop finished first, since `i` had reached `Count`. Two symptoms, one cause, and neither reproduced under a debugger. The rewrite was `foreach (var tenant in tenants) tasks.Add(Task.Run(() => Refresh(tenant)));` — correct because the `foreach` variable is per-iteration — plus a review rule that any lambda handed to `Task.Run` inside a loop must capture a loop-local, never an index.

> 🌍 **In the real world**: an ASP.NET Core service registered a cache-invalidation callback in a singleton from inside a scoped handler: `_bus.Subscribe(() => _dbContext.Reload())`. The lambda captured `this`, `this` held the scoped `DbContext`, and the singleton held the lambda forever. Memory climbed one `DbContext` per request and the eventual crash was `ObjectDisposedException` from a captured context, not `OutOfMemoryException`, which sent the investigation down the wrong path for a day. The mechanical fix was to capture nothing scoped: the callback closes over the singleton `IServiceScopeFactory` instead, and resolves a fresh `DbContext` from a new scope each time it fires. The general rule: a delegate stored somewhere longer-lived than the object that created it must not capture that object.

Allocation counting for closures — how many display classes, and when they can be avoided entirely — is covered in [Memory & Performance](./09-memory-and-performance.md#boxing-checklist--when-value-types-secretly-allocate).

### `const` vs `static readonly` — the value baked into the caller

Both look like "a named constant". They differ in *when* the value is read, and that difference crosses assembly boundaries, which makes it a versioning question rather than a style question.

| | `const` | `static readonly` |
|---|---|---|
| Evaluated | Compile time | Run time (static constructor / field initialiser) |
| Stored as | A literal in the consuming IL | A field read on each access |
| Allowed types | Numbers, `bool`, `char`, `string`, enums, `null` | Any type |
| Value can depend on | Other constants only | Anything — config, `DateTime.Now`, DI |
| Usable in `case` labels, attributes, default parameter values, pattern constants | ✓ | ✗ |
| Changing the value in a library | Requires **recompiling every consumer** | Consumers pick it up on the next assembly load |

The versioning consequence is the whole point, and Microsoft Learn states it plainly in the `const` reference: *"because compilers propagate constants, other code compiled with your libraries needs to be recompiled to see the changes."* The consuming assembly does not call back into yours to ask for the value — it copied the literal at *its* compile time.

```csharp
// In Acme.Shared.dll
public static class Limits
{
    public const int MaxPageSize = 100;              // literal is copied into every caller
    public static readonly int MaxUploadMb = 25;     // callers read the field at run time
}

// In Acme.Api.dll, compiled against v1.0 of Acme.Shared
if (size > Limits.MaxPageSize) { }   // IL contains: ldc.i4.s 100
if (mb > Limits.MaxUploadMb) { }     // IL contains: ldsfld Acme.Shared.Limits::MaxUploadMb
```

Ship `Acme.Shared` v1.1 with `MaxPageSize = 500` and drop the DLL next to an un-recompiled `Acme.Api`: the API still enforces 100, while the library's own code enforces 500. Two limits, one name, no error message.

`const decimal` is a special case worth knowing: `decimal` is not an IL literal type, so the compiler stores the value in a `DecimalConstantAttribute` on the field and reconstructs it. It still behaves as a compile-time constant for C#'s purposes, which is why `const decimal` is legal but `const DateTime` is not.

**Senior rule of thumb:** `const` for values that are true by definition and can never change — `Math.PI`-shaped things, protocol magic numbers, `"application/json"`. `static readonly` for every tunable, limit, timeout, or version string in a package other teams consume.

> 🌍 **In the real world**: a shared `Common.Constants.ApiVersion = "v2"` was declared `const` and referenced by six services to build outbound URLs. The platform team shipped `v3`, bumped the constant, republished the NuGet package, and redeployed the two services that had a code change that sprint. The other four had only their package reference updated by the automated dependency bot — which updates the reference but does not, on its own, produce a rebuilt binary in every pipeline — and one of them was deployed from a cached build artefact. It kept calling `/v2` for three weeks until the endpoint was retired. Nothing about the incident was visible in a diff: the source said `v3` everywhere. The postmortem action was mechanical rather than procedural — `public const string` was banned from the shared package in favour of `static readonly`, so that the value lives in exactly one binary.

### Operators

C# operators behave mostly like other curly-brace languages, but a few have surprises.

**Integer division truncates toward zero:** `7 / 2 == 3`, `-7 / 2 == -3`. To get a real number, cast: `7.0 / 2 == 3.5`.

**Integer overflow is silent by default.** `int.MaxValue + 1 == int.MinValue`. Use `checked` to throw on overflow — covered in depth in [its own section below](#checked--unchecked-and-integer-overflow).

```csharp
int max = int.MaxValue;
int wrapped = max + 1;             // -2147483648 (silent wrap)
int crash = checked(max + 1);      // throws OverflowException

// Project-wide via <CheckForOverflowUnderflow>true</CheckForOverflowUnderflow> in .csproj
```

**Null-related operators (modern C#):**
- `?.` — null-conditional access. `x?.Y` is `null` if `x` is `null`, else `x.Y`.
- `??` — null-coalescing. `a ?? b` returns `a` if non-null, else `b`.
- `??=` — null-coalescing assignment. `a ??= b` assigns `b` to `a` if `a` is null.
- `!` — null-forgiving (post-fix). Tells the compiler "I know this is non-null." No runtime effect; suppresses NRT warnings.

```csharp
// Chaining null-conditional
string? city = order?.Customer?.Address?.City;  // any null in the chain → null

// Coalescing
string display = name ?? "(unknown)";

// Coalescing assignment
_cache ??= LoadFromDisk();
```

**Bit operators:** `&` `|` `^` `~` `<<` `>>` (and `>>>` for unsigned shift, C# 11). Often used for flag enums; rarely otherwise.

**Two arithmetic edge cases interviewers like.** Integer division by zero always throws `DivideByZeroException` — and one *non*-zero division throws as well, with a different exception, even in an `unchecked` context:

```csharp
int a = int.MinValue, b = -1;
int c = a / b;        // throws OverflowException — |int.MinValue| is not representable as an int
```

There is no positive counterpart to `int.MinValue` in two's complement, so the result cannot exist and the runtime throws rather than wrapping. `unchecked` does not suppress it. The second case: unary minus on a `uint` promotes to `long`, because the negation has to be representable somewhere:

```csharp
uint u = 5;
var n = -u;                       // n is long, value -5
Console.WriteLine(n.GetType());   // System.Int64
```

### `checked` / `unchecked` and integer overflow

C# integer arithmetic is **silently wrapping by default**. `int.MaxValue + 1 == int.MinValue`, not an exception. This was a perf decision in 2000: arithmetic without overflow detection is one IL instruction; arithmetic with detection is several. For an InfoSec or financial app, that perf choice is the *wrong default* — and the language gives you two knobs to flip it.

**Three scopes:**

```csharp
// 1. Expression-level checked / unchecked
int wrapped   = unchecked(int.MaxValue + 1);   // -2147483648, no exception (default behavior)
int explosive = checked(int.MaxValue + 1);     // throws OverflowException

// 2. Block-level checked { } / unchecked { }
checked
{
    int a = ReadInt();
    int b = ReadInt();
    int sum = a + b;                            // any overflow in this block throws
    int product = a * b;
}

// 3. Project-level via .csproj
// <PropertyGroup>
//   <CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>
// </PropertyGroup>
// Flips the default from 'unchecked' to 'checked' for the whole assembly.
```

**The IL difference (why it matters):**

| Source | IL opcode | Behavior on overflow |
|---|---|---|
| `a + b` (default) | `add` | Silent wrap |
| `checked(a + b)` | `add.ovf` | Throws `OverflowException` |
| `(uint)a + b` (default) | `add` | Silent wrap |
| `checked((uint)a + b)` | `add.ovf.un` | Throws (`.un` = unsigned overflow check) |

`add.ovf` costs an extra check of the CPU's overflow flag and a conditional branch to the throw helper, and it blocks some JIT optimisations (the operation can now throw, so it can't be freely reordered or vectorised). Whether that is measurable depends entirely on the loop; for ordinary business code it is noise, for a numeric kernel it is not. Measure the specific loop rather than carrying a multiplier around in your head.

**What overflows silently in production code:**

```csharp
// Classic: int multiplication for "size in bytes" or "milliseconds"
int seconds = 3600 * 24 * 365;                       // 31_536_000 — fine
int secondsPer10Years = 3600 * 24 * 365 * 10;        // overflows? Let's check: 315_360_000 — fine
int secondsPer100Years = 3600 * 24 * 365 * 100;      // 3_153_600_000 — overflows int.MaxValue (2.147B), wraps to negative

// The fix: widen at least one operand to long BEFORE multiplying
long ok = 3600L * 24 * 365 * 100;                    // multiplication happens in long space, no overflow

// Classic billing bug: int.MaxValue rupees vs cents
int rupees = 22_000_000;
int paise  = rupees * 100;                            // 2_200_000_000 — overflows int.MaxValue (2.147B)
long paiseOk = (long)rupees * 100;                    // ✓
```

**What `checked`/`unchecked` do NOT catch:**
- Floating-point overflow → produces `Infinity`/`-Infinity`, never throws.
- `decimal` overflow → already throws `OverflowException` by default (no `checked` needed).
- Lossy narrowing conversions (`long → int`) → these are *only* checked under `checked` context. Under default `unchecked`, `(int)long.MaxValue == -1` silently.

**Per-project recommendation for senior teams:**

```xml
<PropertyGroup>
  <CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>
</PropertyGroup>
```

Default-on overflow checking in `Debug` and `Release` for any project handling money, IDs, sizes, time durations, or cryptographic counters. Annotate the rare hot loops where wrap is *intentional* (hash mixing, CRCs) with `unchecked { }`. The cost is a small, measurable perf hit in arithmetic-heavy code; the benefit is loud failures instead of silent corruption.

> 🌍 **In the real world**: a warehouse system computed available stock as `onHand - reserved`, both `int`, both non-negative by every invariant the team believed in. A bug in a concurrent reservation path let `reserved` exceed `onHand`, the subtraction went negative, and the negative value was then cast to a `uint` for a message contract — where it became roughly four billion units of available stock. Downstream, the replenishment service dutifully cancelled every purchase order. Turning on `<CheckForOverflowUnderflow>` would not have caught the subtraction (it does not overflow — `int` holds negatives fine); it *would* have caught the `uint` cast, which is a checked-context conversion. That is the useful distinction to carry into an interview: the project flag turns silent narrowing conversions into exceptions, and narrowing conversions are where most of the real damage happens.

### Conversions — implicit, explicit, and the ones that lose data

Every conversion in C# answers two questions: **does the compiler allow it silently**, and **what happens when the value doesn't fit**. Most engineers know the first and assume the second follows from it. It doesn't, and that gap is where the bugs live.

**The rule that surprises people: implicit does not mean lossless.** C# allows an implicit conversion when there is no loss of *magnitude* — the number stays in the right ballpark. Precision is a separate promise, and Microsoft Learn is explicit that it is not made: the implicit conversions from `int`, `uint`, `long`, `ulong`, `nint` or `nuint` to `float`, and from `long`, `ulong`, `nint` or `nuint` to `double`, "can cause a loss of precision, but never a loss of an order of magnitude."

```csharp
int  i = 16_777_217;   // 2^24 + 1
float f = i;           // implicit — no cast, no warning
Console.WriteLine(f);        // 16777216
Console.WriteLine(i == (int)f);  // False — a digit vanished with the compiler's blessing
```

`float` has 24 bits of significand, so it runs out of consecutive integers at 2²⁴. The compiler is content because 16,777,216 is the right order of magnitude. An `int` identity column widened to `float` for a chart axis, or a `long` timestamp implicitly converted to `double` for a JSON number, loses digits exactly this way — silently, with no cast to grep for.

**Numeric promotion: the small integer types barely have operators.** `sbyte`, `byte`, `short`, `ushort` and `char` define only `++` and `--`. For every other arithmetic operator the operands are converted to `int` and **the result is `int`**:

```csharp
byte a = 200, b = 100;
var  c = a + b;                  // c is int, value 300 — not a byte, not 44
Console.WriteLine(c.GetType());  // System.Int32

byte sum = a + b;                // ❌ CS0266: cannot implicitly convert 'int' to 'byte'

char ch = 'A';
var next = ch + 1;               // int 66 — not char 'B'
```

**But compound assignment inserts a cast for you.** `x op= y` is defined as `x = (T)(x op y)` when the promoted result is explicitly convertible back to `x`'s type. So the assignment that *looks* identical compiles, and truncates:

```csharp
byte a = 200, b = 100;
a += b;                 // compiles — equivalent to a = (byte)(a + b)
Console.WriteLine(a);   // 44   (300 truncated into a byte)
```

That is a documented language rule, not a compiler quirk, and it is the reason `+=` on narrow accumulators is a code-review smell. In a `checked` context the same line throws instead.

**What explicit conversions do when the value doesn't fit** — four different behaviours, and knowing which is which is the senior part:

| Conversion | Out-of-range behaviour |
|---|---|
| integer → smaller integer, `unchecked` | Discards the high-order bits; result is fully specified. `(int)long.MaxValue == -1` |
| integer → smaller integer, `checked` | `OverflowException` |
| `double`/`float` → integer, `unchecked` | Truncates toward zero; if the result is out of range the value is **unspecified by the language** — do not rely on it. In practice .NET 9+ *saturates* to the target's `MinValue`/`MaxValue` on every architecture; .NET 8 and earlier on x86/x64 produced `int.MinValue` instead |
| `double`/`float` → integer, `checked` | `OverflowException` |
| `decimal` → integer | Rounds toward zero, and throws `OverflowException` when out of range **regardless of context** |
| `float`/`double` → `decimal` | `OverflowException` for NaN, infinity, or too-large; zero for too-small |

**Cast vs `as` vs pattern.** Three ways to change a reference's static type, with three failure modes:

```csharp
var s1 = (string)o;          // throws InvalidCastException if o isn't a string
var s2 = o as string;        // null if it isn't — reference types and nullable value types only
if (o is string s3) { }      // test and bind in one step; the modern default
```

`as` on a non-nullable value type is a compile error, which is why `o as int` doesn't work and `o as int?` does. Prefer the pattern form: it never produces a null you have to remember to check.

**Truncate or round? `(int)`, `Convert`, and `Math.Round` disagree on purpose.** This is the single most common conversion bug in business code:

```csharp
Console.WriteLine((int)2.5);                 // 2   — cast truncates toward zero
Console.WriteLine((int)3.5);                 // 3   — still truncates
Console.WriteLine((int)(-2.7));              // -2  — toward zero, not toward negative infinity
Console.WriteLine(Convert.ToInt32(2.5));     // 2   — rounds, half to EVEN
Console.WriteLine(Convert.ToInt32(3.5));     // 4   — rounds, half to EVEN
Console.WriteLine(Math.Round(2.5));          // 2   — banker's rounding is the default
Console.WriteLine(Math.Round(2.5, MidpointRounding.AwayFromZero));  // 3
```

`Convert.ToInt32` and `Math.Round` default to **round-half-to-even** (banker's rounding) — documented on Microsoft Learn as "if value is halfway between two whole numbers, the even number is returned; that is, 4.5 is converted to 4, and 5.5 is converted to 6." That is statistically unbiased and is what most accounting standards want; it is also *not* what the person reading your unit test expects. Whenever money is involved, pass `MidpointRounding` explicitly so the intent is in the source rather than in the framework's default.

**User-defined conversions.** A type can declare its own:

```csharp
public readonly struct Money
{
    public decimal Amount { get; }
    public static implicit operator decimal(Money m) => m.Amount;   // safe, always succeeds
    public static explicit operator int(Money m) => (int)m.Amount;  // lossy — force a cast
    public static explicit operator checked int(Money m) => checked((int)m.Amount);  // C# 11
}
```

The design rule: **`implicit` only when the conversion cannot fail and cannot lose information**; anything lossy or throwing must be `explicit`, so the call site shows a cast. C# 11 added user-defined `checked` operators, letting your explicit conversion honour the caller's overflow context the way the built-in ones do — you must define the unchecked version too, and a `checked` context selects the checked one.

**Generic-math conversions (.NET 7+).** `INumberBase<TSelf>` gives you three conversion policies as named methods, which is far clearer than a cast whose behaviour depends on an ambient context:

```csharp
byte.CreateChecked(300);       // throws OverflowException
byte.CreateTruncating(300);    // 44   — keeps the low bits
int.CreateSaturating(3e20);    // int.MaxValue — clamps instead of wrapping
```

`CreateSaturating` is the one most APIs actually want at a boundary: clamp a hostile or absurd input rather than wrap it into a plausible-looking small number.

> 🌍 **In the real world**: a reporting endpoint accepted `?pageSize=` as a `double` (because the front end sent JSON numbers) and did `int size = (int)pageSize;`. A client sent `1e10`. The cast was in an unchecked context and out of range, which the language leaves *unspecified* — and on the x64 servers of the day that meant `int.MinValue`, roughly negative two billion. The page-size guard was `if (size > 100) size = 100;`, and a large negative number sails straight through a `> 100` test, so the query ran with a negative `TOP`. It also refused to reproduce on the team's Apple Silicon laptops, where the same cast saturated to `int.MaxValue` and was duly clamped to 100 — the identical source line, two architectures, two behaviours, because the language never promised one. (.NET 9 made these conversions saturating everywhere, so today both sides give `int.MaxValue` and the guard catches it. The lesson survives the fix: the code was reading a value the specification declines to define.) The fix was to stop converting and start validating: bind the parameter as `int?`, reject anything outside `1..100` with a 400, and — for the places that genuinely had to accept a `double` — use `int.CreateSaturating`, which is defined for every input instead of merely usually behaving.

> 🌍 **In the real world**: a payment reconciliation job compared an amount from the gateway (`decimal`) with an amount from the ledger (a C# `float`, because the ORM had mapped a single-precision SQL `real` column). C# refuses to compare those implicitly, so an earlier developer had "fixed" the compile error with `(decimal)ledgerAmount`. The cast was not the culprit — it faithfully converts whatever precision is left — but `float` carries only about seven significant digits, so any amount past six figures had already lost its cents before the comparison ever ran. A small number of large transactions differed by 0.01, were flagged as fraud-suspect, and were held. The absence of an implicit `double` ↔ `decimal` conversion is a *feature*: it is the language forcing a design decision at every boundary, and casting the error away throws that protection out. The correct fix was upstream, in the column type.

### Parsing and formatting — the culture that changes under you

Parsing is a conversion whose input is text, and text conversions in .NET are **culture-sensitive by default**. `CultureInfo.CurrentCulture` is read from the ambient thread when you don't pass a provider, and it differs between your laptop, the build agent, and the container running with a different `LANG`.

```csharp
var de = new CultureInfo("de-DE");

double.Parse("1.5", de);                        // 15    — '.' is a group separator in de-DE
double.Parse("1.5", CultureInfo.InvariantCulture);  // 1.5
decimal.Parse("1.234", de);                     // 1234
```

Read that first line again: no exception, no warning, a value off by a factor of ten. The default `NumberStyles` for `double.Parse` includes `AllowThousands`, so `"1.5"` is read as "one thousand five" with a stray separator. A German-locale server parsing an American-format CSV does not fail loudly; it produces confident, wrong numbers.

**The rule that prevents all of it:** *machines talk to machines in `InvariantCulture`; humans see `CurrentCulture`.*

| Direction | Use |
|---|---|
| Reading a config file, CSV, HTTP payload, database string, another service's JSON | `CultureInfo.InvariantCulture` (or the culture the format actually specifies) |
| Rendering a price, date or number for a user | `CultureInfo.CurrentCulture`, or the user's stored preference |
| Comparing identifiers, keys, protocol tokens, file extensions | Not a culture question at all — use `StringComparison.Ordinal` |

Formatting has the mirror image of the problem: `amount.ToString()` on a de-DE thread emits `1234,5`, which a downstream invariant parser will reject or misread. Round-tripping (`"O"` for dates, `"R"`/default for floating point) plus `InvariantCulture` is the machine-to-machine default.

**The ICU switch (.NET 5).** From .NET 5, .NET uses ICU rather than the OS's NLS for globalization on Windows 10 May 2019 Update and later, which changed results for culture-sensitive operations. Microsoft's own documented example is `"Hello\r\nworld!".IndexOf("\n")`: `6` on .NET Core 3.1, `-1` on .NET 5 (ICU treated the newline as an ignorable character in a linguistic search), and `6` again on .NET 6+. Three answers for one line of code across three runtimes — and the code was only ever wrong in the sense that it asked a linguistic question about a control character. `IndexOf("\n", StringComparison.Ordinal)` returns 6 on all of them.

Two more knobs worth naming in an interview: `<InvariantGlobalization>true</InvariantGlobalization>` makes every culture behave like the invariant culture (smaller container images, and a hard failure if any code asks for a real culture), and the analyzers `CA1305` (specify `IFormatProvider`), `CA1307` and `CA1309` (specify / use ordinal `StringComparison`) find these call sites mechanically. Turning those on in a mature codebase is a genuinely senior piece of work — the diff is large, and every suppression needs a reason.

> 🌍 **In the real world**: a pricing importer ran green for a year and then produced catalogue prices inflated by a thousand, but only for one customer. That customer's file came from a system that wrote `1.234` for one-point-two-three-four; every other customer sent `1234.00`. The importer used `decimal.Parse(field)` with no provider, and the container it ran in had picked up a European locale from a base-image change — so `1.234` parsed as `1234`. The prices with no decimal point were unaffected, which is why the bug looked customer-specific rather than environmental. Two changes shipped: `CultureInfo.InvariantCulture` on every parse in the ingest path, and `CA1305` promoted to an error so the next one cannot merge. The interview-ready version of the lesson: a parse without an explicit `IFormatProvider` is a call whose behaviour is set by an environment variable.

### Control flow

**`if` / `else`** — standard. Curly braces optional for single statements but you should always use them.

**`switch` statement** — match by value, falls through requires explicit `case X: case Y:` (no implicit fallthrough; `goto case` for explicit). Each case must end with `break`, `return`, `throw`, or `goto`.

**`switch` expression** — modern (C# 8+). No `break`, no `case`, just `pattern => result`:

```csharp
string DayKind(DayOfWeek d) => d switch
{
    DayOfWeek.Saturday or DayOfWeek.Sunday => "weekend",
    _                                       => "weekday"
};
```

A caveat that belongs with conversions: **exhaustiveness over an enum is not a guarantee**. Any integer can be cast to any enum type without validation — `(DayOfWeek)99` is legal, prints `99`, and `Enum.IsDefined` returns `false` for it. A switch expression that covers every declared member and omits `_` compiles with a warning and throws `SwitchExpressionException` at run time when a value arrives from a database column, a deserialiser, or a cast. Keep the discard arm and make it throw something diagnosable.

> 🌍 **In the real world**: an order-status `switch` expression covered all five declared members of the enum, so the team deleted the `_` arm to satisfy a "no dead code" lint rule. Months later a partner integration wrote a 6 into the status column directly, EF Core materialised it into the enum without complaint — enum conversion performs no validation — and the endpoint began returning 500s with `SwitchExpressionException`, whose message names the unmatched value but not the row. The lasting fix was two-part: a `_ => throw new InvalidOperationException($"Unhandled status {(int)status} on order {id}")` arm that puts the identifier in the message, and validation at the persistence boundary with `Enum.IsDefined`. The interview-shaped lesson: an enum is an `int` with names attached, and every value that arrives from outside your process is an `int`.

**Loops:**
- `for (init; condition; update) { ... }` — classic.
- `while (condition) { ... }` — pre-test.
- `do { ... } while (condition);` — post-test (executes at least once).
- `foreach (var x in collection) { ... }` — sugar over `IEnumerable<T>` / `IEnumerator<T>`. Calls `GetEnumerator()` then iterates.

**`break` / `continue` / `return`:** as expected. **`goto`:** legal but ugly outside of `goto case` in `switch` and rare cleanup patterns; avoid.

### Methods and parameters

**Parameter modifiers:**
- *(none)* — pass by value (for value types: a copy; for reference types: the reference itself, copied).
- `ref` — pass by reference. Caller's variable can be reassigned.
- `out` — pass by reference, but caller doesn't need to assign first; method *must* assign before returning.
- `in` — pass by reference, but read-only (no reassignment, no mutation if struct).
- `params` — variadic (caller can pass 0..N values; method receives an array, or any `IEnumerable<T>` since C# 13).

```csharp
void TryParse(string s, out int result)
{
    result = int.TryParse(s, out var n) ? n : 0;
}

void Increment(ref int x) => x++;

void ReadOnly(in BigStruct s) { /* cannot mutate s */ }

int Sum(params int[] numbers) => numbers.Sum();

// Caller
TryParse("42", out var x);   // 'out var' since C# 7
Increment(ref x);
Sum(1, 2, 3, 4, 5);
```

**Optional and named arguments:**

```csharp
void Greet(string name, string greeting = "Hello", bool exclaim = false)
{
    Console.WriteLine($"{greeting}, {name}{(exclaim ? "!" : ".")}");
}

Greet("Alice");                                     // uses both defaults
Greet("Bob", exclaim: true);                        // skip middle, name the last
Greet(name: "Carol", greeting: "Hi");               // all named, any order
```

**Optional-parameter defaults are baked into the caller, exactly like `const`.** `Greet("Alice")` compiles to `Greet("Alice", "Hello", false)` — the default values are copied into the call site at *the caller's* compile time, not looked up at run time. Change the default in a library and every consumer that isn't recompiled keeps the old one. For a public API that means an optional parameter's default is part of your binary contract; adding a new optional parameter to a method is also a **binary** breaking change even though it is source-compatible, because the call site's compiled signature no longer matches. Overloads do not have that problem, which is why BCL APIs so often prefer an extra overload to an extra default.

> 🌍 **In the real world**: a shared HTTP client wrapper had `SendAsync(request, int timeoutSeconds = 30)`. During an incident the platform team lowered the default to 5 and shipped a patch release, and the services that had been rebuilt that week picked it up while the rest kept timing out at 30. Because both behaviours were "the default", nobody could tell from the source which services had which, and the graph showed two clusters of timeout durations with no code difference to explain them. The rewrite replaced the default with an overload pair and a `TimeSpan` resolved from options at run time — the general fix for anything a library author expects to tune later.

**Local functions** — methods nested inside other methods. Cleaner than private helper methods when only one caller exists; can capture locals like a closure.

```csharp
int Factorial(int n)
{
    return Compute(n);

    static int Compute(int x) => x <= 1 ? 1 : x * Compute(x - 1);
    //     ^^^^ static = no capture, slightly faster
}
```

### `ref` / `out` / `in` — parameter semantics at the IL level

Surface-level: `ref` is in-out, `out` is out-only, `in` is read-only. Senior-level: **all three emit the same IL opcode** (`ldarga`, address-of-argument) and the *only* difference is the contract the C# compiler enforces. Understanding that single fact resolves a half-dozen interview cross-questions.

**The properties box:**

```
┌─────────────────────────────────────────────────────────────┐
│              ref          out          in       │ (none)    │
├─────────────────────────────────────────────────────────────┤
│ Pass by:    address      address      address   │ value     │
│ IL prefix:  byref &T     byref &T     byref &T  │ T         │
│ Caller     ✓ must        ✗ not        ✓ must    │ ✓ must    │
│  pre-assign:required     required     init                  │
│ Callee     ✗ may read    ✓ MUST       ✗ MAY    │ ✓ must    │
│  pre-assign:without write write before  not write          │
│             first        return                              │
│ Mutation    ✓            ✓            ✗ readonly│ ✗ (copy)  │
│  allowed?   in callee    in callee    by callee │           │
│ Copy of     ✗            ✗            ✗         │ ✓ (always)│
│  value?                                          │           │
└─────────────────────────────────────────────────────────────┘
```

The same `&T` byref under the hood — three different contracts the compiler enforces.

**When each is correct:**

```csharp
// out — classic Try* pattern; method must assign, caller doesn't pre-init
public bool TryParse(string s, out int result)
{
    if (!int.TryParse(s, out var n)) { result = 0; return false; }   // MUST assign before return
    result = n;
    return true;
}

// ref — true in-out; both sides communicate via the same storage
public void Swap<T>(ref T a, ref T b)
{
    var tmp = a;
    a = b;
    b = tmp;
}

// in — readonly reference; semantic intent is "I read this struct without copying it"
public double Magnitude(in Vector3 v) => Math.Sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z);

// (none) — pass by value; appropriate for primitives and small structs
public int Add(int a, int b) => a + b;
```

**The `in` defensive-copy trap.** This is the cross-question every senior interviewer reaches for:

```csharp
public struct Counter
{
    public int Value;
    public int ReadValue() => Value;       // not marked readonly → compiler suspects mutation
}

public void Use(in Counter c)
{
    int v = c.ReadValue();
    //          ^^^^^^^^^ — compiler SILENTLY emits a defensive copy of `c`
    // because `in c` is readonly but ReadValue() might mutate (compiler can't prove otherwise).
    // The "avoid the copy" perf win of `in` is silently destroyed.
}
```

**The fix** — either annotate the method `readonly`, or make the whole struct `readonly`:

```csharp
public struct Counter
{
    public int Value;
    public readonly int ReadValue() => Value;     // ✓ compiler proves no mutation, no defensive copy
}

// OR

public readonly struct Counter                    // every field readonly; every method implicitly readonly
{
    public int Value { get; }
    public Counter(int v) { Value = v; }
    public int ReadValue() => Value;              // no annotation needed; the whole type is non-mutating
}
```

The `readonly struct` form is cleaner and is what `Span<T>`, `Memory<T>`, `Vector3`, and most modern value types use.

> 🌍 **In the real world**: a geometry-heavy service profiled a hot intersection test and found it spending its time in `memcpy`-shaped work rather than arithmetic. The struct was 64 bytes and every method took it `in`, which the author had added specifically to avoid copies. It was a mutable `struct` with ordinary (non-`readonly`) property getters, so every single property access inside those methods emitted a defensive copy — the `in` had *increased* the number of copies, because before the change the struct was copied once on entry and then read from a local. Marking the type `readonly struct` removed the copies without touching a single call site. The reusable diagnostic: if `in` didn't help, the type is probably not `readonly`, and the copies moved rather than disappeared.

**`ref` returns and `ref` locals (C# 7, sharpened in .NET 7+):**

```csharp
// ref return — return a reference into a backing store; caller can mutate through it
public ref int GetSlot(int[] array, int index) => ref array[index];

int[] data = { 10, 20, 30 };
ref int slot = ref GetSlot(data, 1);              // ref local — alias for data[1]
slot = 99;                                         // mutates the array element directly
Console.WriteLine(data[1]);                       // 99

// ref readonly return — read-only alias, no mutation through it
public ref readonly int Peek(int[] array, int i) => ref array[i];

// .NET 7+: 'ref' fields in ref structs (this is how Span<T> stores its pointer internally)
public ref struct Slice<T>
{
    public ref T First;       // a managed pointer, captured by the struct
}
```

`ref` returns are how `Span<T>`'s indexer and the `CollectionsMarshal` helpers avoid copying: `CollectionsMarshal.AsSpan(list)` hands you a `Span<T>` over a `List<T>`'s backing array, and `CollectionsMarshal.GetValueRefOrNullRef(dict, key)` returns a `ref TValue` into the dictionary's entry array so you can update a value in place with one lookup instead of two. (Both live in `System.Runtime.InteropServices` — `AsSpan` since .NET 5, `GetValueRefOrNullRef` since .NET 6 — and both are named "Marshal" as a warning: adding to or removing from the collection while the ref or span is alive is undefined behaviour, because the backing array can be reallocated underneath you.) Powerful but easy to misuse — if the underlying storage is freed or relocated, the ref dangles. The compiler enforces what it can statically; the rest is on you.

**`ref readonly` parameters (C# 12) — the modifier `in` should have been.** `in` is silently forgiving at the call site: it accepts literals, properties and implicitly-converted arguments by manufacturing a hidden temporary, so a caller can *think* they are passing by reference while the compiler quietly makes a copy. `ref readonly` closes that hole by making the call site say what it means:

```csharp
public static void Process(ref readonly LargeStruct data) { /* read-only, by reference */ }

Process(in options);            // ✓ explicit, no copy
Process(ref options);           // ✓ also allowed (the variable is writable)
Process(options);               // ⚠ CS9192: argument should be passed with 'ref' or 'in'
Process(new LargeStruct());     // ⚠ CS9193: argument should be a variable — an expression has
                                //    no storage to reference, so a temporary is created
```

Use `ref readonly` for new APIs where passing by reference is the *point* (large structs, interop buffers); keep `in` where you want callers to be able to pass anything conveniently. Note also that `ref`, `in`, `ref readonly` and `out` cannot be used to overload each other — a compiler error if two members differ only by which of them they use — so switching an existing public API from `in` to `ref readonly` is a source-compatible change for callers who already pass `in`, and a new warning for everyone else.

### `params` arrays and collection-expression parameters (C# 12+)

`params` lets a method accept a variable number of arguments. The historical implementation is an array; in modern C# the compiler can pick a more efficient representation.

**Classic `params` array:**

```csharp
public static int Sum(params int[] numbers)
{
    int total = 0;
    foreach (var n in numbers) total += n;
    return total;
}

Sum(1, 2, 3);                  // compiler allocates new int[] { 1, 2, 3 } and passes it
Sum();                         // allocates new int[0] (or uses Array.Empty<int>())
Sum(new[] { 1, 2, 3 });        // explicit array — same call
```

**The cost:** every variadic call site allocates an array on the heap (unless the compiler can prove the array is empty and reuse `Array.Empty<T>()`). In a hot path called millions of times, that's millions of arrays for the GC.

**`params ReadOnlySpan<T>` (C# 13+):** the compiler can stack-allocate the array for `params ReadOnlySpan<T>` parameters — zero heap allocation:

```csharp
public static int Sum(params ReadOnlySpan<int> numbers)   // C# 13
{
    int total = 0;
    foreach (var n in numbers) total += n;
    return total;
}

Sum(1, 2, 3);   // compiler emits: stackalloc int[3]; load 1,2,3; pass as ReadOnlySpan<int>
                // ZERO heap allocations
```

**`params IEnumerable<T>` (also C# 13+):** for when you want to forward to LINQ-style consumers:

```csharp
public static int Sum(params IEnumerable<int> numbers) => numbers.Sum();
```

**When to prefer which signature:**

| Signature | Allocation | Use when |
|---|---|---|
| `params T[]` | Heap array per call | Legacy compat; not perf-critical |
| `params ReadOnlySpan<T>` | Stack-allocated | Hot paths, modern C# 13+ |
| `params IEnumerable<T>` | Boxes if needed | You forward to LINQ-style consumers |
| `IEnumerable<T>` (no `params`) | None (caller controls) | Caller already has a collection — don't force them to splat |

**Senior rule of thumb:** prefer non-`params` `IEnumerable<T>` for library APIs that don't need positional-call ergonomics. `params` is convenient at the call site (`Log("msg", arg1, arg2)`) but every call pays an allocation in the array form. Logger libraries (`Microsoft.Extensions.Logging`) sidestep this with source-generated overloads.

> 🌍 **In the real world**: .NET 9 added `params ReadOnlySpan<T>` overloads to a long list of BCL methods — `string.Format`, `string.Join`, `string.Concat`, `StringBuilder.AppendFormat`, `Task.WhenAll`, `Path.Combine` and more — and C# 13 prefers the span overload over the array one when a call passes arguments individually. Teams got the allocation win by recompiling, with no source change. One team also got a build break: their call to `string.Join` sat inside an `Expression<Func<...>>` lambda, expression trees cannot contain a `ref struct`, and the compiler reported `CS8640`/`CS9226`. The documented workaround is to pass an explicit array so the call binds back to the array overload. It is a good illustration of a senior-level habit — when a recompile changes behaviour, the cause is often overload resolution seeing a new candidate, not the runtime changing its mind.

### Strings — the surprisingly deep type

`string` in C# is **immutable** and **reference-typed**, but with value-like equality semantics (`==` compares contents, not references). Every "modification" of a string allocates a new one.

**Five ways to build strings:**

```csharp
// 1. Concatenation (creates intermediate strings — fine for 2-3 parts)
string s1 = "Hello, " + name + "!";

// 2. Interpolation — preferred for readability
string s2 = $"Hello, {name}!";
//   At compile time, this becomes a call to string.Format or DefaultInterpolatedStringHandler
//   (since C# 10) — which is allocation-light when the result fits in a stack buffer.

// 3. string.Format — when you need explicit format specifiers
string s3 = string.Format("{0:N2} euros", 1234.5);  // "1,234.50 euros"

// 4. StringBuilder — for many appends in a loop
var sb = new StringBuilder();
foreach (var item in items) sb.Append(item).Append(", ");
string s4 = sb.ToString();

// 5. string.Create — allocation-free string building (advanced; see 09-memory-and-performance.md)
string s5 = string.Create(10, state, (span, s) => { /* fill span */ });
```

**Verbatim and raw strings:**

```csharp
string verbatim = @"C:\path\to\file";     // verbatim — \ is literal
string verbatimWithQuote = @"He said ""hi""";  // double "" for one literal "
string raw = """
    {
        "name": "alice",
        "city": "Lahore"
    }
    """;                                   // raw string (C# 11) — no escaping at all
```

Raw strings (`"""..."""`) are a 2022 addition. They:
- Need at least 3 quotes (more if the content contains 3 quotes).
- Strip leading whitespace based on the closing `"""` indent.
- Combine with interpolation: `$"""..."""` (and `$$"""..."""` for content containing `{`).

**UTF-8 string literals (C# 11):** `"hello"u8` produces a `ReadOnlySpan<byte>` of UTF-8 bytes — useful for low-allocation HTTP/file/network code:

```csharp
ReadOnlySpan<byte> contentType = "application/json"u8;
// Bytes baked into the assembly metadata; no runtime UTF-16 → UTF-8 conversion needed.
```

### Text is code units, not characters — surrogate pairs, `Rune`, and comparison

`string` is a sequence of `char`, and a `char` is a **UTF-16 code unit**, not a character. Everything below follows from that one sentence, and it is the difference between a candidate who has shipped internationalised software and one who has not.

**`Length` counts code units.** Any character outside the Basic Multilingual Plane — emoji, many CJK extensions, historic scripts, some mathematical symbols — is stored as a **surrogate pair**: two `char` values that only mean something together.

```csharp
string thumb = "\U0001F44D";                 // 👍
Console.WriteLine(thumb.Length);                                   // 2   — code units
Console.WriteLine(thumb.EnumerateRunes().Count());                 // 1   — Unicode scalar values
Console.WriteLine(new StringInfo(thumb).LengthInTextElements);     // 1   — what a human calls a character
```

Three legitimate answers to "how long is this string", and the one you get by default is the one nobody means. Worse, `Substring`, `[..n]` and any hand-rolled truncation can cut a pair in half:

```csharp
string name = "Ana👍b";               // Length == 6: 'A','n','a', high surrogate, low surrogate, 'b'
string cut  = name.Substring(0, 4);   // "Ana" + a lone high surrogate
```

A lone surrogate is not valid Unicode. It renders as `�`, and it will be rejected or silently mangled by anything that re-encodes it — a UTF-8 database column, a JSON serialiser, a downstream Java service. This is the actual mechanism behind "the display name broke when we added the 20-character limit".

**The three tools, in increasing order of correctness:**

| Type | Represents | Use for |
|---|---|---|
| `char` | One UTF-16 code unit | ASCII-only parsing, delimiters, digits |
| `System.Text.Rune` (.NET Core 3.0+) | One Unicode scalar value | Character-by-character processing that must not split pairs |
| `StringInfo` / text elements | One grapheme cluster (what a user sees) | Truncation, cursor movement, "N characters" limits |

A grapheme cluster can be several scalars — an emoji with a skin-tone modifier, or `e` plus a combining accent — so `StringInfo` is the only one that matches human intuition. Truncating for display? Use text elements. Validating a protocol field? Use `Rune` or bytes.

**Comparison: ordinal by default in some places, culture-sensitive in others.** This is the trap, because the defaults are not consistent and the docs say so:

```csharp
"Hello\r\nworld!".IndexOf('\n');    // ordinal      — IndexOf(char) is culture-insensitive
"Hello\r\nworld!".IndexOf("\n");    // LINGUISTIC   — IndexOf(string) uses the current culture
bool same = a == b;                 // ordinal      — string's == operator
string.Compare(a, b);               // linguistic, current culture
a.StartsWith("x");                  // linguistic, current culture
a.StartsWith("x", StringComparison.Ordinal);   // ordinal, and says so
```

Two methods on the same class, differing only in whether the argument is a `char` or a `string`, use different comparison rules. Microsoft Learn's own recommendation is to never rely on the default: pass a `StringComparison` at every call site, and use `Ordinal` / `OrdinalIgnoreCase` as the safe default for anything non-linguistic.

**Two strings that look identical can compare unequal — and vice versa.**

```csharp
string precomposed = "é";          // é   — one scalar
string decomposed  = "é";         // é   — 'e' + combining acute
Console.WriteLine(precomposed == decomposed);                                  // False (ordinal)
Console.WriteLine(string.Equals(precomposed, decomposed, StringComparison.CurrentCulture)); // True
```

`==` is ordinal, so it says these are different strings — which they are, byte for byte. A linguistic comparison says they are the same, which they also are, to a reader. If you need them to match, normalise first (`s.Normalize(NormalizationForm.FormC)`), typically at the point of input rather than at each comparison. This is why usernames and email addresses are normalised on the way into the database and compared ordinally afterwards.

**The Turkish-I problem** is the canonical security-relevant case, and Microsoft Learn documents it as such: Turkish (`tr-TR`) and Azerbaijani have a dotted capital `İ` and a dotless lowercase `ı`, so `i` does not uppercase to `I`.

```csharp
// The culture is passed explicitly here, so this reproduces on any machine.
// The real bug ships as StartsWith("FILE:", true, null) — null means "current culture".
"file:".StartsWith("FILE:", ignoreCase: true, new CultureInfo("tr-TR"));  // False
"file:".StartsWith("FILE:", StringComparison.OrdinalIgnoreCase);          // True
```

A `IsFileUri`-style check written with a culture-sensitive case-insensitive comparison **passes on an English server and fails on a Turkish one** — Learn spells out the consequence: "on Turkish systems, someone could circumvent security measures that block access to case-insensitive URIs that begin with FILE:". Any case-insensitive check on a scheme, header, file extension, role name or feature flag must be `OrdinalIgnoreCase`. And when normalising case for comparison, Learn recommends `ToUpperInvariant` over `ToLowerInvariant`: `OrdinalIgnoreCase` is itself described as the composition of `ToUpperInvariant` on both arguments plus an ordinal comparison, so uppercase is the direction the runtime already agrees with.

> 🌍 **In the real world**: a support ticket said "profile names with emoji get corrupted after editing". The API truncated display names to 50 with `name[..50]`, which occasionally split a surrogate pair; the lone surrogate survived in the .NET string, failed to encode as valid UTF-8 on the way into the message bus, and arrived downstream as a replacement character. Nobody could reproduce it because it only happened when the 50th code unit landed mid-pair. The fix was `StringInfo`-based truncation on text elements — which also stopped chopping accented characters away from their base letters, a milder bug the team hadn't yet had reported. The reusable framing: `Length` is a storage measurement, and every user-facing limit is a display measurement.

> 🌍 **In the real world**: a feature-flag check written as `if (header.ToLower() == "enabled")` shipped for years. It allocated a string on every request, which was the reason it was flagged in a profiler — but the review found the worse problem: the service had just been deployed to a region whose container image set a Turkish locale, and `ToLower()` on the ambient culture turned `"ENABLED"` into `"enabled"` with a dotless `ı`. The flag silently read as off for that region only. Rewriting it as `string.Equals(header, "enabled", StringComparison.OrdinalIgnoreCase)` removed the allocation and the correctness bug in one edit, which is the usual outcome: on strings, the ordinal path is both the faster one and the one that means what you intended.

### String interning and reference identity

C# strings are immutable, and the CLR exploits that immutability to **intern** identical literal strings — store exactly one instance in a process-wide pool. This is why `ReferenceEquals` does counter-intuitive things with strings.

**The intern pool:**

```csharp
string a = "hello";
string b = "hello";
Console.WriteLine(ReferenceEquals(a, b));        // True  — both point at the SAME pooled instance

string c = new string("hello".ToCharArray());     // explicit allocation, bypasses pool
Console.WriteLine(ReferenceEquals(a, c));        // False — different object on heap
Console.WriteLine(a == c);                       // True  — '==' on string compares content, not identity
```

**Three ways a string ends up interned:**

1. **String literals in source code** — interned automatically by the JIT/runtime.
2. **`const string`** — interned (it's a literal at the IL level).
3. **`string.Intern(s)`** — manually add a dynamically-built string to the pool, returning the pooled instance.

**Three ways a string does NOT end up interned:**

1. Strings built at runtime (`s + "x"`, `string.Format(...)`, `new string(...)`, `StringBuilder.ToString()`).
2. Strings read from files, network, or any IO.
3. Anything `Substring`'d, `Trim`'d, `ToLower`'d from another string.

```csharp
string lit = "ABC";                              // interned
string built = string.Concat("A", "B", "C");      // NOT interned
Console.WriteLine(ReferenceEquals(lit, built));  // False
Console.WriteLine(ReferenceEquals(lit, string.Intern(built)));  // True — Intern returns pooled instance
```

**Why immutable + interned together?** If strings were mutable, interning would be a disaster: one caller's `.Replace('A', 'X')` would change every other caller's `"ABC"`. Immutability is what makes the pool safe — and the pool is what makes string literal comparison ultra-cheap (a reference comparison is one instruction).

**Performance implications:**

- `==` on `string` is **content-equal**, not identity. Internally it short-circuits: if `ReferenceEquals` is true, return true immediately; otherwise compare characters. For interned strings the fast path always wins.
- **Don't `Intern` runtime-built strings as an optimization** — the pool grows for the entire process lifetime; it's never collected. Frequent interning of random strings is a slow memory leak.
- **Why does this matter for `Dictionary<string, X>`?** The dictionary hashes and compares by content (`string.GetHashCode` + `string.Equals`), so interning doesn't speed up lookups. The pool's only direct benefit is reference-equality fast paths.

> 🌍 **In the real world**: a multi-tenant API held a `Dictionary<string, TenantConfig>` and someone "optimised" the lookup by calling `string.Intern(tenantId)` on every incoming request, reasoning that interned keys would make comparisons cheaper. Tenant ids arrive from the wire and are therefore all distinct instances, so every request added a new entry to a pool that is never collected for the lifetime of the process. Memory grew slowly and monotonically and survived every Gen 2 collection. The strings do show up in a heap dump — they are ordinary `System.String` instances — but rooted by the runtime's intern table rather than by any application object, so the usual "who holds a reference to this?" path leads back to the runtime and looks like framework overhead. That is what made it take weeks to find. The correct optimisation was `StringComparer.OrdinalIgnoreCase` on the dictionary, which fixes the comparison semantics (the real bug, since tenant ids arrived in mixed case) and costs nothing.

**The immutability vs `StringBuilder` perf story.** Because strings are immutable, every "modification" allocates. In a loop:

```csharp
// O(n²) — each += allocates a new string and copies everything written so far
string s = "";
for (int i = 0; i < 10_000; i++) s += i.ToString();
// One new string per iteration; all but the last are immediately garbage.
// Total characters copied grows with the SQUARE of the iteration count.

// O(n) — StringBuilder mutates an internal buffer
var sb = new StringBuilder();
for (int i = 0; i < 10_000; i++) sb.Append(i);
string s = sb.ToString();
// One copy of the final content at ToString(), plus a handful of buffer growths.
```

Choosing between them is about *shape*, not a threshold. A fixed, known set of parts (`a + b + c`, or one interpolated string) compiles to a single `string.Concat` / `DefaultInterpolatedStringHandler` call that allocates the result once — a `StringBuilder` there just adds its own object and buffer for no benefit. An unbounded loop is the opposite: the concatenation's cost is quadratic in the number of appends and the builder's is linear, so the builder wins and keeps winning. For a known final length in a hot path, `string.Create(length, state, (span, s) => ...)` allocates exactly the one string and fills it in place.

> 🌍 **In the real world**: an export endpoint built CSV with `csv += line + "\n"` inside a `foreach`. It was invisible for a year at a few hundred rows. A customer with tens of thousands of rows turned it into a request that took minutes and pushed the process into repeated Gen 2 collections — because every iteration allocated a string the size of the entire file so far, and the later ones were large enough to land straight on the Large Object Heap. The tell in the GC trace was not the allocation *count* but the allocation *sizes* climbing linearly. Swapping to `StringBuilder` fixed the incident in one line; streaming directly to the response body with `PipeWriter` fixed the class of problem, because the export then never held the whole file in memory at all.

### `nameof` and `typeof` — compile-time strings vs runtime type tokens

Two operators that look like function calls but are evaluated at compile time. Mixing them up is a senior-interview pitfall.

**`nameof(x)` — compile-time string literal:**

```csharp
public void SetName(string name)
{
    if (name is null) throw new ArgumentNullException(nameof(name));
    //                                                ^^^^^^^^^^^^
    // At compile time, this becomes: throw new ArgumentNullException("name");
    // — but unlike the literal string "name", `nameof(name)` survives refactoring:
    // if you rename the parameter to 'username', the compiler updates the nameof too.
}
```

**Why it matters:** `nameof` makes string references **refactor-safe**. The IDE's "Rename" command updates every `nameof(Foo)` automatically; a hard-coded `"Foo"` string requires manual search-and-replace and is a perpetual source of stale messages.

Use cases:
- `ArgumentNullException`, `ArgumentException`, `ArgumentOutOfRangeException` — pass parameter names as strings.
- `INotifyPropertyChanged.PropertyChanged` event — pass property names.
- Logging structured fields by name.
- ASP.NET routing / model binding errors.

**`typeof(T)` — compile-time `Type` token:**

```csharp
Type t = typeof(int);                         // System.Int32 — compile-time bound
Type listT = typeof(List<int>);               // System.Collections.Generic.List`1[System.Int32]
Type openList = typeof(List<>);               // OPEN generic — the unbound List<T>

// At runtime, every Type is a 'reflection ticket' to the type's metadata.
Console.WriteLine(t.Namespace);               // System
Console.WriteLine(t.FullName);                // System.Int32
Console.WriteLine(listT.GetGenericArguments()[0]);  // System.Int32
```

**`obj.GetType()` — runtime type:**

```csharp
object o = "hello";
Type t1 = typeof(string);     // compile-time: System.String
Type t2 = o.GetType();        // runtime: System.String (same here)

object o2 = "hello";
Type t3 = typeof(object);     // System.Object — what the variable IS DECLARED as
Type t4 = o2.GetType();       // System.String — what the variable IS HOLDING

// typeof is compile-time and uses the *static* type;
// GetType() is runtime and uses the *dynamic* type.
```

**Comparison summary:**

| Operator | Evaluated at | Returns | Refactor-safe? | Typical use |
|---|---|---|---|---|
| `nameof(x)` | Compile time | `string` (literal) | ✓ Yes | Exception args, logging keys, INotifyPropertyChanged |
| `typeof(T)` | Compile time | `System.Type` | ✓ Yes | Reflection, generic type creation, attribute filtering |
| `obj.GetType()` | Runtime | `System.Type` | ✓ Yes (it's the object's runtime type) | Polymorphic dispatch, type-switching at runtime |

**Common pitfalls:**

1. **`nameof(SomeClass.Method())` is illegal.** `nameof` accepts an *expression that names something* — `nameof(SomeClass.Method)` is fine (returns `"Method"`), but invoking the method makes no sense at compile time.
2. **`nameof` of a fully-qualified name returns just the last segment.** `nameof(System.Collections.Generic.List<int>)` returns `"List"`, not `"List<int>"`. (Use `typeof(List<int>).Name` for the full name.)
3. **Confusing `typeof(T)` and `default(T)`.** `typeof(int)` is a `Type` object (the metadata); `default(int)` is `0` (the value). Both are compile-time, very different.
4. **Using strings instead of `nameof` in attributes.** `[CallerMemberName]` and similar attributes accept string parameters at the API boundary; `nameof` is preferred everywhere it's syntactically allowed.

> 🌍 **In the real world**: a validation layer built error keys as `"Order.CustomerId"` string literals so the front end could map them to form fields. A refactor renamed `CustomerId` to `BuyerId`; the compiler was happy, the tests were happy (they asserted on the same literals), and the form stopped highlighting the offending field in production — the error arrived with a key nothing was listening for. Rewriting the keys as `$"{nameof(Order)}.{nameof(Order.CustomerId)}"` made the next rename a compile-time event. The general principle worth stating in an interview: `nameof` converts a class of silent runtime drift into a class of build failures, which is the trade every refactoring-safe API is making.

### Namespaces and `using` directives

**Namespaces** group types. The standard CLR convention is `Company.Project.Layer`:

```csharp
namespace Acme.Billing.Services;   // file-scoped namespace (C# 10) — applies to whole file

public class InvoiceService { /* ... */ }
```

Older block-scoped form (still valid):

```csharp
namespace Acme.Billing.Services
{
    public class InvoiceService { /* ... */ }
}
```

Prefer file-scoped — one namespace per file is the modern convention, and the saved indentation level reads better.

**`using` directives:**

```csharp
using System;                              // bring namespace into scope
using System.Collections.Generic;
using OrderRepo = Acme.Data.OrderRepository;  // alias — useful for name conflicts
using static System.Math;                  // static members directly — Sqrt(2), PI, ...
global using System.Linq;                  // C# 10 — applies to whole project (in csproj or one file)

// C# 12: alias any type, including generics, tuples, arrays
using Coords = (double Latitude, double Longitude);
using IntList = System.Collections.Generic.List<int>;
```

`global using` is best placed in a single `GlobalUsings.cs` file at project root. Modern SDK projects auto-include common globals: `System`, `System.Collections.Generic`, `System.Linq`, etc.

> 🌍 **In the real world**: a team added `global using MyCompany.Extensions;` to cut boilerplate, and a week later an unrelated file started resolving `Where` to their own extension method instead of `System.Linq`'s, because theirs was a closer match on a `List<T>` receiver. The build passed; the behaviour changed, because their version evaluated eagerly. Nothing in the affected file had been edited, and nothing in it mentioned the new namespace — the whole cause lived in a file the reviewer never opened. The rule the team adopted afterwards is a good one to be able to state: `global using` is for namespaces with no chance of ambiguity (`System.*`, your own DTO namespace), never for a namespace containing extension methods on framework types. Disabling `<ImplicitUsings>` and listing globals explicitly makes the set reviewable in one place.

### Top-level statements

C# 9 introduced **top-level statements** — a program can omit the `class Program { static void Main(...) { ... } }` ceremony:

```csharp
// File: Program.cs — entire program
using System;

Console.WriteLine("Hello, world.");

// Local functions and types still allowed
int Add(int a, int b) => a + b;
Console.WriteLine(Add(2, 3));

// 'args' is implicitly available, of type string[]
if (args.Length > 0) Console.WriteLine(args[0]);
```

The compiler synthesizes a hidden `Program.Main` for you. Only one file in a project may contain top-level statements. Modern templates (`dotnet new web`, `dotnet new console`) use this form by default.

> 🌍 **In the real world**: the first integration test written against a minimal-API service failed to compile with "Program is inaccessible due to its protection level" — `WebApplicationFactory<Program>` needs the entry-point type, and the synthesized one is `internal`. The two-line fix is `public partial class Program { }` at the bottom of `Program.cs` (partial, so it merges with the generated half) or an `InternalsVisibleTo` for the test assembly. It is worth knowing cold, because it is the first thing that goes wrong when a team moves from controllers to minimal APIs and it looks like a testing-framework problem rather than a language one.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌─────────────────────────────────────────────────────────┐
│                  C# Source File Structure                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  using System;                       ← directives       │
│  using System.Linq;                                     │
│                                                         │
│  namespace Acme.Service;             ← file-scoped ns   │
│                                                         │
│  public class OrderService           ← type             │
│  {                                                      │
│      private readonly IRepo _repo;   ← field            │
│                                                         │
│      public OrderService(IRepo r)    ← ctor             │
│          => _repo = r;                                  │
│                                                         │
│      public Order Get(int id)        ← method           │
│      {                                                  │
│          var x = _repo.Find(id);     ← local + expr     │
│          return x;                   ← statement        │
│      }                                                  │
│  }                                                      │
└─────────────────────────────────────────────────────────┘
```

**Default values for built-in types:**

| Type | `default(T)` |
|---|---|
| numeric (int, double, decimal, etc.) | `0` |
| `bool` | `false` |
| `char` | `'\0'` |
| reference types (string, object, classes) | `null` |
| structs | all fields set to their default |
| enums | `0` (whether or not the value is named) |

```csharp
int    a = default;        // 0
bool   b = default;        // false
string s = default;        // null
DateTime dt = default;     // 0001-01-01 00:00:00 UTC
DayOfWeek d = default;     // Sunday (because it's the 0 value)
```

</details>
## Common pitfalls

1. **Using `==` for floating-point equality.** IEEE-754 isn't exact. `0.1 + 0.2 != 0.3`. Use `Math.Abs(a - b) < epsilon` or, for money, switch to `decimal`.
2. **Mutating a `string` and expecting it to change.** `s.Replace("a", "b")` returns a *new* string — the original is unchanged. Same for `Trim`, `ToLower`, `Substring`.
3. **`int` overflow silent by default.** If you're computing offsets, sizes, or anything that could overflow, wrap in `checked` or set `<CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>` project-wide.
4. **Implicit `int` to `long` conversion forgetting overflow.** `long ms = int.MaxValue * 1000;` overflows in `int` *before* assigning to `long`. Cast first: `long ms = (long)int.MaxValue * 1000;`.
5. **`var` with literal `0`** locks in `int`. `var x = 0;` is `int`. If you wanted `long` or `double`, write `0L` or `0.0` (or use the explicit type).
6. **Forgetting `out` parameter must be assigned.** Compiler enforces this — but if you're chaining through helper methods, you'll hit a wall. Assign at the top of the method (often `result = default;`) and you're safe.
7. **Default lambda parameters (C# 12) feel like overloads but aren't.** `(int x = 5) => x * 2` produces *one* lambda with a default. It's not two overloads. Reflection over `Method.GetParameters()` shows one parameter.
8. **`@""` raw-style strings vs `"""..."""` raw strings.** Different things. `@"..."` is a verbatim string (still interprets `""` as `"`). `"""..."""` is a raw string (literally everything between the quotes). New code should prefer raw strings.
9. **Parsing or formatting without an `IFormatProvider`.** `double.Parse("1.5")` returns `15` on a `de-DE` thread. Pass `CultureInfo.InvariantCulture` for anything machine-readable and turn on `CA1305`.
10. **Case-insensitive comparison via `ToLower()`/`ToUpper()` or a culture-sensitive overload.** Allocates, and breaks on Turkish locales. Use `string.Equals(a, b, StringComparison.OrdinalIgnoreCase)`.
11. **Treating `string.Length` as a character count.** It counts UTF-16 code units; emoji and other non-BMP characters are two. Truncating on `Length` can split a surrogate pair and produce invalid text. Use `StringInfo` text elements for display limits, `Rune` for scalar-by-scalar work.
12. **`public const` in a shared library.** The value is copied into every consumer at *their* compile time, so changing it does nothing until each one is rebuilt. Use `static readonly` for anything tunable — and note that optional-parameter defaults are baked in the same way.
13. **Capturing a `for` loop variable in a lambda.** All the delegates share one variable and see its final value. `foreach` variables are per-iteration and safe; for `for`, copy into a loop-local first.
14. **Assuming a switch expression over an enum is exhaustive.** Any `int` can be cast to any enum without validation, so a value from a database or deserialiser can reach a switch with no matching arm and throw `SwitchExpressionException`. Keep a `_` arm that throws something diagnosable.

## Interview-ready summary

- **C# is statically typed, garbage-collected, multi-paradigm** (OOP + functional + imperative).
- **15 primitive types** map to CLR `System.*` types — `int` ≡ `System.Int32`. Suffixes pick non-default literal types (`5L`, `5.0m`, `5U`).
- **`var` is implicit static typing**, not dynamic. `dynamic` is true runtime typing (rarely used, slower, no IntelliSense).
- **Definite assignment** — locals must be assigned before read; fields auto-default. The compiler enforces this.
- **Strings are immutable reference types with value-like equality.** Use `StringBuilder` for tight loops, `string.Create` for hot paths, raw strings (`"""`) for embedded JSON/SQL.
- **Parameter modifiers**: `ref` (in/out reference), `out` (must assign), `in` (read-only reference, often used with structs to avoid copies), `params` (variadic).
- **Null operators**: `?.` (conditional access), `??` (coalescing), `??=` (coalescing assignment), `!` (forgiving — compile-time hint, no runtime effect).
- **Top-level statements (C# 9)** + **file-scoped namespaces (C# 10)** + **global usings (C# 10)** = modern minimal-ceremony C#.
- **`switch` expression > `switch` statement** in modern code: terser, exhaustiveness-checked, no fallthrough hazard — but enum exhaustiveness is not a runtime guarantee, since any `int` casts to any enum.
- **Integer arithmetic is silent-wrap by default.** Use `checked` for safety-critical math; the project flag's biggest win is turning silent *narrowing conversions* into exceptions.
- **Implicit conversions preserve magnitude, not precision.** `int → float` and `long → double` are implicit and lossy. Small integer types promote to `int` for arithmetic, and compound assignment silently inserts the narrowing cast back.
- **Casting truncates; `Convert`/`Math.Round` round half-to-even.** State `MidpointRounding` explicitly on anything financial. .NET 7+ generic math names the three policies: `CreateChecked`, `CreateSaturating`, `CreateTruncating`.
- **Text conversions are culture-sensitive by default.** `InvariantCulture` for machines, `CurrentCulture` for humans, `StringComparison.Ordinal` for identifiers. `IndexOf(char)` is ordinal while `IndexOf(string)` is linguistic.
- **`char` is a UTF-16 code unit, not a character.** `Rune` for scalars, `StringInfo` text elements for what users see.
- **Captured variables move to a heap display class.** `for` shares one variable across iterations, `foreach` gives one per iteration; `static` lambdas and local functions make "captures nothing" a compile-time guarantee.
- **`const` and optional-parameter defaults are copied into callers at compile time.** `static readonly` and overloads are the versioning-safe alternatives across assembly boundaries.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — `checked` vs `unchecked` overflow

> **Q**: What does `int.MaxValue + 1` return in C#?
>
> **A**: `int.MinValue` — `-2147483648`. C# integer arithmetic is **silently wrapping** by default (no exception). The IL opcode is `add`, not `add.ovf`.
>
> **Cross-Q**: How do you make it throw instead of wrap?
>
> **A**: Three scopes. (1) Expression: `checked(int.MaxValue + 1)`. (2) Block: `checked { ... }`. (3) Project-wide via `<CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>` in the `.csproj`. The first two emit `add.ovf` IL; the third flips the default for the whole assembly.
>
> **Cross-Q²**: What's the runtime cost of `checked` arithmetic, and when would you `unchecked` *inside* a `checked` project?
>
> **A**: `add.ovf` adds a check of the CPU's overflow flag plus a branch to a throw helper, and because the operation can now throw, the JIT loses some freedom to reorder and vectorise the surrounding code. That is noise in business logic and real in a numeric kernel — quote the mechanism, not a multiplier, and say you'd measure the specific loop with BenchmarkDotNet. Inside a `checked` project, you'd `unchecked { ... }` around CRCs, hash mixing, ring-buffer counters, and pseudo-random number generators — code that **intentionally** wraps as part of the algorithm. The `checked` default catches accidents; explicit `unchecked` documents the intent of the rare correct overflow.

### Drill 2 — `ref` vs `out` vs `in` IL semantics

> **Q**: What's the difference between `ref`, `out`, and `in` parameters?
>
> **A**: At the IL level they emit the **same byref opcode** (`&T`). The difference is purely the contract the C# compiler enforces. `out` requires the callee to assign before returning and exempts the caller from pre-assignment. `ref` requires the caller to pre-assign and lets the callee freely read/write. `in` is a readonly byref — caller pre-assigns, callee can read but not mutate.
>
> **Cross-Q**: What's the "defensive copy" trap with `in`?
>
> **A**: If you pass a mutable struct via `in`, and call a non-`readonly` method on it, the compiler **silently emits a defensive copy** of the struct on the stack — because the method might mutate, but the `in` contract forbids that. The "avoid the copy" perf benefit of `in` is destroyed. Fix: mark the method `readonly` on the struct, or make the entire struct a `readonly struct`.
>
> **Cross-Q²**: What's `ref readonly` return and when would you use it?
>
> **A**: A method that returns a reference into a backing store, but the caller can't mutate through it. Example: `public ref readonly Item GetSlot(int i) => ref _items[i];`. The caller gets a zero-copy alias for read-only access — no defensive copy, no heap allocation, no chance of accidental mutation. `Span<T>.this[int]` returns `ref readonly T` for `ReadOnlySpan<T>`. Use when you want span-like ergonomics for one element of a backing collection.

### Drill 3 — String interning and reference equality

> **Q**: `string a = "hello"; string b = "hello"; ReferenceEquals(a, b)` — true or false?
>
> **A**: True. String literals are **automatically interned** by the runtime — both `a` and `b` point at the single pooled instance for `"hello"`. The CLR exploits string immutability to share literals across the entire process.
>
> **Cross-Q**: What about `string c = new string('h', 1) + "ello"; ReferenceEquals(a, c)`?
>
> **A**: False. Strings built at runtime (via `new`, `+`, `string.Format`, `StringBuilder.ToString`, `Substring`, IO, etc.) bypass the intern pool. `c` is a distinct heap allocation. `a == c` is still `true` because `string.==` compares content; `ReferenceEquals` exposes the identity divergence.
>
> **Cross-Q²**: Should I `string.Intern` runtime-built strings as an optimization?
>
> **A**: Almost never. The intern pool is never garbage-collected for the lifetime of the process — manually interning random strings is a slow memory leak. The pool exists to share *literal* strings, not arbitrary runtime values. The right answer for high-frequency string keys is usually `Dictionary<string, X>` with a normalization step, or a custom `IEqualityComparer<string>` keyed off a hash.

### Drill 4 — `decimal` vs `double` for money

> **Q**: Why is `decimal` the right type for money and `double` the wrong one?
>
> **A**: `double` is base-2 floating point — most "nice" decimal fractions (`0.1`, `0.2`, `0.3`) can't be represented exactly in binary. `0.1 + 0.2 == 0.3` is `false` in `double`. `decimal` stores a 96-bit integer with a base-10 scale factor (0–28), so it represents every base-10 fraction inside 28-29 significant digits exactly. The decisive argument isn't the size of the error, it's that binary rounding isn't reproducible across different orders of operation — two systems can each round correctly and still disagree, and no amount of rounding at the end reconciles them. For values an accountant tracks, `decimal` is non-negotiable. (Note what `decimal` does *not* buy you: `1/3.0m * 3` is still `0.9999999999999999999999999999`. Exact representation, not exact arithmetic.)
>
> **Cross-Q**: What's the perf cost of choosing `decimal`?
>
> **A**: Give the mechanism, not a multiplier. `double` add/multiply are single CPU instructions that vectorise across a SIMD register; `decimal` arithmetic is a software routine that must align two scale factors before operating on 96-bit integers, and the type is 16 bytes against 8, so it costs cache and memory bandwidth too. That's a large gap in a numeric inner loop (Monte Carlo, simulation) and invisible next to a single database round-trip in a business app. If the interviewer wants a number, the correct answer is "I'd measure it with BenchmarkDotNet for that loop" — quoting a remembered multiplier is how people get caught.
>
> **Cross-Q²**: When would you use `float` over `double`?
>
> **A**: Almost never in business code. `float` (~7 digits of precision) is rarely "enough" — `double` has the same speed on modern hardware and 15-17 digits. `float` makes sense only for (1) huge arrays where the 2× memory difference enables SIMD wider lanes (graphics shaders, ML tensors); (2) sensor / hardware interop where the wire format is 32-bit (audio samples, GPU vertex buffers); (3) legacy game engines that committed to 32-bit precision a decade ago. Default for "a real number" is `double`; default for "a monetary value" is `decimal`; `float` requires justification.

### Drill 5 — `params` allocation cost

> **Q**: Does `void Log(string fmt, params object[] args)` allocate on every call?
>
> **A**: Yes — even `Log("ok")` with zero args allocates an empty `object[]` (or reuses `Array.Empty<object>()` since .NET Core 2.0). Calls with value-type args (like `Log("count: {0}", 5)`) also **box** each value into the `object[]` slot. For a logger called millions of times, that's millions of array allocations plus boxing pressure.
>
> **Cross-Q**: How do modern logging libraries avoid this?
>
> **A**: Source generators and strongly-typed delegates. `LoggerMessage.Define<T1, T2>(...)` and the `[LoggerMessage]` source generator produce typed wrappers that never allocate an `object[]` and never box, and they check `ILogger.IsEnabled` before formatting anything. Be careful with the common wrong answer here: the `ILogger` extension methods do **not** have interpolated-string-handler overloads (the API proposal to add them, dotnet/runtime #111283, was closed as not planned), so `logger.LogInformation($"User {id} logged in")` formats the string eagerly *and* destroys the structured-logging template. `Debug.Assert` is the API that genuinely does use one (`AssertInterpolatedStringHandler`, added in .NET 6), which only evaluates the interpolation when the assert fails.
>
> **Cross-Q²**: What about `params ReadOnlySpan<T>` from C# 13?
>
> **A**: The compiler stack-allocates the array for `params ReadOnlySpan<T>` parameters — zero heap allocation, zero boxing for value types. So `Sum(1, 2, 3)` where `Sum(params ReadOnlySpan<int>)` is allocation-free. This is the closest the language gets to "have your variadic cake and eat your perf budget too." It's why .NET 9+'s `string.Format` overloads added `params ReadOnlySpan<object?>` variants.

### Drill 6 — `nameof` vs string literal

> **Q**: Why use `nameof(name)` instead of just `"name"` in `throw new ArgumentNullException(nameof(name))`?
>
> **A**: Refactor safety. `nameof(name)` is a compile-time operator that produces the string `"name"` — but if I rename the parameter to `username` in the IDE, the compiler updates the `nameof` to `nameof(username)` automatically. A hard-coded `"name"` string survives the rename and silently reports the wrong parameter name to the caller forever.
>
> **Cross-Q**: What does `nameof(System.Collections.Generic.List<int>)` return?
>
> **A**: `"List"` — just the last segment. `nameof` returns the simple name, not the fully-qualified name and not the generic-arity-decorated form. For the full name, use `typeof(List<int>).FullName`. For just the type name, `typeof(List<int>).Name` returns `"List\`1"`.
>
> **Cross-Q²**: Is `nameof(SomeClass.Method())` legal?
>
> **A**: No — compile error. `nameof` accepts a *symbol reference*, not an invocation. `nameof(SomeClass.Method)` is legal (returns `"Method"`); `nameof(SomeClass.Method())` makes no sense — there's no name to extract from "the result of calling Method". Similarly `nameof(x + y)` is illegal because `x + y` isn't a name.

### Drill 7 — Boxing of integer constants in `object`

> **Q**: `object o = 5; object p = 5;` — does `ReferenceEquals(o, p)` return true?
>
> **A**: False. Each assignment **boxes** the `int 5` into a fresh heap object — two distinct boxes containing the same value. There is no automatic interning of value-type boxes (unlike string literals).
>
> **Cross-Q**: What about Java's `Integer.valueOf` caching?
>
> **A**: Java caches `Integer` instances for `-128..127` (the so-called integer cache). C# does NOT — every box is a fresh allocation. The reasoning: in C#, `int` and `Int32` are the same type with a value-type identity, and boxing is supposed to be the "escape hatch" you avoid via generics; making it implicitly cached would mask the cost. So `(object)5 != (object)5` by reference in C#.
>
> **Cross-Q²**: How would you make two `int`-as-objects compare equal *by reference*?
>
> **A**: You wouldn't — that's the wrong tool. Use `Equals` or `==` to compare values: `o.Equals(p)` returns `true`. If you need a single shared instance for some optimization, manually intern via a `Dictionary<int, object>`. But the correct answer for "I want to compare two boxed ints" is almost always "don't box in the first place" — use a generic method or `IEquatable<int>`.

### Drill 8 — Default values of fields vs locals

> **Q**: Why does `int x; Console.WriteLine(x);` fail to compile, but `class C { int x; void M() => Console.WriteLine(x); }` works fine?
>
> **A**: **Definite assignment** rule for locals. The C# compiler requires local variables to be assigned before they're read — this is a compile-time check (CS0165). Fields, on the other hand, are auto-initialized to their default value (`0` for `int`, `null` for reference types, `default(T)` for structs) when the containing object is allocated.
>
> **Cross-Q**: Why does the language treat them differently?
>
> **A**: Fields' lifetime is bound to their containing object, and the runtime guarantees zero-init on heap allocations (the CLR clears memory), so a field always has a defined value the moment the object exists. A local has no such moment — its storage is a stack slot reused across calls — so the language demands proof that a write precedes every read. Be precise about the mechanism: C# *does* emit the `.locals init` flag by default, so the stack frame is zeroed too. Definite assignment isn't there to substitute for zeroing; it's a correctness rule that catches "you forgot to set this" at compile time. What it *enables* is the next answer.
>
> **Cross-Q²**: What's `SkipLocalsInitAttribute`?
>
> **A**: An attribute (C# 9 / .NET 5) that removes the `.locals init` IL flag, so the stack frame is no longer zeroed on method entry. `[module: SkipLocalsInit]` applies it to a whole assembly. It's safe for ordinary locals precisely because definite assignment already proves every read follows a write — the language rule is what makes the optimisation legal. It is **not** safe for `stackalloc`, which then hands you whatever was on the stack: with `SkipLocalsInit` on, a `stackalloc` buffer contains garbage rather than zeros, so anything reading before writing leaks previous stack contents. That's the whole trade: the win is real for parsers and IO paths that `stackalloc` large buffers and fill them completely; the hazard is code that assumed zeros.

### Drill 9 — `var` vs explicit type

> **Q**: Is `var x = 5;` the same as `int x = 5;`?
>
> **A**: Identically — `var` is **implicit static typing**, not dynamic. The compiler infers the type at compile time and locks it in. The resulting IL is byte-identical to the explicit-type version.
>
> **Cross-Q**: When does the choice matter?
>
> **A**: Readability and consistency. (1) When the type is obvious from the right-hand side (`var users = new List<User>()`), `var` reduces noise. (2) When the type is not obvious (`var result = SomeMethod();`), explicit types document intent — reviewers shouldn't need to hover to know the return type. (3) For literals, `var x = 0` locks in `int` — if you wanted `long` or `double`, you'd write `0L` or `0.0`, or use the explicit type. Style guides vary; the StyleCop rule is `var` only when the RHS is a `new` expression or a cast.
>
> **Cross-Q²**: What's the difference between `var`, `dynamic`, and `object`?
>
> **A**: `var` = compile-time type inference; full static typing, full IntelliSense, zero runtime cost — the emitted IL is identical to writing the type. `dynamic` = the static type is `object` plus an instruction to defer binding: every member access becomes a DLR call site that resolves the member at run time, allocates and caches a binder, and can throw `RuntimeBinderException`. Describe that cost as "a cached call-site lookup and a delegate invocation instead of a direct call" rather than a multiplier; the exact factor depends on whether the call site's cache hits. `object` = a static type that needs explicit casts to do anything useful. Default to `var` where the right-hand side makes the type obvious; reach for `dynamic` only for COM interop, `ExpandoObject`, or traversing genuinely unknown JSON shapes.

### Drill 10 — Top-level statements and `Program.cs`

> **Q**: What does `Console.WriteLine("hi");` at the top of `Program.cs` compile to?
>
> **A**: The compiler synthesizes a hidden `Program` class with a `Main` method around your top-level code. Roughly: `internal class Program { static async Task<int> Main(string[] args) { ... your code ... } }`. The `args` parameter is implicitly in scope, the return type is inferred (`int` if you `return n;`, `void` otherwise), and the method is `async` if you `await`.
>
> **Cross-Q**: Why is there exactly one allowed top-level-statement file per project?
>
> **A**: Because only one `Main` method is allowed per executable, and top-level statements *are* the `Main`. The compiler errors out if two files contain top-level statements. You also can't declare another `Program` class in the project (unless it's `partial` with the synthesized one) — the compiler reserves the name.
>
> **Cross-Q²**: Can I unit-test code in a top-level-statement Program.cs?
>
> **A**: Yes, but you have to opt in. Add `<InternalsVisibleTo Include="MyTests" />` so the synthesized `internal Program` class is visible to your test project, then write `public partial class Program { }` in your main project to make the access modifier explicit. Alternative: extract the logic into a separate library project and reduce `Program.cs` to thin wiring — the more common pattern.

### Drill 11 — `using static` and when it helps

> **Q**: What does `using static System.Math;` do?
>
> **A**: Brings the static members of `System.Math` into scope, so you can write `Sqrt(2)` instead of `Math.Sqrt(2)`, `PI` instead of `Math.PI`. Compile-time only — no runtime cost, no IL changes.
>
> **Cross-Q**: When is it readable, and when is it noise?
>
> **A**: Readable when (a) the type is universally-known math/conversion utilities (`Math`, `MathF`, `BitOperations`); (b) the file is doing heavy use of those members (a graphics shader translation, a physics sim). Noise when (a) the imported type is a domain-specific helper readers won't recognize; (b) the file uses just one or two static calls — the cost of one extra qualifier is less than the cost of "where did `Foo` come from?".
>
> **Cross-Q²**: What's the interaction with extension methods?
>
> **A**: `using static MyStaticClass` does NOT bring its extension methods into scope as extension methods — it brings them in as static calls. To use extension methods as `obj.Foo()` syntax, you need a regular `using Namespace;`. Senior code review tells: a file that has both forms (`using N;` AND `using static N.SomeClass`) usually has a confused author who doesn't know what each does.

### Drill 12 — `Console.WriteLine(null)` — what prints?

> **Q**: What does `Console.WriteLine(null);` print?
>
> **A**: Trick question — it doesn't compile. `Console.WriteLine` has many overloads, and `null` converts to several of them. The exact compiler error is `CS0121: The call is ambiguous between the following methods or properties: 'Console.WriteLine(char[]?)' and 'Console.WriteLine(string?)'` — note that it is `char[]` versus `string`, **not** `object`: `object` loses to both, because `string` and `char[]` are each more specific, and neither of those two converts to the other, so no winner exists between them. You must cast: `Console.WriteLine((string)null)` prints a blank line; `Console.WriteLine((object)null)` also prints a blank line.
>
> **Cross-Q**: Why doesn't `Console.WriteLine((string?)null)` print "null" like Python or JavaScript?
>
> **A**: Because .NET's `Console.WriteLine(string value)` calls `Out.WriteLine(value)`, which calls `TextWriter.WriteLine(string)`, which writes the string followed by a newline. If the string is `null`, the implementation short-circuits and writes only the newline. The "null" literal in output is a JS/Python convention, not a C# one. If you want it, use `Console.WriteLine(value ?? "null")` or `$"{value ?? "null"}"`.
>
> **Cross-Q²**: What about `Console.WriteLine($"{x}")` when `x` is null?
>
> **A**: Prints an empty string and a newline. The interpolated string handler calls `AppendFormatted(x)`, which for a null reference just appends nothing. Same with `string.Format("{0}", null)` — formats as empty. If you want to surface "null" explicitly, use `x?.ToString() ?? "(null)"` in the interpolation: `$"{x?.ToString() ?? "(null)"}"`.

### Drill 13 — Statement vs expression semantics

> **Q**: When does C# require a *statement* vs an *expression*?
>
> **A**: Loosely: a statement *does*, an expression *computes*. The right-hand side of `=`, the inside of `(...)`, the body of a switch arm — all expression positions. The body of an `if`, the body of a method (when not expression-bodied), the body of a loop — statement positions. C# 6+ added expression-bodied sugar (`=>`) so a single-statement method body can be written as one expression: `int Add(int a, int b) => a + b;`.
>
> **Cross-Q**: What's the difference between `switch` statement and `switch` expression?
>
> **A**: `switch` statement is a control-flow construct — each `case` ends with `break`/`return`/`throw`/`goto`, no value is produced, no exhaustiveness check. `switch` expression (C# 8+) is an expression — each arm has the form `pattern => result`, the whole expression evaluates to one value, and the compiler warns if the patterns aren't exhaustive. Modern code prefers the expression form; statement form remains for cases where you genuinely need side-effecting branches.
>
> **Cross-Q²**: Is `throw` an expression or a statement?
>
> **A**: Both, since C# 7. `throw new Exception();` is a statement. `x ?? throw new ArgumentNullException(nameof(x))` uses `throw` as an expression — the throw "produces a value" of any type (it diverges, so the type-checker assigns it the bottom type and accepts it anywhere a value is expected). Same for the right side of `expr ? a : throw ...` or in switch-expression arms.

### Drill 14 — Definite assignment edge cases

> **Q**: Does `int x; if (cond) x = 1; Console.WriteLine(x);` compile?
>
> **A**: No — definite-assignment analysis sees a path where `cond` is false and `x` is never assigned. Compile error CS0165. The compiler doesn't try to reason about whether `cond` is always true at runtime; the static analysis is conservative.
>
> **Cross-Q**: What about `int x; if (cond) x = 1; else x = 2; Console.WriteLine(x);`?
>
> **A**: Compiles fine. Every path through the `if`/`else` assigns `x`, so the compiler proves `x` is definitely assigned before the read. The analysis is flow-sensitive at the level of basic blocks.
>
> **Cross-Q²**: How does `out var` interact with definite assignment?
>
> **A**: `int.TryParse("5", out var x); Console.WriteLine(x);` is legal — the `out` parameter contract guarantees `TryParse` assigns `x` before returning, regardless of the bool return value (this is `out`'s defining contract). The compiler treats `out var x` as "assignment via a method that promises to write to `x`," which satisfies definite assignment. This is why `TryParse` patterns work fluently in C#.

### Drill 15 — Modern C# string handling

> **Q**: What's the difference between `@"..."` and `"""..."""` strings?
>
> **A**: `@"..."` is a **verbatim** string — backslashes are literal, line breaks are part of the string, and `""` is the escape for a literal `"`. `"""..."""` is a **raw** string (C# 11) — *everything* between the opening and closing `"""` is literal, including any `"` (up to N-1 quotes where N is the count of opening quotes). Raw strings also strip common leading whitespace based on the closing `"""` indent.
>
> **Cross-Q**: When does each beat the other?
>
> **A**: Verbatim wins for short Windows paths (`@"C:\temp"`) and regexes that have many `\`. Raw strings win for embedded JSON, SQL, XML, or anything with `"` — no escaping is needed at all. For new code in 2026, raw strings are the default for multi-line embedded content; verbatim is mostly used for paths and short single-line content.
>
> **Cross-Q²**: What's `$$"""..."""`?
>
> **A**: A raw interpolated string where the interpolation hole is `{{...}}` instead of `{...}`. The `$$` prefix tells the compiler "the interpolation requires *two* braces to start." This lets you embed JSON (which uses single `{` `}` braces) without escaping: `$$"""{ "name": "{{name}}" }"""`. With a single `$`, the literal `{` in the JSON would need to be `{{` to escape. The count of `$` matches the count of braces needed for an interpolation hole.

### Drill 16 — Implicit conversions and rounding

> **Q**: `int i = 16_777_217; float f = i;` — does this compile, and is `i == (int)f`?
>
> **A**: It compiles with no cast, because `int → float` is an *implicit* conversion. And `i == (int)f` is **False** — `f` is 16,777,216. Implicit in C# means "no loss of magnitude", not "no loss of information": Microsoft Learn states that `int`/`uint`/`long`/`ulong`/`nint`/`nuint` → `float` and `long`/`ulong`/`nint`/`nuint` → `double` can lose precision. `float` has 24 bits of significand, so consecutive integers stop being representable past 2²⁴.
>
> **Cross-Q**: `byte a = 200, b = 100;` — why does `byte c = a + b;` fail to compile while `a += b;` succeeds, and what is `a` afterwards?
>
> **A**: `byte`, `sbyte`, `short`, `ushort` and `char` define only `++` and `--`; every other arithmetic operator promotes its operands to `int`, so `a + b` is an `int` with the value 300 and cannot implicitly narrow back to `byte` (CS0266). Compound assignment is defined differently: `x op= y` means `x = (T)(x op y)`, with an *explicit* conversion inserted for you. So `a += b` compiles and `a` becomes **44** — 300 truncated into a byte. In a `checked` context the same line throws `OverflowException` instead.
>
> **Cross-Q²**: `(int)2.5`, `Convert.ToInt32(2.5)`, `Math.Round(2.5)` — three answers, which are they and why?
>
> **A**: `2`, `2`, `2` — but for two different reasons, which is the point. The cast **truncates toward zero** (so `(int)3.5` is `3` and `(int)(-2.7)` is `-2`). `Convert.ToInt32` and `Math.Round` **round half to even** — Learn's wording is "if value is halfway between two whole numbers, the even number is returned; that is, 4.5 is converted to 4, and 5.5 is converted to 6" — so `Convert.ToInt32(3.5)` is `4`. Banker's rounding is unbiased over many values and is what most accounting rules want, and it is not what a reader assumes. Pass `MidpointRounding` explicitly on anything financial. For a boundary that must never throw or wrap, .NET 7+ generic math gives you the policy by name: `CreateChecked` (throw), `CreateSaturating` (clamp), `CreateTruncating` (keep low bits).

### Drill 17 — Closures and the captured loop variable

> **Q**: `for (int i = 0; i < 3; i++) list.Add(() => i);` — what do the three delegates return?
>
> **A**: `3, 3, 3`. The `for` variable is declared once, so the compiler hoists it into a single display-class field that all three lambdas share, and by the time they run the loop has finished and the field holds 3. Change it to `foreach (var i in new[]{0,1,2})` and you get `0, 1, 2`, because the `foreach` iteration variable is a **fresh variable per iteration** — a deliberate change in C# 5 made precisely because the old shared behaviour was a permanent source of bugs.
>
> **Cross-Q**: What actually happens to a captured local at the IL level?
>
> **A**: The compiler generates a *display class* and rewrites the method: the captured local becomes a field on a heap-allocated instance of that class, and every reference to it — inside the lambda and in the original method body — is rewritten to touch that field. That is why the lambda and the enclosing method see the same storage, and why the variable's lifetime is now the delegate's lifetime rather than the block's. One allocation per capturing scope, not per captured variable.
>
> **Cross-Q²**: A singleton holds a `Func<Task>` registered by a scoped service. What's the leak, and how does the language help you prevent it?
>
> **A**: If the lambda touches any instance member, it captures `this`, so the display class roots the whole scoped object — and anything it holds, typically a `DbContext` — for as long as the singleton lives. The usual symptom isn't `OutOfMemoryException`, it's `ObjectDisposedException` from a captured, already-disposed context, which sends people looking in the wrong place. The language-level prevention is `static` lambdas (C# 9) and `static` local functions (C# 8): they cannot reference enclosing locals, parameters or `this`, so an accidental capture becomes a compile error. Resolve what you need inside the callback from an `IServiceScopeFactory` instead.

### Drill 18 — Parsing, culture, and the invariant boundary

> **Q**: On a server whose `CurrentCulture` is `de-DE`, what does `double.Parse("1.5")` return?
>
> **A**: `15`. No exception, no warning. `'.'` is the group separator in `de-DE`, the default `NumberStyles` for `Parse` includes `AllowThousands`, so `"1.5"` reads as "one thousand five with a stray separator". A parse with no explicit `IFormatProvider` is a call whose behaviour is decided by an environment variable.
>
> **Cross-Q**: What's the rule you'd put in a code-review checklist?
>
> **A**: Machines talk to machines in `InvariantCulture`; humans see `CurrentCulture`; identifiers and protocol tokens aren't a culture question at all and use `StringComparison.Ordinal`. Concretely: `InvariantCulture` for config, CSV, HTTP payloads, database strings and cross-service JSON; `CurrentCulture` (or the user's stored preference) only at the rendering edge. Enforce it mechanically with `CA1305` (specify `IFormatProvider`) and `CA1307`/`CA1309` (specify / prefer ordinal `StringComparison`) rather than by asking reviewers to remember.
>
> **Cross-Q²**: Give an example where a culture-sensitive comparison is a security bug.
>
> **A**: The Turkish-I problem, documented by Microsoft Learn. `tr-TR` has a dotted capital `İ` and a dotless lowercase `ı`, so `i` does not uppercase to `I`. A guard written as `path.StartsWith("FILE:", ignoreCase: true, culture)` returns `true` on an English system and `false` on a Turkish one, and Learn spells out the consequence — on Turkish systems someone could get past a block on `FILE:` URIs. Any case-insensitive check on a scheme, header, extension, role or flag must be `OrdinalIgnoreCase`. Related: `.NET 5` switched Windows globalization from NLS to ICU, and the documented example `"Hello\r\nworld!".IndexOf("\n")` returned `6` on .NET Core 3.1, `-1` on .NET 5, and `6` again on .NET 6+ — three answers for one line across three runtimes, all avoided by passing `StringComparison.Ordinal`.

</details>
## Cheat Sheet

- **Statement vs expression**: statement *does*, expression *computes*; `switch` has both forms.
- **`var`**: implicit *static* typing — type locked at compile time, not `dynamic`.
- **Primitives**: 15 types; `int = System.Int32`; suffix `L`/`U`/`m`/`f` picks literal type.
- **Definite assignment**: locals must be written before read; fields default to `0`/`null`/`false`.
- **`string` immutable**: every `Replace`/`Trim`/`Substring` allocates — use `StringBuilder` in loops.
- **`==` on strings**: value-equal (overloaded); on most reference types it's reference-equal.
- **Parameter modifiers**: `ref` (in/out), `out` (must assign), `in` (readonly ref), `params` (variadic).
- **Null operators**: `?.` short-circuits, `??` coalesces, `??=` assigns-if-null, `!` is compile-only.
- **Integer overflow silent**: wrap in `checked { }` or set `<CheckForOverflowUnderflow>true</`.
- **Raw strings `"""`**: literal everything; verbatim `@""` only escapes `""` to `"`.
- **Implicit ≠ lossless**: `int → float`, `long → double` keep magnitude, drop precision.
- **`byte + byte` is `int`**; `byte += byte` compiles because `op=` inserts the cast back (and truncates).
- **Cast truncates, `Convert` rounds half-to-even**: `(int)3.5 == 3`, `Convert.ToInt32(3.5) == 4`.
- **Parse/format**: `InvariantCulture` for machines, `CurrentCulture` for humans — `double.Parse("1.5")` is `15` in `de-DE`.
- **Compare**: `==` and `IndexOf(char)` ordinal; `IndexOf(string)`, `StartsWith`, `Compare` linguistic.
- **`Length` counts UTF-16 code units**: emoji are 2; `Rune` for scalars, `StringInfo` for what users see.
- **Closures**: captured locals become fields of a heap display class; `for` shares one, `foreach` doesn't.
- **`const` is copied into callers**; `static readonly` is read at run time. Same for optional-parameter defaults.

## Walkthrough — Silent int overflow in billing

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A billing service computes `totalCents = priceCents * quantity` and ships fine for years. After a B2B customer orders 50,000 of a $500 item, the invoice shows a *negative* total and the payment processor returns "amount invalid."

**Diagnosis**: `priceCents` is `int` (50000), `quantity` is `int` (50000), product is 2,500,000,000 — exceeds `int.MaxValue` (2,147,483,647) by ~350M. The multiplication wraps silently to a negative `int`. Senior tells: search the codebase for arithmetic on monetary fields with `Grep` for `\*\s*[Qq]uantity` or `\*\s*[Pp]rice`; check the project file for `<CheckForOverflowUnderflow>` (almost certainly absent — it's `false` by default in Release). Reproduce locally with `checked { var x = 50_000 * 50_000; }` — `OverflowException` confirms.

**Fix**: Two layers. (1) Cast operands wide before multiplying: `long total = (long)priceCents * quantity;`. (2) Add `<CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>` to the project file so future violations throw instead of wrapping. (3) Long-term — use `decimal` for monetary values; it can't overflow under realistic magnitudes and avoids floating-point errors.

```xml
<PropertyGroup>
  <CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>
</PropertyGroup>
```

**Why it works**: C# integer ops are silent-wrap by default for performance — the `checked` context (or project flag) inserts overflow-detection instructions. Casting one operand to `long` widens the operation so the multiplication occurs in 64-bit space.

</details>
## Self-test

<details>
<summary>1. What's the difference between `var x = 0;` and `dynamic x = 0;`?</summary>

`var x = 0;` is *implicit static typing* — the compiler infers `int` and locks it at compile time; `x = "hello"` is a compile error and IntelliSense works fully. `dynamic x = 0;` defers all type-checking to the DLR (Dynamic Language Runtime); `x = "hello"; x.NotARealMethod();` compiles and only fails at runtime with `RuntimeBinderException`. `var` has zero runtime cost — identical IL to the explicit type. `dynamic` turns each member access into a call site that must bind at run time, allocating and caching a binder and dispatching through a delegate rather than a direct call.
</details>

<details>
<summary>2. Why does `string.Concat` in a loop kill performance, and what are the three modern alternatives?</summary>

Strings are immutable; `s += "x"` allocates a new string and copies the old contents every iteration — O(n²) total. Alternatives: (1) `StringBuilder` for unknown-length builds (amortized O(n)); (2) `string.Create(length, state, span => ...)` for known-length hot paths (single allocation, no intermediate `char[]`); (3) interpolated string handlers (C# 10+) which `ILogger` and `Debug.Assert` use — the formatter only allocates if the message is actually consumed.
</details>

<details>
<summary>3. Apply: a colleague writes `void Process(in LargeStruct s) { s = newValue; }` and gets a compile error. Explain what `in` means and how to fix without losing the perf benefit.</summary>

`in` passes a struct by readonly reference — avoids the copy of a value type, but the parameter is immutable inside the method. To mutate without copying, change to `ref`. To keep readonly intent but compute a derived value, return it: `LargeStruct Compute(in LargeStruct s) => s with { Field = newValue };`. The performance benefit of `in` (no copy) is preserved; mutation requires explicit `ref` or returning a new struct (cheap if it's small or you use `with`).
</details>

<details>
<summary>4. Analyze: `Console.WriteLine($"User {user.Name} logged in");` — when does this allocate, and how do interpolated string handlers change it?</summary>

In classic C# (≤ 9), the interpolation always allocates: `string.Format` is called, which boxes any value-type args into `object[]` and allocates the result string. From C# 10, the compiler instead lowers an interpolated string to `DefaultInterpolatedStringHandler` — a `ref struct` that appends each component into a pooled buffer and produces one string at the end, avoiding the `object[]` and much of the boxing. An API can go further by declaring its own handler parameter (`[InterpolatedStringHandlerArgument]`) and refusing to build the string at all: `Debug.Assert` does exactly this with `AssertInterpolatedStringHandler` (.NET 6+), so a passing assert formats nothing. Two important negatives: `Console.WriteLine` has no such handler, and neither does `ILogger` — interpolating into `LogInformation` formats eagerly *and* loses the message template that structured logging depends on. Use `[LoggerMessage]` there.
</details>

<details>
<summary>5. Trade-off: when would you choose `decimal` over `double`, and what's the cost?</summary>

Choose `decimal` for any value humans count in base-10 — money, percentages, tax rates — because `double` is base-2 and can't represent `0.1` exactly, leading to drift like `0.1 + 0.2 == 0.30000000000000004` and, worse, to totals that depend on the order of summation. Cost, stated as mechanism: `decimal` is 128 bits (a 96-bit integer plus sign and a base-10 scale) against 64, so it costs cache and bandwidth; its arithmetic is software routines that must align scales rather than single vectorisable FPU instructions. Large in a numeric inner loop, invisible next to a database round-trip — measure the specific loop rather than quoting a factor. For scientific/graphics/ML where rounding errors are part of the model and throughput matters, stick with `double`. Never use `float`/`double` for currency, ever.
</details>

## Cross-references

- **Next file: [Type System Deep Dive](./02-type-system.md)** — value vs reference, structs vs records, `ref struct`.
- **[Modern C# Features](../01-net-core-deep-dive/12-modern-csharp.md)** — single-file reference for C# 9–12 additions (records, primary ctors, collection expressions).
- **[.NET Fundamentals — C# Core Concepts](../01-net-core-deep-dive/01-net-fundamentals.md#2-c-core-concepts)** — the lighter intro this file expands on.
- **[Version History](../01-net-core-deep-dive/18-version-history.md)** — which features shipped in which C# release.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [C# language tour](https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/).
- Microsoft Learn — [C# language specification](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/language-specification/).
- Joseph Albahari — *C# 12 in a Nutshell* (O'Reilly), chapters 2–5.
- Mads Torgersen on Roslyn / language design — [GitHub: dotnet/csharplang](https://github.com/dotnet/csharplang), and the [language version history](https://github.com/dotnet/csharplang/blob/main/Language-Version-History.md) for feature gates.
- Microsoft Learn — [Built-in numeric conversions](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/builtin-types/numeric-conversions) (implicit/explicit tables, precision-loss note, checked/unchecked behaviour).
- Microsoft Learn — [Arithmetic operators](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/arithmetic-operators) (numeric promotion, compound-assignment cast, user-defined `checked` operators).
- Microsoft Learn — [`System.Decimal`](https://learn.microsoft.com/en-us/dotnet/api/system.decimal) (96-bit integer + scale 0–28, trailing-zero preservation) and [`Convert.ToInt32`](https://learn.microsoft.com/en-us/dotnet/api/system.convert.toint32) (round-half-to-even).
- Microsoft Learn — [Method parameters and modifiers](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/keywords/method-parameters) (`in`, `ref readonly`, `params` collections).
- Microsoft Learn — [Best practices for comparing strings](https://learn.microsoft.com/en-us/dotnet/standard/base-types/best-practices-strings) (ordinal vs linguistic defaults, Turkish-I, `ToUpperInvariant`).
- Microsoft Learn — [Breaking change: globalization APIs use ICU on Windows](https://learn.microsoft.com/en-us/dotnet/core/compatibility/globalization/5.0/icu-globalization-api) (the `IndexOf("\n")` example).
- Microsoft Learn — [Breaking change: overload resolution prefers `params` span overloads](https://learn.microsoft.com/en-us/dotnet/core/compatibility/core-libraries/9.0/params-overloads) (the .NET 9 API list).
- Microsoft Learn — [`const` keyword](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/keywords/const) (constant propagation and the recompilation requirement).
- Microsoft Learn — [`INumberBase<TSelf>`](https://learn.microsoft.com/en-us/dotnet/api/system.numerics.inumberbase-1) (`CreateChecked` / `CreateSaturating` / `CreateTruncating`, .NET 7+).

</details>
<!-- nav-footer-start -->

---

[← Previous: C# Mastery — Basics to Advanced](README.md) · [↑ Back to top](#c-fundamentals) · [Next: Type System Deep Dive →](02-type-system.md)

<!-- nav-footer-end -->
