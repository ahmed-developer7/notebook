# Reflection, Attributes & Source Generators

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | Medium | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Attributes — metadata on types and members](#attributes--metadata-on-types-and-members)
  - [Defining a custom attribute](#defining-a-custom-attribute)
  - [Reflection — `Type`, `MethodInfo`, `PropertyInfo`](#reflection--type-methodinfo-propertyinfo)
  - [The cost of reflection](#the-cost-of-reflection)
  - [`dynamic` and the DLR](#dynamic-and-the-dlr)
  - [Source generators — replacing reflection at compile time](#source-generators--replacing-reflection-at-compile-time)
  - [Roslyn analyzers vs source generators](#roslyn-analyzers-vs-source-generators)
  - [AOT considerations](#aot-considerations)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--reflection-killing-aot-publish)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Reflection is how runtime metadata becomes manipulable code: ASP.NET Core's controller discovery, EF Core's entity mapping, JSON serializers, DI containers, ORMs — everything that "works without you wiring it up" uses reflection (or now, source generators). 

Modern .NET is moving aggressively from reflection to **source generators**: same end result (auto-wired serialization, logging, mapping) without the runtime cost or the AOT incompatibility. Knowing both is a senior expectation. Source generators are not an obscure compiler-team thing anymore — `System.Text.Json`, `Microsoft.Extensions.Logging`, `Microsoft.AspNetCore.Mvc`, `EFCoreCompiledModel` all ship source-generator paths.

This file covers attributes, runtime reflection, the `dynamic` keyword (rarely used but important to know), and source generators as the modern alternative.

## Core concepts

### Attributes — metadata on types and members

An attribute is a piece of metadata attached to a type, member, parameter, or assembly. Attributes are inert at compile time — they're just data. Code that wants to react to them must read them via reflection.

```csharp
[Obsolete("Use NewMethod instead", error: false)]
public void OldMethod() { /* ... */ }

[Serializable]
public class User { /* ... */ }

[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    [HttpGet("{id}")]
    [Authorize(Roles = "Admin")]
    public async Task<IActionResult> Get([FromRoute] int id) { /* ... */ }
}
```

**Common BCL attributes you'll encounter:**
- `[Obsolete]` — marks something as deprecated; compiler warns or errors.
- `[Serializable]` — opts a class into binary serialization (legacy; modern .NET prefers JSON).
- `[Conditional("DEBUG")]` — method calls compiled out when the symbol isn't defined.
- `[CallerMemberName]`, `[CallerFilePath]`, `[CallerLineNumber]` — auto-fill parameters at call site.
- `[Flags]` — marks an enum as a bit-flag set (changes `ToString()` output).
- `[Pure]` — declares a method has no side effects (analyzer hint).

**ASP.NET Core / EF Core / DI attributes:**
- `[ApiController]`, `[Route]`, `[HttpGet]`, `[FromBody]`, `[FromRoute]`, `[FromQuery]`, `[Authorize]`.
- `[Table]`, `[Column]`, `[Key]`, `[ForeignKey]`, `[NotMapped]`, `[ConcurrencyToken]`.
- `[Required]`, `[StringLength]`, `[Range]`, `[EmailAddress]` (DataAnnotations).

### Defining a custom attribute

A custom attribute is a class deriving from `System.Attribute`, conventionally named `<Name>Attribute` (the `Attribute` suffix can be omitted at the call site).

```csharp
[AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, AllowMultiple = false)]
public sealed class RedactAttribute : Attribute
{
    public string Reason { get; }
    public RedactAttribute(string reason) => Reason = reason;
}

// Usage
public class User
{
    public string Name { get; init; }

    [Redact("PII")]
    public string Email { get; init; }
}
```

**`AttributeUsage` is essential:** it controls *where* the attribute can be placed and *whether* it can be applied multiple times. Without it, attribute users get worse errors when they misuse it.

**Conventions:**
- Always `sealed` unless explicitly designed for inheritance.
- Constructor parameters are *required*; properties are *optional* (set with `[Foo(Reason = "x")]` syntax).
- Keep them small (data only, no behavior).

### Reflection — `Type`, `MethodInfo`, `PropertyInfo`

Reflection is the runtime API for inspecting types, methods, properties, attributes, and invoking them dynamically.

```csharp
Type t = typeof(User);              // metadata token, not an instance
Type t2 = user.GetType();           // get type of an instance

// Properties
foreach (PropertyInfo p in t.GetProperties())
    Console.WriteLine($"{p.PropertyType.Name} {p.Name}");

// Methods
MethodInfo? m = t.GetMethod("Save", BindingFlags.Public | BindingFlags.Instance);

// Attributes
RedactAttribute? attr = p.GetCustomAttribute<RedactAttribute>();
if (attr != null)
    Console.WriteLine($"Redact reason: {attr.Reason}");

// Invoke
object? instance = Activator.CreateInstance(t);                  // call parameterless ctor
m?.Invoke(instance, new object[] { /* args */ });               // dynamic call

// Read/write a property
var nameProp = t.GetProperty("Name");
nameProp?.SetValue(instance, "Alice");
object? value = nameProp?.GetValue(instance);
```

**Common `BindingFlags`:**
- `Public` / `NonPublic` — accessibility.
- `Instance` / `Static` — member kind.
- `DeclaredOnly` — exclude inherited.
- `IgnoreCase` — case-insensitive name matching.

Combine with bitwise OR: `BindingFlags.NonPublic | BindingFlags.Instance` for "private instance members."

**Generic type reflection:**

```csharp
Type listOpen = typeof(List<>);                        // open generic
Type listClosed = listOpen.MakeGenericType(typeof(int));  // List<int>

bool isList = obj.GetType().IsGenericType && obj.GetType().GetGenericTypeDefinition() == typeof(List<>);
```

### The cost of reflection

Reflection is **slow** compared to direct calls. A `MethodInfo.Invoke` is ~100-500x slower than a direct call. `GetProperty().SetValue()` is similarly expensive. In a hot loop, this matters.

**Mitigation strategies, in order of effort:**

1. **Cache the metadata.** `t.GetProperty("X")` does a lookup every call. Cache the `PropertyInfo` once and reuse.
2. **Compile to a delegate.** Use `Expression.Lambda<...>()` to build a typed accessor at runtime — first call is slow, subsequent calls are roughly direct-speed.
   ```csharp
   var prop = typeof(User).GetProperty("Email")!;
   var p = Expression.Parameter(typeof(User), "u");
   var body = Expression.Property(p, prop);
   var getter = Expression.Lambda<Func<User, string>>(body, p).Compile();
   string email = getter(user);   // near-direct-call speed
   ```
3. **Use source generators (preferred for new code).** Avoid the runtime cost entirely — the right code is already in your assembly.
4. **`DynamicMethod` + IL emit** for the most performance-critical scenarios. Rare; libraries like Dapper use this pattern.

The rule: **reflection is fine for one-time metadata (startup, configuration, schema mapping)**, expensive in hot paths.

### `dynamic` and the DLR

`dynamic` is a static type that defers all type checking to runtime. Calls on `dynamic` go through the **Dynamic Language Runtime (DLR)** — a layer over reflection optimized for repeated calls.

```csharp
dynamic obj = ...;
obj.SomeMethod(42);          // resolved at runtime
int x = obj.SomeProperty;    // also runtime
```

**When `dynamic` is the right tool:**
- COM interop (Office automation, etc.).
- Traversing `dynamic` JSON (`JsonNode` is usually better, but legacy `dynamic` JSON exists).
- Bridging to Python/Ruby via the DLR (rare).

**Otherwise, avoid:**
- No IntelliSense.
- Errors surface as exceptions at runtime.
- ~10-50x slower than typed calls (the DLR caches resolution, so repeated calls aren't as bad as raw reflection, but still slow).
- Doesn't compose with NRT, generics, or pattern matching cleanly.

In modern code, `dynamic` should be a deliberate, isolated choice — not a casual one.

### Source generators — replacing reflection at compile time

A **source generator** is a compiler plugin (a `Microsoft.CodeAnalysis.ISourceGenerator` or `IIncrementalGenerator`) that runs *during compilation*, examines the user's code via Roslyn, and emits *additional* C# source files that get compiled alongside.

The win: features that previously required runtime reflection (serialization, logging, dependency injection, mapping) now generate the right code at build time — same API surface for the user, **zero runtime reflection cost**, and AOT-compatible.

**Examples shipping in .NET:**

- **`System.Text.Json`** — `JsonSerializerContext`-driven generator. Mark a partial context class, get specialized serializers per type. No reflection at runtime; works under NativeAOT.
   ```csharp
   [JsonSerializable(typeof(User))]
   [JsonSerializable(typeof(List<User>))]
   internal partial class AppJsonContext : JsonSerializerContext { }

   var json = JsonSerializer.Serialize(user, AppJsonContext.Default.User);
   ```
- **`Microsoft.Extensions.Logging`** — source-generated logging.
   ```csharp
   public partial class OrderService
   {
       [LoggerMessage(LogLevel.Information, "Order {OrderId} created at {Time}")]
       partial void LogOrderCreated(int orderId, DateTime time);
   }
   ```
   The compiler generates an efficient implementation. No string interpolation cost when log level is disabled, no boxing of args.
- **`Microsoft.AspNetCore.Mvc`** — source-generated minimal API metadata for OpenAPI / endpoint discovery.
- **EF Core 8+** — `CompiledModel` source generator that pre-builds the model snapshot, slashing startup time.
- **Community: `Mapperly`, `Refit`, `MediatR.SourceGenerator`, `Mediator`** — replace reflection-based mapping/HTTP/dispatch with codegen.

**Writing your own** (high-level, full code is beyond scope):

```csharp
[Generator]
public class HelloGenerator : IIncrementalGenerator
{
    public void Initialize(IncrementalGeneratorInitializationContext context)
    {
        context.RegisterPostInitializationOutput(ctx =>
            ctx.AddSource("Hello.g.cs", "namespace Generated; public static class Hello { public static string Greet() => \"Hi\"; }"));
    }
}
```

Reference `Microsoft.CodeAnalysis.CSharp` and `Microsoft.CodeAnalysis.Analyzers`. The generated file `Hello.g.cs` shows up in the user's compilation as if they wrote it themselves.

### Roslyn analyzers vs source generators

Two compiler plugin types, often confused:

| | Analyzer | Source Generator |
|---|---|---|
| What it does | Reports diagnostics (warnings/errors) | Adds new source files to the compilation |
| Output | `IDE highlight + build warning/error` | Generated `.cs` files compiled alongside user code |
| Use case | Enforce coding rules, catch bugs early | Codegen (serialization, logging, etc.) |
| Examples | `IDE0011 (add braces)`, `CA1849 (await async APIs)` | `JsonSerializerContext`, `LoggerMessage` |
| API | `DiagnosticAnalyzer` | `IIncrementalGenerator` (modern), `ISourceGenerator` (legacy) |

A single project (a "Roslyn component") can ship both. Most production source-gen libraries also ship a paired analyzer to flag misuse.

### AOT considerations

NativeAOT (`dotnet publish -p:PublishAot=true`) compiles your app ahead of time, producing a single self-contained native binary. To work, the entire app graph must be reflection-free or have explicit "trim hints" — anything reachable only through reflection might be trimmed away (or fail at runtime if the trimmer wasn't told).

**The shift to source generators is largely AOT-driven.** Code that formerly used reflection (JSON, logging, regex, MVC) has source-generator paths because *those* paths produce code the AOT compiler can statically see and keep.

For new AOT-targeted code:
- Always use `JsonSerializerContext` instead of reflection-based JSON.
- Use `[GeneratedRegex]` (C# 11+) instead of `new Regex(...)`.
- Use source-generated logging.
- Avoid `Activator.CreateInstance` in hot paths.

For existing reflection-heavy libraries, the path forward is `[DynamicallyAccessedMembers]` annotations, telling the trimmer "don't trim this thing because reflection will reach it." But it's a stopgap; source generators are the destination.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌───────────────────────────────────────────────────────────────┐
│   Reflection vs Source Generation — runtime cost               │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│   Reflection (runtime)                                         │
│   ──────────────────                                           │
│   1. Compile time: emit no extra code.                         │
│   2. First call: walk type metadata, find member, invoke.      │
│       └─ slow: ~ 100-500× direct call                          │
│   3. Subsequent calls: same (unless you cache MethodInfo).     │
│                                                                │
│                                                                │
│   Source generator (compile time)                              │
│   ───────────────────────────────                              │
│   1. Compile time: generator inspects user code, emits         │
│      specialized methods (e.g. void Serialize(User u, Stream s)│
│      ... explicit code for each property ...).                 │
│   2. First call: direct call, JIT-compiled normally.           │
│       └─ same speed as hand-written code                       │
│   3. AOT-friendly: trimmer sees real method calls.             │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

**Reflection performance hierarchy (fast → slow):**

```
1. Direct call                                  (1× baseline)
2. Source-generated wrapper                     (1×)
3. Cached delegate (Expression.Compile)         (1.5×)
4. Cached MethodInfo + Invoke                   (~50×)
5. dynamic on cached call site                  (~5-50×)
6. Repeated GetMethod() + Invoke()              (~500×)
7. Repeated GetMethod() with NonPublic flags    (~1000×)
```

If you find yourself in tier 4-7, ask whether a source generator (or just compiling once into a delegate) would be cleaner.

</details>
## Common pitfalls

1. **Calling `GetProperty(name)` in a loop.** It walks metadata every call. Cache the `PropertyInfo` once at startup or use an `Expression`-compiled getter.
2. **`Activator.CreateInstance(type, ...)` for hot paths.** Use a compiled factory delegate or `new()` constraint instead.
3. **`Type.GetMethods()` with no `BindingFlags`.** Default flags exclude non-public and static. Be explicit: `BindingFlags.Public | BindingFlags.Instance`.
4. **Forgetting `[AttributeUsage]`.** Without it, your custom attribute can be applied to anything, multiple times, leading to confusing behavior.
5. **Using `dynamic` for "convenience."** Errors at runtime, slower, no IDE help. If you find yourself reaching for `dynamic`, ask: can I deserialize to a concrete record? Can I use generics?
6. **Source generator that throws.** Build fails with confusing errors and no stack trace. Always wrap your generator's logic in try/catch and emit a diagnostic, not throw.
7. **Reflection bypassing access modifiers without thought.** `BindingFlags.NonPublic` + `Invoke` works, but you've coupled to the implementation. Prefer designing a public API or using `InternalsVisibleTo` for testing.
8. **Forgetting to mark generator output `partial`.** If the user's class is `class Foo {}` and you generate `class Foo { static method }`, the build fails. Source generators always work via `partial class` extension.
9. **AOT failures discovered too late.** Reflection-heavy code "works" until you publish AOT. Always run `dotnet publish -p:PublishAot=true` early in CI for AOT targets — surfaces trim warnings.
10. **Caching `MethodInfo` across DLL reload boundaries.** If you reload an assembly (rare in modern .NET, but happens with plugin systems), `MethodInfo` from the old version is stale. Invalidate cache on reload.

## Interview-ready summary

- **Attributes** are inert metadata on types/members. Define by deriving `Attribute`, mark with `[AttributeUsage(...)]`. Code reads them via reflection.
- **Reflection** lets you inspect and invoke types at runtime. Useful for plugin loaders, DI, ORMs. **Slow** — cache `MethodInfo` / `PropertyInfo`, or compile to a delegate via `Expression.Lambda(...).Compile()`.
- **`dynamic`** routes calls through the DLR — type-checks at runtime. Use sparingly: COM, JSON traversal, language interop. Avoid for general code.
- **Source generators** replace reflection at compile time — same convenience, near-zero runtime cost, AOT-compatible. `System.Text.Json`, `Microsoft.Extensions.Logging`, MVC, EF Core 8+ all ship source-generator paths.
- **Roslyn analyzer** ≠ source generator: analyzers report diagnostics (warnings/errors), generators emit new source files.
- **AOT** drives the source-gen migration: anything reachable only through reflection might be trimmed unless explicitly preserved. Use `JsonSerializerContext`, `[GeneratedRegex]`, source-generated logging in AOT targets.
- **Performance hierarchy**: direct call ≈ source-gen ≈ compiled delegate ≪ cached `MethodInfo.Invoke` ≪ uncached reflection ≪ repeated `dynamic`.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Cost of reflection

> **Q**: Roughly how much slower is `methodInfo.Invoke(obj, args)` than a direct method call?
>
> **A**: **~100-500× slower** for the call itself — typically ~µs vs ~ns. The cost comes from argument validation, boxing of value-type args into `object[]`, security checks (pre-.NET 5), and the unboxing/dispatching of the return. Add `GetMethod(name)` lookup in the loop and it balloons to 500-1000×. A single reflective call is invisible (sub-microsecond); a million per request is fatal.
>
> **Cross-Q**: How would you bring that within 2× of direct call?
>
> **A**: Cache the metadata once and **compile to a delegate**. Use `Expression.Lambda<Func<...>>(...).Compile()` to build a typed accessor at class-init time. Subsequent invocations are within 1-2× of a direct method call (the delegate adds one indirection, no boxing, no metadata lookup). For property accessors specifically, the pattern is: build `Expression.Property(param, prop)`, wrap in `Lambda<Func<TInstance, TValue>>`, `.Compile()`, cache. .NET 8+ added `MethodInfo.CreateDelegate<T>()` which fills a similar role with less Expression-tree boilerplate.
>
> **Cross-Q²**: Why is `Delegate.CreateDelegate` even faster than a compiled Expression tree?
>
> **A**: `CreateDelegate` binds the delegate directly to the method's IL — zero overhead beyond a normal delegate invocation. Expression-compiled delegates emit a *new* method via `DynamicMethod` that calls into the original; one extra indirection. For known-signature scenarios (you know `T` and the parameter types at code-write time), `MethodInfo.CreateDelegate<T>()` is the fastest reflective invocation path. Expression trees are more flexible (transformations, runtime composition) at small extra cost.

### Drill 2 — Reflection vs source generators

> **Q**: When is reflection the right tool over source generation?
>
> **A**: When the **types aren't known at compile time** — plugin loaders that drop DLLs into a folder at runtime, scripting hosts (Roslyn-scripted user code), ORMs over arbitrary user entities, DI containers scanning unknown assemblies. Source generators only see what's in your compilation; if your code is "load whatever is in `/plugins` and instantiate every `IPlugin`," generators can't help. Reflection is also fine for **one-time startup work** — service registration, attribute scanning at init — where ~1 ms per type doesn't matter.
>
> **Cross-Q**: And when does source generation crush reflection?
>
> **A**: When the same reflective work happens repeatedly at runtime on **types known at build time** — JSON serialization, logging, model binding, regex compilation, mapper code. Source generators emit the specialized code at compile time: zero runtime metadata lookups, zero allocations, AOT-compatible, trimmer-safe. `System.Text.Json`'s `JsonSerializerContext` benchmarks at 1.5-2× faster than reflection-based serialization, with 90% fewer allocations on the hot path. Logging via `[LoggerMessage]` skips string interpolation entirely when the log level is disabled.
>
> **Cross-Q²**: A library author has a reflection-based API and wants to add source-gen support. What's the migration shape?
>
> **A**: The pattern is to keep the reflection path as fallback and let users opt in to source-gen. **`System.Text.Json` is the reference**: `JsonSerializer.Serialize(obj)` still works (reflection); `JsonSerializer.Serialize(obj, AppJsonContext.Default.UserDto)` uses a generated context. The library exposes a `JsonSerializerContext` base class with virtuals; the generator emits a partial class overriding those virtuals with type-specialized code. Users can mix both modes in the same app. Same pattern works for logging, mapping, validation libraries — keep reflection for "unknown types," generate code for "known types."

### Drill 3 — Why attributes are baked at compile time

> **Q**: Why do attributes have to be evaluated at compile time?
>
> **A**: Attributes are **emitted into the assembly's metadata** at compile time — they're not stored as runtime objects until something reads them. The compiler validates the attribute call (constructor arguments must be constants), encodes them in the metadata tables, and stops there. Some attributes like `[Obsolete]` and `[Conditional]` are also acted upon **by the compiler itself** during compilation — `[Obsolete]` triggers warnings on use sites, `[Conditional("DEBUG")]` causes the compiler to skip emitting calls when the symbol isn't defined.
>
> **Cross-Q**: That means attribute constructor arguments must be... what?
>
> **A**: **Compile-time constants** — string literals, numeric literals, enum values, typeof expressions, arrays of these, and named-property assignments to the same constants. You **cannot** pass a method-returned value, a non-readonly field, a constructed object, or a runtime expression. `[Foo(MyHelper.Compute())]` won't compile. `[Foo("literal")]`, `[Foo(MyEnum.Value)]`, `[Foo(typeof(string))]` all work. This restriction exists because the value must be encodable into metadata tables, which only support specific primitive forms.
>
> **Cross-Q²**: If attributes are stored as metadata, when does an attribute *object* actually get constructed?
>
> **A**: **Lazily, on first reflection access.** Calling `member.GetCustomAttribute<FooAttribute>()` triggers the runtime to construct a fresh `FooAttribute` instance using the stored metadata (running its actual constructor with the encoded args). Each call returns a *new* instance by default — caching is your job. `MemberInfo.GetCustomAttributes(inherit: true)` traverses the inheritance chain looking for inherited attributes; cache results aggressively in hot paths.

### Drill 4 — `[CallerMemberName]`

> **Q**: How does `[CallerMemberName]` work?
>
> **A**: It's a **compile-time call-site injection attribute**. When a method has a parameter marked `[CallerMemberName] string memberName = ""`, the compiler injects the calling member's name (method, property, event) as the default value at each call site. The injection happens at compile time — no reflection at runtime. The default value can still be overridden explicitly.
>
> **Cross-Q**: Where's this used in real-world code?
>
> **A**: Two canonical patterns. (1) **`INotifyPropertyChanged`** — `protected void OnPropertyChanged([CallerMemberName] string name = "") => PropertyChanged?.Invoke(this, new(name));` — setters call `OnPropertyChanged()` with no argument, and the compiler injects the setter's property name. Eliminates the `nameof(MyProperty)` string-typing in every setter. (2) **Logging** — `_logger.LogError(ex, "Failed in {Method}", [CallerMemberName])` automatically tags the caller in log output. Combined with `[CallerFilePath]` and `[CallerLineNumber]`, you get a full stack-context-free trace inserted at compile time.
>
> **Cross-Q²**: What's `[CallerArgumentExpression]` and when did it ship?
>
> **A**: C# 10 (2021). It captures the **textual expression** passed for a different parameter. Canonical use: `ArgumentNullException.ThrowIfNull(object? arg, [CallerArgumentExpression(nameof(arg))] string? paramName = null)` — calling `ThrowIfNull(user.Profile)` injects `"user.Profile"` as the param name into the exception message. You get accurate exception text without manually writing the name. Used everywhere in the modern BCL for argument validation.

### Drill 5 — Positional vs named attribute arguments

> **Q**: What's the difference between `[Foo("bar", baz: 5)]`'s `"bar"` and `baz: 5`?
>
> **A**: `"bar"` is a **positional argument** — it must match a constructor parameter by position. `baz: 5` is a **named argument** — it must match a public read/write **property or field** (not a constructor parameter) on the attribute class. Positional args go to the constructor; named args are set via property assignment *after* construction.
>
> **Cross-Q**: Can the same name be both a positional and a named arg?
>
> **A**: Technically yes if the attribute defines a constructor param *and* a property of the same name, but it's a code smell. The compiler disambiguates by position vs syntax (`Foo("x")` is positional; `Foo(arg: "x")` is the named form bypassing the constructor). The convention is: **constructor params for required values, properties for optional values**. `[AttributeUsage(AttributeTargets.Class, AllowMultiple = true)]` — `AttributeTargets.Class` is positional (required by ctor); `AllowMultiple` is named (optional property).
>
> **Cross-Q²**: Why does `[Required]` work without any args but `[Range(1, 100)]` requires both?
>
> **A**: `[Required]` has a parameterless constructor — no positional args needed. `[Range]` has a constructor `Range(int min, int max)` — both positional args are required because they're constructor parameters with no defaults. The attribute author decides which args are mandatory by choosing constructor vs property. **Style rule**: make truly-required values constructor params (compile-time enforcement), make tuning options properties (named, optional, easier to evolve without breaking existing usages).

### Drill 6 — `AttributeUsage.Inherited`

> **Q**: What does `[AttributeUsage(..., Inherited = true)]` actually inherit?
>
> **A**: When `true` (the default), the attribute is **inherited by derived classes**. So if `[Audit]` is on `BaseController` and `inherited=true`, then `UsersController : BaseController` also has `[Audit]` as far as `GetCustomAttribute<AuditAttribute>(inherit: true)` is concerned. When `false`, the attribute applies only to the exact type it's declared on; derived types don't see it.
>
> **Cross-Q**: Is `inherited` the same as `inherit: true` on the reflection call?
>
> **A**: They work together but aren't the same thing. **`AttributeUsage.Inherited`** is set at *attribute definition time* — it says whether this attribute is *inheritable in principle*. **`MemberInfo.GetCustomAttribute(inherit: true)`** is set at *read time* — it says "walk the chain looking for attributes." For inheritance to work, *both* must be true: the attribute must be defined as inheritable, AND the read call must opt into traversal. If `AttributeUsage.Inherited = false`, the `inherit: true` on the read does nothing for that attribute.
>
> **Cross-Q²**: What about interface attributes — does an attribute on an interface flow to implementing classes?
>
> **A**: **No** — `AttributeUsage.Inherited` only walks the **class inheritance chain**, not interface implementations. An `[Audit]` attribute on `IService` is *not* discoverable on `Service : IService` via `GetCustomAttribute(inherit: true)`. You must explicitly enumerate the type's interfaces: `type.GetInterfaces().SelectMany(i => i.GetCustomAttributes(...))`. This trips up framework authors writing convention-based discovery — many frameworks add helpers to walk both chains. ASP.NET Core's `[Authorize]` discovery, for instance, explicitly walks interfaces.

### Drill 7 — `Type.GetMethods()` and binding flags

> **Q**: `type.GetMethods()` with no arguments — what do you get?
>
> **A**: **Only public instance methods**, plus inherited public methods from base classes. **Excluded by default**: private, protected, internal, static, constructors. The default flags are `BindingFlags.Public | BindingFlags.Instance | BindingFlags.FlattenHierarchy` (FlattenHierarchy is implicit for the parameterless overload).
>
> **Cross-Q**: How do I get private and static methods declared on this type only (no inherited)?
>
> **A**: `type.GetMethods(BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly)`. Three flags combined: `NonPublic` (private + protected + internal), `Static` (no instance), `DeclaredOnly` (no inherited). **Gotcha**: by default, *NOT* specifying `Public` excludes public; specifying *only* `NonPublic` excludes public. You almost always want `BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static` to get *everything*, then filter manually if needed.
>
> **Cross-Q²**: Why does `GetMethod("ToString")` sometimes return `null` even though every type has `ToString`?
>
> **A**: Likely binding flags. Without explicit flags, `GetMethod` uses defaults (public instance, base-walked). It returns `null` if there are *multiple* candidates (overloads — `ToString()` vs `ToString(IFormatProvider)`) since the overload-less call is ambiguous. Use `GetMethod("ToString", Type.EmptyTypes)` to specify "the parameterless overload." Or pass explicit `BindingFlags` + `Type[]` for parameter types. The ambiguity-throws-null trap is one of the most common reflection bugs.

### Drill 8 — `MethodInfo.Invoke` vs `Delegate.CreateDelegate`

> **Q**: When would you reach for `Delegate.CreateDelegate` over `MethodInfo.Invoke`?
>
> **A**: When you'll **call the method many times** with a **known signature** at code-write time. `CreateDelegate` produces a `Delegate` you can invoke directly — call overhead is one indirection, similar to a virtual call. `MethodInfo.Invoke` boxes args into `object[]`, validates each call, and is 100-500× slower. The trade-off: `CreateDelegate` requires you to know the signature at compile time to cast to the right `Func<>` / `Action<>` type.
>
> **Cross-Q**: Sketch the code.
>
> **A**:
> ```csharp
> // One-time setup (slow):
> var method = typeof(User).GetMethod("GetEmail")!;
> var getEmail = (Func<User, string>)Delegate.CreateDelegate(typeof(Func<User, string>), method);
> 
> // Hot path (fast):
> string email = getEmail(user);   // near-direct-call speed
> ```
> The cast type (`Func<User, string>`) must match the method's signature exactly. For instance methods, the first parameter of the delegate is `this`. For static methods, drop the receiver.
>
> **Cross-Q²**: How does this compare to a compiled `Expression.Lambda`?
>
> **A**: `Delegate.CreateDelegate` is slightly faster (no extra indirection through generated IL) but **only works when the signature is statically known**. `Expression.Lambda<...>().Compile()` works for **arbitrary IL emission** — you can compose property access, method calls, conversions, branches inside an expression tree, then compile. Use `CreateDelegate` for "I have a `MethodInfo`, want a fast wrapper"; use Expression trees for "I want to dynamically build a getter for property X with type coercion."

### Drill 9 — `dynamic` and the DLR

> **Q**: What does the DLR do behind the scenes when you call a method on `dynamic`?
>
> **A**: The DLR (Dynamic Language Runtime) replaces the call site with a **call-site cache**. First call: invoke a **binder** that uses reflection to find the method, generate IL for the dispatch, and cache it. Subsequent calls with the same argument types hit the cache and dispatch in ~5-20× direct-call cost — still slow, but not catastrophic. Different argument types cause **polymorphic inline cache** updates, with a fallback to full reflection if the cache thrashes.
>
> **Cross-Q**: So `dynamic` is faster than `MethodInfo.Invoke`?
>
> **A**: For **repeated calls with the same types**, yes — after warm-up, dynamic is ~5-50× direct; `MethodInfo.Invoke` is ~100-500×. For **single calls or polymorphic call sites**, dynamic can be slower because each cache miss triggers a fresh reflection lookup. The DLR optimizes the steady-state case (same types over and over); for one-off calls, cached `MethodInfo` is comparable.
>
> **Cross-Q²**: Why would you not just use `dynamic` everywhere reflection is needed?
>
> **A**: (1) **No IntelliSense** — the IDE can't help. (2) **Runtime errors only** — `obj.Tyoeo` (typo) compiles fine, blows up at runtime. (3) **Doesn't compose** with generics (`T dynamic` doesn't make sense), NRT (`dynamic?` is ill-defined), or pattern matching (`if (x is SomeType)` requires concrete types). (4) **AOT-hostile** — the DLR emits IL at runtime, which AOT can't precompile. Use `dynamic` for **legacy COM interop, traversing genuinely dynamic data (legacy JSON dynamic API), or scripting host bridges**. For typed-but-reflection scenarios, prefer cached `MethodInfo` or compiled delegates.

### Drill 10 — `System.Text.Json` source generation

> **Q**: What changes between `JsonSerializer.Serialize(obj)` (reflection) and `JsonSerializer.Serialize(obj, ctx.UserDto)` (source-gen)?
>
> **A**: **Reflection mode**: at first call, walks `UserDto`'s public properties via reflection, builds a `JsonTypeInfo` (cached for subsequent calls), and writes each property by reflective `GetValue`. **Source-gen mode**: a build-time generator emits a specialized class (`UserDtoJsonTypeInfo`) with hand-written-equivalent serialization code — direct property access, no reflection, no allocation of metadata structures. The reflection path's first call is ~10× slower; both warm paths are similar but source-gen has **~80% fewer allocations** and is **AOT-safe**.
>
> **Cross-Q**: Setup for source-gen?
>
> **A**: Define a partial context:
> ```csharp
> [JsonSerializable(typeof(UserDto))]
> [JsonSerializable(typeof(List<UserDto>))]
> internal partial class AppJsonContext : JsonSerializerContext { }
> 
> // Use at call site
> var json = JsonSerializer.Serialize(user, AppJsonContext.Default.UserDto);
> ```
> The generator inspects each `[JsonSerializable(typeof(T))]` and emits a typed property `Default.T` returning a specialized `JsonTypeInfo<T>`. Add `JsonSourceGenerationMode.Serialization` for serialize-only (smaller code), `Metadata` for both serialize and deserialize.
>
> **Cross-Q²**: What if my DTO has a `dynamic` field or a reference cycle?
>
> **A**: **Source-gen can't handle `dynamic`** — it would require runtime type resolution. The build fails or emits a fallback to reflection. **Reference cycles** require `ReferenceHandler.Preserve` which is a runtime feature; source-gen supports it but emits more code. The general rule: source-gen excels at **closed-shape DTOs**; the moment you need polymorphic deserialization, `JsonElement` tree traversal, or dynamic shapes, fall back to reflection mode. Most apps mix both — source-gen for hot-path types, reflection for one-off admin endpoints.

### Drill 11 — Reflection emit and dynamic types

> **Q**: When would you ever use `TypeBuilder` / `ILGenerator`?
>
> **A**: Rarely in modern .NET. The classic use cases were **proxy generation** (Castle.DynamicProxy, Moq pre-NetCore3), **AOP weavers**, **ORM accessor generation** (Dapper, EF Core internals). Modern alternatives: `System.Linq.Expressions` covers 90% of these cases with less code; **source generators** cover the remaining "I need real types at runtime" cases at compile time. **Honest answer**: in 2026, only library/framework authors writing the next Dapper or building a JIT-style scripting host touch `ILGenerator`.
>
> **Cross-Q**: What's `DynamicMethod` then?
>
> **A**: A lighter-weight cousin — emit a single method's IL without building a full type. Often paired with `MethodBuilder` for proxy patterns. The .NET BCL uses `DynamicMethod` internally for things like compiled regexes (pre-`[GeneratedRegex]`) and reflection delegate creation. From user code, the modern equivalent is `Expression.Lambda(...).Compile()` — it internally emits a `DynamicMethod`, exposing only the high-level expression-tree API.
>
> **Cross-Q²**: Why are Expression trees a better choice than IL emit for most cases?
>
> **A**: (1) **Type-safe at construction** — the compiler checks `Expression.Property(p, "Name")` against the declared type; raw IL emit just throws `InvalidProgramException` at execution if wrong. (2) **Composable** — you can transform expression trees (replace nodes, rewrite, optimize) before compiling. (3) **Debuggable** — `.ToString()` on an expression tree gives readable output. (4) **Higher-level constructs** — `Expression.Loop`, `Expression.TryCatch`, `Expression.Block` model real C# semantics; IL emit forces you to manage stack, labels, locals manually. Reach for raw IL only when you need IL features Expression trees don't support (fault handlers, value-type vararg, advanced calling conventions).

### Drill 12 — Expression trees vs `MethodInfo.Invoke`

> **Q**: I have a `MethodInfo` for `GetName(int id)`. Best way to invoke it 1 million times with different IDs?
>
> **A**: Compile to a strongly-typed delegate once. Two paths: (1) `Delegate.CreateDelegate<Func<int, string>>(method)` — simplest, fastest. (2) Expression tree if you need to inject type coercion or build the call dynamically:
> ```csharp
> var p = Expression.Parameter(typeof(int));
> var call = Expression.Call(instance: null, methodInfo, p);
> var fn = Expression.Lambda<Func<int, string>>(call, p).Compile();
> for (int i = 0; i < 1_000_000; i++) fn(i);   // ~direct-call speed
> ```
> Both are 100-500× faster than calling `methodInfo.Invoke(null, new object[] { i })` in the loop.
>
> **Cross-Q**: What about caching `MethodInfo` and using `Invoke` — how slow is that vs a compiled delegate?
>
> **A**: **~50× direct-call** for cached `Invoke` vs **~1-2× direct-call** for a compiled delegate. The `Invoke` path still boxes the `int` arg into an `object`, validates parameter count, and unboxes the return — overhead per call. The compiled delegate jumps directly to the method body. In a million-call loop, the difference is several hundred milliseconds.
>
> **Cross-Q²**: Why doesn't .NET cache the compiled delegate automatically for `MethodInfo.Invoke`?
>
> **A**: Because **`Invoke` is signature-agnostic** — it accepts `object[]` for any method's args. To cache a typed delegate, the runtime would need to commit to a specific signature, which it doesn't know at the `Invoke` call site. .NET 7+ added `MethodInvoker` which **does** internally cache an IL stub specialized to the method's signature (giving 10-20× speedup over plain `Invoke`), but it's a separate API. The pattern is: if you're calling `Invoke` more than a handful of times, switch to `MethodInvoker` or `CreateDelegate`.

### Drill 13 — Detecting `[Obsolete]`: compile-time vs runtime

> **Q**: How does `[Obsolete]` produce a compile warning?
>
> **A**: The C# compiler **inspects the attribute during compilation**. When emitting a call to a method, it checks the method's metadata for `ObsoleteAttribute`; if present, it emits a `CS0612`/`CS0618` warning (or error if `Obsolete(error: true)`). The check happens at *every call site* across the assembly being compiled. No runtime cost — the warning is purely a compile-time signal.
>
> **Cross-Q**: Could I write my own attribute that produces a compile-time warning?
>
> **A**: **Not directly** — `[Obsolete]` is special-cased by the C# compiler. To produce custom compile-time diagnostics, you write a **Roslyn analyzer** that registers an `OperationKind.Invocation` callback, inspects the called method's attributes, and emits a `Diagnostic` of your custom severity. The pattern is exactly what `Microsoft.Extensions.Logging.Analyzers` does for `[LoggerMessage]` mismatches. **You can simulate `[Obsolete]`** by detecting any custom attribute (e.g., `[Deprecated]`) in your analyzer and emitting a warning. Without an analyzer, your attribute is invisible to the compiler.
>
> **Cross-Q²**: How does the runtime detect `[Obsolete]` on a type accessed via reflection?
>
> **A**: It doesn't — automatically. `[Obsolete]` is only a *compiler signal*. At runtime, reflection sees `ObsoleteAttribute` like any other custom attribute via `GetCustomAttribute<ObsoleteAttribute>()`. You can read it and log a warning, but the runtime won't enforce anything. Some IDEs and tools (Resharper, IDE0001) flag obsolete reflection usage by static analysis, but the runtime itself is silent. **Lesson**: `[Obsolete]` deters *compile-site* use; runtime/reflection-based use of obsolete APIs slips through unless your team has analyzer-driven CI checks.

### Drill 14 — `IsAbstract` vs `IsInterface`

> **Q**: At runtime, what makes a `Type` "abstract" vs "interface"?
>
> **A**: They're different bits in the **TypeAttributes flags** stored in the type's metadata. `IsInterface` is true when the type was declared with the `interface` keyword (CIL flag `ClassSemanticsMask == Interface`). `IsAbstract` is true when the type cannot be instantiated — set for both interfaces *and* abstract classes (CIL flag `Abstract`). **So all interfaces are `IsAbstract == true`, but not all abstract types are `IsInterface == true`.**
>
> **Cross-Q**: How do I check "is this an abstract class specifically, not an interface"?
>
> **A**: `type.IsAbstract && !type.IsInterface`. The combination filters out interfaces while keeping `abstract class` types. Useful for DI containers that want to reject "this is unconstructible" types: `if (type.IsAbstract) throw new InvalidOperationException("Cannot construct " + type.Name);` covers both. **`IsClass`** is also useful — `IsClass && IsAbstract && !IsSealed` gives you the canonical "abstract class" shape.
>
> **Cross-Q²**: What about `IsSealed`, `IsValueType`, `IsEnum`?
>
> **A**: `IsSealed` — type cannot be subclassed (set for `sealed class`, structs, and enums). `IsValueType` — derives from `System.ValueType` (structs, enums). `IsEnum` — derives from `System.Enum`. `IsClass` — reference type that's neither interface nor delegate (true for `class` and `record class`). **`IsValueType` and `IsClass` are mutually exclusive**; everything reference-shaped except interfaces and delegates is `IsClass`. Modern code prefers `is ValueType` pattern over reflection where possible (`if (typeof(T).IsValueType)` in generics has a special JIT optimization called *intrinsic specialization*).

### Drill 15 — Roslyn analyzer vs source generator

> **Q**: What's the operational difference between a Roslyn analyzer and a source generator?
>
> **A**: An **analyzer** reports **diagnostics** (warnings, errors, info messages) — it tells the user "this code has an issue." A **source generator** emits **new C# files** that get compiled alongside user code — it tells the compiler "here's more code to compile." Same plugin pipeline, different outputs: analyzer = `Diagnostic` objects; generator = `.cs` source text.
>
> **Cross-Q**: Can a single Roslyn component ship both?
>
> **A**: **Yes — and most do.** The pattern: ship a generator + a paired analyzer that catches user errors in how the generator is used. `LoggerMessageSourceGenerator` ships with an analyzer that flags malformed `[LoggerMessage]` attributes ("template references {Foo} but parameter is named bar"). `JsonSourceGenerator` ships an analyzer for `[JsonSerializable]` mismatches. The analyzer guides the user; the generator does the heavy lifting. Both live in the same Roslyn component DLL.
>
> **Cross-Q²**: What's the difference between `IIncrementalGenerator` and the older `ISourceGenerator`?
>
> **A**: **`ISourceGenerator`** (legacy, .NET 5-6 era) — runs over the *entire* compilation on every keystroke. For large projects with many generators, this caused IDE slowdowns. **`IIncrementalGenerator`** (.NET 6+) — declares a **dataflow pipeline** of inputs and transformations; the framework caches intermediate values and re-runs only the affected steps when an input changes. Same end output (generated source files), dramatically better IDE performance. Modern generators always use `IIncrementalGenerator`; `ISourceGenerator` is deprecated but still supported for compat.

### Drill 16 — `RuntimeHelpers.GetHashCode`

> **Q**: What does `RuntimeHelpers.GetHashCode(obj)` return?
>
> **A**: The **identity-based hash code** for the object — derived from the object's heap address (or a stable identity assigned by the runtime). It **ignores any `GetHashCode` override** on the type. So two `record`s that are `Equals`-equal will have **the same** `obj.GetHashCode()` but **different** `RuntimeHelpers.GetHashCode()` (because they're different heap objects).
>
> **Cross-Q**: When do I actually want identity hash instead of value hash?
>
> **A**: When you're building an **identity-keyed structure** — `ConditionalWeakTable<TKey, TValue>` uses it internally to associate values with specific instances regardless of value equality. **Memoization caches** that want to dedupe by reference (`Dictionary<object, T>` keyed by ref equality). **Object tracking in serializers** to detect cycles. **Debuggers** showing "two different `record` instances that happen to be equal." In ordinary application code, you almost never reach for it — but in framework/serializer code, it's essential.
>
> **Cross-Q²**: Is `RuntimeHelpers.GetHashCode` stable across GC compactions?
>
> **A**: **Yes** — that's its key guarantee. The first call to `RuntimeHelpers.GetHashCode(obj)` triggers the runtime to compute and **store the hash in the object header** (in the sync block or method table tail). Subsequent calls return the stored value, even after the GC moves the object during compaction. Heap address would change after compaction; the stored hash doesn't. This is why it's safe to use as a long-lived key. The trade-off: every object that ever has `RuntimeHelpers.GetHashCode` called grows by ~4 bytes of header storage.

</details>
## Cheat Sheet

- **Attribute**: inert metadata; derive from `Attribute`, mark `[AttributeUsage(Targets, Inherited, AllowMultiple)]`.
- **Reflection cost**: ~100-1000× slower than direct call — *always* cache `MethodInfo`/`PropertyInfo`.
- **Faster invoke**: `Expression.Lambda<Func<...>>(...).Compile()` produces a delegate — near direct-call speed.
- **`dynamic`**: DLR-bound runtime calls; ~10-50× slower than static; no IntelliSense; runtime errors.
- **Source generator**: emits `.cs` at compile time via `IIncrementalGenerator`; partial classes only.
- **Source-gen winners**: `System.Text.Json` (`JsonSerializerContext`), `LoggerMessage`, `[GeneratedRegex]`, MVC.
- **Analyzer ≠ generator**: analyzer emits *diagnostics*; generator emits *source*.
- **AOT-safe**: source-gen + no reflection on user types; mark with `[DynamicallyAccessedMembers]` if needed.
- **Trim warnings**: `IL2026`, `IL2070` etc. — must be addressed for `PublishAot=true` builds.
- **Perf hierarchy**: direct ≈ source-gen ≈ compiled delegate ≪ cached `MethodInfo` ≪ raw reflection ≪ `dynamic`.

## Walkthrough — Reflection killing AOT publish

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: Team migrates a microservice to AOT (`dotnet publish -p:PublishAot=true`) for sub-50 ms cold starts on Azure Container Apps. Build emits 80 trim warnings (`IL2026`, `IL2070`); the published binary boots but throws `MissingMetadataException` deep inside `JsonSerializer.Deserialize<UserDto>` on the first request.

**Diagnosis**: AOT trimming removes "unreachable" code — but reflection-driven calls are invisible to the linker, so types referenced only by reflection get trimmed. Run the publish with `-p:TrimmerSingleWarn=false` to see every offending call site. Check `dotnet-trace` collected during a non-AOT run with the `Microsoft-Diagnostics-DiagnosticSource` provider — confirms heavy reflection in JSON, logging, and minimal-API model binding.

**Fix**: Migrate each reflection consumer to its source-generator counterpart. (1) Replace `JsonSerializer.Serialize(obj)` with a context-aware overload using `[JsonSerializable(typeof(UserDto))]` on a `partial JsonSerializerContext`. (2) Replace `_logger.LogInformation("User {Id} created", id)` with a source-generated `[LoggerMessage]` partial method. (3) Replace `new Regex(@"...")` with `[GeneratedRegex]`. (4) For controllers, switch to minimal APIs which have first-class AOT support.

```csharp
[JsonSerializable(typeof(UserDto))]
internal partial class AppJsonContext : JsonSerializerContext { }
// usage:
var json = JsonSerializer.Serialize(user, AppJsonContext.Default.UserDto);
```

**Why it works**: Source generators emit explicit code at compile time — every type, every accessor, every method is statically reachable. The trimmer can prove what's used, the AOT compiler can pre-compile to native code, and there's no runtime metadata lookup. Cold start drops because no JIT is needed; binary size shrinks because dead code is provably removable.

</details>
## Self-test

<details>
<summary>1. What's the difference between a Roslyn analyzer and a source generator?</summary>

Both run inside the compiler's pipeline as `Microsoft.CodeAnalysis.*` plugins. An *analyzer* (`DiagnosticAnalyzer`) emits **diagnostics** — warnings, errors, info messages — and optionally code fixes through a `CodeFixProvider`. A *source generator* (`IIncrementalGenerator`) emits **new source files** that become part of the compilation. Practically: analyzers say "this code is wrong"; generators say "here's more code." A modern source generator is *incremental* — it caches per-input results, so changing one file doesn't re-run the generator over every file.
</details>

<details>
<summary>2. Apply: a teammate uses `Activator.CreateInstance(typeof(Foo), arg1, arg2)` in a hot path. The profiler shows it as 30% of CPU. Replace it without changing the API.</summary>

Compile a factory delegate once, cache it, invoke many times:
```csharp
private static readonly Func<int, string, Foo> _factory = ((Expression<Func<int, string, Foo>>)((a, b) => new Foo(a, b))).Compile();
public Foo Make(int a, string b) => _factory(a, b);
```
The expression-tree compile happens once at class-init; subsequent calls run as fast as a virtual method call (one indirection). For type-known-at-compile-time, prefer `where T : new()` constraint or a manually-written lambda. The performance jump from `Activator.CreateInstance` → cached compiled delegate is typically 100×.
</details>

<details>
<summary>3. Trade-off: when does reflection beat source generation?</summary>

When the *types* aren't known at compile time — plugin systems where DLLs are dropped into a folder at runtime, scripting hosts, ORMs over user-defined entities discovered at first connection. Source generators see only what's in the compilation; if your code says "load whatever DLLs are in /plugins and instantiate every `IPlugin`," generators can't help. Reflection (or assembly load + interface scanning) is the right tool. Cost: slower first call, no AOT, larger memory footprint. Reflection is also fine for compile-time-rare code (DI registration at startup, attribute scanning during initialization) where 1ms doesn't matter.
</details>

<details>
<summary>4. Analyze: why does `[GeneratedRegex(@"\d+")]` outperform `new Regex(@"\d+")` even outside AOT?</summary>

`new Regex(pattern)` parses the pattern string, builds an internal automaton, and either interprets it or, with `RegexOptions.Compiled`, JITs IL at runtime — both pay first-call cost. `[GeneratedRegex]` runs a source generator that emits a fully-typed C# class with the pattern hard-compiled into static methods at *build* time — no parsing, no IL emission, no JIT. Benchmarks (.NET 7+) typically show 30-60% faster matches and zero allocations vs. `Regex.Match`. Bonus: AOT-safe, smaller binary in single-file deployments, full Roslyn analyzer validation of the pattern.
</details>

<details>
<summary>5. You see `[DynamicallyAccessedMembers(DynamicallyAccessedMemberTypes.PublicProperties)]` on a `Type` parameter. Explain its role.</summary>

It's a hint to the *linker/trimmer* that the receiver of this `Type` will reflect over its public properties. Without the attribute, the trimmer can't prove which members are needed and may strip them, breaking reflection at runtime in trimmed/AOT builds. With the attribute, the trimmer preserves all public properties of any type that flows into this parameter. Pair it with `IL2070` warning resolution: when calling `t.GetProperties()`, the analyzer requires the source `Type` came from a parameter/field annotated with `[DynamicallyAccessedMembers(PublicProperties)]` — propagating the requirement up the call stack.
</details>

## Cross-references

- **Previous: [Nullability & Pattern Matching](./07-nullability-and-pattern-matching.md)** — NRT attributes are reflection metadata.
- **Next: [Memory & Performance](./09-memory-and-performance.md)** — `Span<T>`, source generators for allocation-free hot paths.
- **[Modern C# Features](../01-net-core-deep-dive/12-modern-csharp.md)** — `[GeneratedRegex]`, source-generated logging idioms.
- **[Configuration](../01-net-core-deep-dive/15-configuration.md)** — IOptions discovery uses reflection.
- **[DI in .NET 10](../01-net-core-deep-dive/02-dependency-injection.md#4-dependency-injection-in-net-10)** — open generic registrations and reflection.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [Attributes (C#)](https://learn.microsoft.com/en-us/dotnet/csharp/advanced-topics/reflection-and-attributes/) and [Reflection](https://learn.microsoft.com/en-us/dotnet/fundamentals/reflection/).
- Microsoft Learn — [Source generators overview](https://learn.microsoft.com/en-us/dotnet/csharp/roslyn-sdk/source-generators-overview).
- Andrew Lock — *"Source generators in .NET 6/7/8"* series at [andrewlock.net](https://andrewlock.net/) — best practical walkthroughs.
- Stephen Toub — *"Performance Improvements in .NET 8"* — `JsonSerializerContext` and source-gen logging benchmarks.
- David Fowler / Damian Edwards — talks on minimal APIs source-gen.

</details>
<!-- nav-footer-start -->

---

[← Previous: Nullability & Pattern Matching](07-nullability-and-pattern-matching.md) · [↑ Back to top](#reflection-attributes--source-generators) · [Next: Memory & Performance Idioms →](09-memory-and-performance.md)

<!-- nav-footer-end -->
