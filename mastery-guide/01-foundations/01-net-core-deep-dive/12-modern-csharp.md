# Modern C# Features

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-08 |

> 📖 **Companion files**: deeper, topical treatment lives in [C# Mastery](../05-csharp-mastery/README.md). Per-version language deltas (C# 11 → C# 14) live in [.NET Version History](./18-version-history.md). This file is the **single-page reference**: every feature you should be using on .NET 10, with the trade-offs spelled out.

**Level:** Beginner to Advanced &nbsp;·&nbsp; **Reading time:** ~30 min &nbsp;·&nbsp; **Scope:** C# 10–14 features that change how you write everyday production code.

---

## Why Modern C# Matters

The C# you write today should not look like the C# you wrote in 2018. Records replaced ~80% of hand-written DTOs. Pattern matching replaced sprawling `if/else` ladders and most of the visitor-pattern boilerplate. Nullable reference types replaced runtime `NullReferenceException` discovery with compile-time errors. Primary constructors deleted the field-and-constructor ceremony that every DI'd service used to start with.

Each individual feature looks small. Together they make idiomatic .NET 10 code dramatically shorter, safer, and clearer than the .NET Framework era — and crucially, they shift entire classes of bug from runtime to compile time. A team that has internalized these features ships fewer null bugs, fewer mutability bugs, and fewer "did I match every case" bugs.

This file is structured as a reference: each feature has a properties box, a "without/with" comparison, when-to-use vs when-not-to-use guidance, and worked examples. Skim for what you need, or read top-to-bottom to upgrade an old codebase mentally in one sitting.

## Contents
- [Modern C# Features](#23-modern-c-features)
  - [Record Types (C# 9+)](#record-types-c-9)
  - [Pattern Matching (C# 8-12)](#pattern-matching-c-8-12)
  - [Primary Constructors (C# 12)](#primary-constructors-c-12)
  - [Collection Expressions (C# 12)](#collection-expressions-c-12)
  - [Raw String Literals (C# 11)](#raw-string-literals-c-11)
  - [Required Members (C# 11)](#required-members-c-11)

---

## 23. Modern C# Features

### Table of Contents
1. [Introduction](#introduction)
2. [Record Types (C# 9+)](#record-types-c-9)
3. [Init-Only Setters (C# 9)](#init-only-setters-c-9)
4. [Required Members (C# 11)](#required-members-c-11)
5. [Primary Constructors (C# 12)](#primary-constructors-c-12)
6. [Pattern Matching (C# 8-12)](#pattern-matching-c-8-12)
7. [Collection Expressions (C# 12)](#collection-expressions-c-12)
8. [Raw String Literals (C# 11)](#raw-string-literals-c-11)
9. [File-Scoped Namespaces & Top-Level Statements](#file-scoped-namespaces--top-level-statements)
10. [Implicit & Target-Typed `new` (C# 9)](#implicit--target-typed-new-c-9)
11. [Nullable Reference Types (C# 8)](#nullable-reference-types-c-8)
12. [`Span<T>` and `Memory<T>` — basics](#spant-and-memoryt--basics)
13. [Source Generators — what to know](#source-generators--what-to-know)
14. [Comparison Matrix — Old vs Modern Idioms](#comparison-matrix--old-vs-modern-idioms)
15. [Common Pitfalls](#common-pitfalls)
16. [Best Practices](#best-practices)
17. [Real-World Scenarios](#real-world-scenarios)
18. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
19. [Cross-References](#cross-references)
20. [Sources](#sources)

---

### Introduction

#### Without modern C# vs With modern C#

```
WITHOUT MODERN C# (C# 7-era DTO + handler):
─────────────────────────────────────────────
public class CreateOrderCommand
{
    public string CustomerName { get; set; }
    public List<OrderLine> Lines { get; set; }
    public CreateOrderCommand() { Lines = new List<OrderLine>(); }
    public CreateOrderCommand(string name, List<OrderLine> lines)
    { CustomerName = name; Lines = lines ?? new List<OrderLine>(); }
    public override bool Equals(object obj) { /* ... 15 lines ... */ }
    public override int GetHashCode()       { /* ... 8 lines ... */ }
}

public class OrderHandler
{
    private readonly IOrderRepo _repo;
    private readonly ILogger<OrderHandler> _logger;
    public OrderHandler(IOrderRepo repo, ILogger<OrderHandler> logger)
    { _repo = repo; _logger = logger; }

    public string ClassifyTotal(decimal total)
    {
        if (total < 0) throw new ArgumentException();
        if (total == 0) return "Free";
        else if (total < 100) return "Small";
        else if (total < 1000) return "Medium";
        else return "Large";
    }
}
~ 35 lines, 4 NREs waiting to happen, equality you'll forget to update.

WITH MODERN C# (.NET 10):
─────────────────────────────────────────────
public record CreateOrderCommand(
    string CustomerName,
    IReadOnlyList<OrderLine> Lines);

public class OrderHandler(IOrderRepo repo, ILogger<OrderHandler> logger)
{
    public string ClassifyTotal(decimal total) => total switch
    {
        < 0    => throw new ArgumentException(),
          0    => "Free",
        < 100  => "Small",
        < 1000 => "Medium",
        _      => "Large"
    };
}
~ 12 lines. Equality and immutability for free. Total exhaustiveness checked.
```

Same behavior. Less code, fewer bugs, more obvious intent.

#### Real-world analogy: the standard kitchen

A 1990s kitchen had one knife, one pan, and a stove. You learned to do everything with that. A modern kitchen has a knife, a pan, a stove — *and* a microwave, food processor, immersion blender, sous-vide. None of the new tools replace the old. But "I'll just use the knife for everything" is now a sign you're ignoring purpose-built tools that exist for the cases that come up daily.

Modern C# features are those tools. `record` doesn't replace `class`; it replaces *the cases where you wrote a class because that was the only option*. Each feature in this file is the right tool for a specific recurring case.

---

### Record Types (C# 9+)

```
┌────────────────────────────────────────┐
│ record / record struct Properties      │
├────────────────────────────────────────┤
│ ✓ Value-based equality (auto)          │
│ ✓ Concise primary-ctor syntax          │
│ ✓ Non-destructive `with` mutation      │
│ ✓ Auto-generated ToString              │
│ ✓ Deconstruction support               │
│ ✓ `record struct` for value-type perf  │
│ ✗ Not a free pass — still a heap obj   │
│   (unless `record struct`)             │
│ ✗ Equality includes ALL public members │
│   (collections compared by reference!) │
└────────────────────────────────────────┘
```

```csharp
// Positional record (most common for DTOs):
public record UserDto(string Name, string Email, string Role);

var user  = new UserDto("Ahmed", "ahmed@x.com", "User");
var admin = user with { Role = "Admin" };       // non-destructive copy

// Value equality, not reference equality:
var u1 = new UserDto("Ahmed", "ahmed@x.com", "User");
var u2 = new UserDto("Ahmed", "ahmed@x.com", "User");
Console.WriteLine(u1 == u2);                    // True
Console.WriteLine(ReferenceEquals(u1, u2));     // False

// Deconstruction:
var (name, email, _) = user;

// ToString is auto-generated, useful in logs:
Console.WriteLine(user);  // UserDto { Name = Ahmed, Email = ahmed@x.com, Role = User }
```

#### Class records vs record structs

```
record (reference type)              record struct (value type)
──────────────────────              ──────────────────────────
Heap-allocated                       Stack/inline-allocated
GC-tracked                           Not GC-tracked
Cheap copy = copy reference          Copy = full bitwise copy
Use for: DTOs, command messages,     Use for: small, hot, short-lived
        immutable domain values              points, vectors, tuples-with-meaning
```

```csharp
public record       Customer(int Id, string Name, decimal Balance);   // ref type
public record struct Point(double X, double Y);                       // value type
public readonly record struct Money(decimal Amount, string Currency); // immutable + value
```

#### When to Use Records

```
✅ Reach for record when:
├─ DTO, request/response, command, event payload
├─ Domain value object (Money, Address, EmailAddress)
├─ Cached object that should compare by content
├─ Test fixtures and expected-results
└─ Any "data first, behavior second" type

❌ Do NOT use record when:
├─ The type owns mutable state (entity with EF change tracking)
├─ Inheritance hierarchy with significant behavior (use class)
├─ You need explicit lifecycle (IDisposable resources)
├─ Equality should be identity (e.g. an Aggregate Root)
└─ Equality on collection-typed members would be wrong
   (record equality compares lists by reference, not by elements!)
```

#### Worked example — DTO refactor

```csharp
// Before:
public class GetUserResponse
{
    public int    Id    { get; set; }
    public string Name  { get; set; } = "";
    public string Email { get; set; } = "";
    // 30 more lines of boilerplate equality you never wrote
}

// After:
public sealed record GetUserResponse(int Id, string Name, string Email);
```

#### Worked example — pretend Money

```csharp
public readonly record struct Money(decimal Amount, string Currency)
{
    public Money Add(Money other) =>
        Currency == other.Currency
            ? this with { Amount = Amount + other.Amount }
            : throw new InvalidOperationException("Currency mismatch");
}

var a = new Money(10m, "USD");
var b = new Money(5m,  "USD");
var c = a.Add(b);              // Money { Amount = 15, Currency = USD }
Console.WriteLine(a == new Money(10m, "USD"));   // True
```

> Deep dive: [Type System › Records & value equality](../05-csharp-mastery/02-type-system.md#records--value-equality-reference-types).

---

### Init-Only Setters (C# 9)

```csharp
public class User
{
    public string Name  { get; init; } = "";
    public string Email { get; init; } = "";
}

var u = new User { Name = "Ahmed", Email = "a@b.com" };
// u.Name = "Bob";   // ❌ compile error: init-only

// But still settable in object initializers and constructors.
```

`init` lets you build immutability **without** giving up the readable object-initializer syntax. Combine with `required` to remove the constructor entirely.

---

### Required Members (C# 11)

```
┌────────────────────────────────────────┐
│ required Properties                    │
├────────────────────────────────────────┤
│ ✓ Compile-time enforced initialization │
│ ✓ Eliminates "did I forget a field?"   │
│ ✓ Plays well with init-only            │
│ ✓ Works with serializers (STJ supports)│
│ ✗ Caller must set in object initializer│
│ ✗ Can't be enforced through reflection │
│   without [SetsRequiredMembers] dance  │
└────────────────────────────────────────┘
```

```csharp
public class User
{
    public required string Name  { get; init; }
    public required string Email { get; init; }
    public string?         Bio   { get; init; }   // optional
}

// var u = new User();                                 // ❌ CS9035: Required member not set
var u = new User { Name = "Ahmed", Email = "a@b.com" }; // ✅
```

#### `required` + `record`

```csharp
public record CreateUserRequest
{
    public required string Name  { get; init; }
    public required string Email { get; init; }
    public string  Role          { get; init; } = "User";
}
```

This combination — `record` + `required` + `init` — is the **modern DTO**. Equality, immutability, mandatory fields, and zero ceremony.

> Deep dive: [Type System › `readonly` and immutability primitives](../05-csharp-mastery/02-type-system.md#readonly--immutability-primitives).

---

### Primary Constructors (C# 12)

```
┌────────────────────────────────────────┐
│ Primary Constructor Properties         │
├────────────────────────────────────────┤
│ ✓ Removes field-and-ctor boilerplate   │
│ ✓ Parameters in scope across all method│
│ ✓ Works for class, struct, record      │
│ ✓ Cleanest pattern for DI services     │
│ ✗ Parameters are NOT auto-properties   │
│   (unlike record)                      │
│ ✗ No readonly enforcement on params    │
│ ✗ Can capture mutable state — careful  │
└────────────────────────────────────────┘
```

```csharp
// Before (C# 11 and earlier):
public class UserService
{
    private readonly IUserRepository       _repo;
    private readonly ILogger<UserService>  _logger;

    public UserService(IUserRepository repo, ILogger<UserService> logger)
    {
        _repo   = repo;
        _logger = logger;
    }

    public Task<User?> GetAsync(int id) => _repo.GetByIdAsync(id);
}

// After (C# 12):
public class UserService(IUserRepository repo, ILogger<UserService> logger)
{
    public Task<User?> GetAsync(int id)
    {
        logger.LogInformation("Getting user {Id}", id);
        return repo.GetByIdAsync(id);
    }
}
```

#### Subtle but important difference vs records

```
record Person(string Name)        →  Name is a public init-only property
class  Person(string name)        →  name is a captured constructor parameter
                                     (NOT a property; not visible from outside)
```

This is the single most common confusion. In a class, primary-constructor parameters are **not** properties — they're available within the class body and can be captured by methods, but to expose them you must declare an explicit property:

```csharp
public class Customer(string name, decimal balance)
{
    public string Name => name;          // explicit projection
    // balance is private to the class body
}
```

#### When to Use Primary Constructors

```
✅ Reach for primary ctor when:
├─ DI service — clean, single line
├─ Helper class with a few injected deps
├─ Decorator / adapter wrapping another type
├─ Test class with shared setup args
└─ Anywhere you'd write "private readonly X _x; ctor sets _x"

❌ Avoid primary ctor when:
├─ You need true `readonly` semantics on the captured value
│  (param is not readonly; it can be reassigned in the class body)
├─ Multiple constructors with different shapes are needed
├─ You want to perform meaningful constructor logic / validation
│  (do it in a static factory + private regular ctor instead)
└─ Equality/serialization should treat params as data — use record instead
```

> Deep dive: [OOP & Polymorphism › Primary constructors](../05-csharp-mastery/03-oop-and-polymorphism.md#primary-constructors-c-12).

---

### Pattern Matching (C# 8-12)

Pattern matching is the most consequential language change of the last decade. Used well, it eliminates whole categories of `if/else` chains and makes total/exhaustive logic obvious.

```
┌────────────────────────────────────────┐
│ Pattern Matching Properties            │
├────────────────────────────────────────┤
│ ✓ Type, property, relational, list,    │
│   var, constant, discard, recursive    │
│ ✓ `switch` expression (returns value)  │
│ ✓ Compiler warns on non-exhaustive     │
│ ✓ Combines naturally with records      │
│ ✗ Compiler exhaustiveness is heuristic │
│   — closed type hierarchies still need │
│   a default arm                        │
│ ✗ Overuse can hurt readability         │
└────────────────────────────────────────┘
```

#### Property patterns

```csharp
string GetDiscount(Customer c) => c switch
{
    { Tier: "Gold",   YearsActive: > 5 } => "30% off",
    { Tier: "Gold" }                     => "20% off",
    { Tier: "Silver" }                   => "10% off",
    { IsNewCustomer: true }              => "5% off",
    _                                     => "No discount"
};
```

#### Relational patterns

```csharp
string Temperature(double c) => c switch
{
    < 0  => "Freezing",
    < 15 => "Cold",
    < 25 => "Pleasant",
    < 35 => "Warm",
    _    => "Hot"
};
```

#### List patterns (C# 11)

```csharp
string Describe(int[] xs) => xs switch
{
    []                  => "empty",
    [var x]             => $"single: {x}",
    [var first, ..]     => $"starts with {first}",
    [.., var last]      => $"ends with {last}",
    [1, 2, .., 9, 10]   => "looks like a wrapped sequence",
    _                   => "other"
};
```

#### Type + var patterns (the visitor killer)

```csharp
abstract record Shape;
record Circle(double R) : Shape;
record Square(double Side) : Shape;
record Rect(double W, double H) : Shape;

double Area(Shape s) => s switch
{
    Circle  { R: var r }              => Math.PI * r * r,
    Square  { Side: var x }           => x * x,
    Rect    { W: var w, H: var h }    => w * h,
    _ => throw new ArgumentException(nameof(s))
};
```

Combined with sealed/closed hierarchies, this replaces double-dispatch and the visitor pattern entirely.

#### Logical patterns — `and`, `or`, `not` (C# 9)

```csharp
bool IsLetterOrDigit(char c) => c is (>= 'a' and <= 'z')
                                  or (>= 'A' and <= 'Z')
                                  or (>= '0' and <= '9');

if (response is not null and { StatusCode: >= 200 and < 300 })
    HandleSuccess(response);
```

> Deep dive: [Nullability & Pattern Matching](../05-csharp-mastery/07-nullability-and-pattern-matching.md).

---

### Collection Expressions (C# 12)

```
┌────────────────────────────────────────┐
│ Collection Expression Properties       │
├────────────────────────────────────────┤
│ ✓ Single syntax for arrays, lists,     │
│   spans, immutable collections, etc.   │
│ ✓ Spread operator `..`                 │
│ ✓ Compiler picks optimal allocation    │
│ ✓ Works as parameters and returns      │
│ ✗ Type must be inferable from context  │
│ ✗ Not all custom collection types are  │
│   supported as targets (yet)           │
└────────────────────────────────────────┘
```

```csharp
// Same syntax, different target types — compiler picks the best representation:
int[]                  arr  = [1, 2, 3];
List<string>           list = ["A", "B", "C"];
Span<int>              span = [1, 2, 3];
ImmutableArray<int>    imm  = [1, 2, 3];
HashSet<int>           set  = [1, 2, 3];

// Spread:
int[] head = [1, 2, 3];
int[] tail = [4, 5, 6];
int[] all  = [..head, 0, ..tail];   // [1, 2, 3, 0, 4, 5, 6]

// As method args:
void Log(params ReadOnlySpan<string> lines) { /* ... */ }
Log(["one", "two", "three"]);
```

> Deep dive: [LINQ](../05-csharp-mastery/06-linq-language-deep-dive.md) and [List patterns](../05-csharp-mastery/07-nullability-and-pattern-matching.md#list-patterns-c-11).

---

### Raw String Literals (C# 11)

```
┌────────────────────────────────────────┐
│ Raw String Properties                  │
├────────────────────────────────────────┤
│ ✓ No escape sequences needed           │
│ ✓ Preserves indentation visually       │
│ ✓ JSON, SQL, regex without backslash   │
│   forests                              │
│ ✓ `$$` for interpolation when literal  │
│   `{` is needed                        │
│ ✗ Closing `"""` indentation defines    │
│   the left margin — easy to misalign   │
└────────────────────────────────────────┘
```

```csharp
var json = """
    {
      "name": "Ahmed",
      "tags": ["dev", "lead"]
    }
    """;
//  └─ closing quotes set the indent baseline; leading spaces above are stripped to it.

// With interpolation — use $$"""...""" so single { } stay literal:
var name = "Ahmed";
var role = "Admin";
var jsonInterp = $$"""
    {
      "name": "{{name}}",
      "role": "{{role}}",
      "ts":   "{{DateTime.UtcNow:O}}"
    }
    """;

// SQL without escaping:
var sql = """
    SELECT u.id, u."name", u.email
    FROM   "Users" u
    WHERE  u.tenant_id = @tenant
    AND    u.deleted_at IS NULL
    """;
```

> Deep dive: [Fundamentals › Strings](../05-csharp-mastery/01-fundamentals.md#strings--the-surprisingly-deep-type).

---

### File-Scoped Namespaces & Top-Level Statements

#### File-scoped namespace (C# 10)

```csharp
// Before:
namespace MyApp.Services
{
    public class UserService { /* ... */ }
}

// After (one less indent for the entire file):
namespace MyApp.Services;

public class UserService { /* ... */ }
```

#### Top-level statements (C# 9)

```csharp
// Program.cs — no class, no Main, no namespace:
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
var app = builder.Build();
app.MapControllers();
app.Run();
```

The compiler synthesizes the `Program` class. Use this for `Program.cs` and small CLI tools — not for libraries.

---

### Implicit & Target-Typed `new` (C# 9)

```csharp
// Old:
private readonly Dictionary<string, List<int>> _map = new Dictionary<string, List<int>>();

// New:
private readonly Dictionary<string, List<int>> _map = new();
private List<Customer> _buffer = new(capacity: 1024);

User u = new() { Name = "Ahmed", Email = "a@b.com" };
```

Useful when the type is on the left-hand side or is an obvious method parameter type. Avoid in `var` declarations — there the type is suddenly invisible from both sides.

---

### Nullable Reference Types (C# 8)

```
┌────────────────────────────────────────┐
│ Nullable Reference Types Properties    │
├────────────────────────────────────────┤
│ ✓ Compile-time null analysis           │
│ ✓ `string` non-null, `string?` nullable│
│ ✓ Forces explicit handling at API edges│
│ ✓ Eliminates ~most NREs in new code    │
│ ✗ Annotations are advisory, not hard   │
│   (unlike Kotlin) — runtime can violate│
│ ✗ Migrating large legacy code is work  │
│ ✗ Generic `T` is "agnostic" — needs    │
│   `T : notnull` or `T?` carefully      │
└────────────────────────────────────────┘
```

```csharp
// Enable in csproj:
// <Nullable>enable</Nullable>

string  name  = "Ahmed";    // non-null
string? maybe = null;       // explicitly nullable

// Compiler tracks flow:
void Greet(string? n)
{
    // Console.WriteLine(n.Length);   // ⚠️ CS8602: dereference of possibly null
    if (n is null) return;
    Console.WriteLine(n.Length);     // ✅ flow says n is not null here
}

// Null-forgiving (`!`) — assertion of "I know better":
var name = config["UserName"]!;      // use sparingly; you own the failure if wrong
```

#### Common annotations

```csharp
[return: NotNullIfNotNull(nameof(input))]
public string? Trim(string? input) => input?.Trim();

public bool TryGet(string key, [NotNullWhen(true)] out User? user) { /* ... */ }

public string GetOrThrow([NotNull] string? input)
{
    ArgumentNullException.ThrowIfNull(input);
    return input;       // compiler now knows input is not null
}
```

#### Migrating a legacy codebase

```
1. Set <Nullable>enable</Nullable> at solution level.
2. Project-by-project, fix warnings or pragma-disable per file:
     #nullable disable    // top of legacy file as a placeholder
3. Re-enable file-by-file, addressing real nullability bugs.
4. Treat new warnings as errors in CI (TreatWarningsAsErrors)
   — but only for paths that have been migrated.
```

---

### `Span<T>` and `Memory<T>` — basics

```
┌────────────────────────────────────────┐
│ Span<T> Properties                     │
├────────────────────────────────────────┤
│ ✓ Zero-allocation slicing of arrays    │
│ ✓ Works on stack, heap, or native mem  │
│ ✓ Massive perf wins for parsing /      │
│   binary protocols / hot string ops    │
│ ✗ `ref struct` — can't be in fields    │
│   of regular classes, can't be async-  │
│   captured                              │
│ ✗ Mental model is non-trivial          │
│ ✗ Use `Memory<T>` when you need to     │
│   cross async boundaries               │
└────────────────────────────────────────┘
```

```csharp
ReadOnlySpan<char> Trim(ReadOnlySpan<char> s)
{
    int start = 0, end = s.Length - 1;
    while (start <= end && char.IsWhiteSpace(s[start])) start++;
    while (end >= start && char.IsWhiteSpace(s[end]))  end--;
    return s.Slice(start, end - start + 1);
}

// Slicing without allocation:
ReadOnlySpan<char> input = "  hello world  ";
var trimmed = Trim(input);       // no string allocation
Console.WriteLine(trimmed.ToString());  // "hello world"
```

For most application code you don't need to write Span by hand — just **prefer APIs that take it** (`int.Parse(ReadOnlySpan<char>)`, `Encoding.UTF8.GetBytes(ReadOnlySpan<char>, ...)`).

> Deep dive: [Performance & Memory](../05-csharp-mastery/09-memory-and-performance.md).

---

### Source Generators — what to know

Source generators run at compile time and emit additional C# code into the build. The runtime sees ordinary code, with no reflection cost.

```
┌────────────────────────────────────────┐
│ Source Generator Properties            │
├────────────────────────────────────────┤
│ ✓ Eliminate runtime reflection         │
│ ✓ AOT-friendly (works with NativeAOT)  │
│ ✓ Built-in: STJ, regex, logging,       │
│   COM interop                           │
│ ✗ Build-time tooling complexity if you │
│   write your own                       │
│ ✗ Debug story is improving but rough   │
└────────────────────────────────────────┘
```

```csharp
// Source-generated regex (no runtime parsing):
public partial class Validators
{
    [GeneratedRegex(@"^\+?[1-9]\d{1,14}$")]
    public static partial Regex Phone();
}

// Source-generated logging (no boxing, no string formatting on disabled levels):
public static partial class Log
{
    [LoggerMessage(EventId = 1001, Level = LogLevel.Information,
        Message = "Order {OrderId} created for {Customer}")]
    public static partial void OrderCreated(ILogger logger, int orderId, string customer);
}

// Source-generated JSON (AOT-safe):
[JsonSerializable(typeof(User))]
public partial class AppJsonContext : JsonSerializerContext { }
```

This file just acknowledges them; the deep treatment lives in [Reflection, Attributes, and Source Generators](../05-csharp-mastery/08-reflection-attributes-and-source-gen.md).

---

### Comparison Matrix — Old vs Modern Idioms

| Old idiom | Modern replacement | Why |
|-----------|--------------------|-----|
| Hand-written DTO with equality | `record` | Less code, correctness for free |
| `class { get; set; }` mutable defaults | `record` + `init` + `required` | Immutability + safety |
| `ctor { _x = x; ... }` | Primary constructor | Boilerplate elimination |
| `if/else if/else` ladder on type | `switch` expression | Exhaustive, returns value |
| `null != x && x.Length > 0` | `x is { Length: > 0 }` | Single null-safe check |
| `string.Format(...)` for JSON/SQL | Raw string literal `"""…"""` | No escape forest |
| `new List<T>() { ... }` | Collection expression `[ ... ]` | Target-typed, optimal alloc |
| `namespace X { class Y { } }` | File-scoped `namespace X;` | One fewer indent |
| `static void Main(string[] args)` | Top-level statements | Less ceremony |
| Reflection-based regex / logging | `[GeneratedRegex]` / `[LoggerMessage]` | AOT, perf |
| Untyped `Object`-on-`Object` equality | `==` on records | Value equality by default |

---

### Common Pitfalls

1. **Record equality on collection members.**
   `record Order(int Id, List<Item> Items)` compares `Items` by reference, not contents. Two records with equal item lists are *not* equal. Use `IReadOnlyList<>` and either a custom `Equals` or wrap in a sequence-equality helper.

2. **Primary constructor params are not properties (in classes).**
   `public class S(IDep dep)` — `dep` is captured but not exposed. Don't expect `s.Dep` to compile.

3. **Mutating a record's mutable property.**
   `record User { public List<string> Tags { get; set; } = []; }` — yes, you can. Records aren't automatically deeply immutable; only positional parameters are init-only by default.

4. **`with` on a record struct copies the entire value.**
   That's the point, but don't use record structs for *large* data — every `with` is a full bitwise copy.

5. **Pattern-matching exhaustiveness on open hierarchies.**
   The compiler can't prove `_ =>` is unreachable for non-sealed types. Either seal the hierarchy or accept the discard arm.

6. **`required` + serializers without `JsonConstructor`.**
   Some serializers fail on required members. `System.Text.Json` supports it on `init`/required combinations in .NET 8+, but custom serializers may not.

7. **Null-forgiving (`!`) as a habit.**
   `x!.Foo` silences the analyzer but doesn't fix the bug. If you reach for `!`, justify it with a comment or an explicit `ArgumentNullException.ThrowIfNull`.

8. **Top-level statements + global `using` from libraries.**
   In tiny utility projects, accidental global usings can cause the unit test project to see types it shouldn't. Be explicit in shared library code.

9. **Raw string indentation.**
   The closing `"""`'s indentation defines the left margin. Indent it differently from the content lines and you get either an exception (less indent than content) or unintended leading whitespace.

10. **`new()` everywhere.**
    `var x = new();` doesn't compile. `Foo x = new();` does. Don't write `new()` where you can't see the type.

---

### Best Practices

1. **Use `record` for DTOs, commands, events, value objects.** It's almost always the right answer for "data first" types.

2. **Combine `record` + `required` + `init` for the modern DTO.** Mandatory fields, immutability, equality, all without writing a constructor.

3. **Adopt nullable reference types day-one in new projects.** Treat warnings as errors. Migrate legacy projects file-by-file.

4. **Prefer `switch` expressions over `if`/`else` chains.** They make exhaustiveness obvious and force you to handle every case.

5. **Prefer primary constructors for DI'd classes.** Drop the field+ctor boilerplate. Switch back to a regular ctor if you need validation or readonly semantics.

6. **Use raw string literals for any structured text in code.** JSON test fixtures, SQL strings, regex patterns, prompts.

7. **Default to file-scoped namespaces.** No reason to keep the extra indent.

8. **Use collection expressions (`[ ... ]`) instead of `new List<T> { ... }`.** Same readability, smarter allocation.

9. **Reach for source-generated regex / logging on hot paths.** They're free perf if you can use them.

10. **Don't over-modernize.** If the legacy code works and isn't being touched, leave it. Modernize when you're already in the file for another reason.

---

### Real-World Scenarios

#### Scenario 1 — Refactoring a DTO to a record

```csharp
// Before — 40 lines:
public class CreateOrderRequest
{
    public string CustomerName { get; set; }
    public List<OrderLine> Lines { get; set; }
    public DateTime? RequestedDeliveryDate { get; set; }

    public CreateOrderRequest() { Lines = new(); CustomerName = ""; }
    public CreateOrderRequest(string customerName, List<OrderLine> lines, DateTime? d)
    { CustomerName = customerName; Lines = lines; RequestedDeliveryDate = d; }

    public override bool Equals(object? obj) { /* hand-written */ }
    public override int GetHashCode() { /* hand-written */ }
}

// After — 4 lines:
public sealed record CreateOrderRequest(
    string                   CustomerName,
    IReadOnlyList<OrderLine> Lines,
    DateTime?                RequestedDeliveryDate);
```

If callers depended on hand-rolled equality semantics that included collection contents, wrap the list in a value-type collection (e.g. `EquatableArray<T>`) or override `Equals` explicitly — record's default reference-compares lists.

#### Scenario 2 — Eliminating null-check noise with NRT

```csharp
// Before:
public string FormatName(User user)
{
    if (user == null) throw new ArgumentNullException(nameof(user));
    if (user.FirstName == null && user.LastName == null) return "";
    if (user.FirstName == null) return user.LastName!;
    if (user.LastName == null)  return user.FirstName!;
    return $"{user.FirstName} {user.LastName}";
}

// After (with NRT enabled, FirstName/LastName modeled as `string?`):
public string FormatName(User user) =>
    (user.FirstName, user.LastName) switch
    {
        (null,        null)        => "",
        (null,        var last)    => last,
        (var first,   null)        => first,
        (var first,   var last)    => $"{first} {last}"
    };
```

Half the code, exhaustive, no defensive null check at the top — the type system already proved `user` is non-null at the call site.

#### Scenario 3 — Primary constructor for a DI'd handler

```csharp
public class OrderHandler(
    IOrderRepository repo,
    IPricingService  pricing,
    ILogger<OrderHandler> logger)
    : IRequestHandler<CreateOrderCommand, OrderResult>
{
    public async Task<OrderResult> HandleAsync(
        CreateOrderCommand cmd, CancellationToken ct)
    {
        logger.LogInformation("Creating order for {Customer}", cmd.CustomerName);

        var price = await pricing.QuoteAsync(cmd.Lines, ct);
        var order = new Order(cmd.CustomerName, cmd.Lines, price);

        await repo.SaveAsync(order, ct);
        return new OrderResult(order.Id, price);
    }
}
```

No fields, no constructor, no assignment ceremony. The class focuses on what it does, not on plumbing.

#### Scenario 4 — Pattern matching collapses an old visitor

```csharp
// Closed hierarchy:
public abstract record PaymentMethod;
public sealed record CreditCard(string Last4, string Brand) : PaymentMethod;
public sealed record BankTransfer(string Iban)              : PaymentMethod;
public sealed record StoreCredit(decimal Balance)           : PaymentMethod;

// Pricing fee — the kind of dispatch that used to require a visitor:
decimal Fee(PaymentMethod m, decimal amount) => m switch
{
    CreditCard   { Brand: "Amex" }  => amount * 0.029m,
    CreditCard                      => amount * 0.022m,
    BankTransfer                    => 0.50m,
    StoreCredit { Balance: var b } when b >= amount  => 0m,
    StoreCredit                     => throw new InvalidOperationException("Insufficient credit"),
    _ => throw new NotSupportedException()
};
```

Adding a new payment method now provokes a compiler warning at every `switch` if you've enabled `CS8509`, pointing you to every site that needs to handle it.

---

### Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

#### Drill 1 — `record class` vs `record struct` vs `class`

> **Q**: When do you reach for `record class`, `record struct`, and plain `class`?
>
> **A**: `record class` for reference-type DTOs / commands / value objects that want auto-generated value equality and `with` expressions. `record struct` for small, hot, short-lived value types where you also want value equality (points, money, vectors). Plain `class` for mutable entities (EF tracked entities, services with state) where reference equality is correct.
>
> **Cross-Q**: Why isn't every DTO a `record struct` — it avoids heap allocation, right?
>
> **A**: Because `with` on a record struct copies the *entire* value. For anything beyond ~16-24 bytes, that's slower than allocating once and passing by reference. Record structs are also copied on every method call by default — pass `in`/`ref readonly` to avoid it. The break-even is roughly "fits in two CPU registers"; bigger than that and `record class` wins.
>
> **Cross-Q²**: I have `record class Order(int Id, List<Item> Items)`. Two orders with the same Id and equal-content lists. Are they equal?
>
> **A**: **No.** Record equality is field-by-field, and `List<T>.Equals` is reference equality. The two `Items` lists are different objects, so the records are not equal. Fix: wrap in `EquatableArray<T>` / `ImmutableArray<T>` with content equality, or override `Equals`/`GetHashCode` manually, or use `IReadOnlyList<T>` and accept the limitation. **This is the #1 record gotcha in production code.**

#### Drill 2 — Primary constructor on a class

> **Q**: What's the difference between a class primary constructor parameter and an explicit `private readonly` field?
>
> **A**: A primary-ctor parameter is **captured** in the class's compiler-generated state, scoped to the entire class body, and **not readonly** — it can be reassigned. An explicit `private readonly` field is immutable after the ctor returns and clearly visible as state in the type's shape.
>
> **Cross-Q**: So if I want true readonly semantics, what do I write?
>
> **A**: Either go back to explicit fields (`private readonly IDep _dep;`) or project the parameter through a readonly field: `public class S(IDep dep) { private readonly IDep _dep = dep; }`. The latter looks redundant but actually enforces immutability and gives you the modern syntax for the rest of the file.
>
> **Cross-Q²**: Does a class primary constructor create properties like a record does?
>
> **A**: **No.** This is the single most common confusion. `public record Person(string Name)` exposes `Name` as a public init-only property. `public class Person(string name)` makes `name` a captured parameter — invisible from outside the class. To expose it you must write an explicit property: `public string Name => name;`. People keep expecting `class Person(string Name).Name` to compile and are surprised when it doesn't.

#### Drill 3 — `required` keyword

> **Q**: What does `required` (C# 11) actually enforce?
>
> **A**: At compile time, every caller constructing the type must set the `required` member — either in an object initializer or via a constructor decorated `[SetsRequiredMembers]`. If they don't, CS9035. It's the missing "non-null, mandatory" guarantee that `init` alone couldn't enforce.
>
> **Cross-Q**: Does `required` survive deserialization?
>
> **A**: It depends on the serializer. `System.Text.Json` (.NET 8+) honors `required` and throws if the JSON omits the field. Older serializers and reflection-based deserializers may silently skip it because they bypass the constructor — they set fields directly. If you ship a public DTO with `required`, test deserialization explicitly.
>
> **Cross-Q²**: Can I use `required` on a struct?
>
> **A**: Yes — and it solves the historical problem of "structs always have a parameterless ctor that zero-inits, so I can't force the caller to set anything." `public struct Money { public required decimal Amount; public required string Currency; }` — `new Money()` is still legal at the call site but now refuses to compile without the initializer setting both fields. **This was specifically designed to let structs feel like classes for mandatory-field DTOs.**

#### Drill 4 — Init-only setters

> **Q**: When would you choose `init` over `public set` or making the property fully immutable (readonly field)?
>
> **A**: `init` when you want **object-initializer syntax** at construction time but immutability afterward. `public set` when the property genuinely changes during the object's lifetime. Plain readonly field when you don't need the property at all (private state).
>
> **Cross-Q**: Can `init`-set properties be modified through reflection?
>
> **A**: Yes — `init` is enforced by the C# compiler, not by the CLR. Reflection (`PropertyInfo.SetValue`) treats it as a regular setter. So `init` is a strong source-code guarantee, not a runtime invariant. Serializers like System.Text.Json use this to populate `init`-set properties during deserialization.
>
> **Cross-Q²**: What's the difference between `init` and `record`'s positional parameter?
>
> **A**: `record Foo(string Bar)` is sugar for a `record` with a public `init`-set property `Bar` plus a primary constructor that sets it. So they're the same thing under the hood when you positionalize them. The difference is syntactic: positional records give you `with`-expression-friendly defaults and deconstruction for free; explicit `init` properties give you more control over property names, modifiers, and ordering.

#### Drill 5 — Raw string literals

> **Q**: When is the syntactic overhead of `"""..."""` worth it?
>
> **A**: Whenever the content contains `"` or `\` characters that would otherwise need escaping — JSON, SQL, regex, embedded XML/HTML, JSON Schema. Three quotes, no escaping, preserved line breaks. The break-even is "two or more escape characters" — at that point raw strings are clearer.
>
> **Cross-Q**: How does raw string indentation work?
>
> **A**: The closing `"""`'s indentation defines the left margin. Every content line must be indented at least that much; the compiler strips that many leading spaces from each line. If you misalign — indent the closing fewer than content lines — the compiler errors. If you indent content less than the closing, the leading whitespace is preserved.
>
> **Cross-Q²**: Interpolation needs `{` inside the string. How does `$$"""..."""` resolve that?
>
> **A**: The number of `$` signs (1 → `{ }`, 2 → `{{ }}`, 3 → `{{{ }}}`, etc.) determines how many braces *together* mark an interpolation hole. So `$$"""{ "a": {{x}} }"""` produces JSON where single `{` and `}` are literal and `{{x}}` is the interpolation. This is **why raw-string JSON templating beats `string.Format`** — `{` doesn't need to be doubled in your literal text.

#### Drill 6 — List patterns

> **Q**: When would you choose a list pattern over an `if/else` chain on `.Count` + indexing?
>
> **A**: When the *shape* of the collection drives the logic — empty, single-element, head-and-tail, suffix-match. List patterns make the shape obvious at the call site and exhaustively cover it, where an if-chain is easy to miss a case.
>
> **Cross-Q**: How does `[var first, .., var last]` work on a `Span<int>`?
>
> **A**: Identically to an array. The compiler emits `.Length >= 2`, then `first = s[0]; last = s[^1]`. The `..` (slice pattern) is a length check, not an allocation. Span supports `[]` and `^` indexing, so the pattern lowers to direct index access — zero-allocation pattern matching on stack data.
>
> **Cross-Q²**: Can I use list patterns on `IEnumerable<T>`?
>
> **A**: **No.** List patterns require *length and indexer* — i.e., something countable and indexable. `IEnumerable<T>` is sequential-only, so the compiler refuses. Works on: arrays, `List<T>`, `Span<T>`, `ReadOnlySpan<T>`, anything implementing `IList<T>` or providing `Length`/`Count` + indexer. To use it on an `IEnumerable<T>` you must materialize first: `arr = seq.ToArray(); arr switch {...}`.

#### Drill 7 — Property + recursive patterns

> **Q**: What does this match? `c is { Address: { City: "NYC" } }`.
>
> **A**: It tests `c != null && c.Address != null && c.Address.City == "NYC"`. The pattern is **recursive** — each `{ }` opens a property pattern that itself can contain nested patterns. Null checks are implicit at every level.
>
> **Cross-Q**: How would you rewrite it for non-null nested access without recursive patterns?
>
> **A**: `c is { Address.City: "NYC" }` — C# 10+ added the dotted property-pattern shortcut. Same null-safe semantics, fewer braces. For deep paths this is much more readable than nesting.
>
> **Cross-Q²**: When would you *prefer* the nested-brace form over the dotted shortcut?
>
> **A**: When you also want to bind intermediate values: `c is { Address: { City: var city, Zip: var zip } }` — you get both `city` and `zip` as variables in scope. The dotted form can only check, not bind. So: use dotted for pure checks, nested-braces for "check + capture."

#### Drill 8 — Top-level statements

> **Q**: When are top-level statements appropriate and when not?
>
> **A**: Appropriate: `Program.cs` of a single-entry-point app, small CLI utility, sample / repro project. Inappropriate: libraries (no entry point), multi-entry-point projects, anything that needs an explicit `Main(string[] args)` signature for reasons like `[STAThread]` or testing the entry point directly.
>
> **Cross-Q**: Can I have multiple files with top-level statements in one project?
>
> **A**: **No.** Exactly one file in a project may contain top-level statements; the compiler synthesizes the `Program` class from it. Two files with top-level statements is a compile error. If you need more entry-point-style code, factor it into static classes the top-level file calls.
>
> **Cross-Q²**: How do I access `args` and how does testing the entry point work?
>
> **A**: `args` is implicitly in scope as a `string[]` in the top-level file — no `Main(string[] args)` needed. For testing, the synthesized `Program` class is `internal`; add `<InternalsVisibleTo Include="MyApp.Tests" />` to expose it, then call `Program.Main(myArgs)` from your test. .NET 6+ also generates a partial `Program` class so you can extend it in tests (`public partial class Program { }`) — that's what `WebApplicationFactory<Program>` keys off.

#### Drill 9 — File-scoped namespaces

> **Q**: Is there any measurable difference between `namespace X;` and `namespace X { }`?
>
> **A**: Functionally identical — same IL, same metadata, same runtime behavior. The only differences are syntactic: one fewer level of indentation and a slightly clearer visual that the entire file lives in the namespace. **It's a readability change, not a performance change.**
>
> **Cross-Q**: Can I mix file-scoped and braced namespaces in the same file?
>
> **A**: **No.** A file with `namespace X;` cannot also have `namespace Y { }` — the file-scoped form claims the whole file. If you need multiple namespaces per file (rare, usually a code smell), you must use the braced form throughout.
>
> **Cross-Q²**: I have a file scoped namespace and a separate `using System;` line. Does the order matter?
>
> **A**: `using` directives must come **before** the file-scoped `namespace X;` declaration if they're file-level, or **after** the namespace if they're namespace-scoped — same as the braced form. The conventional placement is `using` lines at top, then `namespace X;`, then types.

#### Drill 10 — Nullable reference types on legacy

> **Q**: How would you turn on NRT for a 200-file legacy project without exploding the warning count?
>
> **A**: Enable at the *project* level (`<Nullable>enable</Nullable>` in csproj), then top each legacy file with `#nullable disable`. Walk file-by-file: remove `#nullable disable`, fix the warnings, commit. CI treats warnings as errors only for migrated files (via per-file `#nullable enable` rather than project-wide `TreatWarningsAsErrors`). This converts "200 files of warnings" into "1 file at a time of real bugs."
>
> **Cross-Q**: What's the difference between `#nullable enable` and `#nullable enable warnings`?
>
> **A**: `#nullable enable` turns on both annotations (you can declare `string?`) and warnings (compiler flags potential nulls). `#nullable enable warnings` keeps the legacy annotations-disabled mode (`string` is "unaware," not non-null) but emits warnings where the *flow* would suggest a null. Useful for the first phase of migration — see the bugs before committing to annotations.
>
> **Cross-Q²**: How does NRT interact with `default(T)` on a generic?
>
> **A**: For `class T`, `default(T)` is `null`, but the compiler doesn't know unless you constrain. Three approaches: (1) `where T : class` plus return `T?`, (2) `where T : notnull` plus throw rather than return default, (3) `[MaybeNull]` attribute on the return type if you must return default but want to flag callers. The unconstrained case (`T?` for an unconstrained generic) means "the nullable version of whatever T is" — for `int`, `int?`; for `string`, `string?`. Subtle but documented.

#### Drill 11 — Collection expressions

> **Q**: I write `int[] xs = [1, 2, 3];` — what does the compiler emit?
>
> **A**: An optimized form roughly equivalent to `new int[] { 1, 2, 3 }` — sometimes even better. For small literals the compiler may stack-allocate via `RuntimeHelpers.CreateSpan` and copy from a read-only data segment. The compiler **picks the optimal representation for the target type**, which is the whole point of collection expressions.
>
> **Cross-Q**: What's the target-type inference for `var xs = [1, 2, 3];`?
>
> **A**: **It doesn't compile.** Collection expressions require a target type — there's no canonical "the type of a collection literal." `var` has nothing to infer from. You must write `int[] xs = [1, 2, 3]` or `List<int> xs = [1, 2, 3]` or use it where the type is determined by context (a method parameter, return type, etc.).
>
> **Cross-Q²**: How does `..` (spread) work with mixed types?
>
> **A**: `[..head, ..tail]` requires that `head` and `tail` are enumerable of an element type compatible with the target. For `int[] all = [..head, 0, ..tail]` the compiler iterates both spans (or arrays) and copies in. For `Span<T>` and arrays of the same `T` it's a `MemoryCopy` — extremely fast. For `IEnumerable<T>` it's an iteration. The performance difference can be 10x; prefer span/array sources when concatenating in hot loops.

#### Drill 12 — `params` collections

> **Q**: How does C# 13's `params ReadOnlySpan<int>` differ from `params int[]`?
>
> **A**: `params int[]` allocates a new heap array on every call. `params ReadOnlySpan<int>` lets the compiler stack-allocate the argument array (via `stackalloc`) when the count is small and known, eliminating the allocation entirely. For hot logging / formatting paths called millions of times, this is a measurable win.
>
> **Cross-Q**: What types can be `params` in C# 13?
>
> **A**: Any "collection expression target" — `T[]`, `Span<T>`, `ReadOnlySpan<T>`, `List<T>`, `IEnumerable<T>`, `IReadOnlyCollection<T>`, custom types with `CollectionBuilder` attribute, etc. The compiler picks the cheapest at the call site. **The historical "params arrays" pattern is now "params collections," with arrays as one of many backends.**
>
> **Cross-Q²**: If both `void Log(params string[] xs)` and `void Log(params ReadOnlySpan<string> xs)` exist on the same type, what happens?
>
> **A**: Overload resolution prefers the **`Span`-typed overload** because it avoids the allocation (the C# 13 spec elevates spans/readonly-spans for params resolution). If you want callers to keep using the array overload (compat), keep only it. If you're providing both, callers will silently move to the span overload, which is usually what you want. **This is how `string.Format` and logging APIs are being modernized without breaking the call site.**

#### Drill 13 — Static abstract members on interfaces

> **Q**: What problem does `static abstract` (C# 11) on an interface solve?
>
> **A**: Generic math. Before C# 11, you couldn't write a generic `Sum<T>(T a, T b) => a + b` because `+` isn't an interface member. With `static abstract`, `INumber<T>` declares `static abstract T operator +(T, T)` and a constraint `where T : INumber<T>` lets the JIT call the operator on the concrete `T`. Hash, parse, zero, one, comparison — all expressible generically.
>
> **Cross-Q**: How is this implemented under the hood — virtual dispatch through a static?
>
> **A**: The JIT specializes the generic method per concrete `T`. Each specialization gets a direct call to the static operator on that type — no vtable lookup, no boxing. So `Sum<int>` calls `int.operator +` directly, `Sum<double>` calls `double.operator +`. It's *not* a virtual call at runtime; it's a per-type specialization made possible by the constraint.
>
> **Cross-Q²**: Why is `INumber<T self>` parameterized on `T self`?
>
> **A**: That's the **curiously recurring template pattern** (CRTP) — the interface refers to the type that's implementing it. It's needed because static members are not virtual through "interface reference" — there's no instance to dispatch on. The generic constraint `where T : INumber<T>` lets the compiler resolve `T.Add(a, b)` by knowing that `T` *is* the interface implementer. Without `T self`, you couldn't talk about "the type that's implementing this interface" in a method signature.

#### Drill 14 — `nameof` with method groups

> **Q**: What does `nameof(MyClass.MyMethod)` return when `MyMethod` is overloaded?
>
> **A**: The string `"MyMethod"` — `nameof` returns the *identifier*, not a fully-qualified or overload-resolved name. It's purely a compile-time string. For overloaded methods, it gives the same value regardless of overload.
>
> **Cross-Q**: How does `nameof` interact with generics? `nameof(List<int>.Add)`?
>
> **A**: Returns `"Add"`. `nameof` only ever looks at the rightmost identifier. For `nameof(List<int>)` you get `"List"` (not `"List<int>"`) — it strips generic arity. This is intentional: `nameof` is for IDE-refactor-safe string references, not for runtime introspection. Use `typeof(...).Name` / `.FullName` if you want the generic-aware string.
>
> **Cross-Q²**: Can `nameof` reference `this`?
>
> **A**: **No.** `nameof(this)` is a compile error — `this` isn't an identifier. `nameof` requires a namespace, type, member, or parameter name. For self-referential code use `MethodBase.GetCurrentMethod()?.Name` or `[CallerMemberName]` parameter attribute on the receiving method.

#### Drill 15 — Switch expression vs switch statement

> **Q**: When should I use `switch` expression (returns a value) vs `switch` statement (executes side effects)?
>
> **A**: Expression when you're **computing a value**: `var fee = method switch { ... };` — exhaustiveness-checked, returns once, single assignment. Statement when you're **executing side effects** that don't naturally compose to a value: `switch (event) { case A: DoA(); break; case B: DoB(); break; }` — multiple statements per arm, no return-value requirement.
>
> **Cross-Q**: What does the compiler warn about for a non-exhaustive switch expression?
>
> **A**: CS8509: "The switch expression does not handle all possible values." For sealed hierarchies / enum types with all known values, the compiler can prove exhaustiveness and won't warn. For open hierarchies it always warns until you add `_ => default` or `_ => throw new...`. **This is the killer reason to seal record hierarchies** — you get exhaustiveness checking at every `switch` for free.
>
> **Cross-Q²**: A switch statement falls through by default? Or breaks?
>
> **A**: C# **forbids implicit fallthrough**. Every case must end in `break`, `return`, `throw`, `goto case X`, or `goto default`. Forgetting `break` is a compile error (CS0163: "Control cannot fall through from one case label..."). This is one of C#'s deliberate departures from C/C++/Java — fallthrough bugs were one of the most expensive C-era footguns, and C# refused to inherit them. Switch *expressions* don't have this concept at all — each arm yields a value, no flow control.

</details>

---

### Self-Test

<details>
<summary>1. You cache a <code>record Order(int Id, List&lt;Item&gt; Items)</code> and compare the cached copy against a freshly built one with identical contents. Why does <code>==</code> return false, and what does that cost you in production?</summary>

Record equality is compiler-synthesized over the type's data members, and each member is compared with *its own* equality. `Id` compares by value; `Items` is a `List<T>`, which never overrode `Equals`, so it compares by reference. Two lists holding equal elements are still two different objects, so the two records are not equal. Declaring the member as `IReadOnlyList<Item>` changes nothing — the runtime type is still a list or an array, and neither compares by content. The mirror image is just as surprising and is in Microsoft's own docs: build two records over the *same* array instance, then mutate that array's contents, and the records remain equal. Record equality never looks inside a reference-typed member.

Nothing throws, which is why this survives code review. What breaks is everything built on equality: a cache-hit check that never hits, `Distinct()` that dedupes nothing, a `HashSet<T>` or dictionary key that grows one entry per request, an idempotency check that lets the duplicate through. `with` compounds it — the result is a *shallow* copy, so the original and the copy share the same list instance and a mutation through one is visible through the other.

Fixes, in order of preference: model the collection with a type that implements content equality (a Roslyn-style `EquatableArray<T>` wrapper), or write `Equals`/`GetHashCode` by hand, or keep the default and state explicitly that the record has identity semantics for that member. `ImmutableArray<T>` is *not* a fix — its equality also compares the underlying array reference.
</details>

<details>
<summary>2. This page dates primary constructors to C# 12, yet <code>record Person(string Name)</code> compiled in C# 9. What did C# 12 actually add, and what changes the moment the type is a plain <code>class</code>?</summary>

C# 9 gave *positional records*. C# 12 extended the same parenthesised syntax to non-record `class` and `struct` declarations — that is the new part, and it is exactly why the two forms look identical and behave differently.

In a record the compiler synthesizes a public property per positional parameter (init-only on `record class` and `readonly record struct`, read-write on `record struct`) plus a `Deconstruct`. In a class or struct it synthesizes none of that. Microsoft states the rules flatly: primary constructor parameters "aren't members of the class" — a parameter named `param` "can't be accessed as `this.param`" — they "don't become properties, except in `record` types", and they "can be assigned to."

Three consequences worth being able to say out loud. (a) `svc.Dep` does not compile; if callers need the value, project it — `public IDep Dep => dep;`. (b) You get no `readonly` guarantee: any member in the body can reassign `dep`, which is why `private readonly IDep _dep = dep;` is still worth writing on a service whose invariants matter. (c) Storage is conditional — the compiler creates a hidden field only when the parameter is accessed from a member body, so a parameter used solely in a field initializer or a `base(...)` call is never captured at all.
</details>

<details>
<summary>3. Nullable is enabled project-wide, the parameter is declared <code>string name</code>, and you still take a <code>NullReferenceException</code> on <code>name.Length</code> in production. How?</summary>

Because nullable reference types are a compile-time feature only. Microsoft's wording is that they are "entirely a compile-time feature" and that "the runtime behavior of your program is unchanged." `string` and `string?` are the same `System.String` at runtime; the `?` is metadata plus compiler diagnostics, and nothing is injected to check anything. The annotation therefore holds only over code the compiler actually analysed under an enabled context.

Most practical NREs after adopting NRT come from a boundary the analysis doesn't cover: a caller in a project or NuGet package compiled without nullable enabled, a deserializer or ORM that materialises the object without running your constructor, reflection, or your own `!`. `config["UserName"]!` is a promise, not a check — if the key is absent you own the failure, and it surfaces far from the `!`.

Don't claim *every* NRE arrives from outside, though — Microsoft documents pitfalls that sit inside code the compiler did analyse. `string[] values = new string[3];` hands you three null elements typed as non-nullable `string`, and neither the allocation nor a later `values[0].Length` produces a single warning; `default(T)` on a struct with non-nullable reference fields is the sibling case. Pass one of those into `Greet(string name)` and the parameter is null with nothing suppressed anywhere.

The senior answer is that NRT changes *where* you validate, not whether you validate. Inside the assembly, trust the flow analysis and delete the defensive checks. At public entry points that untyped or untrusted callers reach, keep a real runtime check — `ArgumentNullException.ThrowIfNull(input)` — and then let the attributes carry the contract outward (`[NotNull]` after the throw, `[NotNullWhen(true)]` on a `TryGet`, `[return: NotNullIfNotNull]` on a passthrough) so callers get the compiler's help instead of a comment.
</details>

<details>
<summary>4. What does <code>required</code> (C# 11) buy you that <code>init</code> alone cannot, and what still gets past it?</summary>

`init` controls *when* a member may be set; `required` controls *whether* it must be. Every expression that creates the type has to set every required member in an object initializer, and the compiler errors when one is missing (CS9035). That is the "mandatory field" guarantee `init` could never give — with `init` alone, `new User()` compiles happily and leaves a non-nullable `Email` holding `null`.

What still gets past it, in increasing order of how likely you are to meet it. `[SetsRequiredMembers]` on a constructor switches the check off for that construction path, and Microsoft's own warning is that the attribute "disables the compiler's checks that all `required` members are initialized" — it is an assertion, never verified. Generic code is where people *expect* a hole and don't get one: a type with required members can't be used as a type argument when the type parameter carries a `new()` constraint at all (CS9040), precisely because `new T()` has no object initializer for the compiler to check. The hole opens only when you combine the two — give that type a `[SetsRequiredMembers]` parameterless constructor and it satisfies `new()` again, so `new T()` compiles and returns an instance whose required member was never set.

The one that reaches production is deserialization. `System.Text.Json` does honour `required` — `Deserialize` throws `JsonException` when the property is *absent* from the payload. But a payload that sends `"email": null` deserializes without complaint: `required` means "present", not "non-null". Chain that with the previous question and a `required string Email` can still be `null` at runtime, so validate the inbound DTO rather than assuming the type system did it for you.
</details>

<details>
<summary>5. The <code>Fee</code> switch in Scenario 4 ends with <code>_ =&gt; throw new NotSupportedException()</code>. A teammate ships a fourth <code>PaymentMethod</code>. What happens, and what did that arm cost you?</summary>

The build stays green and the first order paid with the new method throws `NotSupportedException` out of the fee calculation, at checkout. The discard arm made the switch exhaustive *by construction*, so CS8509 — "the switch expression does not handle all possible values of its input type (it is not exhaustive)" — can never fire on it. You traded a compile-time diagnostic for a production exception — and the same trade is sitting in every other `switch` over `PaymentMethod` that ends the same way.

Drop the catch-all and the compiler goes back to telling you the switch isn't exhaustive; if a value still reaches it at runtime, the generated code throws `SwitchExpressionException`, documented as indicating "that a switch expression that was non-exhaustive failed to match its input at runtime". It derives from `InvalidOperationException` and carries the offending value in `UnmatchedValue` — a strictly better failure than a hand-written `NotSupportedException`, because it names what didn't match.

The judgement call is that CS8509 is a *warning*, so on its own it ships. Be precise about what dropping the discard buys you, though. Through C# 14 there is no way to tell the compiler a class hierarchy is closed, so the moment the catch-all goes, CS8509 fires on the switch you have *today* — "the pattern `_` is not covered" — not on the day the fourth subtype lands. Putting `<WarningsAsErrors>CS8509</WarningsAsErrors>` on top of that doesn't arm a tripwire; it breaks the build immediately. On .NET 10 the two honest options are to keep the discard and throw from it with the unmatched value in the message, or to drop it and treat the standing CS8509 warnings as a permanent inventory of the sites a new subtype would touch. (C# 15 adds a `closed` modifier that finally closes the gap: mark the base `closed`, handle every direct descendant, and the switch is exhaustive with no discard and no warning.)

One number to keep straight: over an `enum` the diagnostic is **CS8524**, not CS8509 — a separate code for the unnamed-value case, because any underlying integer can be cast to the enum. A `WarningsAsErrors` list naming only CS8509 misses every enum switch in the codebase.
</details>

---
### Cross-References

- **[Type System](../05-csharp-mastery/02-type-system.md)** — records, structs, ref structs, immutability primitives.
- **[OOP & Polymorphism](../05-csharp-mastery/03-oop-and-polymorphism.md)** — primary constructors, sealed hierarchies, when to prefer composition.
- **[LINQ Language Deep Dive](../05-csharp-mastery/06-linq-language-deep-dive.md)** — collection expressions in pipelines.
- **[Nullability & Pattern Matching](../05-csharp-mastery/07-nullability-and-pattern-matching.md)** — exhaustive treatment of patterns and NRT.
- **[Reflection, Attributes, and Source Generators](../05-csharp-mastery/08-reflection-attributes-and-source-gen.md)** — `[GeneratedRegex]`, `[LoggerMessage]`, custom generators.
- **[Performance & Memory](../05-csharp-mastery/09-memory-and-performance.md)** — `Span<T>`, `Memory<T>`, allocation profiling.
- **[.NET Version History](./18-version-history.md)** — per-version (C# 11 → C# 14) deltas.
- **[Unit Testing Foundations](../../09-testing/01-unit-testing-foundations.md)** — records as test fixtures.

---

### Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — *What's new in C# 10 / 11 / 12 / 13 / 14*.
- Microsoft Learn — *Records (C# reference)*, *Pattern matching*, *Nullable reference types*.
- Mads Torgersen, *C# Language Design Notes* (record equality, primary constructors).
- Stephen Toub — *Performance Improvements in .NET* (annual series; covers `Span<T>` adoption and source-generator wins).

---

</details>
<!-- nav-footer-start -->

---

[← Previous: SignalR — Real-Time Communication](11-signalr.md) · [↑ Back to top](#modern-c-features) · [Next: Exception Handling & Result Pattern →](13-exception-handling.md)

<!-- nav-footer-end -->
