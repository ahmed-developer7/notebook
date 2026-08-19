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
  - [Trimming and Native AOT are two different guarantees](#trimming-and-native-aot-are-two-different-guarantees)
  - [The generic instantiation problem](#the-generic-instantiation-problem)
  - [`[UnsafeAccessor]` — private access without reflection](#unsafeaccessor--private-access-without-reflection)
  - [Reading attributes without constructing them](#reading-attributes-without-constructing-them)
  - [Inside an incremental generator — the pipeline is a cache](#inside-an-incremental-generator--the-pipeline-is-a-cache)
  - [Plugins, `AssemblyLoadContext`, and the unload contract](#plugins-assemblyloadcontext-and-the-unload-contract)
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

Modern .NET is moving aggressively from reflection to **source generators**: same end result (auto-wired serialization, logging, mapping) without the runtime cost or the AOT incompatibility. Knowing both is a senior expectation. Source generators are not an obscure compiler-team thing anymore — `System.Text.Json`, `Microsoft.Extensions.Logging`, the minimal-API request delegate generator, the configuration-binding generator, and `[GeneratedRegex]` all ship in the box.

This file covers attributes, runtime reflection, the `dynamic` keyword (rarely used but important to know), source generators as the modern alternative, and the two deployment models — trimming and Native AOT — that are the actual reason the industry moved.

> 🌍 **In the real world**: the interview version of this topic is almost never "how do you call a method by name?". It is "you added `<PublishAot>true</PublishAot>` and got 80 warnings — walk me through triaging them." The candidate who can separate `IL2xxx` (the trimmer can't prove which members you reflect on) from `IL3xxx` (the compiler cannot generate the native code you'll ask for at runtime) is answering the question. The candidate who says "we replaced reflection with source generators" has described the destination without describing the road. The two warning families have genuinely different fixes, and knowing which one you're looking at is the whole skill.

> 🌍 **In the real world**: a team moved a small internal API to Native AOT for cold-start reasons and hit the wall in an order that surprised them. JSON was the *easy* fix — one `JsonSerializerContext` and it was done. What actually cost the sprint was that MVC controllers are not supported under Native AOT at all, so the port became a rewrite to minimal APIs, and their configuration binding, their `IOptions` validation, and their in-house `IEnumerable<IHandler>` assembly-scanning registration all had to be re-expressed. The transferable lesson: **the cost of an AOT migration is not the reflection you wrote, it is the reflection your framework wrote on your behalf** — DI scanning, model binding, and configuration binding are where it lives.

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
- `[Experimental("DIAGID")]` (C# 12+) — the *second* attribute the C# compiler interprets the same way it interprets `[Obsolete]`. Using an annotated API produces a diagnostic under the ID you supply, which callers suppress deliberately via `NoWarn`. Use it for APIs you intend to change, so that "I depended on a preview API" becomes a visible, per-ID decision rather than a surprise.
- `[Serializable]` — a legacy marker for `BinaryFormatter`. The in-box `BinaryFormatter` implementation was removed in .NET 9 and always throws; the attribute is now essentially inert metadata.
- `[Conditional("DEBUG")]` — method calls compiled out when the symbol isn't defined.
- `[CallerMemberName]`, `[CallerFilePath]`, `[CallerLineNumber]` — auto-fill parameters at call site.
- `[Flags]` — marks an enum as a bit-flag set (changes `ToString()` output).
- `[Pure]` — declares a method has no side effects (analyzer hint).

**Two kinds of attribute live in metadata, and they are not stored the same way.** Ordinary custom attributes are rows in the metadata's custom-attribute table: a constructor reference plus a blob of encoded arguments. But a handful — `[Serializable]`, `[StructLayout]`, `[FieldOffset]`, `[MarshalAs]`, `[DllImport]`, `[In]`/`[Out]` — are *pseudo-custom attributes*: the compiler consumes them and sets bits and rows elsewhere in the metadata (`TypeAttributes.Serializable`, the ClassLayout table, the ImplMap table). Reflection synthesizes an attribute object back on demand when you ask, which is why `Type.IsSerializable` and `Type.StructLayoutAttribute` exist as first-class properties: they read those metadata bits directly instead of going through the custom-attribute table (`IsSerializable` returns a `bool`; `StructLayoutAttribute` builds an attribute object from the ClassLayout row). The practical consequence is that "everything is just a custom attribute" is a useful 90% model and a bad 100% model, and the tell is when a tool that reads raw metadata (a source generator, ILSpy, `System.Reflection.Metadata`) doesn't see an attribute you can plainly see in reflection.

> 🌍 **In the real world**: a compliance team wanted every DTO property carrying PII tagged so an audit tool could enumerate them. The first design put `[Redact]` on the properties and had the audit tool call `Assembly.GetTypes()` on the deployed binaries. It worked in dev and returned an empty list in the trimmed staging build, because the trimmer had removed the types nothing statically referenced — the audit tool was the only consumer, and it consumed them through a `string` type name. Nothing threw; the report was simply, silently, correct-looking and empty. The eventual design flipped the direction: a source generator read the same attribute *at build time* and emitted a static array of tagged member names into the assembly, which the tool then read as ordinary code. The general lesson worth carrying: **an attribute that only a reflection-based tool reads is invisible to every static analysis in your build**, including the one that decides what to delete.

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
- If a source generator will consume the attribute, ship the attribute *itself* from the generator via `RegisterPostInitializationOutput`, so the consuming project needs no runtime package reference at all. This is the pattern `[GeneratedRegex]`-style generators use, and it is why a generator-only NuGet package can define attributes you write in your code.

> 🌍 **In the real world**: a platform team shipped `[FeatureFlag("name")]` on handler classes and had a startup routine reflect over the assembly to wire them up. Two years later a second team put the same attribute on an *interface* and spent a day convinced the registry was broken. It wasn't: `AttributeUsage.Inherited` walks the class inheritance chain and does not look at interfaces, so `GetCustomAttribute<FeatureFlagAttribute>(inherit: true)` on the implementing class genuinely returns `null`. The fix was one line — also enumerate `type.GetInterfaces()` — but the durable lesson is about the *shape* of the bug: convention-based discovery fails silently, produces no exception, and reads as "the feature just isn't on". Any attribute-driven registry should log what it registered at startup, precisely so that "found zero" is visible rather than indistinguishable from "found nothing to do".

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

`MakeGenericType` looks like an ordinary reflection call and is the single most consequential one on this page: it is annotated `[RequiresDynamicCode]`, it produces `IL3050` under AOT analysis, and it is the API behind almost every "worked in dev, threw in production" AOT story. See [The generic instantiation problem](#the-generic-instantiation-problem).

> 🌍 **In the real world**: a background job walked every entity in a batch and read a `[DisplayName]` attribute off each property to build a human-readable change log. The code was `item.GetType().GetProperties()` inside the per-item loop, and `GetCustomAttribute<DisplayNameAttribute>()` inside a nested per-property loop. For a batch of a few hundred items nobody noticed. When the batch size grew to the tens of thousands, the job's CPU profile was dominated not by the database and not by the diffing logic but by `RuntimePropertyInfo` allocation and attribute *construction* — because `GetCustomAttribute` builds a brand-new attribute instance from metadata on every single call, and the metadata could not possibly have changed between iterations. The fix was one `ConcurrentDictionary<Type, (PropertyInfo prop, string label)[]>` populated on first sight of a type. The generalisable observation: **reflection results for a given `Type` are immutable for the life of the process** — every reflection call inside a loop over *instances* is recomputing something that was already true, and that framing tells you where to put the cache without a profiler.

### The cost of reflection

Reflection is slow compared to a direct call, and it is worth being able to say *why* rather than quoting a multiplier. `methodInfo.Invoke(obj, args)` pays, per call:

- **An `object[]` for the arguments** — one array allocation, plus **one box per value-type argument**.
- **Argument validation** — count, assignability, and by-ref/`Missing` handling, all decided at runtime because `Invoke` has one signature for every method in existence.
- **Unbox-and-store on the way in, box on the way out** — the return value comes back as `object`.
- **No inlining, ever.** The JIT sees a call into the reflection stack, not into your method.

Every one of those is *per call*, and none of them depends on how slow your method is — which is why the overhead is invisible on a method that does I/O and dominant on a property getter.

`GetProperty("X")` / `GetMethod("X")` add a *lookup* on top: a name-and-signature match over the type's member tables, plus allocations for the `MemberInfo` objects the runtime hands back. That part is cacheable and should always be cached.

**Mitigation strategies, in order of effort:**

1. **Cache the metadata.** `t.GetProperty("X")` does a lookup every call. Cache the `PropertyInfo` once and reuse. This is the single change with the best effort-to-benefit ratio and it removes an allocation as well as a lookup.
2. **Use `MethodInvoker` / `ConstructorInvoker` (.NET 8+).** Created once from a `MethodBase`, an invoker builds an invocation stub specialized to *that method's signature*, so the per-call validation work `MethodBase.Invoke` repeats is done once. Microsoft's own remarks are explicit about the trade: it "provides better performance than `Invoke` … when the caller can cache the `MethodInvoker` instance for additional invoke calls", at the cost of not honouring `Type.Missing` default-value lookup, and the target may be inlined and therefore absent from stack traces.
   ```csharp
   private static readonly MethodInvoker s_invoker = MethodInvoker.Create(typeof(User).GetMethod("Save")!);

   s_invoker.Invoke(user);                  // receiver only
   s_invoker.Invoke(user, arg1, arg2);      // up to 4 args have dedicated overloads —
                                            // no params array is allocated
   ```
   There are fixed-arity overloads for zero to four arguments plus a `Span<object?>` overload, precisely so the common cases don't allocate an argument array at all.
3. **Bind a typed delegate.** `MethodInfo.CreateDelegate<T>()` (the generic overloads are .NET 5+; the non-generic `CreateDelegate(Type)` has been there since .NET Framework 4.5) produces a real delegate over the target method. Invoking it costs one indirection — no `object[]`, no boxing, no validation.
   ```csharp
   var getEmail = typeof(User).GetMethod("GetEmail")!.CreateDelegate<Func<User, string>>();
   string email = getEmail(user);
   ```
4. **Compile an expression tree** when the shape isn't known until runtime (type coercion, composed member access, a dynamically assembled predicate).
   ```csharp
   var prop = typeof(User).GetProperty("Email")!;
   var p = Expression.Parameter(typeof(User), "u");
   var body = Expression.Property(p, prop);
   var getter = Expression.Lambda<Func<User, string>>(body, p).Compile();
   string email = getter(user);
   ```
   `Compile()` emits IL through `DynamicMethod`, so the first call is expensive and the delegate must be cached. **Under Native AOT there is no `DynamicMethod`**: `System.Linq.Expressions` falls back to its interpreter, which the Native AOT docs describe as "slower than runtime generated compiled code". An expression-compiled accessor is therefore a JIT-only optimization that quietly stops being an optimization when you publish AOT.
5. **Use source generators (preferred for new code).** Avoid the runtime cost entirely — the right code is already in your assembly, and it is code the trimmer and the AOT compiler can see.
6. **`[UnsafeAccessor]` (.NET 8+)** when the only reason you reached for reflection was *accessibility* rather than *dynamism* — see [below](#unsafeaccessor--private-access-without-reflection). Zero per-call overhead and, unlike everything above, fully AOT-safe.

The rule: **reflection is fine for one-time metadata (startup, configuration, schema mapping)**, expensive in hot paths.

**How to talk about the cost without inventing a number.** If you're asked "how much slower", the honest and more impressive answer is a *shape*: "the overhead is a fixed per-call cost — an array, a box per value argument, and validation — so the ratio depends entirely on what the target method does. On a property getter it dominates completely; on a method that opens a socket it's noise. I'd measure it with BenchmarkDotNet using `[MemoryDiagnoser]` and compare `Direct` / `CachedInvoke` / `MethodInvoker` / `CreateDelegate` over the *same* target, because the allocation column usually settles the argument before the time column does."

> 🌍 **In the real world**: an internal audit library serialized every outgoing DTO to a flat key/value bag by walking `GetProperties()` and calling `GetValue` per property, per object, per request. Nobody had written a benchmark, because "it's just reflection, it's only used for logging". The allocation trace under load told the story without one: `System.Object[]`, `System.Reflection.RuntimePropertyInfo[]`, and boxed `Int32`/`DateTime` accounted for a large share of Gen0 traffic, all attributed to a component whose *output* nobody read on the happy path. The first fix was mechanical — cache the `PropertyInfo[]` per type in a `ConcurrentDictionary<Type, PropertyInfo[]>` — and it removed the array and the lookup but not the boxing, because `GetValue` returns `object` by definition. The second fix removed the rest by generating a per-type `void Append(T value, IBufferWriter<byte> w)` at build time. The transferable point: **`GetProperties()` in a loop is two separate costs — the lookup, which caching fixes, and the boxing, which only codegen fixes** — and teams routinely do the first, declare victory, and wonder why the allocation graph barely moved.

> 🌍 **In the real world**: a service kept a `ConcurrentDictionary<string, Func<object, object>>` of expression-compiled property getters, keyed by `$"{type.FullName}.{propertyName}"`, populated on demand from user-supplied field names in a query API. It was fast and it leaked. `Expression.Compile()` produces a `DynamicMethod` and its backing objects; the cache was keyed on strings that came from *request input*, so a caller probing `?fields=` with junk names grew the dictionary without bound, and the delegates it held were never collected because the dictionary rooted them. Memory grew slowly enough to look like a normal working-set climb for weeks. Two things were wrong and only one was obvious: the unbounded cache, and the fact that the key was attacker-controlled. The rule that came out of it: **a cache of compiled code must be keyed by something from your own type system, not by something from the wire**, and validating the field name against the real `PropertyInfo` set *before* touching the cache is the check that makes both problems go away.

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
- Errors surface as exceptions at runtime (`RuntimeBinderException`), including typos.
- Slower than a typed call. The DLR caches binding decisions per call site, so a *monomorphic* site — same argument types every time — settles into a cached dispatch rather than repeating a full lookup; a site that sees many different runtime types keeps missing the cache. Either way you are paying a call-site cache probe and a delegate invocation that a typed call does not.
- Doesn't compose with NRT, generics, or pattern matching cleanly.
- **AOT-hostile by construction**: the DLR generates code at runtime, which is exactly the thing Native AOT does not have.
- Drags in the binder: using `dynamic` at all pulls `Microsoft.CSharp` (part of the shared framework on modern .NET, a package reference on .NET Framework) into the deployment, and everything it reaches becomes something the trimmer can't reason about.

In modern code, `dynamic` should be a deliberate, isolated choice — not a casual one.

> 🌍 **In the real world**: an integration layer parsed vendor webhooks into `dynamic` because "the shape varies by vendor", and for two years it was fine — the code read like the JSON, which is exactly its appeal. It broke on a Friday when a vendor renamed a field from `orderId` to `order_id`. The handler didn't throw where the field was read; it threw three frames later, in a `catch`-less async continuation, as a `RuntimeBinderException` whose message named the member but not the vendor, the payload, or the endpoint. Nothing in the type system had ever recorded what shape was expected, so there was no schema to diff and no test that could have failed. The replacement was `JsonNode` for traversal plus a per-vendor `record` with explicit `[JsonPropertyName]`, and a contract test per vendor built from a captured payload. The transferable point: **`dynamic` doesn't make the shape flexible, it makes the shape undocumented** — and the cost isn't the performance, it's that the failure arrives with no information about what was expected.

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
   The consuming class *and* the method must be `partial`, and the method must return `void`. A `static` method takes the `ILogger` as a parameter (add `this` to make it an extension method); an instance method finds an `ILogger` field on the containing class, or — from .NET 9 — an `ILogger` primary-constructor parameter. The generated body does the level check before touching any argument, so nothing is formatted or boxed when the level is disabled.
- **`[GeneratedRegex]`** — a `partial` method returning `Regex` (the generator shipped in .NET 7 / C# 11), backed by a generated `Regex`-derived class with the matching logic emitted as C#. **From .NET 9 the attribute can also go on a `partial` property**, which needs C# 13's partial-property support — so "property or method" is version-dependent, and only the method form works on .NET 7/8. Either way the pattern is parsed at build time, so there is no pattern parsing at runtime, no `Reflection.Emit`, and no `RegexOptions.Compiled` JIT step at startup — and the emitted code is real C# you can read and step through.
- **The minimal-API request delegate generator (RDG)** — emits the parameter-binding and result-writing code for `app.MapGet(...)` endpoints that would otherwise be built by reflecting over the lambda's signature. It is enabled implicitly by `PublishTrimmed` and `PublishAot` in .NET 8+. Note the boundary carefully: this is **minimal APIs, not MVC** — MVC is listed as *not supported* under Native AOT.
- **The configuration-binding source generator** — replaces the reflection-based `IConfiguration.Bind` / `Get<T>()` path, also enabled by `PublishTrimmed`/`PublishAot`.
- **EF Core** — *compiled models* are generated by the `dotnet ef dbcontext optimize` CLI command, not by a Roslyn generator running in your build; the command writes C# you check in, and you opt in with `optionsBuilder.UseModel(MyContextModel.Instance)`. It is a startup-time optimization for large models, and the docs list real limitations (global query filters unsupported; lazy-loading *and* change-tracking proxies unsupported; value converters referencing private methods unsupported; custom `IModelCacheKeyFactory` unsupported; and the model must be manually regenerated whenever the model definition changes). Separately, EF Core 9 added **precompiled queries** — the piece that matters for Native AOT — to the same `optimize` command.
- **Community: `Mapperly`, `Refit`, `Mediator`** — replace reflection-based mapping/HTTP/dispatch with codegen.

**Seeing what a generator produced.** Add `<EmitCompilerGeneratedFiles>true</EmitCompilerGeneratedFiles>` and build; the output lands under `obj/<Config>/<tfm>/generated/`. Pair it with `<CompilerGeneratedFilesOutputPath>` to redirect it somewhere you'd rather look. This is the first thing to do when a generator "doesn't work" — most of the time the generated file is right there and explains itself, and the remaining cases are the generator not running at all, which the empty directory also tells you.

> 🌍 **In the real world**: a team adopted `[LoggerMessage]` across a service and measured no allocation change on the paths they cared about, which was correct and disappointing — those paths already used the message-template overload, which was already allocation-light. Where it paid off was somewhere nobody predicted: the generator's paired analyzer immediately flagged four log statements whose template placeholders didn't match their parameter names, which meant four structured-logging fields had been silently absent from the log pipeline since the day they shipped. The dashboards that filtered on those fields had been quietly matching nothing. **The value of moving a convention from runtime to compile time is not always speed; often it is that a whole class of mistakes becomes a build error.**

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

A single project (a "Roslyn component") can ship both. Most production source-gen libraries also ship a paired analyzer to flag misuse — and that pairing is the point, not a nicety. A generator that emits code from your attributes has, by construction, a set of ways you can misuse the attribute; without an analyzer those become confusing compile errors *in generated code you didn't write*, which is the worst diagnostic experience in the toolchain.

> 🌍 **In the real world**: a team wrote their first source generator and it worked beautifully until someone applied the attribute to a nested class inside a generic type. The generator emitted a `partial class` declaration without the containing type's generic parameters, and the build failed with three cascading errors pointing at a file under `obj/` that the developer had never seen and couldn't open from the error list. It took an afternoon to work out that the generator was at fault rather than their code. The two changes that fixed it permanently were: a paired analyzer reporting "this attribute is not supported on nested types" *at the attribute*, and a `try`/`catch` around the generator's transform that reports a `Diagnostic` instead of letting an exception surface as an opaque build failure. **A generator's error messages are part of its API**, and the default when you write none is that your users debug your generated code instead of their own.

### AOT considerations

Native AOT (`<PublishAot>true</PublishAot>` plus `dotnet publish -r <RID>`) compiles your app ahead of time, producing a single self-contained native binary with no JIT.

**Reflection is not banned under AOT — it is *bounded*.** `typeof(User).GetProperties()` works fine if the AOT compiler could see that `User`'s properties were needed. What breaks is (a) reflecting on members nothing statically reaches, so they were removed, and (b) asking the runtime to produce code that doesn't exist. Those are two different failures with two different warning families, and conflating them is the most common way this topic goes wrong in an interview.

**The shift to source generators is largely AOT-driven.** Code that formerly used reflection (JSON, logging, regex, minimal-API binding, configuration binding) has source-generator paths because *those* paths produce code the AOT compiler can statically see and keep.

For new AOT-targeted code:
- Always use `JsonSerializerContext` instead of reflection-based JSON.
- Use `[GeneratedRegex]` (C# 11+) instead of `new Regex(...)`.
- Use source-generated logging.
- Avoid `Activator.CreateInstance` in hot paths.

For existing reflection-heavy libraries, the path forward is `[DynamicallyAccessedMembers]` annotations, telling the trimmer "don't trim this thing because reflection will reach it." But it's a stopgap; source generators are the destination.

> 🌍 **In the real world**: a team enabled `PublishTrimmed` — not AOT, just trimming — on a worker service to shrink the container image, and everything passed CI. Three weeks later a rarely-used admin command started returning empty results. The command reflected over an enum to build a list of allowed values by reading `[Description]` attributes; the trimmer had removed the enum's field metadata because nothing statically referenced the fields, and the reflection returned an empty array rather than throwing. The reason it survived CI is that the integration tests ran against the **untrimmed** build, which is the default for `dotnet test`. The process change that came out of it was cheap and is the one worth stealing: run the smoke-test suite against the *published* artifact, not against a `dotnet run` of the same source. **Trimming is a build-output transformation, so a test that doesn't run the build output isn't testing it.**

> 🌍 **In the real world**: a library author added `<IsAotCompatible>true</IsAotCompatible>` to make their package attractive to AOT consumers and got a clean build, because the analyzer only sees the code in that project. A consumer publishing AOT got warnings anyway — from a transitive dependency the library used for date parsing, which reflected internally. The library's claim was sincere and wrong. Two things would have caught it: a **trimming test app** (a small console project that references the library, sets `PublishTrimmed`, and lists the library under `<TrimmerRootAssembly>` so the trimmer analyzes every path through it, since reference assemblies alone don't carry enough information), and .NET 10's `<VerifyReferenceAotCompatibility>` to flag dependencies with no compatibility metadata at all. The general shape: **an annotation is a claim about your transitive closure, and the only thing that checks a transitive closure is publishing.**

### Trimming and Native AOT are two different guarantees

Teams say "AOT" when they mean four separate things that ship as four separate MSBuild switches, and the switches compose in one direction only.

| Switch | What it does | What it takes away |
|---|---|---|
| `PublishTrimmed` | Runs ILLink: removes IL nothing statically reaches | Members reachable only through reflection. Also turns off trim-incompatible features and, in .NET 8+, turns *on* the configuration-binding and request-delegate generators |
| `PublishSingleFile` | Bundles the app into one file | `Assembly.Location` and friends stop returning a real path |
| `PublishReadyToRun` | Pre-JITs IL to native as a *startup* optimization | Nothing — the JIT is still present and can still generate code |
| `PublishAot` | Whole-program native compilation, no JIT in the output | Everything trimming takes away, **plus** all runtime code generation |

`PublishAot` implies trimming and single-file. `PublishReadyToRun` is the odd one out and the one candidates most often mix in: it is ahead-of-time *compilation* without ahead-of-time *closure*, so it has none of these restrictions.

**Two analyzers, two warning families, two attributes.**

- **`IL2xxx` — trim analysis.** "You are reflecting over something I cannot prove will still be here." Expressed by `[RequiresUnreferencedCode("...")]` on a member that is fundamentally unanalyzable, and by `[DynamicallyAccessedMembers(...)]` on a `Type`-typed parameter, field, or return to say *which* members will be reflected on. The annotation propagates: annotate the parameter and every caller passing an unannotated `Type` now warns, until the requirement reaches a public API or a concrete `typeof(X)` where the trimmer can satisfy it and stop.
- **`IL3xxx` — AOT analysis.** "You are asking for code that will not exist." Expressed by `[RequiresDynamicCode("...")]`. `IL3050` is the one you'll actually see: `MakeGenericType`, `MakeGenericMethod`, `Expression.Compile`, and anything in `System.Reflection.Emit` carry it.

The distinction matters because the *fixes* are different. An `IL2026` can often be resolved by annotating and preserving — the code is fine, the trimmer just needed to be told. An `IL3050` usually cannot be annotated away, because there is no native code to preserve; the docs are blunt about it: "There aren't many workarounds for `RequiresDynamicCode`. The best fix is to avoid calling the method at all when building as Native AOT and use something else that's AOT compatible."

Three escape hatches, in descending order of how much you should want to use them:

1. **`[DynamicallyAccessedMembers]`** — express the requirement so the tool can satisfy it. Always try this first.
2. **`[DynamicDependency("Helper", "MyType", "MyAssembly")]`** — "keep this other member alive whenever this one is kept." It preserves but does *not* silence warnings, and the docs call it a last resort.
3. **`[UnconditionalSuppressMessage("ReflectionAnalysis", "IL2063", Justification = "...")]`** — a suppression that survives into IL and is therefore visible to the publish step (a plain `#pragma` or `[SuppressMessage]` is source-only and the trimmer never sees it). You are now personally guaranteeing an invariant the tool couldn't prove, and the documentation's warning is worth memorising: "it's only valid to suppress a warning if there are annotations or code that ensure the reflected-on members are visible targets of reflection. It isn't sufficient that the member was a target of a call, field, or property access." The docs' worked counter-example is a serializer whose justification is that it only needs the properties the app already uses — labelled **INVALID**, because a property that is not a visible reflection target can be inlined, renamed, or moved.

**Library-side switches.** `<IsTrimmable>true</IsTrimmable>` marks an assembly as trim-safe and turns on the analyzer; `<IsAotCompatible>true</IsAotCompatible>` implies `IsTrimmable` plus the trim, single-file, and AOT analyzers. `<EnableTrimAnalyzer>` turns on warnings *without* claiming compatibility, which is the right first step on a library you haven't audited. .NET 10 adds `<VerifyReferenceTrimCompatibility>` / `<VerifyReferenceAotCompatibility>` to warn when a dependency carries no such annotation (`IL2125` / `IL3058`) — opt-in, because plenty of compatible libraries simply predate the metadata.

**Feature switches — the mechanism nobody explains.** A set of MSBuild properties removes whole framework subsystems: `EventSourceSupport`, `MetricsSupport`, `DebuggerSupport`, `StackTraceSupport`, `HttpActivityPropagationSupport`, `InvariantGlobalization`, `UseSystemResourceKeys`, `EnableUnsafeBinaryFormatterSerialization`, `MetadataUpdaterSupport`, and (in .NET 10) `Http3Support` and `UseSizeOptimizedLinq`. These are not magic. Each writes a `RuntimeHostConfigurationOption` into the runtime config *and* is declared to the trimmer, which then treats the corresponding `Feature.IsSupported` property as a **compile-time constant** and deletes the dead branch behind it — including everything only that branch reached. .NET 9 exposed this to your own code: `[FeatureSwitchDefinition]` marks a property as a trimmer-foldable switch, and `[FeatureGuard]` marks a property as a legitimate guard for code annotated `[RequiresUnreferencedCode]` / `[RequiresDynamicCode]`, so `if (Feature.IsSupported) { ... }` stops warning.

That last one is how a library ships one binary that works on JIT and AOT. The shape below is the one the AOT-warnings docs demonstrate (their example uses the same `"Aot"` / `"IL3050:RequiresDynamicCode"` suppression around an `IsDynamicCodeSupported` guard):

```csharp
[UnconditionalSuppressMessage("Aot", "IL3050:RequiresDynamicCode",
    Justification = "Guarded by IsDynamicCodeSupported; branch is removed under AOT.")]
static IPropertyReader Build(PropertyInfo p)
{
    if (RuntimeFeature.IsDynamicCodeSupported)
        return CompileWithExpressionTrees(p);   // JIT only
    return new ReflectionReader(p);             // AOT fallback
}
```

`RuntimeFeature.IsDynamicCodeSupported` is `false` under Native AOT and `true` under a JIT runtime. Because it is a recognised feature switch, the AOT compiler folds it to a constant `false`, deletes the first branch, and deletes everything only that branch reached — so the expression-tree machinery never ships in the binary. The suppression is what quiets the analyzer, and the guard is what makes the suppression *true*; writing one without the other is either a warning you didn't fix or a lie you told the toolchain. .NET 9's `[FeatureGuard]` is the mechanism that lets your own switch properties be recognised as legitimate guards for `[RequiresDynamicCode]` / `[RequiresUnreferencedCode]` code in the same way.

> 🌍 **In the real world**: a service enabled `InvariantGlobalization` to shrink a container image, shipped, and started sorting customer names wrong weeks later. Nothing threw. Invariant mode is not "the English culture", it is *no culture data at all*, and the runtime's own design doc is explicit about the consequence: "String operations like `Compare`, `IndexOf` and `LastIndexOf` are always performed as ordinal and not linguistic operations **regardless of the string comparing options passed to the APIs**." So `string.Compare(a, b, StringComparison.CurrentCulture)` silently stops being culture-aware — the argument is accepted and ignored. Casing degrades to the ASCII range, time-zone display names on Linux fall back to standard names, and IDN handling stops normalising. (The one thing that *does* fail loudly is culture creation: since .NET 6, `PredefinedCulturesOnly` defaults to `true` in invariant mode, so `new CultureInfo("fr-FR")` throws `CultureNotFoundException` rather than quietly returning something invariant-shaped.) The switch had been reviewed as a size optimization, by people thinking about disk. **A feature switch is a behavioural change that happens to reduce size** — read the runtime-config page for each one, and treat `UseSystemResourceKeys` with the same suspicion, since it replaces every `System.*` exception message with a bare resource ID and will make your next production stack trace considerably less useful.

### The generic instantiation problem

This is the deepest AOT mechanism, it is the one that produces the weirdest runtime failures, and it is genuinely worth explaining properly rather than naming.

The CLR does not generate one native method body per generic method. It **shares** one canonical body across all *reference-type* instantiations — `List<string>`, `List<User>`, and `List<Stream>` all run the same machine code, because every `T` is a pointer of the same size and the runtime passes a hidden type handle for the cases that need it. It **cannot** share across *value-type* instantiations: `List<int>` and `List<DateTime>` have different sizes, different field layouts, and different copying rules, so each needs its own specialized code.

Under JIT that difference is invisible, because a missing instantiation is simply compiled on demand at first use. Under Native AOT there is nothing to compile on demand. The Native AOT docs state the consequence directly: "Generic parameters substituted with struct type arguments have specialized code generated for each instantiation. In the dynamic runtime, many instantiations are generated on-demand. In Native AOT, all instantiations are pre-generated."

Two things follow, and both surprise people:

**1. `MakeGenericType` over a value type is a runtime bomb the compiler warns about.** `typeof(Handler<>).MakeGenericType(typeof(int))` gets `IL3050` at publish, and if you run it anyway you get an exception at the `MakeGenericType` call — not a graceful fallback. The same call with `typeof(string)` will frequently work, because the shared reference-type body probably exists. **This is the worst possible failure mode: it works for the reference types you tested and throws for the value type a customer used**, so "we tested it and it was fine" is not evidence.

**2. Generic code has a *size* cost under AOT that it doesn't have under JIT.** Every value-type instantiation that is statically reachable gets compiled into the binary whether or not it runs. Generic virtual methods and generic instance methods multiply further — one instantiation per implementing or overriding type. A deeply generic abstraction that costs nothing under JIT (because only the instantiations you actually use ever get compiled) can visibly inflate a Native AOT binary. .NET 10's `UseSizeOptimizedLinq` — on by default with `PublishAot` — exists precisely because LINQ's throughput optimizations are heavily generic and pay for themselves in code size.

```
JIT                                    Native AOT
───                                    ──────────
Repo<Order>   ─┐                       Repo<Order>   ─┐
Repo<User>    ─┼─► one shared body     Repo<User>    ─┼─► one shared body   (refs share)
Repo<Invoice> ─┘   (all reference)     Repo<Invoice> ─┘

Repo<int>      ──► compiled on         Repo<int>      ──► compiled at publish
                   first use                               ONLY IF statically reachable
Repo<Guid>     ──► compiled on         Repo<Guid>     ──► if only reachable via
                   first use                               MakeGenericType: NOT COMPILED
                                                           → IL3050 at build
                                                           → throws at run
```

> 🌍 **In the real world**: a message dispatcher resolved handlers with `typeof(IHandler<>).MakeGenericType(messageType)` and `Activator.CreateInstance`, which is the canonical shape of this bug. Under JIT it was flawless for years. The AOT publish produced `IL3050`, someone suppressed it with `[UnconditionalSuppressMessage]` on the grounds that "all the handlers are registered in DI so the types are definitely there" — a justification that is about *types existing*, not about *native code for an instantiation existing*, which are different claims. It shipped. Every message whose payload was a class worked. The one message type that was a `readonly record struct` threw on first receipt in production. The fix was to invert the direction: a source generator read the `IHandler<T>` implementations at build time and emitted an explicit `switch` over message types returning concrete handlers, which made every instantiation statically reachable and deleted the reflection entirely. **The general rule: under AOT, `MakeGenericType` is safe only for instantiations something else in the program already forces into existence — and "something else forces it" is exactly what you cannot see from the call site.**

### `[UnsafeAccessor]` — private access without reflection

A large fraction of real-world reflection isn't about dynamism at all. It's about *accessibility*: a test needs to poke a private field, a serializer needs a private setter, a library needs an `internal` member of a framework type it can't change. That use of reflection has been AOT-hostile and slow for no good reason, and since .NET 8 it has an answer.

`[UnsafeAccessor]` is applied to an `extern static` method with no body. The runtime supplies the implementation by matching the attribute's `Kind` and `Name` against the type identified by the **first parameter**, and the call site compiles down to a direct access — no `MemberInfo`, no `object[]`, no boxing, no per-call lookup, and nothing for the trimmer to be uncertain about.

```csharp
// The type you don't own:
public class Order
{
    private Order(decimal total) => _total = total;
    private decimal _total;
    private void Recalculate(bool force) { }
}

internal static class OrderAccessors
{
    // A ref to the private field — read and write through it.
    [UnsafeAccessor(UnsafeAccessorKind.Field, Name = "_total")]
    public static extern ref decimal Total(Order o);

    // A call to the private method. The first parameter is the receiver.
    // (a string, necessarily — nameof can't reference an inaccessible member)
    [UnsafeAccessor(UnsafeAccessorKind.Method, Name = "Recalculate")]
    public static extern void Recalculate(Order o, bool force);

    // A private constructor: no receiver parameter; the return type names the target.
    [UnsafeAccessor(UnsafeAccessorKind.Constructor)]
    public static extern Order Create(decimal total);
}

// usage
Order order = OrderAccessors.Create(0m);
OrderAccessors.Total(order) = 42m;          // assign through the returned ref
OrderAccessors.Recalculate(order, force: true);
```

Rules worth knowing, because they are the ones that bite:

- The **first parameter identifies the owning type**, and **only that type is searched — the hierarchy is not walked.** A private field on a base class needs an accessor whose first parameter is the base type.
- For instance members on a **struct**, the first parameter must be `ref`.
- **Field accessors must return `ref`** — that's what makes them both readable and writable.
- For `StaticMethod` / `StaticField`, the first argument's value is unused and may be `null`; it exists purely to name the type.
- If nothing matches, the body throws `MissingFieldException` / `MissingMethodException` — a *runtime* failure, so this is not a compile-time-checked backdoor. Signature matching follows ECMA-335 metadata rules and **includes the return type**.
- Generic parameters are supported **from .NET 9**, and constraints must match the target exactly or you get `InvalidProgramException`.
- Always set `Name` explicitly rather than relying on the accessor method's own name: the docs call out that C# local functions get mangled IL names, so the default is a trap. The docs' recommended form is `Name = nameof(X)`, which works only when the member is visible to you; when it isn't — the usual case — `Name` has to be a string literal.
- .NET 10 adds **`[UnsafeAccessorType]`**, which names the target type as a *string* — for `internal` types in another assembly or private nested types you cannot write down in C# at all.

> 🌍 **In the real world**: a test suite verified internal state by caching `FieldInfo` in static fields and calling `GetValue`/`SetValue`. It was fine until someone renamed a private field during a refactor: nothing failed to compile, three tests started asserting against `null`, and because they were asserting a negative ("the cache should be empty") they *passed*. Converting them to `[UnsafeAccessor]` didn't make the rename break the build either — the name is still a string — but it changed the failure from a silent `null` to a `MissingFieldException` at first use, which the test run reports as an error rather than a pass. **When you must couple to a private name, pick the mechanism that fails loudly**; `[UnsafeAccessor]` and reflection cost the same in coupling and differ entirely in what happens when the coupling breaks.

### Reading attributes without constructing them

`member.GetCustomAttribute<FooAttribute>()` does something people forget: it **runs the attribute's constructor**, on the spot, to hand you a live object. That requires loading the assembly the attribute type lives in and executing code from it. Usually irrelevant; occasionally the whole problem.

`GetCustomAttributesData()` returns `CustomAttributeData` instead — the raw metadata: which constructor was referenced, what the encoded positional arguments were, what the named arguments were. Nothing is constructed and, per the docs, you can use it specifically when "you might want to avoid loading the assembly that contains the code for a custom attribute."

Two consequences that are easy to get wrong in an interview:

- `CustomAttributeData` gives you **the values that were written at the use site**, not the semantics of the constructor. If the attribute's constructor normalises its input, or a property has side effects, you won't see any of that.
- `CustomAttributeData` **does not walk the inheritance chain**. There is no `inherit: true`. If you need inherited attributes, you're back to `GetCustomAttributes`.

This is also the only sane way to inspect assemblies you cannot or should not load. `Assembly.ReflectionOnlyLoad` still exists in the API surface on modern .NET but throws `PlatformNotSupportedException` — the reflection-only *context* is gone. The replacement is **`MetadataLoadContext`** (the `System.Reflection.MetadataLoadContext` NuGet package). It loads assemblies as pure metadata — right architecture or not, reference assembly or not — resolves dependencies through a `MetadataAssemblyResolver` you supply (usually `PathAssemblyResolver`, and you must include the core assembly), and **cannot execute anything**. Which is exactly why the docs tell you to use `GetCustomAttributesData` rather than `GetCustomAttributes` inside one.

```csharp
var paths = new List<string>(Directory.GetFiles(RuntimeEnvironment.GetRuntimeDirectory(), "*.dll"))
{
    "Plugin.dll"
};
using var mlc = new MetadataLoadContext(new PathAssemblyResolver(paths));

Assembly a = mlc.LoadFromAssemblyPath("Plugin.dll");
foreach (Type t in a.GetTypes())
    foreach (CustomAttributeData cad in t.GetCustomAttributesData())
        Console.WriteLine($"{t.FullName}: {cad.AttributeType.FullName}");
```

One trap the docs call out explicitly: **types from a `MetadataLoadContext` and runtime types are not interchangeable.** `typeof(IPlugin).IsAssignableFrom(loadedType)` is always false, because they're different `Type` objects from different worlds. Load `typeof(IPlugin).Assembly.Location` into the same context and compare *those*.

> 🌍 **In the real world**: a build-time validation step scanned plugin DLLs to check they declared a `[Plugin]` attribute with a supported schema version, by `Assembly.LoadFrom`-ing each one and reading the attribute. It ran on the CI agent, which meant the CI agent executed static constructors from unreviewed third-party code, and it could not validate a plugin built for a different architecture at all. Rewritten over `MetadataLoadContext` + `GetCustomAttributesData`, the check executed nothing, worked cross-architecture, and got faster because it never loaded dependency graphs. **"Read the metadata" and "load the assembly" are two different operations and only one of them runs somebody else's code.**

### Inside an incremental generator — the pipeline is a cache

Most people can say "`IIncrementalGenerator` is faster than `ISourceGenerator`". Far fewer can say *what makes it fast*, and that is the question a senior gets asked.

An incremental generator does not "run". It **declares a dataflow pipeline** of providers and transformations, and the host caches the output of every step keyed by the equality of that step's inputs. When you type a character, the host re-runs only the steps whose inputs actually changed — and if a step's output is `Equals` to what it produced last time, everything downstream is served from cache and never runs at all.

That single sentence generates every real rule about writing them:

**1. Use `ForAttributeWithMetadataName` — it is not sugar.** The naive `CreateSyntaxProvider` predicate is invoked for essentially every syntax node in the compilation on every edit. `ForAttributeWithMetadataName` (Roslyn 4.3 / the .NET 7 SDK and later) uses an index the compiler already maintains, so it discards the overwhelming majority of nodes and edits before your predicate is ever called — and it still resolves `using` aliases correctly, which hand-rolled syntactic matching gets wrong.

```csharp
IncrementalValuesProvider<Model> models = context.SyntaxProvider
    .ForAttributeWithMetadataName(
        "MyLib.RedactAttribute",
        predicate: static (node, _) => node is PropertyDeclarationSyntax,
        transform: static (ctx, _) => Extract(ctx));   // ctx.TargetSymbol is the *annotated* member
```

**2. Never put a `Compilation`, `ISymbol`, or `SyntaxNode` in the pipeline.** They have reference equality, they change on every keystroke, and they root the entire compilation in memory. The cache then misses every time and you have written a slow `ISourceGenerator` with extra ceremony. Project each match down to a small, value-equal **data model** — a `record` of strings, enums, and booleans — as early as possible, and let everything downstream see only that.

**3. `record` equality is not automatically the equality you want.** A `record` containing an `ImmutableArray<T>` compares that array by *reference*, so two structurally identical models won't be equal and the cache still misses. Either wrap collections in a comparer that compares element-wise, or flatten them into a single string. This is the bug that silently undoes the whole optimization, and it is invisible — the generator still produces correct output, just slowly, forever.

**4. Emit through `RegisterPostInitializationOutput` for anything that doesn't depend on user code** — marker attributes, base classes, static helpers. It runs once, before any analysis, which is what lets a generator-only package define the attributes you decorate your code with.

**5. Generators cannot see each other's output.** All generators run against the same input compilation; one generator's emitted file is not an input to another's analysis in that pass. If your design needs "generator A produces the type that generator B reflects on", it doesn't work — merge them.

**6. Generators can only *add*.** They cannot modify or delete existing code, which is why every generator-backed API is built on `partial`. The one exception is **interceptors**: a generator emits a method annotated `[InterceptsLocation(...)]` whose data encodes a specific call site (file, position, and a content hash), and the compiler redirects *that exact call* to the generated method. The caller's source is untouched; the binary calls somewhere else. This is how the minimal-API request delegate generator replaces `app.MapGet(...)`'s reflection-based binding without asking you to change a line. Two guard rails matter: only generators should emit them (the location data has to be recomputed by the compiler on every build, so hand-written ones rot instantly), and the consuming project must opt in by listing the generator's namespace in `<InterceptorsNamespaces>` — a package cannot silently reroute your calls.

**7. Never throw from a generator.** An exception surfaces as an opaque build error with no useful stack. Catch, and report a `Diagnostic` instead.

> 🌍 **In the real world**: a team wrote a mapper generator, shipped it internally, and within a month people started complaining that IntelliSense in the largest project had become unusable — several seconds of lag per keystroke. The generator was correct; it was also re-running in full on every edit, because its pipeline carried a `record Model(string Name, ImmutableArray<string> Properties)` and `ImmutableArray<string>` compares by reference. Every keystroke produced a fresh array, every model compared unequal, every downstream step re-ran, and the emitted text was byte-for-byte identical every time. The fix was a dozen lines: an `IEquatable<T>` wrapper doing an element-wise comparison. What makes this worth remembering is that **the failure had no symptom in the output** — no wrong code, no build error, nothing a test could catch. The only signal was IDE latency, which is exactly the signal teams attribute to their laptop.

### Plugins, `AssemblyLoadContext`, and the unload contract

This is the honest counter-example to "just use a source generator": the one scenario where runtime reflection is not a legacy habit but the actual requirement. If DLLs arrive in a folder after your build, no generator can help, and neither can trimming or AOT — dynamic assembly loading is listed as a known trimming incompatibility for exactly this reason.

.NET Core has no `AppDomain` to unload. The replacement is a **collectible `AssemblyLoadContext`**, and the crucial difference is in the word *cooperative*: `AppDomain.Unload` was forced (it aborted threads); `AssemblyLoadContext.Unload()` merely *initiates* unloading. It completes only when, per the docs, no thread has a frame from those assemblies on its stack **and** nothing outside holds a strong reference to any assembly, type, or instance from the context.

```csharp
sealed class PluginContext(string mainAssemblyPath) : AssemblyLoadContext(isCollectible: true)
{
    private readonly AssemblyDependencyResolver _resolver = new(mainAssemblyPath);

    protected override Assembly? Load(AssemblyName name)
        => _resolver.ResolveAssemblyToPath(name) is { } path ? LoadFromAssemblyPath(path) : null;
}
```

The list of things that quietly prevent unload is longer than anyone expects, and every item on it is a real production bug:

- A **`MethodInfo` or `Type` held in a local or a static** anywhere outside the context — including locals the JIT kept alive that you never named. This is why the sample code puts load-and-run inside a `[MethodImpl(MethodImplOptions.NoInlining)]` method: so the stack slots go out of scope.
- A **thread still running plugin code**. Cooperative means cooperative; nothing is aborted for you.
- A **strong or pinned `GCHandle`** to anything from the context, from inside *or* outside it.
- A pending **`RegisteredWaitHandle`** whose callback points into the plugin.
- **Fields on your own `AssemblyLoadContext` subclass** that reference loaded types — while unloading is in progress the runtime holds a strong handle to the context to coordinate, so those fields stay rooted even after you drop your reference. Clear them.
- Only `WeakReference`/`WeakReference<T>` are exempt, which is why the canonical "did it unload?" check is a `WeakReference` to the context plus a bounded `GC.Collect()` / `GC.WaitForPendingFinalizers()` loop.

Also: C++/CLI assemblies can't be loaded collectibly at all, and ReadyToRun code in a collectible context is ignored (it gets JITted instead).

When it doesn't unload, the debugging recipe is fixed: load SOS, `!dumpheap -type LoaderAllocator` to find the `LoaderAllocator` for the context, then `!gcroot <address>` to get the reference chain holding it, and `~*e !clrstack` to check whether a thread still has a plugin frame.

> 🌍 **In the real world**: a rules engine hot-reloaded customer-authored rule assemblies into collectible contexts on every config change. Memory grew by a few megabytes per reload and nobody noticed for months, because each reload was small and reloads were rare. The root, when SOS finally pointed at it, was a `ConcurrentDictionary<Type, Func<Context, bool>>` compiled-delegate cache in the *host* — keyed by plugin types, holding delegates over plugin code, living in a static field outside the context. It pinned every version of every rule assembly ever loaded. The lesson generalises past plugins: **a cache is a strong reference with a friendly name**, and any cache keyed by a `Type` from a collectible context has to be cleared in the context's `Unloading` event or be built on weak references from the start.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌───────────────────────────────────────────────────────────────┐
│   Reflection vs Source Generation — where the work happens     │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│   Reflection (runtime)                                         │
│   ──────────────────                                           │
│   1. Compile time: emit no extra code.                         │
│   2. Every call: walk type metadata, find member, box args     │
│      into object[], validate, invoke, unbox result.            │
│   3. Caching MethodInfo removes step "find member" only —      │
│      the array, the boxing and the validation remain.          │
│   4. Trimmer/AOT cannot see the target → may be removed.       │
│                                                                │
│                                                                │
│   Source generator (compile time)                              │
│   ───────────────────────────────                              │
│   1. Compile time: generator inspects user code, emits         │
│      specialized methods (e.g. void Serialize(User u, Stream s)│
│      ... explicit code for each property ...).                 │
│   2. Every call: a normal C# call. No array, no boxing,        │
│      no validation, and the JIT may inline it.                 │
│   3. AOT-friendly: trimmer sees real method calls.             │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

**Reflection invocation ladder (cheapest → most expensive).** Ordinal, not measured — the actual ratios depend entirely on what the target member does, so benchmark your own case rather than quoting a multiplier:

```
  cheapest
    │
    │  1. Direct call / source-generated call     no indirection; inlinable
    │  2. [UnsafeAccessor] extern static          direct access; AOT-safe
    │  3. MethodInfo.CreateDelegate<T>()          one delegate indirection
    │  4. Expression.Lambda<T>().Compile()        delegate + generated stub
    │                                             (interpreted under AOT!)
    │  5. MethodInvoker.Create(...) cached        signature-specialized stub
    │  6. Cached MethodInfo + Invoke              object[] + box + validate
    │  7. dynamic, monomorphic call site          DLR call-site cache hit
    │  8. dynamic, polymorphic call site          cache miss → rebind
    │  9. GetMethod(...) + Invoke() in the loop   all of 6, plus a lookup
    │     and an allocation, every single call
    ▼
  most expensive
```

Two things to read off it. First, the jump that matters most is **6 → 3**: not "reflection is slow" but "the `object[]`-and-boxing calling convention is slow", and binding a typed delegate removes the calling convention rather than the reflection. Second, tiers 4, 7 and 8 are the ones that change *behaviour* under Native AOT rather than just getting slower — 4 falls back to the expression interpreter, and `dynamic` doesn't work at all. Tiers 6 and 9 keep working under AOT provided the members they reach were preserved; they just stay slow.

**The shape of the benchmark that settles this**, if you're asked to design one:

```csharp
[MemoryDiagnoser]                       // the allocation column usually decides it
public class InvokeBench
{
    private static readonly User s_user = new();
    private static readonly MethodInfo s_mi = typeof(User).GetMethod(nameof(User.GetEmail))!;
    private static readonly MethodInvoker s_invoker = MethodInvoker.Create(s_mi);
    private static readonly Func<User, string> s_del = s_mi.CreateDelegate<Func<User, string>>();

    [Benchmark(Baseline = true)] public string Direct()   => s_user.GetEmail();
    [Benchmark] public object? CachedInvoke()             => s_mi.Invoke(s_user, null);
    [Benchmark] public object? Invoker()                  => s_invoker.Invoke(s_user);
    [Benchmark] public string  Delegate_()                => s_del(s_user);
}
```

Note what is *not* in it: no `GetMethod` inside a `[Benchmark]` method (that measures lookup, not invocation), and a target with a trivial body — because a target that does real work hides exactly the fixed cost you're trying to see. If the interviewer's real question is "should we optimize this", the benchmark above answers the wrong one; the right one is what fraction of a request this call accounts for.

</details>
## Common pitfalls

1. **Calling `GetProperty(name)` in a loop.** It walks metadata every call. Cache the `PropertyInfo` once at startup or use an `Expression`-compiled getter.
2. **`Activator.CreateInstance(type, ...)` for hot paths.** Use a compiled factory delegate or `new()` constraint instead.
3. **`Type.GetMethods()` with no `BindingFlags`.** The parameterless overload returns *public* methods — instance **and** static — plus inherited public *instance* methods, but not inherited public *statics* (those need `FlattenHierarchy`) and never constructors. Non-public is excluded. Be explicit rather than remembering the table.
4. **Forgetting `[AttributeUsage]`.** Without it, your custom attribute can be applied to anything, multiple times, leading to confusing behavior.
5. **Using `dynamic` for "convenience."** Errors at runtime, slower, no IDE help. If you find yourself reaching for `dynamic`, ask: can I deserialize to a concrete record? Can I use generics?
6. **Source generator that throws.** Build fails with confusing errors and no stack trace. Always wrap your generator's logic in try/catch and emit a diagnostic, not throw.
7. **Reflection bypassing access modifiers without thought.** `BindingFlags.NonPublic` + `Invoke` works, but you've coupled to the implementation. Prefer designing a public API or using `InternalsVisibleTo` for testing. When you genuinely must, `[UnsafeAccessor]` is the same coupling with none of the runtime cost and none of the AOT problem.
8. **Forgetting to mark generator output `partial`.** If the user's class is `class Foo {}` and you generate `class Foo { static method }`, the build fails. Source generators always work via `partial class` extension.
9. **AOT failures discovered too late.** Reflection-heavy code "works" until you publish AOT. Put `<PublishAot>true</PublishAot>` in the project file rather than passing it on the command line — the docs are specific that it "controls behaviors outside publish", so it's what turns on the analyzer during ordinary builds and editing. Then publish in CI, with `<TrimmerSingleWarn>false</TrimmerSingleWarn>` so each `PackageReference` doesn't collapse to one useless warning.
10. **Suppressing a trim warning with `[SuppressMessage]` or `#pragma`.** They're source-only; the publish-time trimmer never sees them, so the warning comes back and the risk was never addressed. `[UnconditionalSuppressMessage]` is the one that persists into IL — and using it means you are personally asserting an invariant the tool could not prove.
11. **Caching `MethodInfo` across DLL reload boundaries.** If you reload an assembly (rare in modern .NET, but happens with plugin systems), `MethodInfo` from the old version is stale — and worse, the cache holding it is precisely what prevents the old `AssemblyLoadContext` from unloading. Invalidate on the context's `Unloading` event.
12. **`GetCustomAttribute` in a hot path.** Each call constructs a *new* attribute instance from the stored metadata. In a per-request or per-item loop that's an allocation plus a constructor call for data that cannot have changed since compile time. Cache per member.
13. **Assuming `GetMethod(name)` returns `null` when it's ambiguous.** It throws `AmbiguousMatchException`. `null` means "not found"; the exception means "found several".
14. **Enabling a trimming feature switch for size without reading what it changes.** `InvariantGlobalization`, `UseSystemResourceKeys`, and `StackTraceSupport` all alter observable behaviour, not just binary size.

## Interview-ready summary

- **Attributes** are inert metadata on types/members. Define by deriving `Attribute`, mark with `[AttributeUsage(...)]`. Code reads them via reflection — and the attribute object is constructed lazily, on each read, from encoded metadata.
- **Reflection's cost is a calling convention, not a mystery**: an `object[]`, a box per value argument, per-call validation, and no inlining. Caching `MethodInfo` removes the lookup only; `CreateDelegate<T>()` or `MethodInvoker` (.NET 8+) removes the convention.
- **`dynamic`** routes calls through the DLR — type-checks at runtime, caches per call site, generates code. Use sparingly: COM, genuinely dynamic data, language interop. Never under AOT.
- **Source generators** replace reflection at compile time — same convenience, no runtime metadata work, AOT-compatible. `System.Text.Json`, `[LoggerMessage]`, `[GeneratedRegex]`, the minimal-API request delegate generator, and the configuration-binding generator all ship in the box.
- **Roslyn analyzer** ≠ source generator: analyzers report diagnostics (warnings/errors), generators emit new source files. An `IIncrementalGenerator` is a *cached dataflow pipeline*, so its performance lives or dies on whether your pipeline data model has value equality.
- **Trimming and AOT are different guarantees.** Trimming (`IL2xxx`, `[RequiresUnreferencedCode]`, `[DynamicallyAccessedMembers]`) is about members that might be *removed*. AOT (`IL3xxx`, `[RequiresDynamicCode]`) is about native code that will never be *generated* — `MakeGenericType`, `Reflection.Emit`, `Expression.Compile`. `PublishAot` implies trimming and single-file; `PublishReadyToRun` implies neither.
- **The generics rule under AOT**: reference-type instantiations share one body; value-type instantiations each need their own, and all of them must be pre-generated. So `MakeGenericType(typeof(string))` usually works and `MakeGenericType(typeof(int))` throws — the worst possible failure shape.
- **`[UnsafeAccessor]`** (.NET 8+; generics .NET 9; `[UnsafeAccessorType]` .NET 10) gets you private/internal access with no reflection, no allocation, and full AOT compatibility. Reach for it whenever the reason you wanted reflection was accessibility rather than dynamism.
- **Reflection still wins** for one thing: types that don't exist at build time. Plugin hosts, scripting, DLLs dropped in a folder. That path also means no trimming and no AOT, and unloading requires a collectible `AssemblyLoadContext` whose unload is *cooperative*.
- **Invocation ladder**: direct ≈ source-gen ≈ `[UnsafeAccessor]` < `CreateDelegate` < compiled expression < `MethodInvoker` < cached `Invoke` < `dynamic` < `GetMethod` in the loop. Ordinal only — measure your own case with `[MemoryDiagnoser]`.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Cost of reflection

> **Q**: Why is `methodInfo.Invoke(obj, args)` slower than a direct method call?
>
> **A**: Not because "reflection is slow" — because `Invoke` has **one signature for every method in existence**, so everything a normal call resolves at compile time has to be resolved per call. Concretely: an `object[]` allocation for the arguments, **a box per value-type argument**, runtime validation of count and assignability plus by-ref and `Type.Missing` handling, an unbox-and-store on the way in, a box on the way out, and no possibility of inlining. All of that is a *fixed* cost per call, independent of what the target does — which is why it's dominant on a property getter and invisible on a method that hits a database. Adding `GetMethod(name)` inside the loop layers a metadata lookup and more allocations on top. I'd avoid quoting a multiplier: the ratio is entirely a function of the target's own cost.
>
> **Cross-Q**: How would you get close to direct-call cost?
>
> **A**: Stop using the `object[]` convention. Three options in ascending order of flexibility. (1) **`MethodInfo.CreateDelegate<T>()`** — the generic overloads shipped in **.NET 5**; the non-generic `CreateDelegate(Type)` is much older. You get a real delegate; invoking it is one indirection, no array, no boxing, no validation. (2) **`MethodInvoker.Create(methodBase)`** (**.NET 8**) — when the signature isn't statically known so you can't name a `Func<>`. It builds an invocation stub specialized to that method's signature once, so the validation isn't repeated; the trade documented by Microsoft is that it skips `Type.Missing` default-value lookup and the target may be inlined out of stack traces. (3) **`Expression.Lambda<T>().Compile()`** when the shape is composed at runtime — but note it emits via `DynamicMethod`, and under Native AOT there is no `DynamicMethod`, so expressions fall back to the interpreter.
>
> **Cross-Q²**: Why is `CreateDelegate` faster than a compiled expression tree?
>
> **A**: `CreateDelegate` binds a delegate straight at the target method — the invocation is an ordinary delegate call. `Expression.Lambda(...).Compile()` emits a **new** method through `DynamicMethod` whose body calls the original, so you pay an extra frame, plus a substantial one-time compile cost, plus the memory for the generated method. Use `CreateDelegate` when you have a `MethodInfo` and know the signature; use expression trees when you need to *build* something — a getter with a type conversion, a composed predicate, a constructor call with defaults. And know the AOT asymmetry: `CreateDelegate` is fine under Native AOT, `Compile()` silently degrades to interpretation.

### Drill 2 — Reflection vs source generators

> **Q**: When is reflection the right tool over source generation?
>
> **A**: When the **types aren't known at compile time** — plugin loaders that drop DLLs into a folder at runtime, scripting hosts (Roslyn-scripted user code), ORMs over arbitrary user entities, DI containers scanning unknown assemblies. Source generators only see what's in your compilation; if your code is "load whatever is in `/plugins` and instantiate every `IPlugin`," generators can't help. Reflection is also fine for **one-time startup work** — service registration, attribute scanning at init — where a per-type cost paid once, before the first request, is not on any latency budget you care about. The caveat is that "startup" stops being free when the process starts often: at hundreds of instances or in a scale-to-zero serverless model, startup reflection *is* the p99, which is exactly the pressure that produced compiled models and the configuration-binding generator.
>
> **Cross-Q**: And when does source generation crush reflection?
>
> **A**: When the same reflective work happens repeatedly at runtime on **types known at build time** — JSON serialization, logging, model binding, regex compilation, mapper code. Source generators emit the specialized code at compile time: no runtime metadata lookups, no metadata structures to allocate, AOT-compatible, trimmer-safe. Microsoft's own write-up on the `System.Text.Json` generator reports "up to 40% or more startup time reduction, private memory reduction, throughput speed increase (in serialization optimization mode), and app size reduction" — worth citing as *their* number rather than one of mine, and worth noting that the biggest single component is **startup**, because the reflection path's cost is dominated by building `JsonTypeInfo` on first use. Logging via `[LoggerMessage]` does the level check before touching any argument, so a disabled level costs nothing at all.
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
> **A**: **Compile-time constants** — literals, `const` fields, enum values, `typeof` expressions, `nameof`, single-dimensional arrays of these, and named-property assignments to the same. Note the sharp edge: a `const string` works and a **`static readonly string` does not**, because `readonly` is a runtime guarantee and `const` is a compile-time substitution — the compiler needs the actual bytes to write into the metadata blob. You also cannot pass a method result, a constructed object (`[Foo(new Uri("..."))]`), or any runtime expression. The workaround for a non-constant is always the same: pass a `string` or a `typeof` and resolve it in the consumer.
>
> **Cross-Q²**: If attributes are stored as metadata, when does an attribute *object* actually get constructed?
>
> **A**: **Lazily, on every reflection access.** Calling `member.GetCustomAttribute<FooAttribute>()` makes the runtime construct a *fresh* `FooAttribute` instance from the stored metadata, actually running its constructor with the encoded args. Each call allocates a new one — caching is your job — and it requires **loading the assembly the attribute type lives in and executing code from it**. If that's a problem (a build tool inspecting untrusted assemblies, a `MetadataLoadContext` where nothing can execute), use `GetCustomAttributesData()` instead: it returns `CustomAttributeData` describing the constructor reference and the encoded arguments, with nothing constructed. Two caveats — it reports the values as *written*, not whatever the constructor would have normalised them to, and it has no `inherit: true`, so it never walks the base chain.

### Drill 4 — `[CallerMemberName]`

> **Q**: How does `[CallerMemberName]` work?
>
> **A**: It's a **compile-time call-site injection attribute**. When a method has a parameter marked `[CallerMemberName] string memberName = ""`, the compiler injects the calling member's name (method, property, event) as the default value at each call site. The injection happens at compile time — no reflection at runtime. The default value can still be overridden explicitly.
>
> **Cross-Q**: Where's this used in real-world code?
>
> **A**: Two canonical patterns. (1) **`INotifyPropertyChanged`** — `protected void OnPropertyChanged([CallerMemberName] string name = "") => PropertyChanged?.Invoke(this, new(name));` — setters call `OnPropertyChanged()` with no argument, and the compiler injects the setter's property name. Eliminates the `nameof(MyProperty)` string-typing in every setter. (2) **Your own logging helper**, since you can't put the attribute at a call site — it goes on the *parameter of the helper you call*:
> ```csharp
> void LogFailure(Exception ex, [CallerMemberName] string method = "", [CallerLineNumber] int line = 0)
>     => _logger.LogError(ex, "Failed in {Method} at line {Line}", method, line);
>
> // call site — no arguments, compiler fills both in
> LogFailure(ex);
> ```
> Note what this buys over a stack trace: it's resolved at compile time, so it survives inlining, release builds, and trimmed deployments where `StackTraceSupport` may be off.
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
> **A**: **No** — `AttributeUsage.Inherited` only walks the **class inheritance chain**, not interface implementations. An `[Audit]` attribute on `IService` is *not* discoverable on `Service : IService` via `GetCustomAttribute(inherit: true)`. If you want it you must enumerate the interfaces yourself: `type.GetInterfaces().SelectMany(i => i.GetCustomAttributes(typeof(AuditAttribute), inherit: false))`. The same applies at the member level — an attribute on an interface *method* does not flow to the implementing method. This is the single most common surprise in convention-based discovery, and the reason it hurts is that the failure is silent: you get an empty result, not an exception. Any attribute-driven registry should log its registration count at startup so "found none" is distinguishable from "nothing to do".

### Drill 7 — `Type.GetMethods()` and binding flags

> **Q**: `type.GetMethods()` with no arguments — what do you get?
>
> **A**: The docs phrase it as "all the **public** methods of the current `Type`" — which means public **instance and static**, equivalent to `BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static`. **Excluded**: everything non-public (private, protected, internal), and constructors — those need `GetConstructors()`. On inheritance the rule is asymmetric: inherited public *instance* methods **are** returned; inherited public *statics* are **not**, unless you ask for `FlattenHierarchy`. `FlattenHierarchy` is *not* implicit. One more detail people miss: from .NET 7 the returned order is deterministic (metadata order in the assembly); on .NET 6 and earlier it was explicitly unspecified — so any code that depends on ordering was always a bug and is now merely a bug that happens to work.
>
> **Cross-Q**: How do I get private and static methods declared on this type only (no inherited)?
>
> **A**: `type.GetMethods(BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly)`. Three flags combined: `NonPublic` (private + protected + internal), `Static` (no instance), `DeclaredOnly` (no inherited). **Gotcha**: the accessibility and the instance/static axes are independent, and you must supply at least one from each or you get nothing back — `BindingFlags.Default` alone returns an empty array by design. Also note `NonPublic` returns protected and internal methods from base classes but **not private ones**, since private members aren't inherited. Reaching for everything means `Public | NonPublic | Instance | Static`, then filtering.
>
> **Cross-Q²**: What does `typeof(int).GetMethod("ToString")` do?
>
> **A**: It **throws `AmbiguousMatchException`** — it does not return `null`. `Int32` has four `ToString` overloads and the name-only lookup can't choose. That's the important distinction: `null` means *not found*; the exception means *found several*. Disambiguate by passing the parameter types — `GetMethod("ToString", Type.EmptyTypes)` for the parameterless one, or `GetMethod("ToString", [typeof(IFormatProvider)])`. The reason this matters beyond trivia is that generic helper code written as `t.GetMethod(name) is null ? throw new(...) : ...` looks like it handles every failure and handles exactly one of them; a plugin or config-driven lookup will eventually meet an overloaded name and surface an exception the author never anticipated.

### Drill 8 — `MethodInfo.Invoke` vs `Delegate.CreateDelegate`

> **Q**: When would you reach for `Delegate.CreateDelegate` over `MethodInfo.Invoke`?
>
> **A**: When you'll **call the method many times** with a **known signature** at code-write time. `CreateDelegate` produces a `Delegate` you can invoke directly — call overhead is one indirection, similar to a virtual call. `MethodInfo.Invoke` allocates an `object[]`, boxes every value-type argument, validates the arguments on every call, and boxes the return. The trade-off: `CreateDelegate` requires you to know the signature at compile time to name the right `Func<>` / `Action<>` type.
>
> **Cross-Q**: Sketch the code.
>
> **A**:
> ```csharp
> // One-time setup (slow):
> var method = typeof(User).GetMethod("GetEmail")!;
>
> // .NET 5+ generic overload — preferred, no cast:
> var getEmail = method.CreateDelegate<Func<User, string>>();
>
> // Older / non-generic form, note it is an instance method on MethodInfo:
> var getEmail2 = (Func<User, string>)method.CreateDelegate(typeof(Func<User, string>));
>
> // Hot path:
> string email = getEmail(user);
> ```
> There is **no** `Delegate.CreateDelegate<T>` static — the generic overloads live on `MethodInfo`. The delegate type must match the method's signature exactly. For an *open* instance delegate the first parameter is the receiver (`Func<User, string>` above); to bind the receiver up front, use the `CreateDelegate<T>(object? target)` overload and drop it from the signature (`Func<string>`). For statics, no receiver either way.
>
> **Cross-Q²**: How does this compare to a compiled `Expression.Lambda`?
>
> **A**: `Delegate.CreateDelegate` is slightly faster (no extra indirection through generated IL) but **only works when the signature is statically known**. `Expression.Lambda<...>().Compile()` works for **arbitrary IL emission** — you can compose property access, method calls, conversions, branches inside an expression tree, then compile. Use `CreateDelegate` for "I have a `MethodInfo`, want a fast wrapper"; use Expression trees for "I want to dynamically build a getter for property X with type coercion."

### Drill 9 — `dynamic` and the DLR

> **Q**: What does the DLR do behind the scenes when you call a method on `dynamic`?
>
> **A**: The compiler turns each `dynamic` operation into a **`CallSite<T>`** with a **binder**. The first execution invokes the binder, which runs the C# overload-resolution rules against the *runtime* types, produces an expression tree for the dispatch, compiles it to a delegate, and installs it in the call site's cache. Subsequent executions with the same runtime types run the cached delegate after a type-guard check. Different types add rules to the site's cache (a small polymorphic cache), and beyond that it falls back to a shared L2 cache and then to re-binding.
>
> **Cross-Q**: So `dynamic` is faster than `MethodInfo.Invoke`?
>
> **A**: For **repeated calls at a monomorphic site** — the same runtime types over and over — a warm `dynamic` site is typically the better of the two, because it has compiled a typed dispatch and no longer touches `MemberInfo` or `object[]`. For **one-off calls or a site that sees many types**, it's the worse of the two: you pay binder execution and expression compilation, which is far more than a cached `MethodInfo.Invoke` costs. I'd resist quoting ratios either way — the point is that the two have different *shapes*: `Invoke` has a flat per-call cost; `dynamic` has a large first-call cost amortized over a cache that only pays off if it hits.
>
> **Cross-Q²**: Why would you not just use `dynamic` everywhere reflection is needed?
>
> **A**: (1) **No IntelliSense** — the IDE can't help. (2) **Runtime errors only** — `obj.Tyoeo` (typo) compiles fine, blows up at runtime. (3) **Doesn't compose** with generics (`T dynamic` doesn't make sense), NRT (`dynamic?` is ill-defined), or pattern matching (`if (x is SomeType)` requires concrete types). (4) **AOT-hostile** — the DLR emits IL at runtime, which AOT can't precompile. Use `dynamic` for **legacy COM interop, traversing genuinely dynamic data (legacy JSON dynamic API), or scripting host bridges**. For typed-but-reflection scenarios, prefer cached `MethodInfo` or compiled delegates.

### Drill 10 — `System.Text.Json` source generation

> **Q**: What changes between `JsonSerializer.Serialize(obj)` (reflection) and `JsonSerializer.Serialize(obj, ctx.UserDto)` (source-gen)?
>
> **A**: **Reflection mode**: on first use, `JsonSerializer` walks `UserDto`'s public members via reflection and builds a `JsonTypeInfo` — property metadata, converters, getter delegates — which it then caches on the `JsonSerializerOptions`. Steady-state calls reuse that. **Source-gen mode**: a build-time generator emits the `JsonTypeInfo` as code, so the metadata-building step doesn't happen at runtime at all, and in *serialization-optimization* (fast-path) mode it also emits a method that writes directly to `Utf8JsonWriter` with no metadata indirection. The headline difference is therefore **startup and first-call**, not steady-state throughput — plus the thing that actually forces the decision, which is that the reflection path is not AOT-safe.
>
> One real limitation to name, because it catches people: source-gen mode supports only `public` or `internal` members and accessors. Putting `[JsonInclude]` on a `private` property works in reflection mode and throws `NotSupportedException` at runtime under source generation.
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
> The generator inspects each `[JsonSerializable(typeof(T))]` and emits a typed property `Default.T` returning a specialized `JsonTypeInfo<T>`. `JsonSourceGenerationMode.Serialization` emits only the fast path (serialize-only, smaller code); `Metadata` emits the metadata needed for both directions; the default emits both. In ASP.NET Core you don't pass the context at each call — you register it once: `options.SerializerOptions.TypeInfoResolverChain.Insert(0, AppJsonContext.Default)`.
>
> **Cross-Q²**: What happens if my options turn on something the fast path can't do?
>
> **A**: **The serializer detects it and falls back to metadata mode for that type** — silently, per type, at runtime. The documented list of options the fast path does not support includes `Converters`, `Encoder`, `NumberHandling`, `DictionaryKeyPolicy`, and — the one people hit — **`ReferenceHandler`**, so `ReferenceHandler.Preserve` for cycles always takes the slow path. Attribute-wise, `[JsonConverter]`, `[JsonConstructor]`, and `[JsonExtensionData]` also disable it. Two implications worth stating: (1) benchmark with *your* options, because a single global converter can quietly disable the fast path everywhere; (2) if you configured `JsonSourceGenerationMode.Serialization` **only**, there is nothing to fall back *to*, and serialization can fail outright for those types. As for `dynamic` — the generator sees `object`, because `dynamic` is `object` plus a marker at the metadata level; it emits polymorphic handling that resolves the runtime type at serialization time, which is exactly the resolution that has nothing to resolve against under AOT. The general rule stands: source-gen excels at **closed-shape DTOs**; open-ended shapes belong in reflection mode, and most apps mix both.

### Drill 11 — Reflection emit and dynamic types

> **Q**: When would you ever use `TypeBuilder` / `ILGenerator`?
>
> **A**: Rarely in modern .NET. The classic use cases were **proxy generation** (Castle.DynamicProxy, which Moq still builds on), **AOP weavers**, and **ORM accessor generation**. Modern alternatives: `System.Linq.Expressions` covers most of these cases with far less code; **source generators** cover the "I need real types" cases at compile time instead. And there is now a hard constraint that settles the argument for a lot of codebases: **`System.Reflection.Emit` is unsupported under Native AOT** — it's listed as "no runtime code generation" in the deployment limitations. Any library that wants to be AOT-compatible has to have a non-emit path, which is why mocking frameworks built on dynamic proxies remain a reason teams can't AOT their *test* projects even when the product code is clean.
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
> **A**: Bind a strongly-typed delegate once. Two paths: (1) `methodInfo.CreateDelegate<Func<int, string>>()` — simplest and cheapest per call. (2) Expression tree if you need to inject type coercion or build the call dynamically:
> ```csharp
> var p = Expression.Parameter(typeof(int));
> var call = Expression.Call(instance: null, methodInfo, p);
> var fn = Expression.Lambda<Func<int, string>>(call, p).Compile();
> for (int i = 0; i < 1_000_000; i++) fn(i);
> ```
> Either removes the per-call `object[]`, the box of `i`, the argument validation, and the unbox of the result that `methodInfo.Invoke(null, [i])` pays a million times.
>
> **Cross-Q**: What about caching `MethodInfo` and using `Invoke` — what exactly does that leave on the table?
>
> **A**: Caching removes the *lookup* and the `MemberInfo` allocations. It leaves the entire calling convention: an `object[]` allocation per call, a box of the `int`, count-and-assignability validation, and an unbox of the returned `string` reference. A bound delegate has none of those. This is why "we cached the `MethodInfo`, it's fine now" is only half a fix — and the allocation column of a benchmark shows the remaining half immediately.
>
> **Cross-Q²**: Why doesn't .NET cache the compiled delegate automatically for `MethodInfo.Invoke`?
>
> **A**: Because **`Invoke` is signature-agnostic by contract** — one method that accepts `object[]` for any target, plus semantics like `Type.Missing` default-value lookup that a typed stub can't reproduce. To specialize, the runtime would have to commit to a signature it doesn't know at the call site, and change documented behaviour. **.NET 8** added `MethodInvoker` (and `ConstructorInvoker`) as the opt-in version of exactly that: you create one from a `MethodBase`, it builds a stub specialized to that signature once, and you cache the invoker. The docs are explicit that it's faster "when compatibility with [`Invoke`] isn't necessary and when the caller can cache the `MethodInvoker` instance", and that it deliberately drops the `Missing` handling and may let the target be inlined out of stack traces. Rule of thumb: more than a handful of calls → `MethodInvoker` if the signature is dynamic, `CreateDelegate` if it isn't.

### Drill 13 — Detecting `[Obsolete]`: compile-time vs runtime

> **Q**: How does `[Obsolete]` produce a compile warning?
>
> **A**: The C# compiler **inspects the attribute during compilation**. When emitting a call to a method, it checks the method's metadata for `ObsoleteAttribute`; if present, it emits a `CS0612`/`CS0618` warning (or error if `Obsolete(error: true)`). The check happens at *every call site* across the assembly being compiled. No runtime cost — the warning is purely a compile-time signal.
>
> **Cross-Q**: Could I write my own attribute that produces a compile-time warning?
>
> **A**: **Not with an arbitrary attribute of your own** — `[Obsolete]` is special-cased by the C# compiler. But there is a second attribute in the same club: **`[Experimental("MYLIB001")]`** (C# 12+). The compiler treats it the same way, reporting a diagnostic under the ID *you* choose at every use site, which callers acknowledge by adding that ID to `NoWarn`. That covers the "this API will change" case without writing any tooling. For anything else — "don't call this from a background thread", "this overload is deprecated in favour of that one" — you write a **Roslyn analyzer**: register an `OperationKind.Invocation` action, inspect the target's attributes, report a `Diagnostic`. That is exactly what the analyzer paired with the `[LoggerMessage]` generator does for malformed templates. Without an analyzer or one of the two special-cased attributes, your attribute is invisible to the compiler.
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
> **A**: `IsSealed` — type cannot be subclassed (set for `sealed class`, structs, and enums). `IsValueType` — derives from `System.ValueType` (structs, enums). `IsEnum` — derives from `System.Enum`. `IsClass` — the docs define it as "a class **or a delegate**; that is, not a value type or interface", so `typeof(Action).IsClass` is `true`. It's `false` for structs and enums even when boxed, and — a genuine trap — it is `true` for `typeof(Enum)` and `typeof(ValueType)` themselves, since those are reference types that merely act as base types. **`IsValueType` and `IsClass` are mutually exclusive.** One last thing worth knowing: `typeof(T).IsValueType` inside a generic method is not a real reflection call at runtime — the JIT specializes the method per value-type instantiation and folds the test to a constant, so `if (typeof(T).IsValueType)` compiles away entirely. That's exactly the specialization that must be pre-generated ahead of time under Native AOT.

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
> **A**: **Yes** — that's its key guarantee, and the mechanism is worth knowing because it's often described wrongly. Every managed object on CoreCLR already carries a machine-word **object header** immediately before its method-table pointer. On the first `RuntimeHelpers.GetHashCode(obj)`, the runtime computes a hash and stores it **in that existing header word** (a flag bit says "these low bits are a hash code rather than a sync-block index"). Subsequent calls read it back. So the value survives GC compaction — the address moves, the header moves with the object — and, importantly, **the object does not grow**: the header is already there whether you call this or not. The only case that costs extra storage is when an object needs *both* a hash and a real sync block — the header word can hold one or the other, not both, so if the object is also contended-locked or acquires COM interop state, the runtime "inflates" it by allocating a sync-block entry in a side table and moving the hash there. (Weak references are *not* on that list: they're GC handles in the handle table, not sync-block state.) That inflation is the real cost of `lock`ing on arbitrary objects, and it is the same header word that pays for it.

### Drill 17 — Trim warning vs AOT warning

> **Q**: Your build emits `IL2026` on one call and `IL3050` on another. What's the difference and does the same fix work for both?
>
> **A**: They come from **different analyzers with different concerns**. `IL2026` is trim analysis: the callee is annotated `[RequiresUnreferencedCode]`, meaning it reflects in a way the trimmer can't follow, so members it needs might be *removed from the app*. The code is fine, the tool just can't prove what to keep. `IL3050` is AOT analysis: the callee is annotated `[RequiresDynamicCode]`, meaning it will ask the runtime to **produce native code that doesn't exist** — `MakeGenericType`, `MakeGenericMethod`, `Expression.Compile`, `Reflection.Emit`. Different fixes: `IL2026` can often be resolved by expressing the requirement with `[DynamicallyAccessedMembers]` so the trimmer preserves the right members, or by preserving explicitly with `[DynamicDependency]`. `IL3050` usually cannot be annotated away, because there is nothing to preserve — Microsoft's guidance is literally "avoid calling the method at all when building as Native AOT."
>
> **Cross-Q**: You've decided a specific `IL3050` is genuinely unreachable under AOT. How do you say that to the toolchain?
>
> **A**: Guard the call with `RuntimeFeature.IsDynamicCodeSupported` and suppress with `[UnconditionalSuppressMessage("Aot", "IL3050:RequiresDynamicCode", Justification = "...")]`. Two details matter. First, it must be `UnconditionalSuppressMessage`, not `SuppressMessage` or `#pragma` — the latter two are source-only, and the trimmer runs at publish time over IL, so it never sees them. Second, the guard isn't decorative: `IsDynamicCodeSupported` is a recognised feature switch, so under AOT it is folded to a constant `false` and the whole branch, plus everything only it reached, is removed. .NET 9 lets you build the same thing for your own switches with `[FeatureSwitchDefinition]` and `[FeatureGuard]`.
>
> **Cross-Q²**: When is suppressing a trim warning actually *wrong*, even if the app works today?
>
> **A**: When the justification is "this member is used elsewhere in the app, so it'll still be there." The docs call that out as an explicitly **invalid** suppression. Being *called* is not the same as being a *visible target of reflection*: a property that nothing reflects on can be inlined, renamed, or moved by the trimmer — the docs note that Native AOT already optimizes such members away and that IL trimming may follow. A valid suppression rests on an annotation or a `[DynamicDependency]` somewhere that makes the member a reflection target the analyzer can see; you are just asserting that the analyzer can't connect the two ends. If you can't point at that other end, you don't have a suppression, you have a bug with a comment on it.

### Drill 18 — `MakeGenericType` under Native AOT

> **Q**: `typeof(Handler<>).MakeGenericType(messageType)` runs fine in your AOT-published app for a month, then throws on one message type. What happened?
>
> **A**: That message type is a **struct**. The runtime shares one native code body across all *reference-type* instantiations of a generic — every `T` is a same-sized pointer — so `Handler<Order>`, `Handler<User>`, and `Handler<AnythingElse>` all run the same machine code and the reflective instantiation finds something to use. **Value types cannot share**: different sizes and layouts mean each needs its own specialized body. Under JIT that body is compiled on demand; under Native AOT, per the docs, "all instantiations are pre-generated" at publish, and one that is reachable *only* through `MakeGenericType` is not statically reachable, so it was never generated. There is no code to run and you get an exception at the `MakeGenericType`/instantiation point. The build warned about this with `IL3050`.
>
> **Cross-Q**: Why is that the worst possible failure mode?
>
> **A**: Because it's **type-dependent, not code-dependent**. The same line works for the reference types you tested and fails for a struct you didn't, so the failure is triggered by *data shape from a caller*, not by a code path you can reach in a test. It also means "we published AOT and smoke-tested it" is not evidence of anything — the smoke test exercised the shared body. The only reliable signal was the `IL3050` at build time, which someone suppressed.
>
> **Cross-Q²**: How do you make an open-generic dispatcher AOT-safe?
>
> **A**: Make the instantiations statically reachable, which means turning the runtime lookup into build-time code. A source generator enumerates every `IHandler<T>` implementation in the compilation and emits an explicit `switch` (or a static dictionary of typed factories) mapping message type to a concrete `new SpecificHandler()`. Now every instantiation appears in real IL, so the AOT compiler generates it, the trimmer keeps it, and the reflection disappears entirely. The design point generalises: **AOT doesn't forbid open generics, it forbids instantiations that only exist in a string or a `Type` variable.** If you can't or won't generate, the fallback is a hand-maintained registration list — uglier, same effect, and at least it fails at compile time when someone adds a handler and forgets.

### Drill 19 — `[UnsafeAccessor]`

> **Q**: A test needs to read a private field. Reflection or `[UnsafeAccessor]`?
>
> **A**: `[UnsafeAccessor]` (.NET 8+), unless you need to discover the member name at runtime. You declare an `extern static` method with no body, and the runtime supplies the implementation by matching the attribute's `Kind` and `Name` against the type named by the **first parameter**. The call compiles to a direct field access — no `FieldInfo`, no boxing, no per-call lookup — and it's fully trim- and AOT-safe, because the accessor is a real method the tooling can see.
> ```csharp
> [UnsafeAccessor(UnsafeAccessorKind.Field, Name = "_total")]
> static extern ref decimal Total(Order o);
>
> Total(order) = 42m;   // read and write through the ref
> ```
>
> **Cross-Q**: What are the rules that trip people up?
>
> **A**: Four. (1) **Only the type named by the first parameter is searched — the hierarchy is not walked**, so a base-class private field needs an accessor whose first parameter is the base type. (2) **Field accessors must return `ref`**; that's what makes them writable. (3) For instance members on a **struct**, the first parameter must be `ref`, or you'd mutate a copy. (4) Matching is by ECMA-335 metadata signature **including the return type**, and if it doesn't match you get `MissingFieldException`/`MissingMethodException` **at runtime** — this is not compile-time-checked. Also: always set `Name` explicitly, because the accessor method's own name is the default and C# mangles local-function names into something that won't match. Use `nameof` when the member happens to be visible to you (the docs' own examples do); when it isn't — the usual case — it has to be a string literal.
>
> **Cross-Q²**: The type I need is `internal` in another assembly, so I can't even write its name in C#. Now what?
>
> **A**: **.NET 10's `[UnsafeAccessorType]`**, which lets you specify the target type as a fully-qualified *string* for a parameter or return whose type isn't visible at compile time — internal types in another assembly, private nested types, anything you deliberately don't want to reference. Before .NET 10, `[UnsafeAccessor]` alone couldn't express this and would fail at runtime. Worth flagging the trade honestly: you've now got a string type name in your build, so you've re-acquired the "silent break on rename" property that reflection had — you keep the performance and AOT-safety, not the compile-time checking. The better answer, when you own the other assembly, remains `[InternalsVisibleTo]`.

### Drill 20 — Why is an incremental generator "incremental"?

> **Q**: What actually makes `IIncrementalGenerator` faster than `ISourceGenerator`?
>
> **A**: It isn't a faster generator; it's a **cached pipeline**. You don't write "run over the compilation"; you declare a graph of providers and transforms, and the host memoizes each step's output keyed on the *equality of that step's inputs*. On an edit, only steps whose inputs changed re-run — and if a step produces a result `Equals` to last time's, everything downstream is served from cache and never executes. `ISourceGenerator` had no such structure, so every keystroke re-ran everything, which is what made IDEs crawl on large solutions.
>
> **Cross-Q**: So what's the one mistake that silently defeats it?
>
> **A**: Putting something without **value equality** into the pipeline. `Compilation`, `ISymbol`, `SyntaxNode` all compare by reference and are recreated on every keystroke, so every step downstream misses cache forever — *and* they root the whole compilation in memory. The subtler version is a `record` model that looks value-equal but contains an `ImmutableArray<T>`, which compares by reference to its backing array; two structurally identical models then compare unequal. Both bugs produce **byte-identical, entirely correct output** and cost only IDE latency, which is why they survive review. The fix is to project down to a small `record` of strings/enums/bools inside the transform, and give any collection an element-wise `IEqualityComparer`.
>
> **Cross-Q²**: And what's the API that makes discovery cheap?
>
> **A**: `SyntaxProvider.ForAttributeWithMetadataName` (Roslyn 4.3 / .NET 7 SDK and later). The naive `CreateSyntaxProvider` invokes your predicate for essentially every node in the compilation on every edit; `ForAttributeWithMetadataName` uses an index the compiler already maintains for attribute usages, so the overwhelming majority of nodes and edits are eliminated before your predicate runs. It also resolves `using` aliases correctly, which hand-rolled "does this node have an attribute whose name ends in `Foo`" matching gets wrong. Note the shape of the callback: the node handed to you is the **target** — the class or property the attribute is on — not the attribute syntax.

### Drill 21 — Interceptors

> **Q**: Source generators can only *add* code. So how does the minimal-API request delegate generator replace the binding logic behind `app.MapGet(...)` without you changing a line?
>
> **A**: **Interceptors.** The generator emits a method annotated `[InterceptsLocation(...)]` whose data identifies one specific call site — file, position, and a content hash of the call — and the compiler redirects *that exact call* to the generated method. Your source is untouched; the compiled binary calls somewhere else. That's the escape hatch from "generators can only add": they still only add a method, but the compiler rewires an existing call to it. It's what lets ASP.NET Core replace reflection-based parameter binding with generated, AOT-friendly code for endpoints written in ordinary minimal-API syntax.
>
> **Cross-Q**: Why must interceptors always come from a generator, never be hand-written?
>
> **A**: Because the location data is positional and hash-checked. The compiler recomputes it on every build, so the moment anyone adds a line above the intercepted call, a hand-written attribute points at the wrong place or fails its hash check. A generator recomputes it as part of the same compilation, so it's always in sync by construction. This is also why the mechanism is safe rather than terrifying: it can't drift.
>
> **Cross-Q²**: That still sounds like a package could silently reroute my code. What stops it?
>
> **A**: The consuming project has to **opt in by namespace**: an interceptor is only honoured if its containing namespace is listed in the project's `<InterceptorsNamespaces>` MSBuild property. Adding a NuGet package is not consent; naming its generator's namespace in your own `.csproj` is. In practice you rarely type it yourself, because setting `PublishTrimmed` or `PublishAot` is what turns on the in-box generators that use it — which is a reasonable design, since those are exactly the modes where the reflection-based path was going to fail anyway.

### Drill 22 — When reflection is still the right answer

> **Q**: Give me a case where you'd *keep* runtime reflection in 2026 and defend it.
>
> **A**: Anything where the types don't exist at build time. A plugin host loading DLLs dropped into a folder; a scripting or rules engine compiling customer-authored code; a test framework discovering `[Fact]` methods in an assembly it was handed. A source generator can only see what's in *your* compilation, so it structurally cannot help. Microsoft's trimming docs list dynamic assembly loading as a known incompatibility for exactly this reason. The honest framing is that this isn't reflection as a shortcut — it's reflection as the requirement, and the cost is that you give up trimming and AOT for that process.
>
> **Cross-Q**: You load plugins, run them, and want to unload them. How, and what goes wrong?
>
> **A**: A **collectible `AssemblyLoadContext`** — `base(isCollectible: true)`, with `AssemblyDependencyResolver` in the `Load` override to resolve the plugin's own dependencies from its `.deps.json`. The critical difference from the old `AppDomain.Unload` is that this one is **cooperative**: `Unload()` only *initiates* it. It completes when no thread has a frame from those assemblies on its stack and nothing outside holds a strong reference to any assembly, type, or instance from the context. What goes wrong is always the same category — something still holds a reference. A cached `MethodInfo` in a static field. A `Func<>` compiled from plugin code sitting in the host's cache. A strong `GCHandle`. A background thread the plugin started. A field on your own `AssemblyLoadContext` subclass — the runtime holds a strong handle to the context while unloading, so those fields stay rooted even after you drop yours. Only `WeakReference` is exempt, which is why the canonical check is a `WeakReference` to the context plus a bounded `GC.Collect()` / `WaitForPendingFinalizers()` loop.
>
> **Cross-Q²**: It doesn't unload. Walk me through the diagnosis.
>
> **A**: The `AssemblyLoadContext` is kept alive by its `LoaderAllocator`, so: attach WinDbg (or LLDB) with SOS, `!dumpheap -type LoaderAllocator` to find the instance, then `!gcroot <address>` to print the chain of references holding it — the first entry is the culprit and it'll be a stack slot, a static, or a GC handle. Then `~*e !clrstack` across all threads to check whether any of them still has a plugin frame. Two things make this harder than it sounds: JIT-introduced locals can root an object you never named in source (which is why the sample code puts load-and-run in a `[MethodImpl(MethodImplOptions.NoInlining)]` method), and statics for reference types are stored in internal object arrays, so `gcroot` shows them as anonymous pinned handles rather than telling you the field name. Prevention beats diagnosis: hook the context's `Unloading` event and clear every cache keyed on plugin types there.

</details>
## Cheat Sheet

- **Attribute**: inert metadata; derive from `Attribute`, mark `[AttributeUsage(Targets, Inherited, AllowMultiple)]`. Args must be **compile-time constants** — `const` yes, `static readonly` no.
- **Attribute instances are built lazily on every read.** `GetCustomAttribute` runs the constructor and loads the defining assembly; `GetCustomAttributesData` reads the raw metadata instead (no `inherit`, no normalisation).
- **`Inherited` walks classes, never interfaces.** An attribute on `IFoo` is invisible on `Foo : IFoo`.
- **Reflection's cost** = `object[]` + a box per value arg + per-call validation + no inlining. Caching `MethodInfo` removes only the *lookup*.
- **Faster invoke**: `mi.CreateDelegate<Func<..>>()` (.NET 5+) > `MethodInvoker.Create(mi)` (.NET 8+) > cached `mi.Invoke`. `Expression.Compile()` when the shape is dynamic — but it's *interpreted* under Native AOT.
- **`[UnsafeAccessor]`** (.NET 8; generics .NET 9; `[UnsafeAccessorType]` .NET 10): private access, zero overhead, AOT-safe. First param names the owning type; hierarchy **not** walked; field accessors return `ref`.
- **`GetMethod(name)` with overloads throws `AmbiguousMatchException`** — it does not return `null`.
- **`GetMethods()`** = public instance **and static**; inherited statics need `FlattenHierarchy`; never constructors.
- **`dynamic`**: DLR call-site cache; fast when monomorphic, expensive when not; no IntelliSense; runtime errors; unusable under AOT.
- **Source generator**: emits `.cs` at compile time via `IIncrementalGenerator`; `partial` only; **cannot see other generators' output**; never throw — report a `Diagnostic`.
- **Generator perf** = pipeline cache. Use `ForAttributeWithMetadataName`; never put `Compilation`/`ISymbol`/`SyntaxNode` in the pipeline; beware `ImmutableArray` reference equality in `record` models.
- **Interceptors** are the only way a generator changes existing code; generator-emitted only, opt in via `<InterceptorsNamespaces>`.
- **Source-gen winners**: `JsonSerializerContext`, `[LoggerMessage]`, `[GeneratedRegex]`, minimal-API RDG, config binding. **Not MVC** — MVC is unsupported under Native AOT.
- **Analyzer ≠ generator**: analyzer emits *diagnostics*; generator emits *source*. Most real packages ship both.
- **`IL2xxx` = trimming** (`[RequiresUnreferencedCode]`, `[DynamicallyAccessedMembers]`, `[DynamicDependency]`) — members might be **removed**.
- **`IL3xxx` = AOT** (`[RequiresDynamicCode]`) — native code will never be **generated**. `IL3050` = `MakeGenericType` / `Expression.Compile` / `Reflection.Emit`.
- **Suppress with `[UnconditionalSuppressMessage]`** — `#pragma` and `[SuppressMessage]` are source-only and the publish-time trimmer never sees them.
- **`PublishAot` ⇒ trimmed + single-file + no JIT.** `PublishReadyToRun` implies none of that.
- **AOT generics**: reference-type instantiations share a body; every value-type instantiation must be pre-generated. `MakeGenericType(typeof(string))` usually works, `typeof(int)` throws.
- **Feature switches** (`InvariantGlobalization`, `EventSourceSupport`, `UseSystemResourceKeys`…) fold a property to a constant so the trimmer deletes the branch. They change **behaviour**, not just size.
- **`RuntimeFeature.IsDynamicCodeSupported`** = the runtime guard that lets one binary serve JIT and AOT.
- **See generated code**: `<EmitCompilerGeneratedFiles>true</EmitCompilerGeneratedFiles>` → `obj/<Config>/<tfm>/generated/`.
- **Plugins**: collectible `AssemblyLoadContext(isCollectible: true)`; unload is **cooperative**; a cached `MethodInfo` or delegate anywhere outside prevents it. Diagnose with `!dumpheap -type LoaderAllocator` + `!gcroot`.

## Walkthrough — Reflection killing AOT publish

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: Team migrates a microservice to Native AOT (`<PublishAot>true</PublishAot>`, `dotnet publish -r linux-x64`) for faster cold starts on Azure Container Apps. The build emits ~80 warnings across two families, and the published binary boots but fails on the first request inside `JsonSerializer.Deserialize<UserDto>` with an `InvalidOperationException` complaining that no `JsonTypeInfo` metadata is available for the type and pointing at `JsonSerializerOptions.TypeInfoResolver`.

**Diagnosis**: Two distinct problems wearing one hat.

- Publish with `<TrimmerSingleWarn>false</TrimmerSingleWarn>`. Without it, each `PackageReference` collapses to a single "this assembly produced trim warnings" line, which tells you nothing actionable.
- **Sort the warnings by family first.** The `IL2xxx` ones (`IL2026`, `IL2070`) say the trimmer can't prove which members reflection will reach. The `IL3xxx` ones (`IL3050`) say something will demand native code that won't exist. They need different fixes and mixing them is why triage stalls.
- The JSON failure is neither, exactly — reflection-based `JsonSerializer` is annotated `[RequiresUnreferencedCode]`/`[RequiresDynamicCode]`, so the warning was there at build time and the runtime failure is that warning coming true.

**Fix**, in the order that removes the most warnings per unit of work:

1. **JSON** — declare a `partial JsonSerializerContext` and register it, rather than passing it at every call:
   ```csharp
   [JsonSerializable(typeof(UserDto))]
   [JsonSerializable(typeof(List<UserDto>))]
   internal partial class AppJsonContext : JsonSerializerContext { }

   builder.Services.ConfigureHttpJsonOptions(o =>
       o.SerializerOptions.TypeInfoResolverChain.Insert(0, AppJsonContext.Default));
   ```
2. **Logging** — replace `_logger.LogInformation("User {Id} created", id)` with a `partial` method carrying `[LoggerMessage]`. Both the class and the method must be `partial`; an instance method picks up an `ILogger` field (or, from .NET 9, an `ILogger` primary-constructor parameter).
3. **Regex** — replace `new Regex(@"...")` with a `[GeneratedRegex]` partial member.
4. **Controllers** — this is the expensive one, and it is not optional. **MVC is listed as *not supported* under Native AOT**; minimal APIs are *partially* supported. So this is a port, not a switch, and the template's `WebApplication.CreateSlimBuilder` will also drop HTTPS, HTTP/3, IIS integration, `UseStartup`, static web assets, and the regex/alpha routing constraints — each of which is a decision, not a detail.
5. **Whatever's left** — usually DI assembly scanning, `IOptions` binding, and one in-house mapper. Configuration binding fixes itself (the source generator turns on with `PublishAot`); the scanner and the mapper need explicit registration or a generator.

**What you can't fix by annotating**: any remaining `IL3050`. If a dispatcher does `MakeGenericType`, no amount of `[DynamicallyAccessedMembers]` helps — there is no member to preserve, there is code that was never compiled. Either generate the closed instantiations at build time or guard the path with `RuntimeFeature.IsDynamicCodeSupported` and ship a non-generic fallback.

**Why it works**: source generators emit explicit code at compile time — every type, accessor, and method is statically reachable, so the trimmer can prove what's used and the AOT compiler pre-generates every instantiation. Cold start improves because no JIT is needed and no `JsonTypeInfo` is built on first request; binary size shrinks because dead code becomes provably removable.

**The thing to say in the retro**: put `<PublishAot>true</PublishAot>` in the project file from day one of a service that intends to publish AOT, not the week before. The property doesn't only affect publish — it turns on the analyzers during ordinary builds and in the editor, so the warnings arrive one at a time next to the code that caused them, instead of eighty at once next to a deadline.

</details>
## Self-test

<details>
<summary>1. What's the difference between a Roslyn analyzer and a source generator?</summary>

Both run inside the compiler's pipeline as `Microsoft.CodeAnalysis.*` plugins. An *analyzer* (`DiagnosticAnalyzer`) emits **diagnostics** — warnings, errors, info messages — and optionally code fixes through a `CodeFixProvider`. A *source generator* (`IIncrementalGenerator`) emits **new source files** that become part of the compilation. Practically: analyzers say "this code is wrong"; generators say "here's more code." A modern source generator is *incremental* — it caches per-input results, so changing one file doesn't re-run the generator over every file.
</details>

<details>
<summary>2. Apply: a teammate uses `Activator.CreateInstance(typeof(Foo), arg1, arg2)` in a hot path. The profiler shows it as 30% of CPU. Replace it without changing the API.</summary>

Bind a factory once, cache it, invoke many times. If the type is known at compile time, the honest answer is that you don't need reflection *or* an expression tree — a plain cached lambda is the same delegate with none of the ceremony:

```csharp
private static readonly Func<int, string, Foo> s_factory = static (a, b) => new Foo(a, b);
public Foo Make(int a, string b) => s_factory(a, b);
```

If the type is only known at runtime, bind the constructor instead of invoking it:

```csharp
private static readonly Type s_type = ResolveTypeAtStartup();   // not known at compile time
private static readonly ConstructorInvoker s_ctor =             // .NET 8+
    ConstructorInvoker.Create(s_type.GetConstructor([typeof(int), typeof(string)])!);
public object Make(int a, string b) => s_ctor.Invoke(a, b);
```

What you removed: `Activator.CreateInstance(type, args)` allocates an `object[]`, boxes the `int`, resolves and validates the constructor against the argument array, and returns `object` — every call. The cached delegate does none of it; the cached `ConstructorInvoker` does the resolution and validation once. Under Native AOT, note that `Expression.Compile()` is *not* the right third option here — it falls back to the interpreter — and `Activator.CreateInstance` on a `Type` that came from a string is a trim warning waiting to happen unless the parameter is annotated `[DynamicallyAccessedMembers(PublicParameterlessConstructor)]`.
</details>

<details>
<summary>3. Trade-off: when does reflection beat source generation?</summary>

When the *types* aren't known at compile time — plugin systems where DLLs are dropped into a folder at runtime, scripting hosts, ORMs over user-defined entities discovered at first connection. Source generators see only what's in the compilation; if your code says "load whatever DLLs are in /plugins and instantiate every `IPlugin`," generators can't help. Reflection (or assembly load + interface scanning) is the right tool. Cost: slower first call, no AOT, larger memory footprint. Reflection is also fine for compile-time-rare code (DI registration at startup, attribute scanning during initialization) where 1ms doesn't matter.
</details>

<details>
<summary>4. Analyze: why does `[GeneratedRegex(@"\d+")]` outperform `new Regex(@"\d+")` even outside AOT?</summary>

`new Regex(pattern)` parses the pattern string at runtime and builds an internal representation, then either interprets it or — with `RegexOptions.Compiled` — emits IL through `DynamicMethod` and JITs it. Either way you pay a first-use cost, and the compiled option pays a large one. `[GeneratedRegex]` runs a source generator that emits a `Regex` subclass **as C#** at build time, with the matching logic written out as ordinary methods. So: no pattern parsing at runtime, no `Reflection.Emit`, no JIT step, and the emitted matcher can use techniques the runtime engine can't (it can specialize for the specific pattern rather than staying general).

Three consequences beyond speed, and they're the ones worth leading with: it is **AOT-safe** (`RegexOptions.Compiled` is not — it's runtime code generation, so it degrades or warns under AOT); the generated code is **readable and debuggable** C# you can step into via `EmitCompilerGeneratedFiles`; and the generator parses the pattern at build time, so a malformed pattern surfaces as a build diagnostic rather than an `ArgumentException` on the request that first hits it. If you want a number, generate one for your own patterns — matcher performance is extremely pattern-dependent, and a figure quoted for someone else's regex tells you nothing about yours.
</details>

<details>
<summary>5. You see `[DynamicallyAccessedMembers(DynamicallyAccessedMemberTypes.PublicProperties)]` on a `Type` parameter. Explain its role.</summary>

It's a hint to the *linker/trimmer* that the receiver of this `Type` will reflect over its public properties. Without the attribute, the trimmer can't prove which members are needed and may strip them, breaking reflection at runtime in trimmed/AOT builds. With the attribute, the trimmer preserves all public properties of any type that flows into this parameter. Pair it with `IL2070` warning resolution: when calling `t.GetProperties()`, the analyzer requires the source `Type` came from a parameter/field annotated with `[DynamicallyAccessedMembers(PublicProperties)]` — propagating the requirement up the call stack.

The propagation is the part people underestimate. Annotating the parameter doesn't end the conversation; it moves the warning to every caller passing an unannotated `Type`, and you keep annotating outward until either a public API boundary (where the requirement becomes part of your contract) or a concrete `typeof(X)` (where the trimmer can finally satisfy it and stop). If the chain never terminates in one of those two, the honest conclusion is that the design is unanalyzable and the fix is `[RequiresUnreferencedCode]` on the public entry point — telling your callers the truth — rather than a suppression that hides it.
</details>

<details>
<summary>6. Under Native AOT, why does <code>MakeGenericType(typeof(string))</code> usually work while <code>MakeGenericType(typeof(int))</code> throws?</summary>

Because of how generic code is shared. The runtime compiles **one canonical native body** for all reference-type instantiations — every `T` is a pointer of the same size — so if anything in the program forced `Handler<SomeClass>` into existence, `Handler<AnyOtherClass>` reuses that body. Value types cannot share: `Handler<int>` and `Handler<Guid>` have different sizes and layouts and each needs its own specialized body.

Under JIT, a missing value-type instantiation is compiled on demand. Under Native AOT there is nothing to compile on demand — the docs state that "all instantiations are pre-generated" at publish time — and an instantiation reachable *only* through a `Type` variable is not statically reachable, so it was never generated. The build told you: `IL3050`.

This is worth being able to explain because of the failure shape it produces. The bug is triggered by the *type a caller supplies*, not by a code path, so tests over reference types pass and the first struct payload in production throws. The fix is to make the instantiations statically reachable — a generated `switch` over concrete types, or an explicit registration list — not to suppress the warning.
</details>

<details>
<summary>7. You need to read a private field on a type you don't own, in a service that publishes Native AOT. Reflection, <code>[UnsafeAccessor]</code>, or neither?</summary>

`[UnsafeAccessor]` (.NET 8+). Reflection with `BindingFlags.NonPublic` works under JIT but is a trim/AOT liability (the trimmer has no reason to keep a private field nothing references) and costs a lookup plus boxing per access. `[UnsafeAccessor]` on an `extern static` method compiles to a direct field access — nothing to trim away, nothing to look up.

```csharp
[UnsafeAccessor(UnsafeAccessorKind.Field, Name = "_total")]
static extern ref decimal Total(Order o);
```

Know the rules you'll be asked about: the **first parameter names the owning type and only that type is searched** (no hierarchy walk), field accessors must return `ref`, instance members on structs need a `ref` first parameter, and a mismatch throws `MissingFieldException`/`MissingMethodException` **at runtime** — signature matching is metadata-based and includes the return type, so this is not a compile-checked backdoor. Generics require .NET 9; naming a type you can't reference at all requires .NET 10's `[UnsafeAccessorType]`.

The "neither" answer is still worth voicing: if you own the other assembly, `[InternalsVisibleTo]` gives you compile-time checking and none of this. `[UnsafeAccessor]` is for when you don't.
</details>

<details>
<summary>8. A colleague's source generator makes the IDE lag on every keystroke, but the generated output is correct. Where do you look first?</summary>

At what's flowing through the incremental pipeline, because the symptom is a **cache miss**, not a slow generator. `IIncrementalGenerator` memoizes each pipeline step keyed on the equality of its inputs; if a step's output compares equal to last time's, everything downstream is skipped. Three things break that:

1. **A `Compilation`, `ISymbol`, or `SyntaxNode` in the pipeline.** Reference equality, recreated every keystroke, and they root the whole compilation in memory. Project to a small value-equal model inside the transform.
2. **A `record` model containing an `ImmutableArray<T>`.** `record` equality compares that member by reference to its backing array, so structurally identical models compare unequal. Needs an element-wise comparer.
3. **`CreateSyntaxProvider` instead of `ForAttributeWithMetadataName`.** The naive predicate is invoked for essentially every node on every edit; the attribute-indexed API discards nearly all of them before your code runs, and handles `using` aliases correctly as a bonus.

What makes this class of bug durable is that it has **no symptom in the output** — correct code, no diagnostics, nothing a test asserts on. The only signal is editor latency, which developers habitually blame on their machine.
</details>

<details>
<summary>9. Your team wants to hot-reload plugin DLLs. You call <code>AssemblyLoadContext.Unload()</code> and memory keeps growing. Diagnose it.</summary>

`Unload()` is **cooperative** — unlike the old `AppDomain.Unload`, it initiates unloading and nothing more. It completes only when no thread has a frame from those assemblies on its stack **and** nothing outside the context holds a strong reference to any assembly, type, or instance from it. Something does.

The usual suspects, all of which are real bugs people ship: a `MethodInfo` or `Type` cached in a static; a delegate compiled from plugin code sitting in a host cache; a strong or pinned `GCHandle`; a background thread the plugin started; a pending `RegisteredWaitHandle` with a plugin callback; and — the sneaky one — a field on your own `AssemblyLoadContext` subclass, because the runtime holds a strong handle to the context while unloading is in progress, so those fields stay rooted even after you drop your reference. Only `WeakReference`/`WeakReference<T>` are exempt.

Diagnosis is mechanical: SOS, then `!dumpheap -type LoaderAllocator` to find the allocator for the context, `!gcroot <address>` to print the chain holding it, and `~*e !clrstack` to check every thread for plugin frames. Two things make it harder than it reads — JIT-introduced locals can root an object you never named (hence the `[MethodImpl(MethodImplOptions.NoInlining)]` wrapper in Microsoft's sample), and static reference-type fields appear as anonymous pinned handles rather than named fields.

Prevention: clear every cache keyed on plugin types in the context's `Unloading` event, and verify with a `WeakReference` to the context plus a bounded `GC.Collect()`/`GC.WaitForPendingFinalizers()` loop.
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

**Reflection and attributes**
- Microsoft Learn — [Attributes (C#)](https://learn.microsoft.com/en-us/dotnet/csharp/advanced-topics/reflection-and-attributes/) and [Reflection](https://learn.microsoft.com/en-us/dotnet/fundamentals/reflection/).
- Microsoft Learn — [`Type.GetMethods`](https://learn.microsoft.com/en-us/dotnet/api/system.type.getmethods) (default binding behaviour, the base-class member table, .NET 7 ordering guarantee) and [`Type.GetMethod`](https://learn.microsoft.com/en-us/dotnet/api/system.type.getmethod) (`AmbiguousMatchException`).
- Microsoft Learn — [`Type.IsClass`](https://learn.microsoft.com/en-us/dotnet/api/system.type.isclass) — "a class **or a delegate**".
- Microsoft Learn — [`MethodInvoker`](https://learn.microsoft.com/en-us/dotnet/api/system.reflection.methodinvoker) (.NET 8+) and [`MethodInfo.CreateDelegate`](https://learn.microsoft.com/en-us/dotnet/api/system.reflection.methodinfo.createdelegate) (generic overloads .NET 5+).
- Microsoft Learn — [`UnsafeAccessorAttribute`](https://learn.microsoft.com/en-us/dotnet/api/system.runtime.compilerservices.unsafeaccessorattribute) — the matching rules, the first-parameter convention, and the "hierarchy is not walked" note.
- Microsoft Learn — [`CustomAttributeData`](https://learn.microsoft.com/en-us/dotnet/api/system.reflection.customattributedata) and [Inspect assembly contents using `MetadataLoadContext`](https://learn.microsoft.com/en-us/dotnet/standard/assembly/inspect-contents-using-metadataloadcontext).
- Microsoft Learn — [Assembly unloadability](https://learn.microsoft.com/en-us/dotnet/standard/assembly/unloadability) — the definitive list of what prevents a collectible `AssemblyLoadContext` from unloading, plus the SOS recipe.
- dotnet/runtime — [`syncblk.h`](https://github.com/dotnet/runtime/blob/main/src/coreclr/vm/syncblk.h) and the [threading Book of the Runtime chapter](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/botr/threading.md) — object header layout and where the identity hash code lives.

**Source generators**
- Microsoft Learn — [Source generators overview](https://learn.microsoft.com/en-us/dotnet/csharp/roslyn-sdk/source-generators-overview).
- dotnet/roslyn — [`docs/features/incremental-generators.md`](https://github.com/dotnet/roslyn/blob/main/docs/features/incremental-generators.md) — the pipeline model and the cacheability rules. Read this before writing one.
- Microsoft Learn — [`SyntaxValueProvider.ForAttributeWithMetadataName`](https://learn.microsoft.com/en-us/dotnet/api/microsoft.codeanalysis.syntaxvalueprovider.forattributewithmetadataname) (Roslyn 4.3+).
- Microsoft Learn — [Compile-time logging source generation](https://learn.microsoft.com/en-us/dotnet/core/extensions/logger-message-generator) — the `[LoggerMessage]` constraints, including where the `ILogger` comes from.
- Microsoft Learn — [Source-generation modes in `System.Text.Json`](https://learn.microsoft.com/en-us/dotnet/standard/serialization/system-text-json/source-generation-modes) — the exact table of options and attributes that disable the fast path.
- Andrew Lock — *"Creating a source generator"* series at [andrewlock.net](https://andrewlock.net/), especially the parts on pipeline cacheability and on implementing an interceptor.

**Trimming and Native AOT**
- Microsoft Learn — [Native AOT deployment overview](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/) — the authoritative limitations list, including "`System.Linq.Expressions` always use their interpreted form" and the generic-instantiation paragraph.
- Microsoft Learn — [Introduction to AOT warnings](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/fixing-warnings) — `IL3050`, `[RequiresDynamicCode]`, and the `RuntimeFeature.IsDynamicCodeSupported` guard pattern.
- Microsoft Learn — [Prepare .NET libraries for trimming](https://learn.microsoft.com/en-us/dotnet/core/deploying/trimming/prepare-libraries-for-trimming) — `[RequiresUnreferencedCode]`, `[DynamicallyAccessedMembers]`, `[DynamicDependency]`, `[UnconditionalSuppressMessage]`, and the invalid-justification example.
- Microsoft Learn — [Trimming options](https://learn.microsoft.com/en-us/dotnet/core/deploying/trimming/trimming-options) — the full feature-switch table and `TrimmerSingleWarn`.
- Microsoft Learn — [Known trimming incompatibilities](https://learn.microsoft.com/en-us/dotnet/core/deploying/trimming/incompatibilities) — reflection-based serializers, `Reflection.Emit`, dynamic assembly loading, built-in COM, WPF/WinForms.
- dotnet/runtime — [`docs/workflow/trimming/feature-switches.md`](https://github.com/dotnet/runtime/blob/main/docs/workflow/trimming/feature-switches.md) — how a feature switch maps to a runtimeconfig option and a trimmer substitution.
- Microsoft Learn — [ASP.NET Core support for Native AOT](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/native-aot) — the feature compatibility table (MVC: not supported; minimal APIs: partial) and `CreateSlimBuilder`.
- Microsoft Learn — [EF Core advanced performance topics](https://learn.microsoft.com/en-us/ef/core/performance/advanced-performance-topics) — compiled models, `dotnet ef dbcontext optimize`, and their limitations.
- Stephen Toub — the annual *"Performance Improvements in .NET"* posts — the reflection-invoke rewrite and `MethodInvoker` are covered in the .NET 8 edition.

</details>
<!-- nav-footer-start -->

---

[← Previous: Nullability & Pattern Matching](07-nullability-and-pattern-matching.md) · [↑ Back to top](#reflection-attributes--source-generators) · [Next: Memory & Performance Idioms →](09-memory-and-performance.md)

<!-- nav-footer-end -->
