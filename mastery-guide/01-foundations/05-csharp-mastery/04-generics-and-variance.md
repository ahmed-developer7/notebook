# Generics & Variance

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Generic types and methods](#generic-types-and-methods)
  - [Type parameter constraints](#type-parameter-constraints)
  - [Generic constraints — the full catalog](#generic-constraints--the-full-catalog)
  - [Variance — covariance and contravariance](#variance--covariance-and-contravariance)
  - [Covariance and contravariance — beyond interfaces](#covariance-and-contravariance--beyond-interfaces)
  - [Generic specialization on the CLR](#generic-specialization-on-the-clr)
  - [Generic specialization in the JIT — deep dive](#generic-specialization-in-the-jit--deep-dive)
  - [Generic type identity at runtime](#generic-type-identity-at-runtime)
  - [Type inference — when it works and when it doesn't](#type-inference--when-it-works-and-when-it-doesnt)
  - [`default(T)` in generics and the `default!` pattern](#defaultt-in-generics-and-the-default-pattern)
  - [Generic math interfaces (C# 11)](#generic-math-interfaces-c-11)
  - [Generic math — the full surface](#generic-math--the-full-surface)
  - [`allows ref struct` (C# 13)](#allows-ref-struct-c-13)
  - [`unmanaged` and `notnull` constraints](#unmanaged-and-notnull-constraints)
  - [Open vs closed generics](#open-vs-closed-generics)
  - [Variance is a reference conversion — value types never participate](#variance-is-a-reference-conversion--value-types-never-participate)
  - [Static members live per closed generic type](#static-members-live-per-closed-generic-type)
  - [Shared generics, __Canon, and the generic dictionary](#shared-generics-__canon-and-the-generic-dictionary)
  - [The default comparer and the missing IEquatable constraint](#the-default-comparer-and-the-missing-iequatable-constraint)
  - [Constraints are not part of the signature](#constraints-are-not-part-of-the-signature)
  - [Generics under Native AOT and trimming](#generics-under-native-aot-and-trimming)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--ilistdog-cant-flow-into-ilistanimal)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Generics are the spine of modern .NET. `List<T>`, `Dictionary<TKey, TValue>`, `Task<T>`, `IEnumerable<T>`, `Span<T>`, `Action<T>`, every LINQ operator — none of them work without generic type parameters. Once you write more than trivial library code, you start needing constraints, variance annotations, and an understanding of how the CLR specializes generic types. Senior interviews lean on this hard: "explain co/contravariance," "why can't `IList<Dog>` substitute for `IList<Animal>`," "what does `where T : unmanaged` enable."

C# 11 added **static abstract** in interfaces, which together with generic constraints unlocked **generic math** — write one numeric algorithm, run on `int`, `double`, `decimal`, custom types. C# 13 added **`allows ref struct`**, finally letting you use `Span<T>` as a generic argument. The generic surface in 2026 is more capable than it was even three years ago.

## Core concepts

### Generic types and methods

A generic *parameterizes a type or method by another type*. The compiler stamps out a real type for each combination at compile-time (or — for value types — at JIT time, see specialization below).

```csharp
// Generic class
public class Box<T>
{
    public T Value { get; init; }
    public Box(T value) => Value = value;
}

var intBox = new Box<int>(5);
var stringBox = new Box<string>("hello");

// Generic method
public static T Max<T>(T a, T b) where T : IComparable<T>
    => a.CompareTo(b) > 0 ? a : b;

int m = Max(3, 7);                  // T inferred from arguments
string s = Max("apple", "banana");

// Multiple type parameters
public class Pair<TFirst, TSecond>
{
    public TFirst First { get; }
    public TSecond Second { get; }
    public Pair(TFirst f, TSecond s) { First = f; Second = s; }
}
```

**Naming convention:** `T`, or `TXxx` for multiple (e.g., `TKey`, `TValue`, `TResult`). Avoid single non-`T` letters like `K` or `V` — `TKey`, `TValue` reads better and matches BCL conventions.

### Type parameter constraints

Without constraints, a `T` can be *any* type — including ones you don't want. Constraints let you require properties of `T`.

```csharp
// Constraint                         What it requires
where T : class                       // T is a reference type
where T : struct                      // T is a non-nullable value type
where T : new()                       // T has a parameterless constructor
where T : SomeBaseClass               // T inherits from SomeBaseClass
where T : ISomeInterface              // T implements the interface
where T : SomeBaseClass, ISomeIface   // chain multiple
where T : notnull                     // T is non-nullable (ref or value)
where T : unmanaged                   // T is a value type containing only blittable types
where T : System.Enum                 // T is an enum (a base-class constraint, C# 7.3)
where T : System.Delegate             // T is a delegate type (C# 7.3)
where T : U                           // T inherits from / implements another type parameter
where T : allows ref struct           // T may be a ref struct (C# 13)
```

> **Syntax check.** There is no `where T : enum` or `where T : delegate`. `enum` and `delegate` are keywords; the constraint takes a *type*, so you write `where T : System.Enum` and `where T : System.Delegate` (or `System.MulticastDelegate`). Microsoft Learn's *where (generic type constraint)* page spells all three out. Three base types are explicitly disallowed as base-class constraints: `System.Object`, `System.Array`, and `System.ValueType`.

**Order matters in declaration:**
1. The *primary* constraint — at most one: `class` / `class?` / `struct` / `unmanaged`, **or** a base class type (which is where `System.Enum` and `System.Delegate` land). `notnull` also occupies this slot.
2. Interfaces (any number) and other type parameters.
3. `new()`.
4. `allows ref struct` (C# 13) — always last.

Two combination rules the compiler enforces that people forget: `unmanaged` can't be combined with `class` or `struct`, and `new()` can't be combined with `struct` or `unmanaged` — every type satisfying those already has an accessible parameterless constructor, so `new()` would be redundant.

**Real-world examples:**

```csharp
// Repository pattern — entity must inherit from EntityBase and have a parameterless ctor
public abstract class Repository<T> where T : EntityBase, new()
{
    public T New() => new();
    public abstract Task<T?> FindAsync(int id);
}

// Generic equality helper — only works on types with value-type semantics
public static bool BitEquals<T>(T a, T b) where T : unmanaged
{
    var spanA = MemoryMarshal.AsBytes(MemoryMarshal.CreateReadOnlySpan(ref a, 1));
    var spanB = MemoryMarshal.AsBytes(MemoryMarshal.CreateReadOnlySpan(ref b, 1));
    return spanA.SequenceEqual(spanB);
}

// Result pattern — TError must be non-null
public readonly struct Result<TValue, TError> where TError : notnull
{
    /* ... */
}
```

> 🌍 **In the real world**: a team introduced `abstract class Repository<T> where T : EntityBase, new()` so the base class could hand out a blank instance for the "create" path. Eighteen months later an aggregate needed a constructor argument — a tenant id that could not be defaulted — and the only way to satisfy `new()` was to add a parameterless constructor to the entity "just for the ORM". That constructor then became reachable from application code, and a bug shipped where an aggregate was created with `TenantId = Guid.Empty` and saved. The `new()` constraint had quietly turned "the ORM needs to materialise this" into "anyone can construct this in an invalid state". The replacement was a factory constraint — `Repository<T>(Func<T> factory)` in the base, or in modern C#, a `static abstract T Create(TenantId)` on an interface — both of which say what construction actually requires. `new()` is not a general "T is constructible" constraint; it is specifically "T has a *public parameterless* constructor", and that is a design commitment to every caller, not just to you.

### Generic constraints — the full catalog

Each constraint changes what the compiler will let you *do* with `T` inside the method, and changes what the JIT can *assume* when it specializes the code. Memorize the table; in interviews the cross-questions are about what each enables and what it costs.

| Constraint | What it means | What it enables inside the body | JIT / runtime effect |
|---|---|---|---|
| `where T : class` | `T` is a reference type (nullable or not) | `T t = null;` compiles; `t is null` works; `?.` works | Shared ref-type body (one specialization for all reference `T`s) |
| `where T : class?` | `T` is a possibly-nullable reference type | Same as `class` but `T` is treated as nullable for NRT analysis | Identical specialization to `class` |
| `where T : struct` | `T` is a non-nullable value type | Boxing-free interface calls (constrained call); `T?` means `Nullable<T>` | Per-`T` JIT specialization — distinct machine code per concrete value type |
| `where T : new()` | `T` has a **public parameterless** constructor | `new T()` compiles inside the method | Roslyn emits `call Activator.CreateInstance<T>()`, not a direct `newobj`. The runtime special-cases the generic overload — for a value-type `T` it degenerates to zero-init; for a reference type it resolves and caches the default constructor. Measure before assuming it matches a direct `new` |
| `where T : SomeBaseClass` | `T` derives from `SomeBaseClass` | Use `SomeBaseClass`'s public/protected members on `T` | No code-gen change; pure compile-time check |
| `where T : ISomeInterface` | `T` implements the interface | Call interface methods on `T` directly — non-boxing for value types via *constrained call* IL | Big perf win for struct generics: `T.MethodOnInterface()` doesn't box |
| `where T : notnull` | `T` is a non-nullable type (value or reference) | `T?` is permitted in signatures; `null` literal is rejected for `T` | No code-gen change; warning surface only |
| `where T : unmanaged` | `T` is a value type containing only blittable primitives (recursive) | `sizeof(T)`, `stackalloc T[n]`, raw pointer ops, `Span<T>` over native memory | Same JIT specialization as `struct`, but the constraint is stricter — no references inside `T` |
| `where T : System.Enum` (C# 7.3) | `T` is an enum type | Pass `T` where `System.Enum` is expected; write strongly-typed enum helpers instead of leaning on the `Array`-returning `Enum.GetValues(Type)` | It is a *base-class* constraint, so it takes the base-class slot. Enums are value types, so per-`T` specialization still applies |
| `where T : System.Delegate` / `System.MulticastDelegate` (C# 7.3) | `T` is a delegate type | `Delegate.Combine(t1, t2)`, `t.GetInvocationList()` | Also a base-class constraint; no code-gen change. Rare outside event/messaging infrastructure |
| `where T : U` | `T` derives from / implements another type parameter `U` | Use `U`'s contract on `T`; assign `T` to a `U` variable | No code-gen change |
| `where T : allows ref struct` (C# 13) | **Anti-constraint**: `T` *may* be a ref struct (`Span<T>`, `ReadOnlySpan<T>`, …). It widens the accepted set rather than narrowing it | `T` is allowed as a generic argument even though it can't be boxed | `T` now carries every ref-struct restriction: no boxing, no static fields of type `T`, no `T[]`, and `T` can only be passed to another generic whose parameter also says `allows ref struct` |

**A constraint you almost certainly mis-remember: `Enum.Parse<TEnum>` is not constrained to `System.Enum`.** Its signature is `public static TEnum Parse<TEnum>(string value) where TEnum : struct`. The generic overload shipped in .NET Core 2.0, before C# 7.3 made `System.Enum` usable as a constraint, and tightening a constraint on a shipped API is a breaking change — so it stayed as it was. The upshot: `Enum.Parse<int>("5")` compiles cleanly and throws `ArgumentException` at runtime — the docs list "`TEnum` is not an `Enum` type" as a thrown exception, which is the tell that the check is a runtime one. If you are writing your own enum helper, `where T : struct, System.Enum` gives you the compile-time check the BCL couldn't take.

**Combining multiple constraints** on one type parameter — order matters and is checked by the compiler:

```csharp
public class Repository<T>
    where T : EntityBase,          // 1. base class (at most one)
              IAuditable,           // 2. interfaces (any number)
              IComparable<T>,
              new()                 // 3. new() — must come last (except allows ref struct)
{ }

public static void Process<T>(T x)
    where T : IDisposable,          // 1. interfaces
              allows ref struct     // 2. allows ref struct — must come last (C# 13)
{ }
```

The `allows ref struct` clause cannot be combined with `class` or `class?`, and cannot appear on a `T` that is also constrained `where T : U` when `U` is a known reference type — in both cases the constraint and the anti-constraint contradict each other.

**Per-parameter `where` clauses** — each type parameter gets its own `where`:

```csharp
public class Cache<TKey, TValue>
    where TKey : notnull, IEquatable<TKey>
    where TValue : class, new()
{ }
```

**Why `where T : ISomeInterface` is the secret performance unlock for struct generics:**

```csharp
public static int Compare<T>(T a, T b) where T : IComparable<T>
    => a.CompareTo(b);

// For T = Money (struct), the JIT emits a "constrained" call IL prefix.
// The struct's CompareTo is dispatched DIRECTLY — no boxing, no virtual lookup.
// Equivalent to: a.CompareTo(b) on the unboxed struct.
//
// Without the interface constraint, you'd have to do:
//   ((IComparable<Money>)a).CompareTo(b)
// which boxes `a` to a heap allocation, then calls through the interface vtable.
```

This is the mechanical difference between `List<int>.Sort()` and `ArrayList.Sort()`. `ArrayList` stores `object`, so every element is already a boxed `int` on the heap and every comparison chases a pointer to it. `List<int>` stores `int` inline in an `int[]` and the constrained call reaches `Int32.CompareTo(int)` directly. Fewer allocations, better locality, no interface dispatch — state it that way rather than as a multiplier, because the actual ratio depends entirely on element count and comparison cost.

> 🌍 **In the real world**: a pricing service had a `Money` readonly struct and a generic `SortDescending<T>(T[] items)` helper written years earlier as `where T : IComparable` — the *non-generic* `IComparable`, because that is what the original author had used on the class version. It compiled and it sorted correctly. Under load the service showed allocation churn that a memory profiler traced to the sort: every `a.CompareTo(b)` on the non-generic interface boxed the `Money` receiver, so a single sort of a few thousand line items produced tens of thousands of short-lived heap objects and pushed gen-0 collections up. The fix was a one-word change — `where T : IComparable<T>` — after which the compiler emitted a `constrained.` prefix and the boxes disappeared. Nothing about the algorithm changed. The lesson is that on value-type generics the *generic* interface constraint is not a stylistic preference over the non-generic one; it is the thing that decides whether the call boxes, and the compiler will not warn you either way.

### Variance — covariance and contravariance

For most types, `Foo<Dog>` is **not assignable** to `Foo<Animal>`. They're distinct, unrelated types — even though `Dog` derives from `Animal`. This is **invariance** and is the safe default.

But for some types — notably read-only sequences and consumer-of-T delegates — the safe substitution does work. C# expresses this with **`out`** (covariance) and **`in`** (contravariance) on interface and delegate type parameters.

**Covariance — `out T`** ("producer of T"). `IEnumerable<Dog>` *can* substitute for `IEnumerable<Animal>` because every `Dog` is also an `Animal`, and `IEnumerable` only *produces* `T` (via `GetEnumerator`).

```csharp
public interface IProducer<out T>
{
    T Produce();
}

IProducer<Dog> dogs = ...;
IProducer<Animal> animals = dogs;        // ✓ — every Dog is an Animal
Animal a = animals.Produce();            // safe
```

**Contravariance — `in T`** ("consumer of T"). `Action<Animal>` *can* substitute for `Action<Dog>` because anything that handles an `Animal` can certainly handle a `Dog`.

```csharp
public interface IConsumer<in T>
{
    void Consume(T item);
}

IConsumer<Animal> handler = ...;
IConsumer<Dog> dogHandler = handler;     // ✓ — handler accepts any Animal, including Dog
dogHandler.Consume(new Dog());
```

**Invariance** — neither `in` nor `out`. Default for any `T` that's both produced and consumed. `IList<T>` is invariant: it both `Add(T)` (consumes) and `T this[int]` (produces). Allowing covariance on `IList<Dog> → IList<Animal>` would let you `.Add(new Cat())` to a list that only stores Dogs — breaking type safety.

**Memorize:**
- `out T` → covariant → producer position only (returns, get-only).
- `in T` → contravariant → consumer position only (parameters, set-only).
- (no annotation) → invariant → both positions allowed.

**Where you see variance in the BCL:**
- `IEnumerable<out T>` — covariant (only produces `T`).
- `IComparer<in T>` — contravariant (only consumes `T`).
- `Func<in T, out TResult>` — `T` is consumed, `TResult` is produced.
- `Action<in T>` — contravariant (only consumes).
- `IList<T>`, `Dictionary<TKey, TValue>`, `ICollection<T>` — invariant.

**Arrays — the historical exception:** `Dog[]` is covariant to `Animal[]` for legacy reasons (Java compatibility). This is *unsafe*: `Animal[] arr = new Dog[3]; arr[0] = new Cat();` compiles but throws `ArrayTypeMismatchException` at runtime. Avoid relying on array covariance; use `IEnumerable<T>` or `IReadOnlyList<T>` instead.

> 🌍 **In the real world**: an internal library exposed `IList<AuditEvent> GetEvents()` because the implementation happened to have a `List<AuditEvent>` handy and returning the concrete-ish interface felt convenient. Two consumers later, a caller with a `List<SecurityAuditEvent>` (a subtype) could not pass it into a helper typed `IList<AuditEvent>`, and rather than change the signature the developer wrote `.Cast<AuditEvent>().ToList()` — a full copy on a hot admin page, executed per request. The fix was to change the *parameter* type to `IReadOnlyList<AuditEvent>`, which is declared `IReadOnlyList<out T>` and therefore accepts `List<SecurityAuditEvent>` with no conversion at all. The habit worth taking away: choose the parameter type by what the method actually does, not by what the caller happens to hold. A method that only reads should say `IEnumerable<T>` or `IReadOnlyList<T>`, and it gets covariance for free; a method that says `IList<T>` is asserting it might mutate, and invariance is the price of that assertion.

> 🌍 **In the real world**: a scoring engine held rules in a `Rule[]` field and, for a "run every rule" loop, passed it as `object[]` into a generic-looking dispatcher that wrote results back into the same array. It worked in every test. In production, one tenant's configuration produced a `ScoringRule[]` (a subtype array) for the same field, and the dispatcher's write of a plain `Rule` into slot 0 threw `ArrayTypeMismatchException` — from a line that had not changed in two years, for one tenant, at 3am. Array covariance means the *static* type of an array variable tells you nothing about what the runtime will accept on a store; every reference-type array store carries a check against the array's real element type. The rewrite replaced the write-back with `Span<Rule>` over a freshly allocated buffer — `Span<T>` is invariant and has no such check — and the class of bug went away rather than the instance of it.

### Covariance and contravariance — beyond interfaces

Variance is a property of the **type parameter declaration site** — wherever C# lets you put `in` or `out`. It applies to **interfaces** and **delegates**, and shows up implicitly for **arrays**. Class declarations are never variant. Knowing the four flavors cold is a senior-level requirement.

**1. Delegate variance (`Func`, `Action`, `Predicate`, custom delegates).**

`Func<out TResult>` is covariant in its return; `Action<in T>` is contravariant in its parameter; `Func<in T, out TResult>` is both. Read the direction off the position, not off intuition: a `Func<Dog>` flows into a `Func<Animal>` (the *value produced* widens), and an `Action<Animal>` flows into an `Action<Dog>` (the *value consumed* narrows).

```csharp
// Func<out TResult> — covariant return
Func<Dog> getDog = () => new Dog();
Func<Animal> getAnimal = getDog;          // ✓ — every Dog is an Animal
Animal a = getAnimal();                   // safe — actually returns Dog

// Action<in T> — contravariant parameter
Action<Animal> petAnimal = a => Console.WriteLine(a.Name);
Action<Dog> petDog = petAnimal;            // ✓ — a function that handles any Animal handles a Dog
petDog(new Dog());                         // safe

// Func<in T, out TResult> — both
Func<Animal, Dog> animalToDog = a => new Dog();
Func<Dog, Animal> dogToAnimal = animalToDog;  // ✓ — accepts Dog (narrower input), returns Animal (wider output)
```

**Mnemonic — "in narrows on the way in, out widens on the way out":**
- A delegate that *accepts* `Animal` can stand in for one that needs to accept only `Dog` (caller narrows the input — safe).
- A delegate that *returns* `Dog` can stand in for one that needs to return `Animal` (callee widens the output — safe).

**The exception nobody expects: variance does not apply to delegate combination.** Microsoft Learn's *Covariance and Contravariance in Generics* states it flatly: "Variance does not apply to delegate combination. That is, given two delegates of types `Action<Derived>` and `Action<Base>`, you cannot combine the second delegate with the first although the result would be type safe." Assignment is variant; `Delegate.Combine` (the `+=` behind a multicast delegate or an event) requires *exact* type identity.

```csharp
Action<Animal> onAnyAnimal = a => Log(a);
Action<Dog>    onDog       = d => Groom(d);

Action<Dog> assigned = onAnyAnimal;      // ✓ contravariant assignment
Action<Dog> combined = onDog + onAnyAnimal;  // ✗ runtime ArgumentException — types must match exactly
```

> 🌍 **In the real world**: an event-aggregator was typed `Action<TEvent>` per topic, and a cross-cutting audit handler was written once as `Action<DomainEvent>` on the reasoning that "it handles every event, and contravariance means it fits everywhere". Subscribing it to a single topic worked — that is plain contravariant assignment. Registering it *alongside* the topic's own `Action<OrderPlaced>` handler threw `ArgumentException` from `Delegate.Combine` the first time two handlers existed for one topic, which in staging was never and in production was immediately. The audit handler had to be wrapped per topic (`e => audit(e)`, which creates a genuine `Action<OrderPlaced>`) instead of assigned. Worth internalising because it is the one place the variance rules stop: the compiler's assignment conversion and the runtime's multicast combination use different rules, and `+=` on an event is the second one.

> 🌍 **In the real world**: a `SortedSet<Circle>` needed ordering by area and the team already had a `ShapeAreaComparer : IComparer<Shape>` used elsewhere. The first attempt wrote a second comparer for `Circle`, then a third for `Square`, and the three drifted — one of them treated `null` as largest instead of smallest, so one report ordered differently from the other two. `IComparer<in T>` is contravariant, which means the single `IComparer<Shape>` can be passed straight into `new SortedSet<Circle>(comparer)`; Microsoft Learn uses exactly this pair as its contravariance example. Deleting two comparers deleted the drift. The general shape: when you find yourself writing near-duplicate `IComparer<T>` / `IEqualityComparer<T>` / `Action<T>` implementations for a type and its subtypes, contravariance already gave you the one-implementation answer.

**2. Generic type parameter variance rules** — what `in` / `out` is *legal* on:

```csharp
public interface IProducer<out T>    // ✓ T only in OUT positions (returns)
{
    T Produce();
}

public interface IConsumer<in T>     // ✓ T only in IN positions (parameters)
{
    void Consume(T item);
}

public interface IBoth<T>            // must be invariant — T in both positions
{
    T Produce();
    void Consume(T item);
}

// ILLEGAL — compile error:
public interface IBad<out T>
{
    void Consume(T item);            // ✗ "T must be invariantly valid for parameter"
}

public interface IBad2<in T>
{
    T Produce();                     // ✗ "T must be invariantly valid for return"
}
```

The compiler enforces variance positionally: an `out T` member can only have `T` in *return-type position* and `out` parameter position; an `in T` member can only have `T` in *parameter position*. This is what makes variance type-safe.

**Subtle rule — `out T` as a generic argument to an `out`-position generic:** the variance is "contagious" along chains:

```csharp
public interface IDoublyNested<out T>
{
    IEnumerable<T> All();            // ✓ — IEnumerable<out T> in out position with covariant T
}

public interface IBackwards<out T>
{
    IConsumer<T> AsConsumer();       // ✗ — IConsumer<in T> uses T contravariantly; can't put covariant T in here
}
```

The Roslyn message is "type parameter T must be invariantly valid on `IConsumer<T>`." This catches the legitimate type-safety hole.

**3. Why arrays are unsafely covariant — the runtime check.**

`Dog[]` IS-A `Animal[]` for legacy reasons (Java 1.0 compatibility, .NET 1.0 era when generics didn't exist). Reads are safe; writes are checked at runtime:

```csharp
Animal[] arr = new Dog[3];           // ✓ compiles — array covariance
arr[0] = new Dog();                  // ✓ runtime check passes (Dog is Dog)
arr[1] = new Cat();                  // ✗ ArrayTypeMismatchException at runtime!
                                     //   The runtime checks every store against the actual element type.
```

**The cost** — a store into a reference-type array carries a hidden runtime type check, because the static type of the array variable does not determine its real element type. On `T[]` for value-type `T` there is nothing to check: value-type arrays are *not* covariant, so an `int[]` variable can only ever refer to an `int[]`. On `T[]` for reference-type `T`, the JIT emits a check unless it can prove the element type exactly — which it can when the array was just `new`d locally, or when the static element type is `sealed` (nothing can derive from it, so no other array type could be assigned into that variable).

**Workaround for performance-sensitive code** — keep the array's declared element type equal to what you store, prefer `sealed` element types, or write through a `Span<T>`, which is invariant by construction and therefore has no covariance check at all. Don't rely on the JIT eliding the check; confirm it in a profile.

**4. Variance and `nullable` reference types.**

Nullable annotations ride along on variance, and the compiler enforces them with *warnings* rather than errors, because NRT is an analysis layer and not part of the runtime type system.

```csharp
IEnumerable<string?> maybeNulls = ...;
IEnumerable<string>  nonNulls   = maybeNulls;   // ⚠ CS8619 — nullability of reference types
                                                //   doesn't match target type

IEnumerable<string>  nonNulls2  = ...;
IEnumerable<string?> maybeNulls2 = nonNulls2;   // ✓ — widening to "may be null" is safe
```

The direction that warns is the one that would let a `null` escape into code that promised it wouldn't see one. The direction that's silent is the safe widening. At runtime neither conversion does anything — both are the same reference — so a `!` suppression here genuinely does nothing except move the risk to whoever dereferences the element. Be explicit about nullability in variance-carrying APIs; the annotation is the only signal a consumer gets.

### Generic specialization on the CLR

When the JIT compiles a generic type or method, its behavior diverges based on whether `T` is a **value type** or a **reference type**.

- **Reference types share a single specialization.** Code for `List<string>`, `List<object>`, and `List<Order>` is the same machine code at runtime — the JIT generates one body that operates on `object` references. This minimizes memory usage but means each ref-type `T` pays a small indirection cost.
- **Value types each get their own specialization.** `List<int>`, `List<long>`, `List<DateTime>` are distinct machine code bodies. This avoids boxing entirely (the value-type `T` is stored inline) and lets the JIT inline operations on `T`. Big perf win for hot paths.

Microsoft Learn's *Generics in the runtime* puts it this way: "Specialized generic types are created one time for each unique value type that is used as a parameter," whereas for reference types "the runtime reuses the previously created specialized version of the generic type … This is possible because all references are the same size."

This is why `List<int>` avoids the boxing that `ArrayList` (or `List<object>`) forces — and it happens automatically, with no attribute or flag. The flip side: instantiating many distinct value-type generics increases code size, because each one is a separate body.

For more on JIT mechanics, see [.NET Fundamentals — JIT](../01-net-core-deep-dive/01-net-fundamentals.md).

### Generic specialization in the JIT — deep dive

The shallow rule "value types specialized, reference types shared" hides a lot of nuance that comes up in senior interviews. The full picture:

**Reference-type sharing (a single body):**

```
List<string>, List<object>, List<Order>, List<Customer>
       │           │            │            │
       └───────────┴────────────┴────────────┘
                        ▼
       ONE JIT'd method body that operates on object references.
       Type parameter T is essentially "object" at the machine-code level.
       Every list manipulates references uniformly.
```

The shared body uses **MethodTable** lookups for any operations that need T's identity (e.g., `Equals`, `GetHashCode`). The MethodTable for `T` is accessed via a hidden parameter or via the object's own header — both add one indirection per call.

**Value-type specialization (per concrete T):**

```
List<int>      → distinct JIT'd body operating on int (4 bytes inline)
List<long>     → distinct JIT'd body operating on long (8 bytes inline)
List<DateTime> → distinct JIT'd body operating on DateTime (8 bytes inline)
List<Guid>     → distinct JIT'd body operating on Guid (16 bytes inline)
```

Each value-type specialization can:
- Inline `T` operations (no virtual dispatch).
- Use exact `sizeof(T)` for `Array.Copy`, `Span<T>` slicing, etc.
- Devirtualize interface calls via the *constrained call* IL prefix — `IComparable<T>.CompareTo` resolves to a direct call to the struct's method.

**Implications for performance:**

| Aspect | Reference `T` | Value `T` |
|---|---|---|
| Code size | One body for all (small total) | One per concrete `T` (can balloon) |
| Per-call overhead | Indirection through MethodTable | Direct inlined operation |
| Interface calls | Vtable (no devirtualization unless sealed) | Constrained call → direct → potentially inlined |
| Memory layout | Pointer-sized slot (8 bytes on x64) | `sizeof(T)` inline (no boxing) |
| `default(T)` | `null` (no init code) | `default(T)` = zero-init memory |
| Equality | `EqualityComparer<T>.Default` (one lookup, cached) | `EqualityComparer<T>.Default` specialized for `T` |
| Hot-path JIT | Single body, PGO-shared | Per-`T` PGO data — better hot/cold splitting |

**Code-size implication — AOT and trim sizes:**

Native AOT (`PublishAot`) and ReadyToRun ahead-of-time compile each value-type specialization that's reachable from the entry point. A library that exposes `Dictionary<TKey, TValue>` where TKey and TValue have 10 each leaf types each could see **100 distinct specializations** compiled into the binary. For mobile, IoT, or container-size-sensitive deployments, this matters.

**Mitigation patterns:**
- Use `object`-typed inner storage and box at the boundary if `T` doesn't need to be hot.
- Constrain to `class` to force the reference-type-shared path.
- Profile with `dotnet-trace` and check `IL_SIZE` per specialization.

**Devirtualization wins** — the JIT can often see "this `T` is sealed and has no overrides" and replace the constrained call with a static one. With Dynamic PGO (Profile-Guided Optimization, on by default since .NET 8), this can also happen based on the types actually observed at runtime, via a guarded check that falls back to the virtual call when the guess is wrong.

> 🌍 **In the real world**: a telemetry ingestion library was published as a NuGet package, exposed `RingBuffer<T>` and `BatchWriter<TKey, TValue>`, and was consumed by a Native-AOT-published sidecar that ran in a memory-constrained container. Adding a handful of new metric value types to the calling application — each a small struct — grew the published binary noticeably, because every new value type meant new specializations of `RingBuffer<T>`, `BatchWriter<,>`, and every generic method they called transitively. Nobody had changed the library. The team's fix was to keep the hot single-element path generic and give the batching internals an `object[]` backing store, which collapsed the batching half onto the shared reference-type body at the cost of boxing on a path that was already doing I/O. The trade the reader should be able to articulate under questioning: value-type generics buy you no boxing and inlined operations *per instantiation*, and pay for it in code size *per instantiation* — which is invisible on a server and very visible in AOT, mobile, and container-size budgets.

### Generic type identity at runtime

Each closed generic type is a distinct `System.Type`. The runtime does NOT consider `List<int>` and `List<string>` the same type — they have different `MethodTable`s, different vtables, and different metadata.

```csharp
typeof(List<int>) == typeof(List<string>);     // false
typeof(List<int>) == typeof(List<int>);        // true — same closed type
typeof(List<>) == typeof(List<int>);           // false — open vs closed are different
typeof(List<>) == typeof(List<>);              // true — same open generic definition

// Inspect at runtime
Type closed = typeof(List<int>);
closed.IsGenericType;              // true
closed.IsGenericTypeDefinition;    // false — closed, not the definition
closed.IsConstructedGenericType;   // true — closed (constructed)
closed.GetGenericTypeDefinition(); // typeof(List<>)
closed.GetGenericArguments();      // [ typeof(int) ]

Type open = typeof(List<>);
open.IsGenericType;                // true
open.IsGenericTypeDefinition;      // true
open.IsConstructedGenericType;     // false — open
open.GetGenericArguments();        // [ T ] — the unbound parameter
```

**Reflection-time construction with `MakeGenericType`:**

```csharp
Type openList = typeof(List<>);
Type closedListOfInt = openList.MakeGenericType(typeof(int));
Console.WriteLine(closedListOfInt == typeof(List<int>));   // true

// Instantiate it
object listInstance = Activator.CreateInstance(closedListOfInt);
// listInstance is actually a List<int> at runtime — boxed as object here.

// Call methods reflectively
MethodInfo add = closedListOfInt.GetMethod("Add");
add.Invoke(listInstance, new object[] { 42 });
```

**`MakeGenericMethod`** for generic methods:

```csharp
MethodInfo openMethod = typeof(MyClass).GetMethod("Process");  // public T Process<T>(T x)
MethodInfo closedMethod = openMethod.MakeGenericMethod(typeof(int));
closedMethod.Invoke(instance, new object[] { 5 });
```

**Where this matters in real code** — DI containers, ORMs, serializers (`JsonSerializer`), source generators that emit code for closed types. Every time you see a framework "auto-discover" generic types, `MakeGenericType` is involved under the hood.

**Cost** — the first construction of a given closed type has to load metadata, build the runtime type, and JIT any bodies that aren't already compiled. After that the runtime canonicalises constructed generics, so repeat calls return the same cached `Type` instance and are cheap. The shape to describe in an interview is "expensive once, then a dictionary hit" — don't quote a number you haven't measured on the machine in question. If a request path depends on it, pre-warm at startup so the cost lands before traffic does.

> 🌍 **In the real world**: a message dispatcher resolved handlers by building `typeof(IHandler<>).MakeGenericType(messageType)` on every incoming message and calling `MakeGenericMethod` on a `Handle<T>` shim. Throughput was fine. Then the service was republished with `PublishAot` for faster cold start in a serverless deployment, and it started throwing at runtime — but only for the message types that happened to be structs. Native AOT compiles the specializations it can see statically; a value-type instantiation reached only through reflection has no code to run and none can be generated at runtime. Reference-type messages kept working, because all reference instantiations share one body, which masked the problem in every test that used class-based messages. The signal the team had ignored was an `IL3050` warning at publish time, which is exactly what it is for. The dispatcher was rewritten to register a closed-over `Func<object, Task>` per handler at startup — no reflection on the hot path, and the AOT warning went away. See [Generics under Native AOT and trimming](#generics-under-native-aot-and-trimming) below.

### Type inference — when it works and when it doesn't

**Generic method type inference** works on argument types — the compiler matches each parameter type with each argument and solves the system of equations.

```csharp
public static T Identity<T>(T x) => x;

int n = Identity(5);             // T inferred as int
string s = Identity("hello");    // T inferred as string
double d = Identity(3.14);       // T inferred as double

// Inference fails if there's no argument constraining T:
public static T Default<T>() => default(T);
// Default();           // ✗ "type arguments cannot be inferred from the usage"
int x = Default<int>(); // ✓ — explicit
```

**Inference rules — what the compiler can and can't do:**

| Scenario | Inference works? | Why |
|---|---|---|
| `Identity(5)` | ✓ | Argument type `int` constrains `T` |
| `Identity<int>()` | ✓ | Explicit |
| `Default()` (no args) | ✗ | Nothing to infer from |
| `Process(getValue: () => 5)` | ✓ | Lambda return inferred as `int` |
| `Combine(5, "x")` (where `T : both`) | ✗ | Two different types — no unique `T` |
| `Convert<int>(x)` (where input is double) | ✓ | Explicit T overrides any inference |
| `new Box(5)` (any C# version, including C# 14) | ✗ | C# has **never** inferred type arguments from constructor arguments |
| `Box<int> b = new(5);` | ✓ | Not inference — *target-typed `new`* (C# 9). The target type supplies `int` |

**Methods infer; constructors don't — still.** This is a permanent asymmetry, not a version gap. `List<int>.Add(5)` infers nothing (the type is already closed), but you must write `new List<int>()`, never `new List(5)`. Inferring type arguments from constructor arguments has been a long-standing open request against the language and has not shipped. The workaround is a **static factory method**:

```csharp
public static class Box
{
    public static Box<T> Create<T>(T value) => new Box<T>(value);
}

var b = Box.Create(5);          // Box<int> — factory infers; ctor wouldn't
```

Two features are routinely mistaken for constructor inference. Neither is:

```csharp
// Target-typed `new` (C# 9) — the TARGET supplies the type argument, nothing is inferred
// from the argument list.
Box<int> b = new(5);                       // ✓
var       c = new(5);                      // ✗ no target type to read

// Collection expressions (C# 12) — again target-typed.
List<int> list = [1, 2, 3];                // ✓
// var list2 = [1, 2, 3];                  // ✗ no target type

// Genuine constructor type-argument inference: does not exist in any C# version.
// var b2 = new Box(5);                    // ✗
```

The distinction matters in an interview because "C# added it in 12" is a confident wrong answer, and the follow-up ("so what does `var b = new(5);` do?") exposes it immediately.

**Method-vs-constructor inference asymmetry — the canonical interview gotcha:**

```csharp
// Factory method — type inferred from the argument
public static Box<T> CreateBox<T>(T x) => new Box<T>(x);

var b1 = CreateBox(5);               // ✓ → Box<int>, inferred
var b2 = new Box<int>(5);            // ✓ — explicit
// var b3 = new Box(5);              // ✗ — no constructor inference, in any version
Box<int> b4 = new(5);                // ✓ — target-typed new (C# 9), not inference
```

This is why the BCL pairs so many generic types with a non-generic static class of the same name: `Tuple` beside `Tuple<T1, T2>`, `KeyValuePair` beside `KeyValuePair<TKey, TValue>`, `ImmutableArray` beside `ImmutableArray<T>`. Those classes exist so a *method* — `Tuple.Create(1, "x")`, `KeyValuePair.Create(k, v)`, `ImmutableArray.Create(1, 2, 3)` — can do the inferring the constructor can't. When you design a generic type whose constructor takes all its type arguments, ship the same pairing.

> 🌍 **In the real world**: a caching layer had `TryGet<T>(string key, out T value)` and a call site `object cached; if (cache.TryGet(key, out cached))`, written that way because the surrounding method already had an `object` local. `T` inferred as `object`, so the cache stored and compared boxed values, and — worse — the type check inside `TryGet` (`stored is T`) was `stored is object`, which is true for everything. A `Customer` cached under a key that a later refactor reused for an `Order` came back as an `Order` typed `object`, and the `InvalidCastException` surfaced three frames away in the mapper. Nothing about the generic method was wrong; inference had simply been fed the declared type of a local instead of the type the caller wanted. Inference reads the *static* type of the argument, never the runtime type and never the target of the assignment — so an `object`-typed local anywhere near a generic call is a place to look when a generic behaves as though it lost its type.

**`Goo<int>(x)` vs `Goo(x)` — when explicit matters:**
- `Goo(x)` — compiler infers from `x`'s static type. If `x: object` and you want `T=int`, inference picks `T=object`.
- `Goo<int>(x)` — explicit. The compiler then checks `x` is convertible to `T=int`.

```csharp
public static T Echo<T>(T x) => x;

object o = 5;
var e1 = Echo(o);            // T inferred as object — e1 is object, not int
var e2 = Echo<int>(o);       // ✗ compile error — object is not implicitly int
var e3 = Echo<int>((int)o);  // ✓ — T=int with explicit cast
```

**Inference and overload resolution** — when multiple methods are eligible, inference happens *per candidate*. The compiler picks the one with the most specific match. If two candidates tie, it's an ambiguity error.

**Inference for nullable reference types** is best-effort:

```csharp
public static T Find<T>(IEnumerable<T> xs, Func<T, bool> pred) => xs.FirstOrDefault(pred);

string? s = null;
var result = Find(new[] { s }, x => x != null);   // T inferred as string?
```

The compiler propagates nullability annotations through inference but doesn't always pick the most useful one — annotate explicitly when it matters.

### `default(T)` in generics and the `default!` pattern

**Getting "the default" without knowing T's category** — `default(T)` returns the type-appropriate default: `null` for reference types, zero-initialized for value types.

```csharp
public static T Default<T>() => default(T);

Default<int>();          // 0
Default<bool>();         // false
Default<DateTime>();     // DateTime.MinValue (zero-init)
Default<string>();       // null
Default<List<int>>();    // null
```

**The `default` literal (C# 7.1+)** — shorter form, target-typed:

```csharp
public T GetOrDefault<T>(int id) => found ? value : default;
//                                          → default(T) inferred
```

**The IL emitted by `default(T)`:**

For unconstrained `T`, the compiler emits `initobj T` — zero-init the memory slot. For `where T : class`, it emits `ldnull`. The cost is essentially free.

**The `default!` null-forgiving pattern** — when NRT is on and `T` could be a reference type, `default(T)` returns `null`, but the type may be annotated as non-nullable. Use `default!` to assert the compiler should treat the value as non-null:

```csharp
#nullable enable

public class Cache<TKey, TValue>
{
    private TValue _last = default!;     // _last "should not be null" but starts as default

    public TValue GetLast() => _last;     // returns TValue, not TValue?
    public void Set(TValue v) => _last = v;
}
```

Without the `!`, NRT warns "Cannot convert null literal to non-nullable reference type." With it, you're telling the compiler "trust me, I'll set it before reading."

**When this is legitimate:**
- A field that's initialized in a non-ctor lifecycle (e.g., DI `[Inject]`, framework callback).
- A test fixture whose `SetUp` populates state before any test runs.
- A generic class where `T` might be a value type (and `default(T)` is genuinely valid).

**When this is a bug** — using `default!` to silence a warning instead of actually handling the null case. The runtime will throw `NullReferenceException` deep in some unrelated method if the assertion was wrong.

**Alternative — `EqualityComparer<T>.Default.Equals(x, default)`:**

```csharp
public bool IsDefault<T>(T value)
{
    return EqualityComparer<T>.Default.Equals(value, default);
}

IsDefault(0);             // true
IsDefault("");            // false (empty string ≠ null)
IsDefault((string?)null); // true
```

This handles all cases uniformly — reference, value, nullable value — without writing `if (typeof(T).IsValueType)`.

> 🌍 **In the real world**: a repository base class declared `protected TEntity _current = default!;` so that a `TEntity` property could be non-nullable without a constructor argument, on the understanding that `LoadAsync` always ran first. A later maintainer added a second entry point that read `_current` for a "last touched" audit field without calling `LoadAsync`. The `!` had told the compiler to stop asking, so nothing warned; the `NullReferenceException` appeared in the audit writer, several layers from the field that was actually null, and the first three engineers to look at it went hunting in the audit code. `default!` is not a fix — it is a promise made to the compiler that the type system will never re-check. Use it only where the initialisation is genuinely enforced by something outside the constructor (a DI lifecycle hook, a test `SetUp`), and where a `T` might legitimately be a value type. Where the field is simply "set later", `TEntity?` plus an explicit null check at the read site is the honest signature, and it puts the failure at the line that made the wrong assumption.

### Generic math interfaces (C# 11)

C# 11 added `static abstract` interface members. Combined with constraints, this enables **generic math** — algorithms that work on `int`, `double`, custom numeric types, anything implementing the right interface.

The BCL ships:
- `INumber<T>` — addition, subtraction, multiplication, division, comparisons, etc. Implemented by all built-in numeric types (`int`, `long`, `float`, `double`, `decimal`, `BigInteger`, ...).
- `IAdditionOperators<T, T, T>`, `ISubtractionOperators<T, T, T>`, etc. — finer-grained interfaces.
- `IComparable<T>`, `IComparisonOperators<T, T, bool>`, etc.

```csharp
public static T Sum<T>(IEnumerable<T> items) where T : INumber<T>
{
    T total = T.Zero;
    foreach (var item in items)
        total += item;
    return total;
}

int sumI = Sum(new[] { 1, 2, 3 });          // 6
double sumD = Sum(new[] { 1.1, 2.2, 3.3 });  // 6.6
decimal sumM = Sum(new[] { 1.5m, 2.5m });    // 4.0
```

This was previously impossible without massive overload sets or runtime trickery (`dynamic`, codegen). Now it's a one-line constraint.

### Generic math — the full surface

`INumber<T>` is the top of a deep hierarchy of interfaces. The BCL split arithmetic into fine-grained operator interfaces so you can constrain to exactly what you need:

The direction of this hierarchy is the thing interviewers probe, and it is easy to get backwards. `INumberBase<T>` is **above** `INumber<T>`, not below it; `IBinaryInteger<T>` and `IFloatingPoint<T>` are **below**. Note when you read the source that `INumber<T>`'s own declaration lists only five interfaces — `IComparable`, `IComparable<T>`, `IComparisonOperators<T,T,bool>`, `IModulusOperators<T,T,T>` and `INumberBase<T>` — and everything else arrives through `INumberBase<T>`. The API reference flattens that into one long declaration line, which is the set drawn below:

```
                     ┌──────────────────────────────┐
   MORE GENERAL      │      INumberBase<T>          │  numeric conversions, One, Zero,
   (fewer members,   │                              │  IsZero / IsNegative / IsNaN, Parse
    more implementers)└──────────────┬──────────────┘
                                     │ INumber<T>'s full interface set also includes:
                                     │   IAdditionOperators<T,T,T>      +
                                     │   ISubtractionOperators<T,T,T>   -
                                     │   IMultiplyOperators<T,T,T>      *
                                     │   IDivisionOperators<T,T,T>      /
                                     │   IModulusOperators<T,T,T>       %
                                     │   IUnaryNegationOperators<T,T>   unary -
                                     │   IUnaryPlusOperators<T,T>       unary +
                                     │   IIncrementOperators<T>         ++
                                     │   IDecrementOperators<T>         --
                                     │   IEqualityOperators<T,T,bool>   ==  !=
                                     │   IComparisonOperators<T,T,bool> <  <=  >  >=
                                     │   IAdditiveIdentity<T,T>, IMultiplicativeIdentity<T,T>
                                     │   IComparable, IComparable<T>, IEquatable<T>
                                     │   IParsable<T>, ISpanParsable<T>
                     ┌───────────────▼──────────────┐
                     │        INumber<T>            │  Clamp, CopySign, Max, Min, Sign
                     └───────────────┬──────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
   ┌──────────▼─────────┐  ┌─────────▼────────┐  ┌──────────▼─────────┐
   │  IBinaryNumber<T>  │  │ IFloatingPoint<T>│  │ (int, double, …    │
   │  bitwise, Log2     │  │ Floor, Ceiling,  │  │  BigInteger, Half, │
   └──────────┬─────────┘  │ Round, Truncate  │  │  Int128, NFloat)   │
              │            └─────────┬────────┘  └────────────────────┘
   ┌──────────▼─────────┐  ┌─────────▼────────────────┐
   │ IBinaryInteger<T>  │  │ IFloatingPointIeee754<T> │
   │ PopCount, Leading- │  │ Epsilon, NaN, Atan2, …   │
   │ ZeroCount, shifts  │  └──────────────────────────┘
   └────────────────────┘
   MORE SPECIFIC (more members, fewer implementers)
```

If you constrain to something near the bottom you get more operations and fewer accepted types; near the top, the reverse. That is the whole design.

**Why split this way** — minimizing what you require. A `Sum<T>` only needs `IAdditionOperators<T, T, T>` and a way to get `T.Zero`. Demanding the full `INumber<T>` forces every implementer (including custom numeric types) to implement floating-point semantics they may not have:

```csharp
// Tighter constraint — works on int, decimal, BigInteger, custom Money type, etc.
public static T Sum<T>(IEnumerable<T> xs)
    where T : IAdditionOperators<T, T, T>, IAdditiveIdentity<T, T>
{
    T total = T.AdditiveIdentity;        // generic "Zero"
    foreach (var x in xs) total += x;
    return total;
}

// Looser — only works on full INumber<T> types
public static T SumLoose<T>(IEnumerable<T> xs) where T : INumber<T>
{
    T total = T.Zero;
    foreach (var x in xs) total += x;
    return total;
}
```

**`static abstract` member groundwork** — the language feature that makes this possible. Interfaces can declare `static abstract` members, which must be implemented as `static` members on each type that implements the interface:

```csharp
public interface IAdditionOperators<TSelf, TOther, TResult>
    where TSelf : IAdditionOperators<TSelf, TOther, TResult>
{
    static abstract TResult operator +(TSelf left, TOther right);
}

public readonly struct Money : IAdditionOperators<Money, Money, Money>
{
    public decimal Value { get; }
    public Money(decimal v) => Value = v;
    public static Money operator +(Money a, Money b) => new(a.Value + b.Value);
}

// Now generic code can call M + N when T = Money:
public static T Add<T>(T a, T b) where T : IAdditionOperators<T, T, T>
    => a + b;
```

**The `where T : I<T>` self-referential pattern** is the standard idiom. The interface declares it returns `TSelf` (e.g., `T.Zero` returns `T`), and the constraint pins `T` to its own interface implementation. This is called the **curiously recurring template pattern (CRTP)** in C++ terms — and it's what makes `T.Zero` work as a static call on the type parameter.

**Cross-link** — see [OOP — Static abstract members (C# 11)](./03-oop-and-polymorphism.md#static-abstract-members-c-11) for the language-feature side; this section covers the *generic-math consequences* of that feature.

**Performance** — generic math rides on value-type specialization: `Sum<int>` and `Sum<decimal>` are separate JIT'd bodies, each resolving `+` through a `constrained.` call to the concrete type's `op_Addition`, which for `int` is an ordinary machine `add` after inlining. No interface dispatch and no boxing, which is the property that makes the abstraction affordable at all. The cost is the same code-size cost as any value-type generic: one body per numeric type you instantiate. Don't quote a percentage against a hand-written loop — it depends on what else is in the loop, and it's exactly the kind of number an interviewer will ask you to defend.

> 🌍 **In the real world**: a billing library had `Money`, and a request came in to reuse the existing generic aggregation helpers (`Sum`, `Average`, `Median`) with it. The obvious move was `where T : INumber<T>`, so `Money` was made to implement it — which drags in division, modulus, `IParsable<T>`, `ISpanParsable<T>`, `CreateChecked`/`CreateSaturating` conversions and the full comparison surface. Implementing `Money % Money` and `Money / Money` meaningfully is a question nobody on the team wanted to answer, so they were implemented as `throw new NotSupportedException()`. Predictably, a generic helper eventually called one, and a currency conversion crashed in production for a code path that had been "unreachable". The rewrite constrained each helper to the minimum it actually used — `Sum` to `IAdditionOperators<T, T, T>` plus `IAdditiveIdentity<T, T>`, `Median` to `IComparisonOperators<T, T, bool>` — and `Money` dropped `INumber<T>` entirely. The transferable rule: a constraint is a *demand you make of every future implementer*. `INumber<T>` is a large demand, and a type that has to throw to satisfy it is telling you the constraint is wrong, not that the type is deficient.

### `allows ref struct` (C# 13)

Before C# 13, you could not use `Span<T>`, `ReadOnlySpan<T>`, or any `ref struct` as a generic type argument — a type parameter carries an implicit "this may live on the heap" assumption, and ref structs may not. C# 13's `allows ref struct` is an **anti-constraint**: unlike every other `where` clause it *widens* the set of accepted types rather than narrowing it. The C# 13 feature spec is explicit about this: "other syntax items limit the set of types that can fulfill a generic parameter while `allows ref struct` expands the set of types."

```csharp
// The canonical example from the feature spec.
T Identity<T>(T p)
    where T : allows ref struct
    => p;

Span<int> local = Identity(new Span<int>(new int[10]));   // ✓ — impossible before C# 13
```

The price is that `T` inherits every ref-struct restriction. Per the spec, a type parameter bound by `allows ref struct` cannot be boxed, participates in ref-struct lifetime rules, "cannot be used in `static` fields, elements of an array, etc.", and can be marked `scoped`:

```csharp
interface I1 { }

I1 M1<T>(T p) where T : I1, allows ref struct
{
    return p;              // ✗ error — returning T as I1 is a box
}

// T cannot flow into another generic unless that parameter also allows ref struct:
void M2<T>(T p) where T : allows ref struct
{
    var list = new List<T>();   // ✗ List<T>'s parameter does not allow ref struct
    T[] arr = new T[4];         // ✗ array elements may not be ref structs
}
```

Two consequences worth having ready:

- **The anti-constraint is not inherited.** In `class C<T, S> where T : allows ref struct where S : T`, `S` still cannot be a ref struct. You must repeat `allows ref struct` on every parameter that needs it.
- **`Span<Span<T>>` still does not work**, and this is the question people reach for. `Span<T>` does not declare `allows ref struct` on its own `T`, because some of its public surface (`Span(T[] array)`, the implicit conversion from `T[]`) uses `T` as an array element, which a ref struct can never be.

Where you'll genuinely reach for it is abstracting over enumerators and buffer types — writing one `ForEach<TEnumerator>` that accepts both a `List<T>.Enumerator` and a ref-struct span enumerator, instead of two near-identical methods. Outside that, leave it off; adding it to a type parameter you don't need it on only removes capabilities from your own method body.

### `unmanaged` and `notnull` constraints

**`where T : unmanaged`** — `T` is a value type that contains only **blittable** types: primitives (`int`, `byte`, ...), enums, pointers, or other unmanaged structs. Crucially, no references. This unlocks low-level pointer/`Span` operations.

```csharp
public unsafe static int SizeOf<T>() where T : unmanaged
    => sizeof(T);

public static bool BitEquals<T>(T a, T b) where T : unmanaged
{
    var spanA = MemoryMarshal.AsBytes(MemoryMarshal.CreateReadOnlySpan(ref a, 1));
    var spanB = MemoryMarshal.AsBytes(MemoryMarshal.CreateReadOnlySpan(ref b, 1));
    return spanA.SequenceEqual(spanB);
}

// Compiles for: int, double, Guid, custom blittable structs.
// Doesn't compile for: string, List<int>, struct with a string field.
```

**`where T : notnull`** — `T` is a non-nullable type. Either a value type, or a reference type with NRT enabled. Useful for dictionary keys, since `null` is a poor key.

```csharp
public class Cache<TKey, TValue> where TKey : notnull
{
    private readonly Dictionary<TKey, TValue> _store = new();
    public TValue? Get(TKey key) => _store.TryGetValue(key, out var v) ? v : default;
}

// Allowed: Cache<int, ...>, Cache<string, ...>, Cache<Guid, ...>
// Disallowed: Cache<string?, ...>  (warning — but compiles, since NRT is advisory)
```

Note the asymmetry that Microsoft Learn calls out explicitly: "Unlike other constraints, if a type argument violates the `notnull` constraint, the compiler generates a warning instead of an error" — and only in a `nullable enable` context. `notnull` documents intent and catches accidents; it does not enforce anything the runtime will honour.

> 🌍 **In the real world**: a serializer helper was written `where T : unmanaged` so it could do `MemoryMarshal.AsBytes` over the struct and write it straight to a socket — a legitimate use, and it worked for the six DTOs it started with. A year later someone added a `string CorrelationId` field to one of those DTOs, the `unmanaged` constraint stopped being satisfied, and rather than reading what the constraint meant they changed it to `where T : struct` and left the `MemoryMarshal` call in place. That compiles — `AsBytes<T>` is itself declared `where T : struct`, and `struct` permits a value type containing references — so the build went green and the change shipped. What it did **not** do is work: `AsBytes` guards at runtime with `RuntimeHelpers.IsReferenceOrContainsReferences<T>()` and throws `ArgumentException` ("Cannot use type 'T'. Only value types without pointers or references are supported.") the first time that DTO is sent. A compile-time error had been converted into a production exception on one code path, discovered by a customer rather than by CI. That is the real shape of the lesson: `unmanaged` versus `struct` is not a strictness preference. `unmanaged` is the compile-time proof that "reinterpret this as bytes" is a meaningful operation, and downgrading it to `struct` deletes exactly that proof — the BCL then re-checks the same condition at runtime, because reinterpreting a managed reference as bytes is never something it will quietly let you do.

### Open vs closed generics

A *closed* generic has all its type parameters specified: `List<int>`, `Dictionary<string, Order>`. An *open* generic has unspecified parameters: `List<>`, `Dictionary<,>`.

Open generics are visible mostly via reflection and DI registration:

```csharp
// DI — register the open generic, resolve any closed instantiation
services.AddScoped(typeof(IRepository<>), typeof(EfRepository<>));

var repo = serviceProvider.GetRequiredService<IRepository<Order>>();
// → resolves EfRepository<Order>

// Reflection
Type listOpen = typeof(List<>);                       // open
Type listClosed = listOpen.MakeGenericType(typeof(int));  // closed: List<int>
Console.WriteLine(listClosed == typeof(List<int>));   // True
```

Open generic registration is a major DI pattern in ASP.NET Core — it lets you wire up generic abstractions once and resolve them for any closed type the consumer asks for.

> 🌍 **In the real world**: a service registered `services.AddScoped(typeof(IRepository<>), typeof(EfRepository<>))` and, separately, a background hosted service (a singleton) that took `IRepository<Order>` in its constructor. The container resolved it happily — open generic registration does not change lifetime validation's mind about anything, and the captive-dependency check only fires when the scope validation option is on. The scoped `DbContext` inside that repository was therefore captured for the process lifetime: its change tracker grew all day, memory climbed, and stale entities were served after other instances had written newer rows. Two habits came out of it. First, `ValidateScopes` and `ValidateOnBuild` are on in every environment, not just Development, so a captive dependency fails at startup rather than at 4pm. Second, long-lived services take `IServiceScopeFactory` and open a scope per unit of work. Open generic registration is a convenience for *wiring*; it has nothing to say about *lifetime*, and conflating the two is one of the most common senior-level DI mistakes.

### Variance is a reference conversion — value types never participate

This is the single most common follow-up to "explain covariance", and the page you are reading would have left you without an answer. Microsoft Learn's *Covariance and Contravariance in Generics* states the rule in one line:

> "Variance applies only to reference types; if you specify a value type for a variant type parameter, that type parameter is invariant for the resulting constructed type."

So:

```csharp
IEnumerable<string> strings = new List<string>();
IEnumerable<object> objects = strings;      // ✓ — string → object is a reference conversion

IEnumerable<int> ints = new List<int>();
IEnumerable<object> boxed = ints;           // ✗ CS0266 — int → object is a BOXING conversion
```

**Why the runtime cannot allow the second one.** A variance conversion must be a no-op at the machine level: `IEnumerable<Dog>` and `IEnumerable<Animal>` are the same reference, pointing at the same object, and the assignment emits no instructions at all. That works because a `Dog` reference and an `Animal` reference have identical representation — both are a pointer to the object. `int` and `object` do not: turning an `int` into an `object` means allocating a box and copying the value into it. Since `IEnumerable<int>` yields `int`s from an `int[]` with no boxes anywhere, there is no reference for a hypothetical `IEnumerable<object>` view to hand back without allocating one per element — and the CLR's assignment-compatibility check has no mechanism to insert per-element allocations. It therefore refuses.

The same rule explains three things that look unrelated:

| Attempt | Result | Reason |
|---|---|---|
| `IEnumerable<Dog>` → `IEnumerable<Animal>` | ✓ | Reference conversion; identical representation |
| `IEnumerable<int>` → `IEnumerable<object>` | ✗ | Boxing conversion, not a reference conversion |
| `IEnumerable<int>` → `IEnumerable<long>` | ✗ | Numeric conversion; also not a reference conversion, and `long` isn't a base of `int` |
| `IEnumerable<int?>` → `IEnumerable<object>` | ✗ | `Nullable<int>` is a value type too |
| `Action<object>` → `Action<int>` | ✗ | Contravariance is equally restricted to reference types |
| `IEnumerable<string>` → `IEnumerable<IComparable>` | ✓ | Interface implementation is a reference conversion |

**The escape hatch** when you actually need the widened sequence is `Cast<T>` or `OfType<T>`, and you should say out loud what they cost:

```csharp
IEnumerable<object> boxed = ints.Cast<object>();   // ✓ compiles — allocates one box per element,
                                                   //   lazily, as the sequence is enumerated
```

That is not variance. It is a new sequence with a per-element allocation, and if the caller enumerates it twice it boxes twice.

> 🌍 **In the real world**: a reporting endpoint had a helper `string Describe(IEnumerable<object> items)` used for diagnostics. It was called from dozens of places with `List<string>` and friends, all free. One call site passed a `List<int>` of row ids, hit the compile error, and the developer "fixed" it with `.Cast<object>()` because that was the suggestion that made the red squiggle go away. The endpoint ran on a page that could return a few hundred thousand ids, so the diagnostic string — built on every request, including the ones where diagnostics were disabled — boxed every id and pushed a visible step into gen-0 collections. The fix was to make the helper generic (`Describe<T>(IEnumerable<T> items)`), which specializes over `int` and boxes nothing. The reasoning to carry: when a covariant assignment fails on a value type, the compiler is telling you a representation change is required. `Cast<object>` agrees to pay for it; making the method generic declines to.

### Static members live per closed generic type

`Counter<int>` and `Counter<string>` are different types, and the C# standard's §15.5.2 *Static and instance fields* is unambiguous about what that means: "A static field in a non-generic class identifies exactly one storage location. No matter how many instances of a non-generic class are created, there is only ever one copy of a static field. Each distinct **closed constructed type** has its own set of static fields, regardless of the number of instances of the closed constructed type."

```csharp
public class Counter<T>
{
    public static int Count;                 // one per CLOSED type
    static Counter() => Console.WriteLine($"cctor for {typeof(T).Name}");
}

Counter<int>.Count++;        // prints "cctor for Int32";    Counter<int>.Count    == 1
Counter<string>.Count++;     // prints "cctor for String";   Counter<string>.Count == 1
Counter<object>.Count++;     // prints "cctor for Object";   Counter<object>.Count == 1
```

Two properties fall out of this, and both come up:

1. **The static constructor runs once per closed type**, not once per generic definition. Three closed types, three `cctor` executions, three independent sets of statics.
2. **Code sharing does not imply state sharing.** `Counter<string>` and `Counter<object>` execute the *same* JIT'd machine code (see the next section), yet have entirely separate `Count` fields. The shared body reaches its statics indirectly, through the per-instantiation generic dictionary — which is exactly why sharing code is possible without sharing data.

This is the mechanism behind a deliberately useful pattern and a common bug.

**The pattern** — per-type caches with no dictionary lookup and no lock:

```csharp
internal static class Metadata<T>
{
    // Computed once per closed type, on first touch, with the runtime's
    // type-initialization guarantee doing the locking for you.
    public static readonly PropertyInfo[] Properties =
        typeof(T).GetProperties(BindingFlags.Public | BindingFlags.Instance);
}

// Access is a static field read — no ConcurrentDictionary<Type, ...> hash, no lock.
var props = Metadata<Order>.Properties;
```

Serializers and mappers use exactly this shape. It is faster than a `ConcurrentDictionary<Type, PropertyInfo[]>` because the "lookup" is resolved when the code is compiled for that instantiation.

**The bug** — the same mechanism, applied to state that was supposed to be global:

```csharp
public abstract class Repository<T>
{
    private static int _openConnections;   // ✗ one counter PER entity type
}
```

Analyzers flag this (ReSharper's *Static field or auto-property in generic type*, and CA1000 covers the neighbouring "don't declare static members on generic types" guidance) precisely because the reading is ambiguous at a glance. If you want one shared value, put it on a non-generic base or a non-generic static class:

```csharp
internal static class RepositoryStats { public static int OpenConnections; }
public abstract class Repository<T> { /* uses RepositoryStats.OpenConnections */ }
```

> 🌍 **In the real world**: a multi-tenant service had `RateLimiter<TRequest>` with `private static readonly SemaphoreSlim Gate = new(maxConcurrency)`, intended as a global concurrency cap of, say, 20 in-flight calls to a fragile downstream. It behaved for months while only two request types existed. Then a release added eleven more request types, and the effective cap became 13 × 20 — because each closed `RateLimiter<CreateOrder>`, `RateLimiter<CancelOrder>` and so on had its own semaphore. The downstream fell over during the release window and the limiter was the last place anyone looked, since "the limiter is set to 20" was true of every individual instance. Nothing in the code changed to cause it; adding *types* changed the number of static fields in existence. The rule to keep: a static field in a generic type is scoped to the closed type, so ask "is this per-`T` on purpose?" every time you write one, and move it to a non-generic holder if the answer is no.

### Shared generics, __Canon, and the generic dictionary

The earlier section says reference types "share a single specialization". Here is the actual machinery, which is what a deep interview is fishing for.

CoreCLR compiles one canonical body per generic definition covering *all* reference-type instantiations. The canonical instantiation is spelled `System.__Canon` — an internal type that stands in for "some reference type". `List<string>`, `List<object>` and `List<Order>` all execute the code compiled for `List<__Canon>`. The runtime's own design document (`docs/design/coreclr/botr/shared-generics.md` in dotnet/runtime) explains why this is safe: sharing "is currently only supported for instantiations over reference types because they all have the same size/properties/layout/etc."

The consequence is that the shared body **cannot hard-code anything about `T`**. Per the same document, "the canonical code will not have any hard-coded versions of the type handle of `List<T>`, but instead looks up the exact type handle either through a call to a runtime helper API, or by loading it up from the generic dictionary."

```
   List<string>      List<object>       List<Order>
        │                 │                  │
        ├─────────────────┼──────────────────┤
        │   ONE compiled body: List<__Canon> │
        └─────────────────┬──────────────────┘
                          │  needs T's identity? ──► generic dictionary
                          │                            for THIS instantiation
        ┌─────────────────┴──────────────────┐
   ┌────▼─────┐      ┌────▼─────┐      ┌─────▼────┐
   │ dict for │      │ dict for │      │ dict for │   an array of type handles,
   │ <string> │      │ <object> │      │ <Order>  │   method handles, entry
   └──────────┘      └──────────┘      └──────────┘   points, static-field bases
```

**A generic dictionary is**, per the design doc, "an array where the entries are instantiation-specific type handles, method handles, field handles, method entry points, etc." Slots are populated lazily: the first N hold the instantiation's type arguments, the rest start `NULL` and are filled on first use.

**What forces a dictionary lookup** in shared code — the operations that need `T`'s real identity rather than just "a reference":

- `typeof(T)`
- `new T()` (via the `new()` constraint)
- `new T[n]`, and casts like `(T)obj` or `obj is T`
- reading or writing a **static field** of the generic type — the reason statics stay per-instantiation even under shared code
- calling another generic method with `T` as an argument
- `default(T)` comparisons that route through `EqualityComparer<T>.Default`

The runtime resolves these through helpers named in the doc — `JIT_GenericHandleClass` for type dictionaries and `JIT_GenericHandleMethod` for method dictionaries — on the slow path, then caches the answer in the dictionary slot so subsequent executions are an indirect load.

**How to use this knowledge.** Two practical readings:

- The "small indirection cost" the reference-type table row mentions is *this* — a load from the dictionary, not a virtual call. It is cheap and it is per-operation-that-needs-`T`, not per-method-call. Code in a shared body that never asks about `T`'s identity (just moving references around, which is most of `List<T>`) pays nothing.
- Value-type instantiations have **no** dictionary for these purposes: `T` is baked in, so `typeof(T)` is a constant and `new T[n]` knows its element type at compile time. This is a second, less-quoted reason value-type generics are fast, alongside the absence of boxing.

**Generic virtual methods are the exception to be careful about.** A virtual method that is itself generic (`class C { public virtual void M<T>(T x); }`) cannot be dispatched through a normal vtable slot, because the set of instantiations isn't known when the vtable is laid out. The runtime resolves these through a lookup at the call site rather than a fixed slot. They are also the construct most likely to fail under Native AOT, since every reachable instantiation must be discovered statically. Prefer a non-generic virtual method taking an already-closed type, or a generic method on a non-virtual class, when you have the choice.

### The default comparer and the missing IEquatable constraint

This section connects "which constraint did I put on `TKey`" to "why is my dictionary allocating", and it is one of the highest-yield things on this page.

`Dictionary<TKey, TValue>`, `HashSet<T>`, `List<T>.Contains`, `Array.IndexOf` and most of LINQ route equality through `EqualityComparer<T>.Default`. Microsoft Learn documents precisely how that default is chosen:

> "The `Default` property checks whether type `T` implements the `System.IEquatable<T>` interface and, if so, returns an `EqualityComparer<T>` that uses that implementation. Otherwise, it returns an `EqualityComparer<T>` that uses the overrides of `Object.Equals` and `Object.GetHashCode` provided by `T`."

For a **struct that does not implement `IEquatable<T>` and does not override `Equals`/`GetHashCode`**, that "otherwise" branch lands on `System.ValueType`'s implementations. Reading `ValueType.cs` in dotnet/runtime, those are not simple:

- `ValueType.Equals(object)` first asks `CanCompareBitsOrUseFastGetHashCode`. If the struct's layout permits it, it does a raw byte comparison via `SpanHelpers.SequenceEqual`. If **not** — which is the case once the struct contains a reference field, or a `float`/`double` (because `-0.0 == 0.0` must hold and `NaN != NaN`) — it falls back to reflection: `GetType().GetFields(...)` and a per-field `Equals` call.
- The `object` parameter means the argument is **boxed** to reach it, and `Equals(object)` on a struct boxes the receiver too when reached through the non-generic path.
- `ValueType.GetHashCode` has an even sharper edge. Its slow path, per the source comment, is that "we look for the first non-static field and get its hashcode. If the type has no non-static fields, we return the hashcode of the type." A struct whose first field is low-cardinality therefore produces a low-cardinality hash — and a `Dictionary` with a low-cardinality hash degrades toward a linear scan of a bucket chain.

So the difference between these two declarations is not stylistic:

```csharp
// Boxes on comparison; reflection-based Equals if it contains a reference or float;
// hash may come from the first field alone.
public struct OrderKey
{
    public Guid TenantId;
    public int  OrderNumber;
}

// EqualityComparer<OrderKey>.Default picks the IEquatable path; the JIT can devirtualize
// and inline it; no boxing, no reflection, a hash you control.
public readonly struct OrderKey : IEquatable<OrderKey>
{
    public Guid TenantId { get; init; }
    public int  OrderNumber { get; init; }

    public bool Equals(OrderKey other) =>
        TenantId == other.TenantId && OrderNumber == other.OrderNumber;

    public override bool Equals(object? obj) => obj is OrderKey k && Equals(k);
    public override int GetHashCode() => HashCode.Combine(TenantId, OrderNumber);
}
```

**The JIT's part.** RyuJIT treats `EqualityComparer<T>.Default` as an intrinsic and can devirtualize — and then inline — the `Equals` call when `T` is a value type with a known `IEquatable<T>` implementation. That optimization has been in place since .NET Core 2.1 and applies to existing code with no source changes, which is why it is worth adding the interface rather than hand-writing a comparer: you get the fast path *and* the JIT's help.

**Which means the constraint you want on a dictionary key is usually:**

```csharp
public sealed class Cache<TKey, TValue> where TKey : notnull, IEquatable<TKey>
```

`notnull` says "null is not a key". `IEquatable<TKey>` says "comparison is cheap and correct" — and for struct keys it is the difference between the devirtualized path and the reflection path. Note that this is a *stronger* requirement than `Dictionary<,>` itself imposes (which is only `notnull`), so use it on your own types where you control the callers, not as a blanket rule.

**`record struct` gets this for free.** A `record struct` synthesizes `IEquatable<T>`, a field-wise `Equals`, and a `GetHashCode` combining all fields. If you are declaring a small key type today, `readonly record struct OrderKey(Guid TenantId, int OrderNumber);` is a one-liner that lands on the fast path. A plain `struct` does not.

> 🌍 **In the real world**: a pricing cache was keyed on `struct RateKey { public string Currency; public DateOnly Date; }` — a plain struct with a reference field. The endpoint slowed under load in a way that didn't match its query count, and a memory profile showed millions of `RateKey` boxes with nothing obviously allocating them. They came from `Dictionary` lookups: with no `IEquatable<RateKey>`, `EqualityComparer<RateKey>.Default` fell to the `ValueType` path, the `string` field disqualified the bit-comparison fast path, and every probe boxed both operands and compared fields by reflection. The hash was equally poor. Changing one line — `readonly record struct RateKey(string Currency, DateOnly Date)` — removed the boxing, the reflection, and the hash collisions together. The durable lesson is that a struct used as a dictionary key has an implicit contract with `EqualityComparer<T>.Default`, and if you don't satisfy it explicitly the runtime satisfies it for you in the slowest way available, silently.

### Constraints are not part of the signature

Three related rules that trip people up, all following from one fact: **constraints are metadata on the type parameter, not part of the method's signature.**

**1. You cannot overload on constraints.**

```csharp
public static void Handle<T>(T x) where T : class  { }
public static void Handle<T>(T x) where T : struct { }
// ✗ CS0111 — a member named 'Handle' with the same parameter types is already declared
```

Both methods are `Handle<T>(T)`. The constraint is invisible to the signature, so this is a duplicate member — not an ambiguity resolved at the call site, but a compile error at the *declaration*. Options: rename one (`HandleRef` / `HandleValue`), take different parameter types, or dispatch inside a single method with a runtime check.

This also explains why `where T : IFoo` and `where T : IBar` cannot express "either". Constraints are conjunctive: every listed constraint must hold. There is no disjunction in the language.

**2. Constraint violations are reported at the call site.** Declaring `Repo<T> where T : EntityBase` compiles fine on its own; the error appears wherever someone writes `Repo<string>`. So a constraint you add to a library type is a *source-breaking change for consumers*, discovered by them rather than by you. Adding a constraint is a breaking change; removing one is not.

**3. Constraints are inherited, not restated, on overrides — and that creates the `default` constraint.** When you override a generic virtual method, you don't repeat its constraints; the override inherits them. That is normally convenient, and occasionally ambiguous. Consider a base type with two overloads of `M<T>` that differ only in whether `T` is constrained to `struct`:

```csharp
public abstract class B
{
    public          void M<T>(T? item) where T : struct { }   // T? == Nullable<T>
    public abstract void M<T>(T? item);                       // T? == "maybe-null T"
}
```

An override written as `public override void M<T>(T? item) { }` binds to the *first* one, because with no constraint restated the compiler cannot tell which `T?` you meant. C# 9 added `where T : default` to say "the one with no `struct`/`class` constraint":

```csharp
public class D : B
{
    // Without "default", the compiler tries to override the first method in B
    public override void M<T>(T? item) where T : default { }
}
```

`where T : default` is legal **only** on a method that overrides a base method or is an explicit interface implementation. It is a disambiguator, not a constraint — it adds no requirement, it just names which inherited signature you meant. It is also the kind of detail that signals you have actually read the language reference rather than absorbed generics by osmosis.

### Generics under Native AOT and trimming

.NET 10 makes Native AOT a mainstream deployment option, and generics are where AOT and reflection collide. The mechanism is one you already know from two sections up.

- **Reference-type instantiations are fine.** All of them share one body, so the compiler only needs to emit `List<__Canon>` once and every `List<SomeClass>` works — including ones discovered by reflection at runtime.
- **Value-type instantiations must exist ahead of time.** Each one is distinct machine code. If nothing statically reachable from the entry point mentions `List<MyStruct>`, that code was never generated, and Native AOT has no JIT to generate it on demand.

So this is safe under AOT:

```csharp
Type closed = typeof(IHandler<>).MakeGenericType(someClassType);   // OK — shared body exists
```

and this throws at runtime:

```csharp
Type closed = typeof(IHandler<>).MakeGenericType(someStructType);  // may throw — no code emitted
```

The compiler tells you in advance. `MakeGenericType` and `MakeGenericMethod` are annotated `[RequiresDynamicCode]`, which produces **IL3050** ("Using member ... which has 'RequiresDynamicCodeAttribute' can break functionality when AOT compiling") at publish time. Treat IL3050 as an error, not noise — it is the only warning you get, and the failure it predicts is both intermittent and type-dependent, because reference-typed arguments will keep working and hide it.

**What to do instead:**

- Register a closed delegate per type at startup (`Dictionary<Type, Func<object, Task>>` built from explicit registrations) so the hot path is a dictionary hit, not reflection.
- Use a source generator to emit the closed instantiations — this is precisely why `System.Text.Json` has a source-generated mode, and why the generated `JsonSerializerContext` is the AOT-safe entry point.
- Where you must keep reflection, force the instantiations to exist by referencing them from statically reachable code, and verify with a real AOT publish rather than a debug run.
- Test the AOT configuration in CI. A JIT-mode test suite cannot fail this way, which is exactly why it reaches production.

Trimming has a parallel story: the trimmer removes what it can't see referenced, and reflection over generic types is invisible to it. `[DynamicallyAccessedMembers]` on the relevant parameters is how you tell the trimmer to keep members it would otherwise drop.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌──────────────────────────────────────────────────────────────┐
│            Variance — visual cheat sheet                      │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   IProducer<out T>     ← covariant (only returns T)           │
│        │                                                      │
│        ▼                                                      │
│   IProducer<Dog>     →   IProducer<Animal>     ✓ assignable   │
│   (more specific)        (less specific)                      │
│                                                               │
│                                                               │
│   IConsumer<in T>      ← contravariant (only takes T)         │
│        │                                                      │
│        ▼                                                      │
│   IConsumer<Animal>  →   IConsumer<Dog>        ✓ assignable   │
│   (less specific)        (more specific)                      │
│                                                               │
│                                                               │
│   IList<T>             ← invariant (both produce + consume)   │
│        │                                                      │
│        ▼                                                      │
│   IList<Dog>         ↔  IList<Animal>          ❌ unrelated   │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**Constraint cheat sheet — most common in real code:**

```csharp
where T : class                       // ref type only — useful for null comparisons
where T : struct                      // value type only — useful for Nullable<T>
where T : new()                       // can be instantiated with new T()
where T : IComparable<T>              // sortable
where T : INumber<T>                  // generic math
where T : EntityBase, new()           // DDD repository pattern
where TKey : notnull                  // dictionary key
where T : unmanaged                   // low-level pointer / Span<byte> stuff
```

**Method-level inference:**

```csharp
public static T Last<T>(this IEnumerable<T> source) { ... }

var nums = new List<int> { 1, 2, 3 };
int n = nums.Last();       // T inferred as int — no <int> needed
int m = nums.Last<int>();  // explicit — also legal
```

When inference fails (rare), specify explicitly. Inference looks at *argument types only*, not return-type usage.

</details>
## Common pitfalls

1. **Trying covariance on `IList<T>`.** Doesn't work — invariant. Refactor consumers to take `IEnumerable<T>` or `IReadOnlyList<T>` instead.
2. **Forgetting `where T : class` for null comparisons.** Without it, `T t = null;` doesn't compile (because `T` could be a non-nullable struct). With `where T : class`, you can compare to null.
3. **Assuming `Enum.Parse<TEnum>` is constrained to `System.Enum`.** It isn't — its constraint is `where TEnum : struct`, kept for compatibility. `Enum.Parse<int>("5")` compiles and throws `ArgumentException` at runtime. If you want the compile-time check, write your own helper constrained `where T : struct, System.Enum`. (And it is `System.Enum`, never `where T : enum` — that isn't valid syntax.)
4. **Array covariance trap.** `Animal[] a = new Dog[3]; a[0] = new Cat();` compiles, throws at runtime (`ArrayTypeMismatchException`). Use `IReadOnlyList<T>` or be explicit about target type.
5. **`where T : new()` doesn't allow ctor parameters.** Only the parameterless constructor is callable through this constraint. Use `Activator.CreateInstance` or a factory delegate for parameterized cases.
6. **Generic method with multiple constraints in wrong order.** The compiler will tell you, but the order is fixed: primary constraint (`class` / `class?` / `struct` / `unmanaged` / `notnull`, *or* a base class type such as `System.Enum`) → interfaces and other type parameters → `new()` → `allows ref struct`.
7. **Capturing a generic type parameter in a closure that crosses thread boundaries.** Combined with `Task<T>`, this can produce unexpected boxing for value types if the lambda body needs to compare to default. Profile before assuming generics are zero-cost.
8. **Generic specialization code-bloat.** Every distinct value-type instantiation is a separate compiled body. On Native AOT that lands directly in the deployable, so a library used with many struct type arguments grows the binary in a way that server-side JIT deployments never surface. Measure your own publish output — the size depends entirely on how much generic code is reachable.
9. **`allows ref struct` constraint introduced everywhere.** It is an anti-constraint: adding it removes capabilities from *your own method body* (no boxing, no `T[]`, no passing `T` to other generics). Apply it only where you actually need ref-struct type arguments.
10. **Variance only helps interfaces and delegates.** Class declarations cannot be variant — `class Box<out T>` is a compile error. If you need variance, design for an interface and have your class implement it.
11. **Expecting variance to work on value types.** `IEnumerable<int>` does not convert to `IEnumerable<object>`. Variance needs a reference conversion, and `int` → `object` is a boxing conversion. `Cast<object>()` compiles but allocates a box per element — make the method generic instead.
12. **A static field in a generic type that was meant to be global.** `static int Count` inside `Cache<T>` gives you one counter per closed type, not one overall. Move shared state to a non-generic holder class.
13. **A struct dictionary key with no `IEquatable<T>`.** `EqualityComparer<T>.Default` falls back to `ValueType.Equals`/`GetHashCode`, which boxes and — for structs containing references or floats — compares fields by reflection. Use `readonly record struct`, or implement `IEquatable<T>` by hand.
14. **`MakeGenericType` over a value type under Native AOT.** Throws at runtime because the specialization was never compiled. Reference-type arguments keep working, which hides it in testing. Heed IL3050.
15. **Trying to overload two generic methods that differ only in their constraints.** Constraints aren't part of the signature, so it's a duplicate-member error at the declaration, not an ambiguity at the call site.

## Interview-ready summary

- Generics parameterize types/methods by type. Compiler emits one definition; the JIT specializes per **value-type** `T` (separate machine code) and shares one body across **reference-type** `T`s.
- **Constraints** (`where T : ...`) are how you signal what `T` must support: `class`, `struct`, `new()`, base class, interfaces, `notnull`, `unmanaged`, `System.Enum`, `System.Delegate`, and `allows ref struct` (C# 13). Constraints are metadata on the type parameter, not part of the signature — so you can't overload on them.
- **Variance**: `out T` (covariance — producer), `in T` (contravariance — consumer), default invariant. Only on interfaces and delegates, never on classes — **and only for reference type arguments**: `IEnumerable<int>` does not convert to `IEnumerable<object>`.
- **Reference-type instantiations share one compiled body** (`System.__Canon`) and reach `T`'s identity through a per-instantiation generic dictionary. That is why static fields stay separate per closed type even when the code is shared.
- **A struct used as a dictionary key needs `IEquatable<T>`** — otherwise `EqualityComparer<T>.Default` lands on `ValueType.Equals`, which boxes and may compare by reflection. `readonly record struct` gives it to you.
- **`IEnumerable<out T>`** is the canonical covariant interface; **`Action<in T>`** the canonical contravariant delegate.
- **Generic math** (C# 11) — write one numeric algorithm via `where T : INumber<T>`; works for any numeric type.
- **Open generic registration** in DI: `services.AddScoped(typeof(IRepository<>), typeof(EfRepository<>));` — lets one registration cover all closed types.
- **`unmanaged`** unlocks low-level pointer/`Span<byte>` work; **`notnull`** is the right constraint for dictionary keys.
- **Array covariance** is unsafe legacy — `Dog[] → Animal[]` compiles but writes can throw `ArrayTypeMismatchException`. Prefer `IReadOnlyList<T>`.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Variance on `IEnumerable<T>` vs `List<T>`

> **Q**: Why is `IEnumerable<Dog>` assignable to `IEnumerable<Animal>` but `List<Dog>` is not assignable to `List<Animal>`?
>
> **A**: `IEnumerable<out T>` is declared **covariant** — `T` appears only in *output* positions (the `Current` property, the enumerator's return). Returning a `Dog` where an `Animal` is expected is always safe. `List<T>` is **invariant** because `T` also appears in *input* positions: `Add(T)`, `this[int] = T`. Permitting `List<Dog> → List<Animal>` would let a caller `.Add(new Cat())` through the wider reference, corrupting the dog-typed underlying storage.
>
> **Cross-Q**: Could the framework retrofit `IList<T>` to be covariant by changing `Add(T)` to `Add(object)`?
>
> **A**: No — it would break every existing `IList<T>` implementer and consumer, and it would push the type check to runtime (loss of compile-time safety). The actual solution the BCL took is `IReadOnlyList<out T>` (C# 4 era): a separate interface that exposes only the *read* surface, so it's safely covariant. Most modern code takes `IReadOnlyList<T>` or `IEnumerable<T>` for read-only parameters and gets covariance "for free."
>
> **Cross-Q²**: Show me the IL difference between a covariant and invariant interface that demonstrates the type-safety guarantee.
>
> **A**: In the metadata, the type parameter on `IEnumerable<T>` is marked with `+T` (the `out` flag in `GenericParamAttributes.Covariant`). `IList<T>` has no such flag (defaults to invariant). The CLR's type-equivalence checker uses this flag during assignment compatibility: covariant generics check substitutability per-parameter (Dog ↔ Animal); invariant ones check exact-match identity. The flag is metadata, not behavior — there's no runtime "covariance check" cost.

### Drill 2 — The `in T` / `out T` modifiers

> **Q**: What do `in` and `out` mean on a generic type parameter, and where is each legal?
>
> **A**: `out T` declares **covariance** — `T` may only appear in output positions (return types, get-only properties, `out` parameters). `in T` declares **contravariance** — `T` may only appear in input positions (parameters, set-only properties). The compiler enforces this positionally at the interface or delegate declaration.
>
> **Cross-Q**: Can you put both `out` and `in` modifiers in the same generic, e.g., `Func<in T, out TResult>`?
>
> **A**: Yes — that's exactly what `Func<in T, out TResult>` is. Each type parameter has its own variance. `T` is contravariant (parameter), `TResult` is covariant (return). So `Func<Animal, Dog>` is assignable to `Func<Dog, Animal>` — accepting a narrower input (Dog) and returning a wider output (Animal) is the safe transformation. That's two safe substitutions happening in one delegate.
>
> **Cross-Q²**: Why can a class never be declared variant — e.g., why is `class Box<out T>` illegal?
>
> **A**: Classes hold *state*, and state can be written to (fields, properties with setters). Allowing `Box<Dog> → Box<Animal>` would let the consumer write a `Cat` into a `Dog`-storage field through the wider reference. Variance is a property of *interface contracts*, where the compiler can verify T is used only in one direction. Classes don't have that guarantee structurally. Workaround: declare a variant *interface* and have the class implement it: `class Box<T> : IReader<T> { ... }` with `IReader<out T>`.

### Drill 3 — Array covariance

> **Q**: Are arrays in C# covariant? Is that safe?
>
> **A**: Yes, arrays are covariant — `Dog[]` IS-A `Animal[]`. **No, it is not safe.** `Animal[] arr = new Dog[3]; arr[0] = new Cat();` compiles but throws `ArrayTypeMismatchException` at runtime. Every reference-type array store incurs a hidden runtime type check, which is both unsafe (deferred from compile time) and slightly slow.
>
> **Cross-Q**: Why did the .NET designers ship this if it's unsafe?
>
> **A**: It was inherited from Java 1.0 (.NET 1.0 era — before generics existed). Without generics, there was no way to write a function that took "an array of any base-or-derived type" except via covariance. Generics shipped in .NET 2.0 (C# 2.0) and made the safe `IList<T>`-style invariant collections the right pattern. By then, array covariance was load-bearing in too many codebases to remove.
>
> **Cross-Q²**: What's the runtime cost on a tight loop writing to a `string[]` declared as `object[]`?
>
> **A**: Each `arr[i] = "x"` emits a `stelem.ref` IL instruction, and the JIT compiles it into a write preceded by a type check against the array's **actual** element type — read from the array object's method table, not from the static type of the variable. The JIT can elide the check when it can prove the element type exactly (the array was `new`d locally, or its static element type is `sealed`); for a genuine upcast it must always check. Don't quote a figure for the overhead — it's a compare-and-branch per store, so whether it's measurable depends entirely on what else the loop is doing, and an interviewer who hears "10%" will ask where you measured it. Mitigation: declare the array with its real element type, or write through a `Span<T>`, which is invariant and has no covariance check at all.

### Drill 4 — `where T : new()`

> **Q**: What does `where T : new()` constrain, and what does the compiler emit when you write `new T()`?
>
> **A**: It requires `T` to have a *public, parameterless* constructor. Roslyn does **not** emit a `newobj` — it emits `call Activator.CreateInstance<T>()`. The runtime special-cases that generic overload: for a value-type `T` it collapses to zero-initialization, and for a reference type it resolves the default constructor once and caches it. Note also that `new()` cannot be combined with `struct` or `unmanaged`, because every type satisfying those already has an accessible parameterless constructor.
>
> **Cross-Q**: Is it as fast as a direct `new SomeType()`, and how would you avoid the difference if not?
>
> **A**: Don't assert a figure — say the mechanism and then say you'd measure it. It goes through an activation path rather than a straight `newobj`, so it is not automatically inlined the way a direct constructor call is, and whether that shows up depends on how hot the path is. If a benchmark says it matters, the standard escape is to pass a factory delegate — `public T Build<T>(Func<T> factory) => factory();` — because a lambda over a concrete constructor gives the JIT something it *can* inline. DI containers use exactly this shape: they compile a factory once and never call `Activator` on the resolution path.
>
> **Cross-Q²**: Can I require a constructor with parameters? E.g., `where T : new(string)`?
>
> **A**: No — the language only allows the parameterless `new()` constraint. For parameterized construction, either (a) require a factory delegate, (b) require an interface with a static abstract `Create` method (C# 11+: `where T : IConstructable<T>` with `static abstract T Create(string)`), or (c) use `Activator.CreateInstance(typeof(T), args)` with reflection — slow and untyped. The static-abstract approach is the modern idiomatic answer.

### Drill 5 — `where T : struct` vs `where T : class` — JIT implications

> **Q**: How does the JIT treat a generic method differently when `T` is constrained to `struct` vs `class`?
>
> **A**: `where T : struct` → the JIT generates a *separate body per concrete value type* (`Method<int>`, `Method<long>`, `Method<DateTime>` are distinct machine code). Each body uses inline storage for `T`, exact `sizeof(T)`, and no boxing on interface calls (constrained call IL prefix). `where T : class` → the JIT generates *one shared body* for all reference-type Ts; `T` is treated as a pointer-sized object reference at the machine-code level.
>
> **Cross-Q**: Which is faster in a hot loop, and by how much?
>
> **A**: Answer the "which" and refuse the "how much" — the multiplier is the trap. Value-type instantiations win on three named mechanisms: elements live inline instead of as separate heap objects (better locality, no allocation), interface calls go through `constrained.` to a direct call that can then inline, and the JIT knows `sizeof(T)` so bulk operations are exact. Reference-type instantiations pay an extra indirection wherever the shared body needs `T`'s identity. How large the gap is depends on element size, loop body, and how much of the working set fits in cache, so the honest answer is "here's the mechanism, and I'd put it under BenchmarkDotNet before quoting a number." The cost on the other side is code size: one compiled body per distinct value-type `T`, which is invisible on a JIT server and directly visible in an AOT deployable.
>
> **Cross-Q²**: If I write `where T : struct, IComparable<T>`, what's special about the interface call inside the method?
>
> **A**: The compiler emits a `constrained.` IL prefix on the call to `IComparable<T>.CompareTo`. The JIT then resolves the call **directly to the struct's own `CompareTo` method** — no boxing, no virtual dispatch. This is one of the strongest reasons to add `where T : ISomeInterface` to value-type generic code: without it, calling the interface method requires boxing `T` to a heap allocation first. With it, the call is direct and often inlinable.

### Drill 6 — `where T : unmanaged`

> **Q**: What does `where T : unmanaged` enable that `where T : struct` doesn't?
>
> **A**: `unmanaged` means `T` is a value type containing **only blittable types recursively** — no references anywhere in the layout. This unlocks `sizeof(T)`, `stackalloc T[n]`, raw pointer/`Span<byte>` reinterpretation, and FFI patterns. `struct` allows any value type, including `KeyValuePair<int, string>` which has a reference field; that breaks pointer-based ops.
>
> **Cross-Q**: When would you actually use it?
>
> **A**: Three places: (1) **Serialization** — `MemoryMarshal.AsBytes(MemoryMarshal.CreateReadOnlySpan(ref t, 1))` to view a struct as raw bytes for fast serialization. (2) **Interop / P/Invoke** — passing a struct to native code via pointer. (3) **Zero-allocation buffers** — `Span<T> buf = stackalloc T[16];` for a typed buffer on the stack. Outside of perf-sensitive libraries (BCL, Kestrel, RavenDB, etc.), most code never needs it.
>
> **Cross-Q²**: Will `unmanaged` work on `Span<int>` as a generic argument?
>
> **A**: No — `Span<int>` is a `ref struct`, not an unmanaged struct. Ref structs can't be heap-allocated, can't be boxed, and can't be used as generic arguments (pre-C# 13). C# 13 added `allows ref struct` for this case. The two constraints are orthogonal: `unmanaged` is about blittable layout; `allows ref struct` is about heap-allocation discipline. You'd use them together if you wanted `T` to be a ref struct *and* containing only blittable fields — rare, but valid.

### Drill 7 — Generic specialization sharing

> **Q**: Do `List<int>` and `List<string>` share the same JIT'd method bodies?
>
> **A**: No. `List<int>` is **value-type specialized** — gets its own distinct JIT'd body with inline `int` storage. `List<string>` participates in the **reference-type shared body** — one body covers `List<string>`, `List<object>`, `List<Order>`, all reference Ts. So `List<int>` is its own machine code; `List<string>` shares code with every other ref-typed list instantiation.
>
> **Cross-Q**: What's the consequence for binary size with AOT?
>
> **A**: Each value-type `T` adds one specialization. A binary with `List<int>, List<long>, List<Guid>, List<DateTime>, List<MyValue1>, ..., List<MyValueN>` carries N+ method bodies. For native AOT (`PublishAot`), this directly grows the deployable. For mobile / IoT, this matters. The mitigation: where perf isn't critical, force `class` constraints or use `object`-typed inner storage to share the reference-type body.
>
> **Cross-Q²**: How does PGO (Profile-Guided Optimization) interact with generic specialization?
>
> **A**: Dynamic PGO collects type feedback per call site during tier-0 execution and feeds it into the tier-1 recompile. For shared reference-type bodies that's the big win: the shared code can't statically know `T`, but PGO can observe that a given call site sees `string` almost every time and emit a guarded devirtualization — a type check, an inlined `string.Equals` on the hot path, and a fallback to the virtual call otherwise. Value-type instantiations already have `T` baked in, so PGO's contribution there is the ordinary one (block layout, hot/cold splitting) rather than devirtualization. Dynamic PGO has been on by default since .NET 8; treat "and it got better in later versions" as something to say only if you can name the change.

### Drill 8 — `typeof(List<>)` vs `typeof(List<int>)`

> **Q**: What's the difference between `typeof(List<>)` and `typeof(List<int>)` at runtime?
>
> **A**: `typeof(List<>)` is the **open generic type definition** — a Type object representing the unconstructed template. `typeof(List<int>)` is the **closed constructed generic type** — a distinct Type instance with `int` substituted. They are different `Type` objects: `typeof(List<>) != typeof(List<int>)`. The open one has `IsGenericTypeDefinition = true`; the closed one has `IsConstructedGenericType = true`.
>
> **Cross-Q**: When would you use the open form?
>
> **A**: DI registration — `services.AddScoped(typeof(IRepository<>), typeof(EfRepository<>));` registers an open generic; the container constructs the closed pair lazily when something asks for `IRepository<User>`. Also reflection-based code generation — source generators iterate over `List<>` and emit closed-form code per consumer type. Anywhere you need to "register the template" without committing to a specific `T`.
>
> **Cross-Q²**: Can I get the open definition from a closed type at runtime, and vice versa?
>
> **A**: Yes — bidirectional. `typeof(List<int>).GetGenericTypeDefinition()` returns `typeof(List<>)`. `typeof(List<>).MakeGenericType(typeof(int))` returns `typeof(List<int>)`. Round-trip is exact: the runtime canonicalizes constructed generics, so `typeof(List<int>) == typeof(List<>).MakeGenericType(typeof(int))` is `true`. This is how DI containers and serializers move between open and closed forms.

### Drill 9 — `MakeGenericType`

> **Q**: When would you use `MakeGenericType`?
>
> **A**: When you have a closed type only at runtime — typically from configuration, reflection, or a generic interface where the consumer's `T` is unknown at compile time. Examples: DI containers resolving `IRepository<>` to `EfRepository<>` for the requested `T`; serializers building `Dictionary<TKey, TValue>` from JSON shape; ORMs constructing query expressions over user-defined entity types.
>
> **Cross-Q**: What's the perf cost?
>
> **A**: First call loads metadata, builds the runtime type, and may JIT bodies that don't exist yet. Subsequent calls hit the runtime's canonical-type cache and return the same `Type` instance, so it becomes a lookup. "Expensive once, then cached" is the shape; don't attach a number you haven't measured. For hot paths, pre-warm at startup. And say the AOT caveat unprompted — it's the follow-up they're waiting for: under Native AOT, `MakeGenericType` with a *value type* argument can throw at runtime because that specialization was never compiled, and the publish-time warning for it is IL3050.
>
> **Cross-Q²**: How is `MakeGenericMethod` different, and when do you need it?
>
> **A**: `MakeGenericMethod` operates on `MethodInfo` (a generic *method* definition), not `Type` (a generic *type* definition). You use it when you have a generic method like `T Process<T>(T x)` and need to invoke it with a `T` known only at runtime. Pattern: `methodInfo.MakeGenericMethod(typeof(string)).Invoke(instance, new[] { "hello" })`. Same caching story as `MakeGenericType` — first call slow, rest fast. Common in expression-tree compilation and dynamic LINQ.

### Drill 10 — Type inference failures

> **Q**: When does `Goo(x)` infer the wrong type?
>
> **A**: When the argument's *static* type doesn't match the intended `T`. The compiler infers `T` from each argument's compile-time type, not its runtime type. So `Goo(x)` where `x` is typed `object` (but actually holds an `int`) infers `T = object`, not `T = int`. The runtime then treats `T` as `object`, with all the boxing/no-specialization consequences.
>
> **Cross-Q**: Show me a concrete case.
>
> **A**: `object o = 5; var result = Echo(o);` — `T` is inferred as `object`, `result` is `object`, and inside the generic method any `T` operations treat the value as a boxed `int`. The fix: `Echo<int>((int)o)` — explicit type argument plus unbox. Even cleaner: avoid `object`-typed locals and keep `int` typed end-to-end.
>
> **Cross-Q²**: Why doesn't inference look at the *target* variable's type? `int x = Echo(o);` could constrain `T = int`.
>
> **A**: C# inference is **argument-driven**, not return-type-driven. The compiler solves the type-parameter equations from the arguments alone, then checks the result is assignable to the target. Some languages (Haskell, F#) do full bi-directional inference; C# does not, because it would complicate overload resolution and produce more ambiguous-call errors. The escape hatch is explicit type arguments. C# 12 *did* add limited target-typed inference for `new()` and collection expressions, but not for arbitrary generic method calls.

### Drill 11 — Generic method vs generic class

> **Q**: When would you write a generic method vs a generic class?
>
> **A**: Generic *class* — when you need to hold typed *state* across multiple calls: `List<T>`, `Cache<TKey, TValue>`, `Repository<T>`. The `T` is part of the type's identity. Generic *method* — when one operation needs to work for many types but the type doesn't persist: `IEnumerable<T>.Where<T>`, `Equals<T>`, `Max<T>`. The `T` lives only for the method invocation.
>
> **Cross-Q**: What if I want both — a class with a generic method?
>
> **A**: Totally legal: `public class Cache<TKey, TValue> { public T Convert<T>(TKey k) where T : ... { } }`. The class is generic in `TKey, TValue`; the method introduces its own `T` independent of those. Common pattern in serializers: `JsonSerializer.Deserialize<T>(json)` is a generic method on a non-generic class. Use this when the method's type doesn't need to be remembered by the holder.
>
> **Cross-Q²**: Can a generic method's `T` shadow the enclosing class's `T`?
>
> **A**: Yes, and the compiler warns (CS0693): "type parameter 'T' has the same name as the type parameter from outer type." It compiles, but inside the method, `T` refers to the method's parameter, not the class's. Always rename one — convention is `T` for the most-local, `TItem`/`TKey`/`TValue` for the outer. Otherwise refactoring sessions become hellish.

### Drill 12 — Multiple constraints

> **Q**: How do you write a constraint that requires `T` to implement two interfaces and have a parameterless constructor?
>
> **A**: `where T : IFoo, IBar, new()`. The order is enforced by the compiler: primary constraint (`class`/`struct`/`notnull`/etc.) first → base class → interfaces → `new()` → `allows ref struct` (C# 13). Multiple interfaces are comma-separated. There's no AND/OR — all listed constraints must hold.
>
> **Cross-Q**: Can I express "T implements `IFoo` OR `IBar`"?
>
> **A**: No — generic constraints are conjunctive only (all must hold). To express "either," you either (a) introduce a common base interface that both inherit, (b) split into two overloads with separate constraints, or (c) use a discriminated union at the call site via pattern matching. C# has discussed "constraint disjunction" in proposals, but it's not landed.
>
> **Cross-Q²**: What if `IFoo` and `IBar` both have a method `Save()` with different return types?
>
> **A**: The compiler picks the one explicitly called: `((IFoo)t).Save()` vs `((IBar)t).Save()`. If you write `t.Save()` directly and the signatures conflict (different return types), it's a compile error — ambiguous call. The resolution is explicit interface cast. Same principle as default-interface-method diamond ambiguity (CS8705) from the OOP chapter.

### Drill 13 — `default(T)` for unconstrained `T`

> **Q**: For an unconstrained `T`, what does the compiler emit for `default(T)`?
>
> **A**: The `initobj T` IL instruction — zero-initializes the memory slot reserved for `T`. For reference-type `T` at runtime, this writes `null` (8 bytes of zero). For value-type `T`, it writes `sizeof(T)` bytes of zero. Both cases are essentially free — the JIT often elides them when the slot is already zeroed.
>
> **Cross-Q**: How does this change if I add `where T : class`?
>
> **A**: The compiler emits `ldnull` instead of `initobj` — same result, but encoded as a single IL instruction. Both compile to identical machine code on modern JITs. The difference is the language *type* of `default(T)`: with `class`, it's `T?` (nullable); without, it's `T` (the value of `default` is the "default for that kind"). The NRT system uses this difference to suppress null warnings when appropriate.
>
> **Cross-Q²**: I have `public T Find<T>(int id) => found ? value : default;` with NRT enabled, and the compiler warns. Why, and how do I fix it?
>
> **A**: The warning is "possible null return for a non-nullable type" — because `T` could be a reference type (where `default(T)` is `null`) but is annotated as non-nullable. Three fixes: (1) annotate the return as `T?` — most honest, signals "may be missing." (2) Add `where T : notnull` and throw on miss — eliminates the null-return path. (3) Use `default!` to suppress — the null-forgiving operator says "trust me, callers will check." Option (1) is best; (3) is the right fallback when the framework forces a specific signature.

### Drill 14 — Generic math: `Sum<T>`

> **Q**: Write a `Sum<T>(IEnumerable<T> xs)` that works on `int`, `double`, `decimal`, and custom numeric types.
>
> **A**: 
> ```csharp
> public static T Sum<T>(IEnumerable<T> xs) where T : INumber<T>
> {
>     T total = T.Zero;
>     foreach (var x in xs) total += x;
>     return total;
> }
> ```
> The `where T : INumber<T>` constraint requires `T` implements the master numeric interface (which all BCL numeric types do, and which custom types can implement). `T.Zero` is a static abstract member, callable on the type parameter. The `+=` resolves to `IAdditionOperators<T, T, T>.operator +`, which `INumber<T>` requires.
>
> **Cross-Q**: Why not just require `IAdditionOperators<T, T, T>` since you only use `+`?
>
> **A**: That's actually the *tighter* version: `where T : IAdditionOperators<T, T, T>, IAdditiveIdentity<T, T>`. It allows custom numeric types that don't implement full `INumber<T>` (e.g., a `Money` type with only +/- semantics, no division or comparison) to use `Sum`. Best practice: constrain to the *minimum* needed. The looser constraint is more useful at the API boundary; the tighter one is correct.
>
> **Cross-Q²**: How is this compiled — does each `Sum<int>`, `Sum<double>`, etc. get its own machine code?
>
> **A**: Yes — generic math rides entirely on value-type specialization. `Sum<int>` and `Sum<double>` are distinct JIT'd bodies. The `+=` resolves through a `constrained.` call to the concrete type's `op_Addition`, which for the primitives is a single machine instruction once inlined — no virtual dispatch, no boxing. That's the point: without static abstract members the alternative was an interface call per operation, which would have made the abstraction unusable. The cost is one compiled body per numeric type instantiated. Resist quoting a percentage against a hand-written loop; the interviewer's next question is where you measured it.

### Drill 15 — Variance with delegates

> **Q**: Which way round does it go — does `Func<Dog>` work where `Func<Animal>` is expected, or the reverse? Walk me through the type-safety argument.
>
> **A**: `Func<Dog>` flows into `Func<Animal>`, not the reverse. `Func<out TResult>` is **covariant** in `TResult` because the type parameter only ever appears in the return position. A `Func<Dog>` produces a `Dog`; the caller holding it as a `Func<Animal>` expects an `Animal` back and receives a `Dog`, which is an ordinary safe upcast — every value the delegate can produce satisfies what the caller was promised. The reverse fails: a caller holding a `Func<Dog>` will assign the result to a `Dog` variable, and a `Func<Animal>` could hand back a `Cat`. The general test to say out loud: substitution is safe when every value flowing *out* of the substituted type is still acceptable to the consumer.
>
> **Cross-Q**: What about `Action<Animal>` vs `Action<Dog>` — which flows into which, and why?
>
> **A**: `Action<in T>` is **contravariant** in `T`. An `Action<Animal>` handles any Animal as input. It can substitute for `Action<Dog>` because anything that can handle any Animal can certainly handle a Dog — a Dog *is* an Animal. So `Action<Animal>` flows into `Action<Dog>` (less specific → more specific, in the parameter direction). The opposite of `Func`'s direction. Mnemonic: covariant returns are "wider OK"; contravariant parameters are "wider OK on the way in."
>
> **Cross-Q²**: Custom delegate types can be variant too — how do you declare a contravariant delegate?
>
> **A**: 
> ```csharp
> public delegate void Handler<in T>(T item);
> public delegate TResult Transform<in T, out TResult>(T item);
> ```
> Same `in` / `out` modifiers as interfaces. The compiler enforces the positional constraint: `in T` must appear only in input positions; `out T` only in output. The BCL's `Func<,>`, `Action<>`, `Predicate<>` are all declared this way. Custom delegates are rare in modern code (`Func` and `Action` cover almost every case), but the variance machinery is the same.

### Drill 16 — Boxing in generic methods

> **Q**: Does `where T : IFoo` eliminate boxing on a value-type `T`?
>
> **A**: Yes — for the duration of the generic method. The compiler emits the `constrained.` IL prefix on calls to interface members on `T`. The JIT then resolves the call directly to the struct's own method implementation — no box, no virtual dispatch. Outside the generic method (e.g., assigning `T` to an `IFoo` variable), the box happens as usual.
>
> **Cross-Q**: What's the IL look like, and how does the JIT handle it?
>
> **A**: 
> ```il
> ldarga.s    t          // address of T parameter
> constrained. !!T       // ← prefix
> callvirt    IFoo.Method
> ```
> The `constrained.` prefix tells the JIT: "if T is a value type, call the struct's method directly without boxing; if T is a reference type, box and dispatch normally." At JIT-time, with `T` known concretely (value-type specialization), the prefix resolves to a static call. Reference-type generics still take the boxing path (but only one box per call, and the JIT often eliminates it via escape analysis).
>
> **Cross-Q²**: I have `List<KeyValuePair<int, string>>` and I call `Contains(somePair)`. Does it box?
>
> **A**: Careful — this one depends on whether `KeyValuePair<TKey, TValue>` implements `IEquatable<T>`, and it does **not**. `EqualityComparer<T>.Default` checks for `IEquatable<T>` first and, per Microsoft Learn, "otherwise … returns an `EqualityComparer<T>` that uses the overrides of `Object.Equals` and `Object.GetHashCode` provided by `T`." `KeyValuePair<,>` doesn't override them either, so the comparison lands on `ValueType.Equals`, and because the struct contains a `string` reference it can't take the bit-comparison fast path — it compares fields by reflection, with boxing on the way in. The element storage stays unboxed (the `T[]` holds the pairs inline), but the *comparison* does not. This is the general senior point about generic collections: value-type elements stay unboxed through storage automatically, but staying unboxed through *equality* requires `IEquatable<T>`, and you have to put it there yourself.

### Drill 17 — Variance and value types

> **Q**: `IEnumerable<Dog>` converts to `IEnumerable<Animal>`. Does `IEnumerable<int>` convert to `IEnumerable<object>`?
>
> **A**: No. Microsoft Learn states the rule directly: "Variance applies only to reference types; if you specify a value type for a variant type parameter, that type parameter is invariant for the resulting constructed type." `IEnumerable<int>` → `IEnumerable<object>` is a compile error, even though `int` derives from `object`.
>
> **Cross-Q**: Why does the runtime draw the line there? `int` really is an `object`.
>
> **A**: Because a variance conversion has to be free. Assigning `IEnumerable<Dog>` to `IEnumerable<Animal>` emits no instructions at all — it's the same reference to the same object, and a `Dog` reference and an `Animal` reference are bit-identical in representation. Getting from `int` to `object` is a *boxing* conversion: it allocates and copies. An `IEnumerable<int>` yields raw `int`s from inline storage, so an `IEnumerable<object>` view of it would have to allocate a box per element as it enumerated — and the CLR's assignment-compatibility check has no way to inject per-element allocations into what is supposed to be a no-op cast. Variance requires an *identity-preserving or reference* conversion; boxing is neither.
>
> **Cross-Q²**: So how do I get the sequence I wanted, and what does it cost?
>
> **A**: `ints.Cast<object>()`, and say the cost in the same breath: it is a new lazy sequence that boxes one element at a time as you enumerate, and boxes again if you enumerate twice. It is not variance and it is not free. The better answer in most real code is to make the consuming method generic — `Describe<T>(IEnumerable<T> items)` — which specializes over `int` and allocates nothing. Reach for `Cast<object>` only at a boundary you don't control.

### Drill 18 — Static state in generic types

> **Q**: `class Counter<T> { public static int Count; }`. I do `Counter<string>.Count++` and `Counter<object>.Count++`. What are the two values?
>
> **A**: Both are 1. The C# standard (§15.5.2) says that "each distinct **closed constructed type** has its own set of static fields, regardless of the number of instances of the closed constructed type" — so `Counter<string>` and `Counter<object>` have separate `Count` fields, and separate static constructors that each run once.
>
> **Cross-Q**: But `Counter<string>` and `Counter<object>` share the same JIT'd machine code. How can they have different statics?
>
> **A**: That's the good version of this question. The shared body is compiled for `System.__Canon` and contains no hard-coded reference to *any* instantiation's data. Anything requiring the instantiation's identity — including the base address of its static fields — is fetched at runtime from that instantiation's **generic dictionary**, an array of type handles, method handles and field handles built per closed type. So the code is one copy and the data is many; the dictionary is precisely the indirection that makes both true at once.
>
> **Cross-Q²**: Give me a case where per-closed-type statics are the right design, and a case where they're a bug.
>
> **A**: Right: a per-type metadata cache — `static class Metadata<T> { public static readonly PropertyInfo[] Properties = typeof(T).GetProperties(); }`. Access is a static field read with the runtime's type-initializer doing the locking, which beats a `ConcurrentDictionary<Type, PropertyInfo[]>` because the lookup is resolved when the instantiation is compiled. Serializers do this. Bug: anything intended as a global — a connection counter, a rate-limiter semaphore, a circuit-breaker state — placed on a generic type. It silently becomes one per closed type, so adding a new `T` multiplies your "global" limit. Fix by moving the state to a non-generic static holder that the generic type references.

### Drill 19 — Constraints and the method signature

> **Q**: Can I write `void Handle<T>(T x) where T : class` and `void Handle<T>(T x) where T : struct` as two overloads?
>
> **A**: No — CS0111, duplicate member, reported at the *declaration*, not at any call site. Constraints are metadata attached to the type parameter; they are not part of the method's signature. Both declarations are `Handle<T>(T)`. Same reason you can't say "T implements `IFoo` **or** `IBar`" — constraints are conjunctive, and there's no disjunction in the language.
>
> **Cross-Q**: If constraints aren't part of the signature, when does a constraint violation get reported?
>
> **A**: At the call site — `Repo<string>` errors, not the declaration of `Repo<T> where T : EntityBase`. Which has a versioning consequence worth stating: **adding** a constraint to a published generic type is a source-breaking change that your consumers discover, not you. Removing one is safe. Same asymmetry as tightening a parameter type.
>
> **Cross-Q²**: What is `where T : default`, and when do you need it?
>
> **A**: C# 9, and it's a disambiguator rather than a constraint. Overrides don't restate constraints — they inherit them — which becomes ambiguous when a base type declares both `void M<T>(T? item) where T : struct` (where `T?` means `Nullable<T>`) and `void M<T>(T? item)` with no constraint (where `T?` means "maybe-null T"). An override written without a `where` binds to the first. `where T : default` says "I mean the one with neither the `struct` nor the `class` constraint." It adds no requirement and is legal only on an override or an explicit interface implementation.

</details>
## Cheat Sheet

- **Generic specialization**: each value-type `T` gets its own JIT'd code; reference types share one body.
- **`out T`**: covariant producer (`IEnumerable<out T>`); only in *output* positions.
- **`in T`**: contravariant consumer (`Action<in T>`); only in *input* positions.
- **Default invariant**: `List<T>`, `IList<T>`, classes — no implicit upcast/downcast in T.
- **Constraint order**: primary (`class`/`struct`/`unmanaged`/`notnull` or a base class) → interfaces → `new()` → `allows ref struct`.
- **`where T : unmanaged`**: enables `sizeof(T)`, `stackalloc T[n]`, pointer ops; excludes references. Not interchangeable with `struct`.
- **`where T : System.Enum` / `System.Delegate`** — never `where T : enum`, which is not valid syntax.
- **`where T : INumber<T>`** (C# 11): generic math via static abstract operators. `INumberBase<T>` is *above* `INumber<T>`; `IBinaryInteger<T>` and `IFloatingPoint<T>` are below.
- **`allows ref struct`** (C# 13): an **anti-constraint** — it widens what `T` may be, and narrows what your body may do with it.
- **DI open generics**: `AddScoped(typeof(IRepo<>), typeof(EfRepo<>))` — one line for all closed types. Says nothing about lifetime.
- **Array covariance trap**: `Dog[] → Animal[]` compiles, writes can throw `ArrayTypeMismatchException`.
- **Variance needs a reference conversion**: `IEnumerable<int>` ↛ `IEnumerable<object>`; `Cast<object>()` works but boxes per element.
- **Variance doesn't apply to delegate combination**: `+=` needs exact type identity even where assignment is variant.
- **Statics are per closed type**: `Counter<string>.Count` and `Counter<object>.Count` are different fields despite one shared body.
- **`__Canon`**: all reference instantiations share one compiled body; identity operations go through the generic dictionary.
- **Struct dictionary keys need `IEquatable<T>`** — or `EqualityComparer<T>.Default` falls to `ValueType.Equals` (boxing, sometimes reflection).
- **Constraints aren't part of the signature**: no overloading on them; violations surface at the call site; `where T : default` disambiguates overrides.
- **Native AOT**: `MakeGenericType`/`MakeGenericMethod` over *value types* can throw at runtime — publish-time warning IL3050.

## Walkthrough — `IList<Dog>` can't flow into `IList<Animal>`

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A library exposes `void NameAll(IList<Animal> animals)`. The caller has `List<Dog> dogs` and writes `NameAll(dogs);` — compile error: "cannot convert `List<Dog>` to `IList<Animal>`." The dev "fixes" it with `(IList<Animal>)(object)dogs` — runtime `InvalidCastException`.

**Diagnosis**: Read the interface declaration: `IList<T>` has both inputs (`Add(T)`, `this[int] = T`) and outputs (`this[int]`, `IndexOf`). T appears in both positions, which is why the compiler defaults to *invariant* — implicit conversion in either direction would be unsafe. Allowing `IList<Dog> → IList<Animal>` would let the callee `Add(new Cat())` to a list typed `Dog[]` — exactly the array-covariance hole.

**Fix**: If the method only *reads* animals, change the parameter to `IEnumerable<Animal>` or `IReadOnlyList<Animal>` — both are declared `out T` (covariant). `IEnumerable<Dog>` flows into `IEnumerable<Animal>` for free, no cast.

```csharp
// Before — invariant; rejects List<Dog>
void NameAll(IList<Animal> animals) { foreach (var a in animals) Console.WriteLine(a.Name); }
// After — covariant input; accepts List<Dog>, IReadOnlyList<Cat>, Animal[], etc.
void NameAll(IEnumerable<Animal> animals) { foreach (var a in animals) Console.WriteLine(a.Name); }
```

If mutation is required, the right pattern is to add or write through a non-generic-overload (`void Add<T>(T item) where T : Animal`) or take a more specific input.

**Why it works**: Variance is a type-safety contract. `out T` permits implicit upcasts because covariant interfaces only *produce* T — assigning a `Dog` to an `Animal` reference is always safe. Reading a `Dog` *as* an `Animal` is the canonical safe upcast; writing a `Cat` *into* a `Dog` collection is the canonical unsafe one.

</details>
## Self-test

<details>
<summary>1. Why does the CLR generate distinct machine code per value-type generic argument but share one body for all reference types?</summary>

Value types vary in size and layout — `Dictionary<int, V>` stores a 4-byte key inline, `Dictionary<Guid, V>` a 16-byte one — and the `ldobj` / `stobj` / `cpblk` work the generated code has to do needs the exact size, so no single body can serve both. Reference types are uniformly pointer-sized and identical in layout regardless of what they point at, which is exactly the reason the runtime's own shared-generics design document gives for sharing: instantiations over reference types "all have the same size/properties/layout/etc." One canonical body — compiled for `System.__Canon` — therefore serves every reference `T`, and anything in it that needs `T`'s real identity (`typeof(T)`, `new T[n]`, a static field, a cast) goes through that instantiation's generic dictionary. Trade-off: value-type instantiations avoid boxing and indirection but multiply code size; reference-type instantiations are compact but pay a dictionary load wherever identity is needed.
</details>

<details>
<summary>2. Apply: design a generic `Result<TError, TValue>` such that you can pass a `Result<DbError, User>` where `Result<Exception, object>` is expected.</summary>

`Result<TError, TValue>` needs `TError` covariant *out* (you only return errors, never accept) and `TValue` covariant *out* (same). Declare it as an interface: `public interface IResult<out TError, out TValue> { ... }`. With `DbError : Exception` and `User : object`, `IResult<DbError, User>` is implicitly assignable to `IResult<Exception, object>`. The class implementation `Result<TError, TValue> : IResult<TError, TValue>` itself can't be variant — only interfaces/delegates can — so callers should consume via the interface.
</details>

<details>
<summary>3. Trade-off: when does `where T : unmanaged` beat `where T : struct`?</summary>

`struct` allows any value type, including those containing references (e.g., `KeyValuePair<int, string>`). `unmanaged` is stricter — `T` must be a value type containing only blittable primitives recursively (no managed references). `unmanaged` enables `sizeof(T)`, `stackalloc T[n]`, raw `byte*` pinning, and `Span<T>` over native memory. Use `unmanaged` only when you need those — e.g., for serialization to bytes, FFI, or zero-allocation buffers. Otherwise `struct` is broader and just as performant for normal generic use.
</details>

<details>
<summary>4. Analyze: a colleague writes `class Container<out T> { public T Value { get; set; } }` and gets a compile error. Explain.</summary>

Two reasons. (1) Variance modifiers (`out`, `in`) are only allowed on interfaces and delegates — classes can never be declared variant. (2) Even on an interface, `out T` requires `T` to appear only in output positions; `Value { get; set; }` puts T in both `get` (output, OK) and `set` (input, not OK). Fix options: (a) split into `interface IReader<out T> { T Value { get; } }` and `interface IWriter<in T> { T Value { set; } }`; (b) make the class implement `IReader<T>` and add a non-generic write path. The compile error is the type system protecting you from a covariance hole.
</details>

<details>
<summary>5. You see `services.AddScoped(typeof(IValidator<>), typeof(FluentValidator<>));` in `Program.cs`. What does this do, and what's the alternative?</summary>

This is *open generic registration*. The DI container will resolve any closed `IValidator<T>` (e.g., `IValidator<CreateUserCommand>`) by constructing the matching closed `FluentValidator<CreateUserCommand>`. One line covers infinite closed types — ideal for cross-cutting interfaces like `IRepository<>`, `IValidator<>`, `INotificationHandler<>`. Alternative is per-type registration (`AddScoped<IValidator<CreateUserCommand>, ...>()`) — verbose, error-prone, but lets you swap a single specialization. Use open registration as the default; override per-type only when one specialization needs a different implementation.
</details>

## Cross-references

- **Previous: [OOP & Polymorphism](./03-oop-and-polymorphism.md)** — static abstract members, the language feature behind generic math.
- **Next: [Delegates, Events & Lambdas](./05-delegates-events-lambdas.md)** — `Func<>`, `Action<>` are generic delegates with variance.
- **[LINQ — Language Deep Dive](./06-linq-language-deep-dive.md)** — every operator is a generic extension method on `IEnumerable<T>`.
- **[Memory & Performance](./09-memory-and-performance.md)** — `Span<T>` as a generic argument (C# 13 `allows ref struct`).
- **[Data Structures](../03-data-structures.md)** — what each `Dictionary<,>`, `HashSet<>`, `Queue<>` actually is internally.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [Generics (C# guide)](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/types/generics).
- Microsoft Learn — [Covariance and contravariance](https://learn.microsoft.com/en-us/dotnet/standard/generics/covariance-and-contravariance).
- Microsoft Learn — [Generic math support](https://learn.microsoft.com/en-us/dotnet/standard/generics/math).
- Microsoft Learn — [`where` (generic type constraint)](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/keywords/where-generic-type-constraint) — the authoritative list of constraint syntax, ordering, combination rules, and the `default` constraint.
- Microsoft Learn — [Generics in the runtime](https://learn.microsoft.com/en-us/dotnet/csharp/programming-guide/generics/generics-in-the-run-time) — value-type specialization vs. reference-type sharing, in Microsoft's own words.
- Microsoft Learn — [`EqualityComparer<T>.Default`](https://learn.microsoft.com/en-us/dotnet/api/system.collections.generic.equalitycomparer-1.default) — the `IEquatable<T>`-then-`Object.Equals` selection rule that decides whether your struct keys box.
- Microsoft Learn — [`INumber<T>`](https://learn.microsoft.com/en-us/dotnet/api/system.numerics.inumber-1) — read the declaration line to get the interface hierarchy's direction right.
- C# feature specification — [Allow `ref struct` types to implement some interfaces](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/proposals/csharp-13.0/ref-struct-interfaces) — the `allows ref struct` anti-constraint and every restriction it carries.
- dotnet/runtime — [`docs/design/coreclr/botr/shared-generics.md`](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/botr/shared-generics.md) — `System.__Canon`, generic dictionaries, and the lookup helpers. The primary source for how code sharing actually works.
- dotnet/runtime — [`ValueType.cs`](https://github.com/dotnet/runtime/blob/main/src/coreclr/System.Private.CoreLib/src/System/ValueType.cs) — the bit-comparison fast path, the reflection fallback in `Equals`, and the first-field hashing comment in `GetHashCode`.
- Microsoft Learn — [Introduction to AOT warnings](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/fixing-warnings) and [IL3050](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/warnings/il3050) — why reflective generic instantiation over value types breaks under Native AOT.
- Eric Lippert's blog — [variance series](https://ericlippert.com/category/covariance-and-contravariance/) — the clearest explanation of why it works the way it does.
- Stephen Toub — *"Performance Improvements in .NET 8"* — generic specialization examples.

</details>
<!-- nav-footer-start -->

---

[← Previous: OOP & Polymorphism](03-oop-and-polymorphism.md) · [↑ Back to top](#generics--variance) · [Next: Delegates, Events & Lambdas →](05-delegates-events-lambdas.md)

<!-- nav-footer-end -->
