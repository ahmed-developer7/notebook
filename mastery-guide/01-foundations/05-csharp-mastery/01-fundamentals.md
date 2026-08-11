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
  - [Operators](#operators)
  - [`checked` / `unchecked` and integer overflow](#checked--unchecked-and-integer-overflow)
  - [Control flow](#control-flow)
  - [Methods and parameters](#methods-and-parameters)
  - [`ref` / `out` / `in` — parameter semantics at the IL level](#ref--out--in--parameter-semantics-at-the-il-level)
  - [`params` arrays and collection-expression parameters (C# 12+)](#params-arrays-and-collection-expression-parameters-c-12)
  - [Strings — the surprisingly deep type](#strings--the-surprisingly-deep-type)
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
var j = 1_000_000;  // digit separators (any position)
```

**Decimal vs double for money:** `decimal` is base-10, `double` is base-2. `0.1 + 0.2 == 0.3` is `false` in `double` but `true` in `decimal`. Always `decimal` for currency, never `double`. The next section walks through why.

**`var` is not dynamic.** `var` is *implicit static typing* — the compiler infers the type at compile time. Once inferred, it's locked in. `var x = 5;` is identical to `int x = 5;`. If you want runtime typing (which you almost never do), that's `dynamic`.

### `decimal` vs `double` vs `float` — picking the right real number

The three real-number types in C# look interchangeable in toy code. They are not. Choosing wrong silently corrupts financial reports, breaks tax math by a cent per million transactions, and burns afternoons on "why is the total off by 0.00000000000004?"

**The fundamental split: base-2 vs base-10.**

```
┌──────────────────────────────────────────────────────────────────┐
│  float   (System.Single)   4 bytes   IEEE-754 binary32          │
│  double  (System.Double)   8 bytes   IEEE-754 binary64          │
│  decimal (System.Decimal) 16 bytes   IEEE-754 decimal128 (~28d) │
└──────────────────────────────────────────────────────────────────┘
```

`float` and `double` are **binary** floating point — they store numbers as `mantissa × 2^exponent`. Most "nice" decimal fractions (`0.1`, `0.2`, `0.3`) **cannot be represented exactly** in binary, the same way `1/3` cannot be represented exactly in base-10 (`0.333...`).

`decimal` is **decimal** floating point — `mantissa × 10^exponent`. Every base-10 fraction the human writes down is representable exactly (up to 28-29 significant digits).

**The canonical demo every interviewer expects:**

```csharp
double a = 0.1, b = 0.2;
Console.WriteLine(a + b);             // 0.30000000000000004
Console.WriteLine(a + b == 0.3);      // False

decimal c = 0.1m, d = 0.2m;
Console.WriteLine(c + d);             // 0.3
Console.WriteLine(c + d == 0.3m);     // True
```

The `double` result is *not a bug* — it's the closest binary representation of 0.3 differing from `0.1 + 0.2` (also each "the closest binary"). The error accumulates over millions of operations; in a payment processor handling 10M transactions/day, a drift of `1e-15` per op accumulates to noticeable cents over a quarter.

**Comparison matrix:**

| | `float` | `double` | `decimal` |
|---|---|---|---|
| Size | 4 bytes | 8 bytes | 16 bytes |
| Precision | ~7 decimal digits | ~15-17 decimal digits | 28-29 decimal digits |
| Range | ±3.4 × 10³⁸ | ±1.7 × 10³⁰⁸ | ±7.9 × 10²⁸ |
| Exact `0.1` | ✗ | ✗ | ✓ |
| Hardware-accelerated | ✓ SIMD/FPU | ✓ SIMD/FPU | ✗ software emulation |
| Speed (relative) | 1× | 1× | 10-30× slower |
| Default literal suffix | `f` (required) | (none) | `m` (required) |
| Use for | Graphics, ML, sensors | Scientific, statistics | Money, percentages, anything counted in base-10 |

**Decision rules:**

- **Money, ever?** → `decimal`. Non-negotiable. If a financial auditor would ask "did the math reconcile to the cent?", use `decimal`.
- **Physics / graphics / ML / signal processing?** → `double`. Speed dominates, the underlying domain is continuous, rounding errors are part of the model.
- **Memory-constrained sensor / shader data?** → `float`. Only if you've measured that the smaller size wins (cache hits, vectorization width).
- **Default for "a number with decimals"?** → `double` — it's the unsuffixed literal type. But the moment that number represents *currency*, *tax*, *interest*, *commission*, or *anything an accountant tracks*, switch to `decimal`.

**Common pitfalls:**

1. **Storing money as `double` "because it's faster"** — the speed advantage doesn't help when QA reports drift on the year-end statement. `decimal` for money is the engineering equivalent of brushing your teeth: non-optional.
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

C# does not have JavaScript-style hoisting; declaration order generally matters within a method. Two variables with the same name in nested scopes is an error (`CS0136`), unlike C++.

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

`add.ovf` is roughly 2-3x slower than `add` on modern CPUs (an extra branch on the flags register). For 99% of business code that's irrelevant; for tight numerical loops it's measurable.

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

Default-on overflow checking in `Debug` and `Release` for any project handling money, IDs, sizes, time durations, or cryptographic counters. Annotate the rare hot loops where wrap is *intentional* (hash mixing, CRCs) with `unchecked { }`. The cost is a tiny perf hit; the benefit is loud failures instead of silent corruption.

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

`ref` returns are how `List<T>.AsSpan()`, `Dictionary<K,V>`'s ref accessor (`CollectionsMarshal.GetValueRefOrNullRef`), and `Span<T>` indexers avoid copying. Powerful but easy to misuse — if the underlying storage is freed or relocated, the ref dangles. The compiler enforces lifetime rules statically.

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

**The immutability vs `StringBuilder` perf story.** Because strings are immutable, every "modification" allocates. In a loop:

```csharp
// O(n²) — each += allocates a new string and copies all previous content
string s = "";
for (int i = 0; i < 10_000; i++) s += i.ToString();
// ~50 million chars copied total. ~10K allocations.

// O(n) — StringBuilder mutates an internal buffer
var sb = new StringBuilder();
for (int i = 0; i < 10_000; i++) sb.Append(i);
string s = sb.ToString();
// ~10K chars copied at the final ToString. A few buffer-resize allocs.
```

For < 5 appends, `+` or `$""` is faster (no `StringBuilder` overhead). For > 100 appends in a loop, `StringBuilder` wins. For known-length builds in hot paths, `string.Create(length, state, (span, s) => ...)` allocates exactly once and fills the buffer directly.

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

## Interview-ready summary

- **C# is statically typed, garbage-collected, multi-paradigm** (OOP + functional + imperative).
- **15 primitive types** map to CLR `System.*` types — `int` ≡ `System.Int32`. Suffixes pick non-default literal types (`5L`, `5.0m`, `5U`).
- **`var` is implicit static typing**, not dynamic. `dynamic` is true runtime typing (rarely used, slower, no IntelliSense).
- **Definite assignment** — locals must be assigned before read; fields auto-default. The compiler enforces this.
- **Strings are immutable reference types with value-like equality.** Use `StringBuilder` for tight loops, `string.Create` for hot paths, raw strings (`"""`) for embedded JSON/SQL.
- **Parameter modifiers**: `ref` (in/out reference), `out` (must assign), `in` (read-only reference, often used with structs to avoid copies), `params` (variadic).
- **Null operators**: `?.` (conditional access), `??` (coalescing), `??=` (coalescing assignment), `!` (forgiving — compile-time hint, no runtime effect).
- **Top-level statements (C# 9)** + **file-scoped namespaces (C# 10)** + **global usings (C# 10)** = modern minimal-ceremony C#.
- **`switch` expression > `switch` statement** in modern code: terser, exhaustiveness-checked, no fallthrough hazard.
- **Integer arithmetic is silent-wrap by default.** Use `checked` for safety-critical math.

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
> **A**: `add.ovf` is ~2-3× slower than `add` because of the extra branch on the CPU's overflow flag. For 99% of business code that's irrelevant; for tight numerical loops it's measurable. Inside a `checked` project, you'd `unchecked { ... }` around CRCs, hash mixing, ring-buffer counters, and pseudo-random number generators — code that **intentionally** wraps as part of the algorithm. The `checked` default catches accidents; explicit `unchecked` documents the intent of the rare correct overflow.

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
> **A**: `double` is base-2 floating point — most "nice" decimal fractions (`0.1`, `0.2`, `0.3`) can't be represented exactly in binary. `0.1 + 0.2 == 0.3` is `false` in `double`. `decimal` is base-10 floating point and represents every base-10 fraction exactly up to 28-29 significant digits. For values an accountant tracks, `decimal` is non-negotiable.
>
> **Cross-Q**: What's the perf cost of choosing `decimal`?
>
> **A**: Roughly 10-30× slower than `double`. `double` is hardware-accelerated (FPU, SIMD); `decimal` is software-emulated on the CPU's integer unit. `decimal` is also 16 bytes vs 8 — twice the memory bandwidth. For 1M arithmetic ops per second the difference is invisible; for tight numerical inner loops (Monte Carlo, simulation) it matters a lot. For business apps, the perf cost is a rounding error compared to one DB round-trip.
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
> **A**: Source generators + interpolated string handlers. `Microsoft.Extensions.Logging.LoggerMessage` and `[LoggerMessage]` source-generated wrappers produce strongly-typed overloads — `Log<T1, T2>(string fmt, T1 a, T2 b)` — that never allocate `object[]` or box value types. C# 10's `LoggerExtensions.LogInformation($"User {id} logged in")` uses an interpolated string handler that captures arguments inline and only formats if the log level is enabled.
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
> **A**: Fields' lifetime is bound to their containing object, and the runtime guarantees zero-init on heap allocations (the CLR clears memory). Locals live on the stack frame, which is **not** auto-zeroed for perf — the JIT skips zero-init for performance unless `localsinit` is set. Definite-assignment analysis enforces safety without paying the zero-init cost.
>
> **Cross-Q²**: What's `SkipLocalsInitAttribute`?
>
> **A**: A .NET 5+ attribute that lets you opt out of CLR-mandated local-variable zero-init. `[module: SkipLocalsInit]` removes the `.locals init` IL flag, saving the cost of zeroing the stack frame on method entry. Safe to use because the compiler's definite-assignment rules already prove all reads are preceded by writes. Mostly relevant for high-perf code (System.IO, parsers) doing `stackalloc` of large buffers; in those cases the saved zero-init is measurable.

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
> **A**: `var` = compile-time type inference; full static typing, full IntelliSense, zero runtime cost. `dynamic` = compile-time type *erasure*; member access is resolved by the DLR (Dynamic Language Runtime) at runtime — slower (~10-50× per access), no IntelliSense, runtime errors. `object` = the static type, requiring explicit casts to do anything useful; intermediate verbosity. Default to `var` for readability when the RHS makes the type clear; reach for `dynamic` only for COM interop, `ExpandoObject`, or `JsonElement` traversal where types genuinely aren't known until runtime.

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
> **A**: Trick question — it doesn't compile. `Console.WriteLine` has many overloads (`(int)`, `(string)`, `(object)`, etc.), and `null` is ambiguous between `string` and `object`. The compiler errors: "CS0121: The call is ambiguous between `WriteLine(string)` and `WriteLine(object)`." You must cast: `Console.WriteLine((string)null)` prints a blank line; `Console.WriteLine((object)null)` also prints a blank line (boxes nothing, formats as empty).
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

`var x = 0;` is *implicit static typing* — the compiler infers `int` and locks it at compile time; `x = "hello"` is a compile error and IntelliSense works fully. `dynamic x = 0;` defers all type-checking to the DLR (Dynamic Language Runtime); `x = "hello"; x.NotARealMethod();` compiles and only fails at runtime. `var` has zero runtime cost; `dynamic` involves runtime binder lookups (~10-50× slower for member access).
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

In classic C# (≤ 9), the interpolation always allocates: `string.Format` is called, which boxes any value-type args into `object[]` and allocates the result string. From C# 10+ with interpolated string handlers, APIs like `ILogger.LogInformation` and `Debug.Assert` accept `[InterpolatedStringHandlerArgument]` parameters; the compiler rewrites the interpolation into per-component `AppendFormatted` calls, and if the log level is filtered out (e.g., `Information` disabled), the handler short-circuits and *nothing allocates*. `Console.WriteLine` doesn't use this handler — still allocates.
</details>

<details>
<summary>5. Trade-off: when would you choose `decimal` over `double`, and what's the cost?</summary>

Choose `decimal` for any value humans count in base-10 — money, percentages, tax rates — because `double` is base-2 and can't represent `0.1` exactly, leading to drift like `0.1 + 0.2 == 0.30000000000000004`. Cost: `decimal` is 128-bit (vs 64), arithmetic is software-emulated (no SIMD), and is roughly 10-30× slower than `double`. For scientific/graphics/ML where rounding errors are acceptable and throughput matters, stick with `double`. Never use `float`/`double` for currency, ever.
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
- Mads Torgersen on Roslyn / language design — [GitHub: dotnet/csharplang](https://github.com/dotnet/csharplang).

</details>
<!-- nav-footer-start -->

---

[← Previous: C# Mastery — Basics to Advanced](README.md) · [↑ Back to top](#c-fundamentals) · [Next: Type System Deep Dive →](02-type-system.md)

<!-- nav-footer-end -->
