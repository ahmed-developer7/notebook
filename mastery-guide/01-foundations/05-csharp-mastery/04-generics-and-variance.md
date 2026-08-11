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
where T : enum                        // T is an enum
where T : Delegate                    // T is a delegate type
where T : U                           // T inherits from / implements another type parameter
where T : allows ref struct           // T may be a ref struct (C# 13)
```

**Order matters in declaration:**
1. `class` / `struct` / `notnull` / `unmanaged` / `enum` / `Delegate` (the *primary* constraint — at most one).
2. Base class.
3. Interfaces.
4. `new()`.
5. `allows ref struct` (C# 13).

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

### Generic constraints — the full catalog

Each constraint changes what the compiler will let you *do* with `T` inside the method, and changes what the JIT can *assume* when it specializes the code. Memorize the table; in interviews the cross-questions are about what each enables and what it costs.

| Constraint | What it means | What it enables inside the body | JIT / runtime effect |
|---|---|---|---|
| `where T : class` | `T` is a reference type (nullable or not) | `T t = null;` compiles; `t is null` works; `?.` works | Shared ref-type body (one specialization for all reference `T`s) |
| `where T : class?` | `T` is a possibly-nullable reference type | Same as `class` but `T` is treated as nullable for NRT analysis | Identical specialization to `class` |
| `where T : struct` | `T` is a non-nullable value type | Boxing-free interface calls (constrained call); `T?` means `Nullable<T>` | Per-`T` JIT specialization — distinct machine code per concrete value type |
| `where T : new()` | `T` has a public parameterless constructor | `new T()` compiles inside the method | Compiler emits a `call Activator.CreateInstance<T>()` — small reflection-y cost on the first call, cached after |
| `where T : SomeBaseClass` | `T` derives from `SomeBaseClass` | Use `SomeBaseClass`'s public/protected members on `T` | No code-gen change; pure compile-time check |
| `where T : ISomeInterface` | `T` implements the interface | Call interface methods on `T` directly — non-boxing for value types via *constrained call* IL | Big perf win for struct generics: `T.MethodOnInterface()` doesn't box |
| `where T : notnull` | `T` is a non-nullable type (value or reference) | `T?` is permitted in signatures; `null` literal is rejected for `T` | No code-gen change; warning surface only |
| `where T : unmanaged` | `T` is a value type containing only blittable primitives (recursive) | `sizeof(T)`, `stackalloc T[n]`, raw pointer ops, `Span<T>` over native memory | Same JIT specialization as `struct`, but the constraint is stricter — no references inside `T` |
| `where T : enum` | `T` is an enum type | `Enum.Parse<T>`, bitwise ops, `T.HasFlag` | Per-`T` specialization (enums are value types) |
| `where T : Delegate` / `MulticastDelegate` | `T` is a delegate type | `Delegate.Combine(t1, t2)`, `t.GetInvocationList()` | No code-gen change; constraint is rare |
| `where T : U` | `T` derives from / implements another type parameter `U` | Use `U`'s contract on `T`; assign `T` to a `U` variable | No code-gen change |
| `where T : allows ref struct` (C# 13) | `T` may be a ref struct (`Span<T>`, `ReadOnlySpan<T>`, etc.) | `T` is allowed as a generic argument even if it can't be boxed | The compiler enforces that the method body never boxes `T`; specialization works as normal |

**Combining multiple constraints** on one type parameter — order matters and is checked by the compiler:

```csharp
public class Repository<T>
    where T : EntityBase,          // 1. base class (at most one)
              IAuditable,           // 2. interfaces (any number)
              IComparable<T>,
              new()                 // 3. new() — must come last (except allows ref struct)
{ }

public static void Process<T>(T x)
    where T : struct,               // 1. primary (class/struct/notnull/unmanaged/enum/Delegate) — at most one
              IConvertible,         // 2. interfaces
              allows ref struct     // 3. allows ref struct — must come last (C# 13)
{ }
```

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

This is why `List<int>.Sort()` is dramatically faster than `ArrayList.Sort()` — the constrained call elides the box.

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

### Covariance and contravariance — beyond interfaces

Variance is a property of the **type parameter declaration site** — wherever C# lets you put `in` or `out`. It applies to **interfaces** and **delegates**, and shows up implicitly for **arrays**. Class declarations are never variant. Knowing the four flavors cold is a senior-level requirement.

**1. Delegate variance (`Func`, `Action`, `Predicate`, custom delegates).**

`Func<out TResult>` is covariant in its return; `Action<in T>` is contravariant in its parameter; `Func<in T, out TResult>` is both. This means a `Func<Animal>` can be assigned where a `Func<Dog>` is expected — wait, no, it's the other way:

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

**The cost** — every array store of a reference type incurs a hidden runtime type check. On `T[]` for value-type `T`, no check is needed (value types are sealed and have a fixed layout). On `T[]` for reference-type `T`, the JIT emits a check unless it can prove the array's element type matches exactly (e.g., the local variable was just `new`d with the same type).

**Workaround for performance-sensitive code** — `T[]` where `T` is a sealed class has no check. The JIT's escape-analysis can often elide checks too, but never count on it. Profile.

**4. Variance and `nullable` reference types.**

`IEnumerable<string?>` is *not* implicitly assignable to `IEnumerable<string>` even though it might seem to fit the "more permissive on input" model — because NRT analysis is *advisory*, not type-system, the compiler issues a warning (not an error) and the runtime doesn't care. Best practice: be explicit about nullability in variance-laden APIs.

### Generic specialization on the CLR

When the JIT compiles a generic type or method, its behavior diverges based on whether `T` is a **value type** or a **reference type**.

- **Reference types share a single specialization.** Code for `List<string>`, `List<object>`, and `List<Order>` is the same machine code at runtime — the JIT generates one body that operates on `object` references. This minimizes memory usage but means each ref-type `T` pays a small indirection cost.
- **Value types each get their own specialization.** `List<int>`, `List<long>`, `List<DateTime>` are distinct machine code bodies. This avoids boxing entirely (the value-type `T` is stored inline) and lets the JIT inline operations on `T`. Big perf win for hot paths.

This is why `List<int>` is dramatically faster than `ArrayList` (or boxing into `List<object>`) — and it happens automatically. The flip side: instantiating many distinct value-type generics increases code size.

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

**Devirtualization wins** — the JIT can often see "this `T` is sealed and has no overrides" and replace the constrained call with a static one. With PGO (Profile-Guided Optimization, default in .NET 8+), this happens dynamically based on observed types in production.

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

**Cost** — reflection-time construction allocates a `MethodTable`, JITs the body if not already compiled, and caches the result. First call: slow (microseconds). Subsequent: fast (cached). Pre-warm with a startup loop if hot paths depend on it.

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
| `new Box(5)` (pre-C# 12) | ✗ | Constructor type inference didn't exist |
| `new Box(5)` (C# 12+) | ✓ | Constructor type inference added |

**Methods infer; constructors historically don't** — that's why you'd see `List<int>.Add(5)` (clearly type-parameterized) but you have to write `new List<int>()` (not `new List(5)`). Pre-C# 12, the workaround was a **static factory method**:

```csharp
public static class Box
{
    public static Box<T> Create<T>(T value) => new Box<T>(value);
}

var b = Box.Create(5);          // Box<int> — factory infers; ctor wouldn't
```

C# 12 added constructor type inference, but only in limited contexts (collection expressions and target-typed `new`):

```csharp
// C# 12 — works in target-typed contexts
Box<int> b = new(5);                       // ✓ target-typed
List<int> list = [1, 2, 3];                // ✓ collection expression
// var b = new Box(5);                     // ✗ still doesn't work — needs target type
```

**Method-vs-constructor inference asymmetry — the canonical interview gotcha:**

```csharp
// Factory method — type inferred
public static Box<T> CreateBox<T>(T x) => new Box<T>(x);

var b1 = CreateBox(5);               // ✓ → Box<int>
var b2 = new Box<int>(5);            // ✓ — explicit
// var b3 = new Box(5);              // ✗ pre-C# 12 — can't infer through ctor
Box<int> b4 = new(5);                // ✓ C# 12+ target-typed
```

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
IsDefault(""));           // false (empty string ≠ null)
IsDefault((string?)null); // true
```

This handles all cases uniformly — reference, value, nullable value — without writing `if (typeof(T).IsValueType)`.

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

```csharp
INumber<T>                                  // master interface — Zero, One, Abs, ordering, etc.
├── IAdditionOperators<T, T, T>             // +
├── ISubtractionOperators<T, T, T>          // -
├── IMultiplyOperators<T, T, T>             // *
├── IDivisionOperators<T, T, T>             // /
├── IModulusOperators<T, T, T>              // %
├── IUnaryNegationOperators<T, T>           // unary -
├── IUnaryPlusOperators<T, T>               // unary +
├── IIncrementOperators<T>                  // ++
├── IDecrementOperators<T>                  // --
├── IEqualityOperators<T, T, bool>          // ==, !=
├── IComparisonOperators<T, T, bool>        // <, <=, >, >=
├── INumberBase<T>                          // numeric conversions, IsZero, IsNegative
├── IBinaryNumber<T>                        // bitwise ops, log/pow base 2
├── IFloatingPoint<T>                       // floor, ceiling, IsFinite, IsNaN
└── IBinaryInteger<T>                       // popcount, leading-zero-count, byte conversions
```

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

**Performance** — generic math is monomorphized: `Sum<int>` and `Sum<decimal>` generate separate JIT'd bodies, each with direct (often inlined) operator calls. No interface dispatch, no boxing. Often within 1-2% of a hand-written `int`-specific loop.

### `allows ref struct` (C# 13)

Before C# 13, you could not use `Span<T>`, `ReadOnlySpan<T>`, or any `ref struct` as a generic type argument — they'd violate the heap-allocation prohibition. C# 13's `allows ref struct` constraint relaxes this for code paths that don't require boxing.

```csharp
// C# 13 — generic helper that works with Span<T> and Memory<T>
public static int Count<T, TSource>(TSource source, T target) 
    where TSource : allows ref struct, IEnumerable<T>   // (illustrative — interfaces and ref struct combination still has limits)
{
    /* ... */
}

// More common: the constraint is added to a method that uses Span<T> internally.
public static bool ContainsAny<T>(Span<T> haystack, ReadOnlySpan<T> needles)
    where T : IEquatable<T>, allows ref struct
{
    foreach (var n in needles)
        if (haystack.Contains(n)) return true;
    return false;
}
```

The constraint affects what the compiler will allow inside the method (no boxing, no async, etc.). Keep it niche — most generic code doesn't need it.

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
3. **Using `where T : Enum` with `T.Parse` and getting an exception.** The constraint allows enum types, but `Enum.Parse<T>` is the typed entry point; using it without the constraint compiles but loses type safety.
4. **Array covariance trap.** `Animal[] a = new Dog[3]; a[0] = new Cat();` compiles, throws at runtime (`ArrayTypeMismatchException`). Use `IReadOnlyList<T>` or be explicit about target type.
5. **`where T : new()` doesn't allow ctor parameters.** Only the parameterless constructor is callable through this constraint. Use `Activator.CreateInstance` or a factory delegate for parameterized cases.
6. **Generic method with multiple constraints in wrong order.** Compiler will tell you, but the order is fixed: primary (`class`/`struct`/`notnull`/`unmanaged`/`enum`/`Delegate`) → base class → interfaces → `new()` → `allows ref struct`.
7. **Capturing a generic type parameter in a closure that crosses thread boundaries.** Combined with `Task<T>`, this can produce unexpected boxing for value types if the lambda body needs to compare to default. Profile before assuming generics are zero-cost.
8. **Generic specialization code-bloat.** Instantiating `Dictionary<TKey, TValue>` for 50 distinct value-type combinations triples your binary size on AOT. Profile and consolidate.
9. **`allows ref struct` constraint introduced everywhere.** Apply only where you actually use ref-struct generics. Otherwise, omit — the default invariant is fine.
10. **Variance only helps interfaces and delegates.** Class declarations cannot be variant — `class Box<out T>` is a compile error. If you need variance, design for an interface and have your class implement it.

## Interview-ready summary

- Generics parameterize types/methods by type. Compiler emits one definition; the JIT specializes per **value-type** `T` (separate machine code) and shares one body across **reference-type** `T`s.
- **Constraints** (`where T : ...`) are how you signal what `T` must support: `class`, `struct`, `new()`, base class, interfaces, `notnull`, `unmanaged`, `enum`, `Delegate`, and `allows ref struct` (C# 13).
- **Variance**: `out T` (covariance — producer), `in T` (contravariance — consumer), default invariant. Only on interfaces and delegates, never on classes.
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
> **A**: Each `arr[i] = "x"` emits a `stelem.ref` IL instruction, which the JIT compiles into a write that includes the type check. The check compares the array's `_actualElementType` to the value's runtime type. For exact matches the JIT can sometimes elide it; for upcasts (writing a `Dog` to `Animal[]`) it must always check. The overhead is 1-3 ns per store — invisible in business code, 10-30% slowdown in tight numeric/serialization loops. Mitigation: declare the array with its actual element type, or use `Span<T>` (which is invariant and has no covariance check).

### Drill 4 — `where T : new()`

> **Q**: What does `where T : new()` constrain, and what does the compiler emit when you write `new T()`?
>
> **A**: It requires `T` to have a *public, parameterless* constructor. The compiler emits a call to `Activator.CreateInstance<T>()` — which under the hood uses reflection on first call, then caches a factory delegate for subsequent calls. So `new T()` inside a generic method is slightly slower than a direct `new SomeType()` call, but the overhead is amortized.
>
> **Cross-Q**: What's the perf difference, and how would you avoid it?
>
> **A**: `Activator.CreateInstance<T>()` is roughly 30-50 ns on first call (reflection) and 5-10 ns on subsequent calls (cached delegate). A direct constructor call is sub-nanosecond when inlined. To avoid this in hot paths, pass a factory delegate: `public T Build<T>(Func<T> factory) => factory();` — the JIT can inline the lambda and the cost drops to zero. This is the standard pattern in benchmark code and in libraries like Autofac.
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
> **A**: Value-type generics are typically 2-5× faster for arithmetic-heavy code (no boxing, inline storage, devirtualized interface calls) and 1.5-2× faster for general-purpose collection operations. The trade-off is code size: a library used with 10 value-type Ts generates 10 distinct method bodies, which can balloon binary size in AOT scenarios.
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
> **A**: PGO collects type-feedback per call site. For shared reference-type generic bodies, PGO can identify the most common runtime type and inline its specific behavior — e.g., for `List<T>` where T is usually `string`, PGO can speculatively devirtualize `T.Equals` to `string.Equals`. For value-type specializations, PGO improves the per-T body's hot/cold splitting and loop unrolling. .NET 8+ has dynamic PGO on by default; .NET 9+ shipped further generic-aware tiering.

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
> **A**: First call constructs a new `MethodTable`, loads metadata, and potentially JITs the body — microseconds. Subsequent calls hit the runtime's canonical-type cache and return the same `Type` instance — nanoseconds. For hot paths, pre-warm: walk all expected closed types at startup and call `MakeGenericType` once each. Frameworks like ASP.NET Core do this implicitly during DI container build.
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
> **A**: Yes — generic math is value-type specialization. `Sum<int>` and `Sum<double>` are distinct JIT'd bodies, each with the relevant operator inlined. The `+=` becomes a direct `add` instruction (for int) or `addsd` (for double). No virtual dispatch, no boxing. Performance is within 1-2% of a hand-written non-generic loop. The IL bloat cost is real — but for math code, the speed wins.

### Drill 15 — Variance with delegates

> **Q**: Why does `Func<Animal>` work where `Func<Dog>` is expected? Walk me through the type-safety argument.
>
> **A**: `Func<out TResult>` is **covariant** in `TResult` — the type parameter only appears in the return position. So a delegate that returns `Animal` (less specific) can substitute for one expected to return `Dog` (more specific) — wait, that's backwards. Let me restate: a `Func<Dog>` returns `Dog`; you can assign it to `Func<Animal>` because every Dog *is* an Animal. The caller of `Func<Animal>` expects an Animal back, and gets a Dog — perfectly acceptable upcast. So `Func<Dog>` flows into `Func<Animal>`, not the other way.
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
> **A**: No. `List<T>.Contains` uses `EqualityComparer<T>.Default`, which is itself generic. For `T = KeyValuePair<int, string>`, the comparer is `GenericEqualityComparer<KeyValuePair<int, string>>` — a value-type specialization that calls `KeyValuePair`'s own `Equals` directly. No box on the key, no box on the equality comparison. This is one of the foundational wins of generic collections: value-type elements stay unboxed throughout the entire pipeline.

</details>
## Cheat Sheet

- **Generic specialization**: each value-type `T` gets its own JIT'd code; reference types share one body.
- **`out T`**: covariant producer (`IEnumerable<out T>`); only in *output* positions.
- **`in T`**: contravariant consumer (`Action<in T>`); only in *input* positions.
- **Default invariant**: `List<T>`, `IList<T>`, classes — no implicit upcast/downcast in T.
- **Constraint order**: primary → base → interfaces → `new()` → `allows ref struct`.
- **`where T : unmanaged`**: enables `sizeof(T)`, `stackalloc T[n]`, pointer ops; excludes references.
- **`where T : INumber<T>`** (C# 11): generic math via static abstract operators.
- **`allows ref struct`** (C# 13): permits `Span<byte>` as a generic argument.
- **DI open generics**: `AddScoped(typeof(IRepo<>), typeof(EfRepo<>))` — one line for all closed types.
- **Array covariance trap**: `Dog[] → Animal[]` compiles, writes can throw `ArrayTypeMismatchException`.

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

Value types vary in size, layout, and equality semantics — `Dictionary<int, V>` needs to know `int` is 4 bytes inline, `Dictionary<Guid, V>` needs 16 bytes; the JIT can't share IL because the GEN_LDOBJ/STOBJ instructions need exact sizes. Reference types are uniformly pointer-sized (8 bytes on x64), point to the same object header layout, and use the same `Object.Equals` until specialized — so one body works for all `T`. The trade-off: value-type generics are faster (no boxing) but increase code size; reference-type generics are smaller but pay an indirection.
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
- Eric Lippert's blog — [variance series](https://ericlippert.com/category/covariance-and-contravariance/) — the clearest explanation of why it works the way it does.
- Stephen Toub — *"Performance Improvements in .NET 8"* — generic specialization examples.

</details>
<!-- nav-footer-start -->

---

[← Previous: OOP & Polymorphism](03-oop-and-polymorphism.md) · [↑ Back to top](#generics--variance) · [Next: Delegates, Events & Lambdas →](05-delegates-events-lambdas.md)

<!-- nav-footer-end -->
