# OOP & Polymorphism

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Classes — the OOP workhorse](#classes--the-oop-workhorse)
  - [Constructors and chaining](#constructors-and-chaining)
  - [Constructor execution order — the full picture](#constructor-execution-order--the-full-picture)
  - [Primary constructors (C# 12)](#primary-constructors-c-12)
  - [Inheritance — `: base`](#inheritance---base)
  - [`virtual` / `override` / `new` / `sealed`](#virtual--override--new--sealed)
  - [Method dispatch — vtable internals](#method-dispatch--vtable-internals)
  - [Boxing, value types, and interfaces](#boxing-value-types-and-interfaces)
  - [Abstract classes vs interfaces](#abstract-classes-vs-interfaces)
  - [Default interface methods (C# 8)](#default-interface-methods-c-8)
  - [Explicit interface implementation](#explicit-interface-implementation)
  - [Static abstract members (C# 11)](#static-abstract-members-c-11)
  - [Equality, `GetHashCode`, and the records angle](#equality-gethashcode-and-the-records-angle)
  - [Liskov Substitution in code](#liskov-substitution-in-code)
  - [Reflection-based instantiation](#reflection-based-instantiation)
  - [Composition vs Inheritance — the senior verdict](#composition-vs-inheritance--the-senior-verdict)
  - [Polymorphism patterns](#polymorphism-patterns)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--virtual-call-from-base-constructor)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

C# is a multi-paradigm language but its OOP model is the most established. Every framework you'll touch (ASP.NET Core middleware, EF Core conventions, MediatR handlers, xUnit fixtures) is built around classes, inheritance, and interfaces. Senior interview questions often probe not "what is inheritance" but "when would you choose abstract over interface?" — a judgment call that requires understanding both deeply.

C# 8 added default interface methods. C# 11 added static abstract members and made interfaces effectively a substitute for abstract classes in many cases. C# 12 added primary constructors for classes. The OOP surface looks different in 2026 than it did in 2018; this file covers what's current and what each tool is genuinely *for*.

## Core concepts

### Classes — the OOP workhorse

A class is a reference type. It has fields, properties, methods, events, constructors, and finalizers, and it can inherit from one base class and implement any number of interfaces.

```csharp
public class Order
{
    // Fields (state)
    private readonly int _id;
    private decimal _total;

    // Properties (controlled access to state)
    public int Id => _id;                                  // expression-bodied, get-only
    public decimal Total                                   // full property
    {
        get => _total;
        private set => _total = value < 0 ? 0 : value;     // private setter validates
    }

    // Auto-property (compiler generates backing field)
    public string CustomerName { get; init; }

    // Constructor
    public Order(int id, string customer)
    {
        _id = id;
        CustomerName = customer;
    }

    // Method
    public void AddItem(decimal price)
    {
        if (price < 0) throw new ArgumentException(nameof(price));
        _total += price;
    }

    // Static member
    public static Order CreateEmpty(int id) => new(id, "(unknown)");
}
```

**Property forms:**

```csharp
// Auto-property
public string Name { get; set; }

// Auto-property with init (immutable after construction)
public string Email { get; init; }

// Get-only auto-property
public DateTime CreatedAt { get; }                      // assigned in ctor only

// Required (C# 11)
public required string Department { get; init; }

// Expression-bodied (computed)
public string FullName => $"{First} {Last}";

// Full property with backing field
private string _phone;
public string Phone
{
    get => _phone;
    set => _phone = value?.Replace(" ", "");
}

// Field-backed property (C# 14 — `field` keyword)
public string Notes
{
    get;
    set => field = value?.Trim() ?? string.Empty;
}
```

**Access modifiers:**
- `public` — accessible everywhere.
- `internal` — accessible within the same assembly.
- `protected` — accessible within the type and its subclasses.
- `private` — accessible only within the type (the default for class members).
- `protected internal` — protected OR internal (more permissive).
- `private protected` (C# 7.2) — protected AND internal (more restrictive — subclasses in the same assembly).
- `file` (C# 11) — visible only within the file (useful for source-generators avoiding name collisions).

### Constructors and chaining

Constructors initialize an object. A class can have multiple constructors, and one constructor can chain to another (or to a base) using `: this(...)` / `: base(...)`.

```csharp
public class HttpClientWrapper
{
    private readonly Uri _baseAddress;
    private readonly TimeSpan _timeout;

    public HttpClientWrapper(string baseAddress)
        : this(new Uri(baseAddress), TimeSpan.FromSeconds(30))
    {
        // delegates to the other ctor — body still runs after the chained call
    }

    public HttpClientWrapper(Uri baseAddress, TimeSpan timeout)
    {
        _baseAddress = baseAddress;
        _timeout = timeout;
    }
}

public class AuthenticatedHttpClient : HttpClientWrapper
{
    public AuthenticatedHttpClient(string baseAddress, string token)
        : base(baseAddress)            // chain to base class ctor
    {
        // ...
    }
}
```

**Static constructors:**

```csharp
public class Cache
{
    private static readonly Dictionary<string, byte[]> _items;

    static Cache()
    {
        // Runs once, before any static member or instance is touched.
        _items = LoadFromDisk();
    }
}
```

Static constructors run lazily on first use, are guaranteed to run exactly once per `AppDomain`, and are thread-safe by the runtime. Throwing in a static constructor disables the type for the rest of the process — be careful.

### Constructor execution order — the full picture

The exact ordering when `new DerivedDog("Rex")` executes is a classic interview cross-questioning target. Memorize it.

**The full rule** (top-down through the inheritance chain):

1. **Memory allocation** — the runtime allocates space for the most-derived type (vtable pointer + all fields, base + derived).
2. **Field initializers** (the `= value` on field declarations) run **in order from the most-derived class down to `object`** — but only the *current* class's field initializers, then the *base* class's field initializers run as part of the base constructor's invocation. The widely-misquoted rule: field initializers in a class run **before** that class's constructor body but **after** the base class's full construction.
3. **Base constructor chain** — `: base(...)` chains run before the current ctor body. Trace runs from `object` → `Animal` → `Dog`.
4. **Constructor body** of the current type runs.
5. After all that, the `new` expression returns the fully-constructed reference.

**Precise per-class order** (for one class in the chain):
- This class's field initializers (in source order).
- Base ctor (which recursively does its field initializers, then its base ctor, etc.).
- This class's ctor body.

```csharp
public class Animal
{
    public string Species = LogInit("Animal.Species init");   // step (a)
    public Animal()
    {
        Console.WriteLine("Animal ctor body");                // step (b)
    }
    static string LogInit(string m) { Console.WriteLine(m); return m; }
}

public class Dog : Animal
{
    public string Breed = LogInit("Dog.Breed init");          // step (c)
    public Dog()
    {
        Console.WriteLine("Dog ctor body");                   // step (d)
    }
    static string LogInit(string m) { Console.WriteLine(m); return m; }
}

new Dog();
// Output:
//   Dog.Breed init          ← derived field initializers run FIRST
//   Animal.Species init     ← then base field initializers
//   Animal ctor body        ← then base ctor body
//   Dog ctor body           ← then derived ctor body
```

**Why this order surprises people**: derived field initializers run *before* the base ctor body. The .NET runtime initializes fields top-down (most-derived first) so that the base ctor can see derived field values if it (foolishly) calls a virtual method that touches them. But the base ctor body itself runs *before* the derived ctor body. This split is the heart of the **"no virtual call from constructor"** anti-pattern.

**Static constructors interleaved**:
- A static ctor for a type runs the first time that type is touched (instance creation, static-field access, static-method call).
- For `new Dog()`: `Animal`'s static ctor runs first (because constructing `Dog` triggers loading `Animal`'s metadata), then `Dog`'s static ctor, then instance construction proceeds.
- Static ctors are guaranteed thread-safe by the runtime (BeforeFieldInit semantics aside) — but if a static ctor throws, the type becomes unusable for the rest of the AppDomain. `TypeInitializationException` is the wrapper.

**The "no virtual call from ctor" anti-pattern** (this is *why* the cross-questioning matters):

```csharp
public class BaseShape
{
    public BaseShape() { Render(); }                         // virtual call from base ctor
    protected virtual void Render() => Console.WriteLine("BaseShape.Render");
}

public class Circle : BaseShape
{
    private readonly double _radius;
    public Circle(double radius)
    {
        _radius = radius;                                    // ← runs AFTER base ctor
    }
    protected override void Render() => Console.WriteLine($"Circle radius={_radius}");
}

new Circle(5.0);
// Output: "Circle radius=0"
// _radius hasn't been assigned yet when base ctor calls Render()
```

The derived `Render()` is dispatched (because the vtable for `Circle` is wired up at object allocation, before any ctor runs), but the derived field `_radius` is still its default value 0.0. **Never call virtual methods from constructors.** Lint rule: CA2214.

### Primary constructors (C# 12)

C# 12 added **primary constructors for classes**, mirroring records. Parameters declared on the class header are in scope for the entire body and act as captured-by-the-class state.

```csharp
public class OrderService(IRepo repo, ILogger<OrderService> logger)
{
    public Order Get(int id)
    {
        logger.LogInformation("Fetching order {Id}", id);  // 'logger' captured
        return repo.Find(id);
    }
}
```

**Important nuances:**
- Primary-ctor parameters are **not properties**. They're implicit private fields the compiler synthesizes only for parameters that are actually captured by methods.
- They are **mutable** — you can write `repo = newRepo;` from any method (this is rarely a good idea).
- If you need a property, declare one explicitly: `public IRepo Repo { get; } = repo;`.
- Combine well with DI — most services in modern ASP.NET Core can be expressed as one-liners.

```csharp
// Idiomatic DI with primary ctor (C# 12)
public class WeatherService(IHttpClientFactory http, IMemoryCache cache)
{
    public async Task<Weather> GetAsync(string city, CancellationToken ct = default)
    {
        if (cache.TryGetValue(city, out Weather w)) return w;

        var client = http.CreateClient("weather");
        var json = await client.GetStringAsync($"/v1/{city}", ct);
        w = JsonSerializer.Deserialize<Weather>(json)!;

        cache.Set(city, w, TimeSpan.FromMinutes(5));
        return w;
    }
}
```

### Inheritance — `: base`

C# supports **single inheritance** (only one base class) and **multiple interface implementation**.

```csharp
public class Animal
{
    public string Name { get; }
    public Animal(string name) => Name = name;

    public virtual string Speak() => "...";
}

public class Dog : Animal
{
    public Dog(string name) : base(name) { }   // chain to Animal's ctor

    public override string Speak() => "Woof!";
}
```

**Why no multiple class inheritance:** C++ has it; the diamond problem (two parents share a common ancestor) creates ambiguity that C# sidestepped from day one. Multiple interface implementation handles most of the use cases without the ambiguity, and default interface methods (C# 8) cover most of the remaining ones.

### `virtual` / `override` / `new` / `sealed`

These four keywords control **method dispatch**.

**`virtual`** — base-class method that subclasses *may* override. Dispatched at runtime via the type's vtable.

**`override`** — subclass method that replaces a `virtual` (or `abstract`) base member. Same name, signature, and accessibility.

**`new`** — *hides* a base member rather than overriding. The runtime dispatches based on the *static* type of the variable, not the runtime type. Almost always wrong; the compiler warns when you forget `new`.

**`sealed`** — when applied to a class, prevents inheritance. When applied to an `override` method, prevents further override.

```csharp
public class Animal
{
    public virtual string Speak() => "...";
    public virtual string Move() => "moves";
}

public class Dog : Animal
{
    public override string Speak() => "Woof!";          // proper override
    public new string Move() => "runs";                  // hides — different static dispatch
    public sealed override string Speak() => "Woof!";   // C# would have to drop the override here too;
                                                         // shown as illustration of 'sealed override'
}

Animal a = new Dog();
Console.WriteLine(a.Speak());   // "Woof!" — virtual dispatch
Console.WriteLine(a.Move());    // "moves" — base.Move(), because 'new' hides only

Dog d = (Dog)a;
Console.WriteLine(d.Move());    // "runs" — Dog's hiding member
```

**`new` is rarely the right tool.** Mostly you want `override`. The compiler-required `new` keyword exists so that adding a `virtual` method to a base class in a future version doesn't silently break the meaning of subclass methods that happened to have the same name.

### Method dispatch — vtable internals

**The mechanism behind `virtual`/`override`/`new`.** Every reference type has a method table (vtable) — an array of function pointers. Each class lays out its vtable starting with the same slots as its base, then appends its own.

```mermaid
graph TB
    subgraph AnimalV["Animal vtable"]
        A1["[0] Speak → Animal.Speak"]
        A2["[1] Move → Animal.Move"]
        A3["[2] ToString → object.ToString"]
    end
    subgraph DogV["Dog vtable (inherits + overrides)"]
        D1["[0] Speak → Dog.Speak (override)"]
        D2["[1] Move → Animal.Move (inherited)"]
        D3["[2] ToString → object.ToString"]
        D4["[3] Fetch → Dog.Fetch (new slot)"]
    end
    AnimalV --> DogV
```

**Three dispatch flavors** in IL:

| Source | IL opcode | Dispatch |
|---|---|---|
| `animal.Speak()` (animal is `Animal`) | `callvirt Animal::Speak` | Looks up slot in *runtime* type's vtable |
| `animal.NonVirtualMethod()` | `call Animal::NonVirtualMethod` | Direct call — no vtable lookup |
| `new Animal().Move()` | `callvirt Animal::Move` (still!) | `callvirt` is also used for null-checking — even on non-virtual instance calls |
| `((Animal)d).Move()` where Dog `new`s Move | Dispatches via `Animal`'s slot | `new` doesn't add to base's slot, so `Animal.Move()` runs |
| `d.Move()` where d is `Dog`, Move is `new` | Dispatches via `Dog`'s separate slot | `Dog.Move()` runs |

**`override` semantics**: replaces the slot inherited from the base. Calls through *any* reference (base or derived) dispatch via the same slot, so the derived implementation wins.

**`new` semantics**: introduces a **separate slot** with the same name. The base's slot is unchanged. Calls through a `Base` reference hit the base's slot (base's implementation); calls through a `Derived` reference hit the derived's new slot (derived's implementation). This is **why `new` causes the dispatch ambiguity** — static type of the variable decides which slot is used.

```csharp
public class Base { public virtual void Foo() => Console.WriteLine("Base.Foo"); }
public class Derived1 : Base { public override void Foo() => Console.WriteLine("Derived1.Foo"); }
public class Derived2 : Base { public new void Foo() => Console.WriteLine("Derived2.Foo"); }

Base d1 = new Derived1();
Base d2 = new Derived2();
d1.Foo();   // "Derived1.Foo" — override replaces slot
d2.Foo();   // "Base.Foo"      — new is hidden when called through Base ref
((Derived2)d2).Foo();   // "Derived2.Foo" — but visible through Derived2 ref
```

**`sealed override`** — locks an override so further derived classes can't override it again. The JIT can then treat it as final, enabling **devirtualization** (replace the virtual call with a direct call). Same trick applies to a **`sealed class`** — all virtual calls on it can be devirtualized.

```csharp
public class Base { public virtual int Compute() => 1; }
public class Derived : Base { public sealed override int Compute() => 2; }
public class FurtherDerived : Derived { /* CAN'T override Compute() — sealed */ }
```

**Modern devirtualization** (.NET 7+):
- **Sealed types/methods** → guaranteed devirtualization (direct call, possibly inlined).
- **Whole-program analysis** in AOT → all "effectively final" types devirtualized.
- **Dynamic PGO** (Profile-Guided Optimization, on by default in .NET 8+) — speculatively devirtualizes hot virtual calls based on observed runtime types, falling back to the vtable lookup only when the guess is wrong. This makes interface and virtual calls perform like direct calls in hot loops in many real apps.

**The compiler warning (CS0108)**: if you write a method in a derived class with the same signature as a base virtual method but forget `override` *or* `new`, the compiler emits "the keyword `new` is required" warning. It compiles but treats it as `new` implicitly. **Never ignore this warning** — make the intent explicit.

### Boxing, value types, and interfaces

Value types (`struct`) can implement interfaces, but the moment you call an interface method *through the interface reference*, the runtime **boxes** the value type — copies it onto the heap and wraps it in an `object` header. This is one of the silent perf killers in hot loops, and a classic interview cross-question.

```csharp
public struct Money : IComparable<Money>
{
    public decimal Amount;
    public int CompareTo(Money other) => Amount.CompareTo(other.Amount);
}

var m = new Money { Amount = 10 };

// Path 1: through the interface — BOXES
IComparable<Money> cmp = m;            // ← box happens here
cmp.CompareTo(new Money { Amount = 20 });   // virtual interface call

// Path 2: through the struct directly — NO BOX
m.CompareTo(new Money { Amount = 20 });     // direct call, no allocation

// Path 3: through a generic constraint — NO BOX (JIT specializes)
static int CompareGeneric<T>(T a, T b) where T : IComparable<T>
    => a.CompareTo(b);
CompareGeneric(m, new Money { Amount = 20 });   // JIT generates a Money-specific version, no box
```

**The key rule**: boxing happens **at the point of conversion to the interface type**, not at the call site. If you can keep the value typed as the struct (or as `T` constrained to the interface), you avoid the box.

**`IComparable` vs `IComparable<T>`**:
- `IComparable.CompareTo(object)` — non-generic; argument is `object`, so passing a struct boxes it.
- `IComparable<T>.CompareTo(T)` — generic; argument is `T`, no box for value types.
- BCL collections like `List<T>.Sort()` use the generic version when available — that's why `List<int>.Sort()` is fast.

**`using` over a struct that implements `IDisposable`** — interesting subtle case:

```csharp
public struct ScopedTimer : IDisposable
{
    public void Dispose() { /* ... */ }
}

using (var t = new ScopedTimer()) { /* ... */ }
//      ^^^^^^^^^^^^^^^^^^^^^^ — typed as struct, NO BOX. Dispose called directly.

IDisposable d = new ScopedTimer();
using (d) { /* ... */ }
//     ^ — typed as interface; box already happened above; Dispose dispatched via box
```

Modern C# 8+ `using var` declarations preserve the struct type → no box. Old `using ((IDisposable)x)` patterns box; avoid them.

**Identity gotcha**: each box produces a *new heap object*. Reference equality between two boxes of the same struct value is `false`, even though the underlying values are equal.

```csharp
int n = 42;
object a = n;
object b = n;
ReferenceEquals(a, b);   // false! Two separate boxes
a.Equals(b);             // true — Equals checks underlying value
```

**Senior takeaway**: prefer generic methods with interface constraints (`where T : IFoo`) over methods that take `IFoo` directly. The JIT specializes per concrete `T`, avoiding the box on value types and enabling inlining.

### Abstract classes vs interfaces

The classic .NET interview question — "abstract class or interface?" — has a deceptively simple framing. Both define contracts; both can have default implementations (since C# 8); both can mandate static members (since C# 11). The real question isn't "which feature does which" but **"is this behavior, capability, or both?"**

- **Behavior with shared state** — abstract class (state demands inheritance).
- **Pure capability** — interface (capabilities are orthogonal to type identity).
- **Capability with shared default behavior** — interface with default methods (since C# 8).
- **Multiple capabilities on one type** — multiple interfaces (only interfaces compose).

Everything else is downstream of that question.

#### Decision tree

```mermaid
graph TB
    Q1{Does the contract<br/>need shared state<br/>fields, mutable props?}
    Q2{Will multiple<br/>unrelated types<br/>implement it?}
    Q3{Will it evolve<br/>over time on a<br/>public API surface?}
    Q4{Need polymorphic<br/>statics — operators,<br/>factories?}
    Q5{Any code at all<br/>shared between<br/>implementers?}

    AbstractClass[abstract class]
    Interface[interface]
    InterfaceDefault[interface + default<br/>methods, C# 8+]
    InterfaceStatic[interface + static abstract,<br/>C# 11+]

    Q1 -->|yes| AbstractClass
    Q1 -->|no| Q2
    Q2 -->|yes| Q3
    Q2 -->|no| AbstractClass
    Q3 -->|yes| InterfaceDefault
    Q3 -->|no| Q4
    Q4 -->|yes| InterfaceStatic
    Q4 -->|no| Q5
    Q5 -->|yes| InterfaceDefault
    Q5 -->|no| Interface
```

#### Comparison table

| Feature | `abstract class` | `interface` |
|---|---|---|
| Instance fields / mutable state | Yes | No (only `static` since DIM) |
| Constructors | Yes | No |
| Access modifiers on members | Yes | Yes (since C# 8) |
| Can be instantiated | No | No |
| Inheritance | Single | Multiple |
| Default method implementations | Yes (virtual / non-virtual) | Yes (since C# 8 — DIM) |
| `static abstract` members | Indirectly via abstract base | Yes (since C# 11) |
| Memory per instance | +1 vtable pointer | +1 interface map slot |
| Virtual call dispatch cost | ~1 ns (single vtable lookup) | ~2-3 ns (interface map → vtable) |
| Generic constraint usage | `where T : BaseFoo` | `where T : IFoo` (much more common) |
| Versioning — adding member | Source-breaking unless virtual w/ body | Source-breaking unless `default` body |
| Diamond problem | Avoided (single inheritance) | Possible w/ DIM; resolved by explicit impl |
| Reflection cost | Equivalent | Equivalent |

#### When to choose abstract class

- The base needs to hold **state** (fields, properties with backing values, captured dependencies).
- You want a **template method pattern** — base orchestrates, subclasses fill in specific steps.
- The "is-a" relationship is **structural and mandatory** (an `Entity` *is an* entity — it has an Id, equality semantics, domain events).
- You want to **lock down extension** with `sealed`/`internal` patterns in a single hierarchy.
- The implementers are closely related; they share *more than just the contract*.

#### When to choose interface

- You're expressing a **capability** — `IDisposable`, `IComparable<T>`, `IEnumerable<T>`. Implementations are unrelated.
- A type needs to satisfy **multiple contracts** (`Stream` is `IDisposable`, `IAsyncDisposable`, etc.).
- You're designing an **extension point** with implementations across assemblies you don't control.
- You want **evolution-friendly public APIs** (add new members with default bodies).
- You need **polymorphic statics** — `static abstract` operators or factory methods (since C# 11).
- The implementing types are unrelated and share *only the contract*.

**Modern guidance**: prefer interfaces for contracts; reach for abstract classes only when shared state genuinely demands it. Records, primary constructors, and default interface methods have made simple-base-class scenarios less compelling than they were in 2018.

#### 6 worked examples — same problem, both ways

**1. Logger — interface wins.**

```csharp
// ❌ Don't: abstract base
public abstract class LoggerBase
{
    public abstract void Log(string msg);
    public void LogError(string msg) => Log($"ERROR: {msg}");   // shared helper
}

// ✅ Do: interface with default method
public interface ILogger
{
    void Log(string msg);
    void LogError(string msg) => Log($"ERROR: {msg}");          // default helper
}
```
Why: a logger is a capability. Console / Serilog / Seq loggers have nothing structurally in common; an abstract base just blocks them from inheriting from anything else.

**2. Repository — interface for the contract; abstract base for shared SQL (optional).**

```csharp
// Contract — interface
public interface IRepository<T>
{
    Task<T?> GetByIdAsync(int id, CancellationToken ct);
    Task AddAsync(T entity, CancellationToken ct);
}

// Optional shared-SQL base — used by THIS implementation only
internal abstract class EfRepositoryBase<T> : IRepository<T> where T : class
{
    protected DbContext Db { get; }
    protected EfRepositoryBase(DbContext db) => Db = db;

    public virtual Task<T?> GetByIdAsync(int id, CancellationToken ct) =>
        Db.Set<T>().FindAsync(new object?[] { id }, ct).AsTask();

    public abstract Task AddAsync(T entity, CancellationToken ct);
}
```
Why: callers depend on the interface (testable, swappable). The base class is an *implementation detail* of the EF version — Mongo or in-memory implementations skip it.

**3. Domain entity — abstract base wins.**

```csharp
public abstract class Entity
{
    public Guid Id { get; protected set; }
    private readonly List<IDomainEvent> _events = new();

    public IReadOnlyList<IDomainEvent> DomainEvents => _events;
    protected void Raise(IDomainEvent e) => _events.Add(e);
    public void ClearEvents() => _events.Clear();

    public override bool Equals(object? obj) =>
        obj is Entity e && e.Id == Id && GetType() == e.GetType();
    public override int GetHashCode() => HashCode.Combine(Id, GetType());
}

public class Order : Entity { /* ... */ }
public class Customer : Entity { /* ... */ }
```
Why: the Id field, the events list, and the equality logic are **state**. Interfaces can't hold instance state. This is the canonical "abstract class earns its keep" scenario.

**4. HTTP handler — depends on the framework.**

```csharp
// MediatR — interface (capability + generics)
public interface IRequestHandler<TRequest, TResponse>
    where TRequest : IRequest<TResponse>
{
    Task<TResponse> Handle(TRequest request, CancellationToken ct);
}

// Razor Pages — abstract base (state: HttpContext, model binding)
public abstract class PageModel
{
    public HttpContext HttpContext { get; internal set; } = null!;
    public ModelStateDictionary ModelState { get; }
    // ... many helpers ...
}

// Minimal APIs — neither (just plain functions)
app.MapGet("/orders/{id}", (int id, IOrderService svc) => svc.GetAsync(id));
```
Why: MediatR's handler is pure capability + generic dispatch — interface. Razor Pages needs to inject framework state — abstract base. Minimal APIs sidestep both with delegate-based handlers — the most modern shape.

**5. Validation — FluentValidation's abstract base.**

```csharp
// FluentValidation chose abstract base — the rule-building DSL needs to capture state in the constructor
public class OrderValidator : AbstractValidator<Order>
{
    public OrderValidator()
    {
        RuleFor(o => o.CustomerId).GreaterThan(0);
        RuleFor(o => o.Items).NotEmpty();
    }
}
```
Why: `RuleFor(...)` mutates internal state inside `AbstractValidator<T>`. An interface couldn't hold that state. Confirmed: state-heavy DSL → abstract base.

**6. Strategy / Plugin — interface.**

```csharp
public interface IPaymentGateway
{
    Task<PaymentResult> ChargeAsync(decimal amount, string customerId, CancellationToken ct);
}

public class StripeGateway : IPaymentGateway { /* ... */ }
public class PaypalGateway : IPaymentGateway { /* ... */ }
public class MockGateway : IPaymentGateway { /* ... for tests ... */ }
```
Why: gateways are interchangeable behaviors with **no shared state** and **no kinship** between Stripe and PayPal SDKs. Trying to extract a `PaymentGatewayBase` to share code would force unnatural coupling.

#### Anti-patterns to avoid

```csharp
// ❌ ANTI-PATTERN 1: Marker interface (no members)
public interface ITransactional { }   // wrong — use an attribute

[Transactional]   // ✅ right — attribute carries the marker
public class OrderService { /* ... */ }

// ❌ ANTI-PATTERN 2: Capability disguised as inheritance
public abstract class Vehicle
{
    public abstract void Drive();
}
public class Truck : Vehicle, IDrivable { /* IDrivable has Drive() too */ }
// Drive() belongs on Vehicle OR on IDrivable, not both

// ❌ ANTI-PATTERN 3: 4+ level inheritance hierarchy
public abstract class Animal { }
public abstract class Mammal : Animal { }
public abstract class Carnivore : Mammal { }
public abstract class Cat : Carnivore { }
public class HouseCat : Cat { }
// composition + interfaces > deep hierarchies

// ❌ ANTI-PATTERN 4: Abstract class with no abstract members
public abstract class StringUtils
{
    public static string Reverse(string s) => new(s.Reverse().ToArray());
}
// just make it `static class StringUtils` — "abstract" here means nothing

// ❌ ANTI-PATTERN 5: DIM that mutates static fields
public interface IRequestCounter
{
    static int Count = 0;   // shared mutable state in an interface
    void Record() => Count++;
}
// DIM was for default behavior, not shared state. Use a regular class.
```

#### Performance — when it actually matters

| Call type | Cost | Notes |
|---|---|---|
| Direct method call (non-virtual) | ~0 ns | Inlined by JIT |
| Virtual call through abstract base | ~1 ns | Vtable lookup; CPU branch-predicts well |
| Interface call | ~2-3 ns | Interface map → vtable; less predictable |
| Generic-constrained interface call | ~0-1 ns | JIT may **devirtualize** when `T` is known |
| Sealed class virtual call | ~0 ns | JIT devirtualizes (final override) |

For 99% of app code this is irrelevant. It starts mattering in **hot loops with millions of iterations per second** — math libraries, game engines, parsing, JSON serialization. Mitigations: `sealed` keyword on concrete classes (enables devirtualization), generic constraints (`where T : IFoo`), Microsoft.Extensions.ObjectPool for allocation-free abstractions.

**.NET 8+ dynamic PGO** (Profile-Guided Optimization) further reduces interface call overhead by guessing the most common concrete type and inlining for it. The performance gap between abstract base and interface is smaller than ever.

#### Versioning trade-offs — library-author perspective

| Change | Abstract class | Interface |
|---|---|---|
| Add abstract method | **Breaks all subclasses** | **Breaks all implementers** |
| Add virtual method with body | No break | N/A |
| Add member with default body | No break (use `virtual`) | No break (use `default`) — since C# 8 |
| Add `static abstract` member | N/A | **Breaks all implementers** |
| Remove member | Breaks consumers | Breaks consumers |
| Change signature | Breaks consumers | Breaks consumers |

**Library-author rule**: when shipping a public API you'll evolve over years, **prefer interface + default methods** over abstract base. You can add new members with default implementations later without breaking downstream code.

**Application-author rule**: internal abstract classes are fine; you control all the subclasses, so the break-on-add risk is contained.

#### Common mistakes (8 senior interview red flags)

1. **`IDisposable` on contracts that don't manage resources** — bloats the contract; consumers wonder why they need `using`.
2. **Marker interface** like `ITransactional` with no members — use an attribute (queryable via reflection, no method-table overhead).
3. **God-base abstract class** — accumulating concerns into one base because "subclasses might need this." Splits cleanly into composition.
4. **Type-switching on interfaces** (`if (x is IFoo f) ...`) — usually a sign you should have added the behavior to the contract polymorphically.
5. **`new()` constraint just to call a constructor in generic code** — `static abstract` factory method (C# 11+) is cleaner.
6. **DIM calling `this.OtherMethod()`** — couples the default to implementer state in subtle ways; document the assumption or avoid.
7. **Mixing `virtual` and `abstract` without intent** — `abstract` = "must override, no default." `virtual` = "has default, can override." Make the choice deliberate.
8. **Inheritance for helper sharing** — if a base class exists just to give subclasses helper methods, extension methods or composition are usually cleaner.

#### Multi-interface composition

Interfaces compose freely; abstract classes can't:

```csharp
public class FileStream : Stream, IDisposable, IAsyncDisposable
{
    // implements Stream (abstract base, single inheritance)
    // PLUS IDisposable (capability)
    // PLUS IAsyncDisposable (capability)
}
```

The BCL is built on this pattern: pick one structural base if needed, then layer capabilities. This is why senior code review feedback often says "split this base class into two interfaces" — to free types to implement them à la carte. Cross-link: **Interface Segregation Principle** in [SOLID Principles](../02-solid-principles.md).

#### Final decision matrix

| Need | Use |
|---|---|
| Express a capability — "can do X" | **Interface** |
| Multiple unrelated types share one contract | **Interface** |
| Shared default behavior, no state | **Interface + default methods (C# 8+)** |
| Shared state + skeleton (template method) | **Abstract class** |
| "Is-a" relationship is structural / mandatory | **Abstract class** |
| Polymorphic operators or factories | **Interface + `static abstract` (C# 11+)** |
| Public-API evolution-friendly | **Interface + default methods** |
| Locking down a closed hierarchy | **Abstract class** (with `sealed`/`internal`) |
| Plugin / extension point across assemblies | **Interface** |
| Marker (no members, just a tag) | **Attribute, NOT an interface** |
| State-heavy DSL (FluentValidation, builders) | **Abstract class** |
| Generic constraint for "any type with method X" | **Interface** |

#### What to remember

> **Interface for capability. Abstract class for shared state + skeleton. Default interface methods to evolve a public API without breaking. `static abstract` when you need polymorphic statics. Composition over deep inheritance, always.**

### Default interface methods (C# 8)

Interfaces can have *default* member implementations:

```csharp
public interface ILogger
{
    void Log(string message);

    // Default method — implementers don't have to provide one
    void LogError(string message) => Log($"ERROR: {message}");

    // Default property (with backing static field)
    static int InstanceCount { get; set; } = 0;
}
```

**Why this matters:** before C# 8, adding a method to a public interface was a *breaking change* for every existing implementer. With default methods, you can ship an evolved interface without breaking consumers — they pick up the default until they choose to override.

**Caveat:** default interface methods are only callable through the interface, not through the implementing class:

```csharp
ILogger logger = new ConsoleLogger();
logger.LogError("oops");          // ✓ calls the default
((ConsoleLogger)logger).LogError("oops");  // ❌ unless ConsoleLogger overrides it explicitly
```

### Explicit interface implementation

When a class implements multiple interfaces with the same member name, or when the implementing class wants to hide an interface member from its public surface, **explicit implementation** disambiguates:

```csharp
public interface ILoader { void Load(); }
public interface ISaver { void Save(); }

public class Repo : ILoader, ISaver
{
    void ILoader.Load() => Console.WriteLine("loaded");
    void ISaver.Save() => Console.WriteLine("saved");
}

var r = new Repo();
r.Load();              // ❌ doesn't compile — Load is not on Repo's public surface
((ILoader)r).Load();    // ✓ accessed via interface
```

Use explicit implementation when:
- Two interfaces share a method name with different semantics.
- You want callers to opt into using the interface rather than calling on the concrete type (often a deliberate API choice).

### Static abstract members (C# 11)

C# 11 introduced **static abstract** members in interfaces — a member can be `static abstract`, requiring each implementing type to provide its own static implementation. This unlocks **generic math**.

```csharp
public interface IAddable<T> where T : IAddable<T>
{
    static abstract T operator +(T left, T right);
    static abstract T Zero { get; }
}

public readonly struct Money : IAddable<Money>
{
    public decimal Amount { get; }
    public Money(decimal a) => Amount = a;

    public static Money operator +(Money l, Money r) => new(l.Amount + r.Amount);
    public static Money Zero => new(0);
}

// Generic algorithm that works on any IAddable<T>
public static T Sum<T>(IEnumerable<T> items) where T : IAddable<T>
{
    T total = T.Zero;
    foreach (var item in items) total = total + item;
    return total;
}
```

The BCL ships `INumber<T>`, `IAdditionOperators<T,T,T>`, `IComparable<T>`, etc., as preferred constraints when you need generic numeric code. Deep dive in [`04-generics-and-variance.md`](./04-generics-and-variance.md).

### Equality, `GetHashCode`, and the records angle

Equality is a senior-interview minefield. The wrong implementation silently breaks `Dictionary`, `HashSet`, `Distinct()`, EF Core's change tracker, and any LINQ operator that uses default equality. The full picture:

**The four equality APIs**:

1. **`object.Equals(object)`** — virtual on `object`; the foundation. Default for reference types: reference equality (`ReferenceEquals`). Override for value semantics.
2. **`object.GetHashCode()`** — virtual on `object`; must be consistent with `Equals`. Default for reference types: based on object identity (heap address-ish).
3. **`IEquatable<T>`** — generic, strongly-typed `Equals(T)`. Avoids boxing for value types and disambiguates from `object.Equals`. BCL collections check for it.
4. **`operator ==`** — overloadable for both reference and value types. Default for ref types: reference equality; for value types: not generated by default (must overload or use records).

**The contract** (memorize this; interviewers hammer it):

```
1. Reflexive:    x.Equals(x)        == true
2. Symmetric:    x.Equals(y)        == y.Equals(x)
3. Transitive:   if x.Equals(y) && y.Equals(z), then x.Equals(z) == true
4. Consistent:   successive calls return the same result (no mutation between)
5. Null check:   x.Equals(null)     == false (for non-null x)

GetHashCode rules:
- Equal objects MUST have equal hash codes.
- Unequal objects SHOULD have different hash codes (not required, but improves performance).
- Hash code MUST NOT change while the object is in a hash-based collection.
```

**Manual implementation** (the pre-records pattern):

```csharp
public class Money : IEquatable<Money>
{
    public decimal Amount { get; }
    public string Currency { get; }

    public bool Equals(Money? other) =>
        other is not null && Amount == other.Amount && Currency == other.Currency;

    public override bool Equals(object? obj) => obj is Money m && Equals(m);

    public override int GetHashCode() => HashCode.Combine(Amount, Currency);

    public static bool operator ==(Money? l, Money? r) =>
        l is null ? r is null : l.Equals(r);
    public static bool operator !=(Money? l, Money? r) => !(l == r);
}
```

That's ~15 lines to do equality right manually. Records generate all of this automatically.

**Records (C# 9+) — equality for free**:

```csharp
public record Money(decimal Amount, string Currency);

var a = new Money(10m, "USD");
var b = new Money(10m, "USD");

a == b;            // true (value equality auto-generated)
a.Equals(b);       // true
a.GetHashCode() == b.GetHashCode();   // true

// 'with' expression for non-destructive mutation
var c = a with { Amount = 20m };
```

Records auto-generate:
- `Equals(object)` + `Equals(T)` (implements `IEquatable<T>`)
- `GetHashCode()` based on all properties
- `op_Equality` / `op_Inequality`
- `ToString()` showing all properties
- `with` expression support (clones with overrides)
- Deconstructor (`var (amount, currency) = money;`)

**Record class vs record struct**:
- `record class` (the default with `record` keyword) — reference type, heap-allocated, but with value equality semantics.
- `record struct` (C# 10+) — value type, stack-friendly, also with value equality semantics. Best for small DTOs.
- `readonly record struct` — immutable value type, perfect for keys.

**Reference equality** — `object.ReferenceEquals(a, b)` bypasses any override and checks "are these the same heap object?" Useful for:
- Cache key identity checks ("is this the *exact* instance I cached?")
- Avoiding infinite recursion in `Equals` overrides on circular graphs.

**The mutability trap**:

```csharp
var key = new MutableKey { Id = 1 };
var dict = new Dictionary<MutableKey, string> { [key] = "hello" };

key.Id = 2;                    // mutate the key AFTER adding
dict.TryGetValue(key, out _);  // FALSE — hash bucket no longer matches!
dict.Count;                    // 1 — the entry is "lost" but still occupies memory
```

**Rule**: any object used as a dictionary key MUST be immutable for the duration of its membership. Records make this trivially safe (records are immutable by default).

**Common mistakes**:
- Override `Equals` but forget `GetHashCode` → compiler warning CS0659. Listen to it.
- Override `==` but forget `Equals` → same operator, divergent results in LINQ.
- `GetHashCode` based on mutable fields → corrupted hashtables.
- Implement `IEquatable<T>` but not override `object.Equals` → boxing path uses default reference equality; non-boxed path uses your logic. Subtle inconsistency.
- `RuntimeHelpers.GetHashCode(obj)` — bypasses override; returns identity hash. Use only when you specifically need identity-based hashing (e.g., conditional weak table keys).

**Senior takeaway**: in 2026, **use `record` types for any "value-shaped" reference type** — DTOs, query results, value objects. Records eliminate ~15 lines of correct-but-tedious equality plumbing per class.

### Liskov Substitution in code

**The principle** (Barbara Liskov, 1987): if `S` is a subtype of `T`, then objects of type `T` should be replaceable with objects of type `S` without breaking the program. In English: derived classes shouldn't change the *meaning* of the base class's contract.

**Classic violation #1 — Rectangle/Square**:

```csharp
public class Rectangle
{
    public virtual int Width { get; set; }
    public virtual int Height { get; set; }
    public int Area => Width * Height;
}

public class Square : Rectangle
{
    public override int Width
    {
        get => base.Width;
        set { base.Width = value; base.Height = value; }   // sync sides
    }
    public override int Height
    {
        get => base.Height;
        set { base.Width = value; base.Height = value; }
    }
}

void StretchAndCheck(Rectangle r)
{
    r.Width = 5;
    r.Height = 10;
    Debug.Assert(r.Area == 50);   // fails when r is actually a Square — Area = 100
}
```

The `StretchAndCheck` method works on every `Rectangle` but fails on `Square` — `Square` strengthens the precondition that width and height move together. **LSP violation**.

**Fix**: don't model `Square` as a subtype of `Rectangle`. They share an abstract `IShape` (with `Area`), but `Square` and `Rectangle` are siblings.

**Classic violation #2 — Bird/Penguin**:

```csharp
public class Bird
{
    public virtual void Fly() => Console.WriteLine("Flying");
}

public class Penguin : Bird
{
    public override void Fly() => throw new NotSupportedException("Penguins can't fly");
}

void MakeAllBirdsFly(IEnumerable<Bird> birds)
{
    foreach (var b in birds) b.Fly();   // crashes on Penguin
}
```

The `Bird` contract implies "this method works." `Penguin` weakens the contract by throwing. **LSP violation**.

**Fix**: split capability from inheritance. `IFlyer` interface is implemented by `Eagle` and `Pigeon` but not `Penguin`. Or: rename `Fly` to `AttemptFly` and document that it may throw — but that's lipstick on the violation.

**Contract weakening anti-pattern** (general form):
- Derived class **strengthens preconditions** (accepts fewer inputs than base).
- Derived class **weakens postconditions** (returns less / weaker results than base).
- Derived class **throws new exception types** the base didn't declare.
- Derived class **mutates state the base wouldn't have**.

**A real-world LSP-friendly design — `IEnumerable<T>` covariance**:

```csharp
IEnumerable<Dog> dogs = new List<Dog>();
IEnumerable<Animal> animals = dogs;   // ✓ covariant — every IEnumerable<Dog> IS an IEnumerable<Animal>

void PrintAll(IEnumerable<Animal> animals)
{
    foreach (var a in animals) Console.WriteLine(a);
}
PrintAll(dogs);   // works — every Dog is an Animal, the contract is preserved
```

This works because `IEnumerable<T>` is `IEnumerable<out T>` — `T` only appears in *output* positions. Returning `Dog` where `Animal` is expected is safe (every Dog is an Animal). `List<T>` is invariant (T appears in input positions: `Add(T)`), so `List<Dog>` is NOT assignable to `List<Animal>` — preventing the unsafe `animals.Add(new Cat())` scenario. **LSP at the type-system level.**

Cross-link: [SOLID — Liskov Substitution Principle](../02-solid-principles.md) for the full essay treatment.

### Reflection-based instantiation

Reflection-based factories (`IServiceProvider`, JSON deserializers, ORMs, plugin loaders) instantiate types at runtime. Several rules and edge cases come up in senior interviews:

**`Activator.CreateInstance` — what works and what doesn't**:

```csharp
// ✅ Works: concrete class with public parameterless ctor
var u = Activator.CreateInstance(typeof(User));   // returns object; cast to User

// ✅ Works: generic helper
var u = Activator.CreateInstance<User>();          // returns User directly

// ❌ Throws MissingMethodException: abstract class
Activator.CreateInstance(typeof(EntityBase));      // "Cannot create an abstract class"

// ❌ Throws MissingMethodException: interface
Activator.CreateInstance(typeof(IRepository));     // "Cannot create an instance of an interface"

// ❌ Throws MissingMethodException: no public parameterless ctor
class Locked { private Locked() {} }
Activator.CreateInstance(typeof(Locked));          // unless you pass nonPublic: true

// ✅ Works with private ctor + nonPublic: true
Activator.CreateInstance(typeof(Locked), nonPublic: true);

// ✅ Works with ctor arguments
Activator.CreateInstance(typeof(User), new object[] { "Ahmed", 30 });

// ✅ Works on open generics if you provide type args first
var listType = typeof(List<>).MakeGenericType(typeof(int));
var list = Activator.CreateInstance(listType);
```

**`ConstructorInfo.Invoke`** — more control:

```csharp
var ctor = typeof(User).GetConstructor(new[] { typeof(string) });
if (ctor is null) throw new InvalidOperationException("No matching ctor");
var u = ctor.Invoke(new object[] { "Ahmed" });
```

**Common bug**: `GetConstructor` returns `null` when the signature doesn't match — common after a ctor change in upstream code that breaks reflection-based factories silently. Always null-check and throw a clear error.

**Generic `new()` constraint**:

```csharp
public static T CreateDefault<T>() where T : new()
{
    return new T();   // OK
}

CreateDefault<User>();           // ✓
CreateDefault<int>();            // ✓ (all value types have implicit parameterless ctor)
CreateDefault<EntityBase>();     // ✗ compile error — abstract type doesn't satisfy new()
CreateDefault<IRepository>();    // ✗ compile error — interface doesn't satisfy new()
```

Under the hood, `new T()` in a generic method uses `Activator.CreateInstance<T>()`. Modern JIT specializes per concrete `T`, so the cost is near-zero for reference types.

**DI containers** (`Microsoft.Extensions.DependencyInjection`):
- Uses constructor reflection + parameter resolution.
- Picks the constructor with the most parameters it can satisfy from the container.
- Cannot instantiate abstract types or interfaces directly — they must be **registered** against a concrete implementation:
  ```csharp
  services.AddScoped<IRepository, EfRepository>();   // map interface to concrete
  ```
- Cannot resolve types with private constructors unless registered as factory functions:
  ```csharp
  services.AddScoped<Locked>(_ => Locked.Create());
  ```

**Cross-question gotcha**: "Why can't DI just call `Activator.CreateInstance(typeof(IRepository))`?" Because interfaces have no implementation — there's nothing to allocate. Reflection has the same constraint. The container *must* be told which concrete type to use.

**`Type.IsAbstract` / `Type.IsInterface`** — runtime checks to avoid the MissingMethodException:

```csharp
public static object SafeCreate(Type t)
{
    if (t.IsAbstract) throw new ArgumentException($"{t.Name} is abstract");
    if (t.IsInterface) throw new ArgumentException($"{t.Name} is interface");
    return Activator.CreateInstance(t) ?? throw new InvalidOperationException();
}
```

### Composition vs Inheritance — the senior verdict

**The principle**: *favor composition over inheritance*. Gang of Four (1994), still true in 2026. Inheritance creates tight coupling between base and derived; composition lets behavior vary at runtime and across types that don't share an "is-a" relationship.

**When inheritance IS the right tool**:
- Genuine "is-a" relationship with shared state — domain `Entity`, ASP.NET Core `PageModel`, EF Core's `DbContext`.
- Framework-mandated bases (Razor Pages, MVC controllers).
- Sealed final-form hierarchies with no extension needs (e.g., DDD value objects).

**When composition wins** (the 95% case):
- "Has-a" / "uses-a" / "depends-on" relationships.
- Behavior that should be swappable at runtime (Strategy pattern).
- Behavior shared across unrelated types (e.g., logging, caching, retry).
- Anything that might need to vary independently from the type hierarchy.

**Worked refactor — inheritance → composition**:

**Before** (inheritance-heavy):

```csharp
public abstract class LoggerBase
{
    protected abstract void WriteRaw(string line);

    public void Info(string msg) => WriteRaw($"[INFO] {msg}");
    public void Error(string msg) => WriteRaw($"[ERROR] {msg}");
}

public class ConsoleLogger : LoggerBase
{
    protected override void WriteRaw(string line) => Console.WriteLine(line);
}

public class FileLogger : LoggerBase
{
    private readonly string _path;
    public FileLogger(string path) => _path = path;
    protected override void WriteRaw(string line) => File.AppendAllText(_path, line + "\n");
}

// Problems:
// - Can't write to BOTH console AND file (single inheritance).
// - Can't reuse FileLogger logic in a different log format.
// - Subclasses are coupled to LoggerBase's level-prefix format.
```

**After** (composition):

```csharp
public interface IWriter { void Write(string line); }

public class ConsoleWriter : IWriter
{
    public void Write(string line) => Console.WriteLine(line);
}

public class FileWriter : IWriter
{
    private readonly string _path;
    public FileWriter(string path) => _path = path;
    public void Write(string line) => File.AppendAllText(_path, line + "\n");
}

public class CompositeWriter : IWriter
{
    private readonly IWriter[] _writers;
    public CompositeWriter(params IWriter[] writers) => _writers = writers;
    public void Write(string line) { foreach (var w in _writers) w.Write(line); }
}

public class Logger
{
    private readonly IWriter _writer;
    public Logger(IWriter writer) => _writer = writer;
    public void Info(string msg) => _writer.Write($"[INFO] {msg}");
    public void Error(string msg) => _writer.Write($"[ERROR] {msg}");
}

// Now you can:
var multi = new Logger(new CompositeWriter(new ConsoleWriter(), new FileWriter("app.log")));
// — write to BOTH console and file without changing Logger.
```

**The senior signal**: when you see a hierarchy more than 2 levels deep, ask "could this be composition?" Almost always yes. The Decorator pattern is the canonical example of composition replacing inheritance.

**The exceptions** (when not to compose):
- The "wrapper" composition would just be ceremony — e.g., a `DomainEntity` is meaningfully a kind of entity; making `HasId` a separate component is over-engineering.
- Framework requires you inherit (you can't avoid `PageModel` if you're using Razor Pages).
- Performance: composition adds one indirection per call; in microsecond-sensitive code, inheritance may marginally win (rare in modern .NET).

Cross-link: [Design Patterns](../01-net-core-deep-dive/08-patterns-and-best-practices.md) — Decorator, Strategy, Composite all replace inheritance with composition.

### Polymorphism patterns

C# OOP gives you many ways to express "different behavior under the same call." The five most common in real code:

1. **Virtual override** (`Speak()` in the example above) — straight inheritance dispatch.
2. **Strategy pattern** — inject an interface, swap implementations at runtime.
   ```csharp
   public interface ITaxCalculator { decimal Calculate(decimal subtotal); }
   public class CartService(ITaxCalculator tax) { /* ... */ }
   // Compose with USTaxCalculator, EUVATCalculator, etc.
   ```
3. **Template method** — abstract class defines the skeleton; subclasses fill in steps.
   ```csharp
   public abstract class Pipeline
   {
       public void Run() { Setup(); Execute(); Teardown(); }
       protected abstract void Execute();
       protected virtual void Setup() { }
       protected virtual void Teardown() { }
   }
   ```
4. **Pattern matching dispatch** — type switch over a closed set of subtypes (often records).
   ```csharp
   public abstract record Shape;
   public record Circle(double R) : Shape;
   public record Square(double S) : Shape;

   double Area(Shape s) => s switch
   {
       Circle c => Math.PI * c.R * c.R,
       Square q => q.S * q.S,
       _ => throw new ArgumentException()
   };
   ```
5. **Static abstract / generic dispatch** — compile-time monomorphization, no virtual call cost. Used for high-perf code (numeric algorithms, parsers).

Each fits a niche. For new code, prefer **strategy** for runtime variation, **pattern matching** for closed hierarchies (especially with records), and **template method** when shared scaffolding genuinely justifies an abstract class.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌──────────────────────────────────────────────────────────────┐
│        Method Dispatch: virtual / override / new              │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Animal a = new Dog();                                        │
│       │                                                       │
│       ├── a.Speak()  ← virtual                                │
│       │   ├─→ Lookup vtable on actual type (Dog)              │
│       │   └─→ Calls Dog.Speak()                               │
│       │                                                       │
│       ├── a.Move()   ← 'new' (hides)                          │
│       │   ├─→ Static type is Animal                           │
│       │   └─→ Calls Animal.Move()                             │
│       │                                                       │
│       ├── a.Eat()    ← non-virtual base method                │
│       │   └─→ Calls Animal.Eat() (no override possible)       │
│                                                               │
│  Dog d = (Dog)a;                                              │
│       └── d.Move()   ← 'new' (hides)                          │
│           ├─→ Static type is Dog                              │
│           └─→ Calls Dog.Move()                                │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**Diamond avoided via interfaces:**

```
        Animal               <- abstract / virtual base
       /      \
      /        \
    Dog       Cat
      \        /
       \      /
        ???              <- multiple inheritance not allowed in C#

vs.

   IBarker      IPurrer    <- two interfaces
       \        /
        \      /
         Pet              <- one class, both interfaces
```

</details>
## Common pitfalls

1. **Forgetting `override`.** Without it, the compiler warns and your method *hides* the base; the polymorphism you expected silently doesn't happen. Always explicit `override` or `new`.
2. **Calling virtual methods from a constructor.** During base-class construction, the runtime type is the derived class but its fields aren't initialized yet. The virtual call dispatches to the derived override, which may use uninitialized fields. Avoid.
3. **Sealing too early.** Sealing a class is a backward-compat decision; if a future caller needs to subclass, you've blocked them. Default to `sealed` only for types that genuinely shouldn't be extended (records, value-like classes).
4. **Public fields instead of properties.** Hard to evolve. Adding validation, lazy loading, or notifications later requires changing every caller. Always use properties.
5. **Overriding `Equals` without `GetHashCode`.** A type with a custom `Equals` but default `GetHashCode` breaks dictionaries, hash sets, etc. Always override both (or neither).
6. **Treating an interface like a base class.** Default interface methods are not virtual in the same sense; they're only invokable through the interface type. If you need full polymorphic dispatch via a class reference, use an abstract class.
7. **Multiple inheritance of state via interfaces with default methods.** It's tempting to put a default method that uses an abstract property, but interfaces cannot have backing state. The implementing class still owns all state.
8. **Primary constructor parameters captured by surprise.** If you write `public class S(IRepo repo) { /* never use repo */ }`, the compiler doesn't allocate a backing field. But adding `public IRepo Repo => repo;` later silently introduces a hidden field. For clarity in shared code, declare explicit properties: `public IRepo Repo { get; } = repo;`.
9. **Mutating primary-ctor parameters.** They're mutable variables, not read-only fields. `repo = null;` from anywhere in the class compiles. Treat them as readonly by convention or assign to a `readonly` field.
10. **`static abstract` member without a corresponding generic constraint.** Static abstracts are only callable through generic code with the constraint `where T : ITheInterface<T>`. Without that, you can't reach `T.OperatorPlus`. Pair them.

## Interview-ready summary

- C# supports **single class inheritance** + **multiple interface implementation**.
- **`virtual` / `override`** = polymorphic dispatch via vtable. **`new`** hides — almost always wrong.
- **Abstract class** = state + shared skeleton + single inheritance. **Interface** = capability + multiple inheritance + (since C# 8) default methods.
- **Default interface methods** (C# 8) let you evolve interfaces without breaking implementers; only callable through the interface type.
- **Static abstract members** (C# 11) enable generic math via constraints like `where T : INumber<T>`.
- **Primary constructors for classes** (C# 12) — class-header parameters captured by methods; not auto-properties; mutable; idiomatic for DI services.
- **`required`** (C# 11) forces caller to set in object initializer or constructor; works with `init` for "required immutable."
- **Five polymorphism patterns**: virtual override, strategy (inject interface), template method (abstract class skeleton), pattern matching (records + switch), static abstract / generic.
- **Override `Equals`? Override `GetHashCode`.** Always together.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Abstract class vs interface

> **Q**: When would you choose an abstract class over an interface?
>
> **A**: When the contract needs to hold instance state (fields, mutable properties, captured dependencies) or share template-method skeleton logic across implementers that share a structural "is-a" relationship.
>
> **Cross-Q**: Since C# 11 added `static abstract` and C# 8 added default interface methods, can't interfaces do everything abstract classes can now?
>
> **A**: Almost. Interfaces still **cannot hold instance state** — only `static` fields via DIM. Abstract classes can hold instance fields and have constructors that initialize them. For state-carrying contracts (domain `Entity` with Id and domain-events list, framework-mandated bases like `PageModel`), abstract class is still the right answer. Everything else is interface territory.
>
> **Cross-Q²**: If two interfaces both define a default `Log()` method and a class implements both, which one runs?
>
> **A**: Neither — the compiler errors out with CS8705 (diamond ambiguity). You must disambiguate via explicit interface implementation: `void IReader.Log() => ...; void IWriter.Log() => ...;` and a public `Log()` if you want it accessible on the class itself. The class then has three distinct methods that callers reach via the interface they hold a reference to.

### Drill 2 — Constructor execution order

> **Q**: In `new Dog("Rex")` where `Dog : Animal : object`, what's the exact execution order?
>
> **A**: Memory allocation → `Dog`'s field initializers → `Animal`'s field initializers → `object`'s ctor body → `Animal`'s ctor body → `Dog`'s ctor body.
>
> **Cross-Q**: If `Animal`'s ctor calls a virtual method `Render()` that `Dog` overrides, and `Dog`'s `Render()` reads a field that `Dog`'s ctor body would initialize, what happens?
>
> **A**: `Dog.Render()` runs (the vtable was wired up at allocation), but the field is at its default value because `Dog`'s ctor body hasn't run yet. This is the **"no virtual call from constructor"** anti-pattern — flagged by CA2214. The standard fix: don't call virtuals from ctors; initialize in a `protected virtual OnInitialized()` that callers invoke after construction.
>
> **Cross-Q²**: What if `Animal` has a static constructor that throws?
>
> **A**: First access to `Animal` triggers the static ctor; the throw becomes `TypeInitializationException`. Worse: the type is marked **broken for the rest of the AppDomain** — every subsequent attempt to use it (including subclassing `Dog`) throws immediately. Static-ctor exceptions are unrecoverable, which is why static-ctor logic must be bulletproof (no I/O, no config access, no allocation that could OOM).

### Drill 3 — Virtual dispatch

> **Q**: Walk me through `Animal a = new Dog(); a.Speak();` where `Animal.Speak` is virtual and `Dog` overrides it.
>
> **A**: The IL emits `callvirt Animal::Speak`. At runtime, the JIT looks up the `Speak` slot in the *runtime* type's vtable — which for `Dog` points to `Dog.Speak`. So `Dog.Speak()` runs, even through an `Animal` reference. That's polymorphism.
>
> **Cross-Q**: What changes if `Dog` uses `new void Speak()` instead of `override`?
>
> **A**: `new` introduces a *separate slot* in `Dog`'s vtable, not replacing the inherited slot. Calling `a.Speak()` (through `Animal` reference) dispatches via `Animal`'s slot → `Animal.Speak`. Calling `((Dog)a).Speak()` dispatches via `Dog`'s separate slot → `Dog.Speak`. This is **why `new` causes "which one runs?" ambiguity** — the answer depends on the variable's static type, not the object's runtime type.
>
> **Cross-Q²**: If I `sealed override Speak()` in `Dog`, what does the JIT do?
>
> **A**: The JIT knows no further class can override `Speak()`, so it can **devirtualize** the call — replace `callvirt` with a direct `call Dog::Speak`, and potentially inline the body. In a hot loop, that's a measurable perf win (1-3 ns saved per call, plus the inlined code can be further optimized). Same trick applies to `sealed class Dog` — all virtual calls on `Dog` references can be devirtualized.

### Drill 4 — Boxing on value types

> **Q**: Does this code box? `Money m = new Money(); IComparable<Money> c = m; c.CompareTo(...)`.
>
> **A**: Yes. The assignment `IComparable<Money> c = m` boxes `m` — copies the struct to a new heap object wrapped in an `object` header. Subsequent `c.CompareTo` is a virtual interface call on the boxed object.
>
> **Cross-Q**: How would you call `CompareTo` on a value type without boxing?
>
> **A**: Two ways. (1) Call it through the struct type directly: `m.CompareTo(other)` — direct call, no box. (2) Pass through a generic method with an interface constraint: `static int Cmp<T>(T a, T b) where T : IComparable<T> => a.CompareTo(b);` — the JIT specializes per concrete `T`, so for `T = Money` it generates a Money-specific method with no box.
>
> **Cross-Q²**: Why does `List<int>.Sort()` not box, but `ArrayList.Sort()` does?
>
> **A**: `List<int>` is `List<T>` specialized for `int`. Its `Sort()` uses `Comparer<int>.Default`, which in turn uses `IComparable<int>.CompareTo(int)` — non-boxing generic interface call. `ArrayList` stores `object` references, so every element is already boxed when added. Its `Sort()` uses the non-generic `IComparable.CompareTo(object)`, which works on the boxed values. **`List<T>` is one of the strongest reasons to never use `ArrayList` in modern .NET.**

### Drill 5 — Equality

> **Q**: When should you override `Equals` on a class?
>
> **A**: When the class represents a "value" — equal-by-content rather than equal-by-identity. Examples: money, dates, value objects, immutable DTOs. For "entity" classes (Person with Id), reference equality is usually correct because two `Person(Id=42)` instances *should* be considered the same entity but you want to know if they're the same object reference.
>
> **Cross-Q**: What's the `GetHashCode` contract?
>
> **A**: Equal objects MUST have equal hash codes. Unequal objects SHOULD have different hash codes (not required, but improves dictionary perf). Hash code MUST NOT change while the object is in a hash-based collection (mutating a key after `Add` corrupts the dictionary — entry becomes "lost"). Implement `GetHashCode` from the same fields as `Equals`.
>
> **Cross-Q²**: I `Add` a mutable object as a `Dictionary<Foo, string>` key, then mutate a field that participates in `GetHashCode`. What happens to the entry?
>
> **A**: It's still in the dictionary (count is unchanged) but **`TryGetValue` with the same reference now returns false** — the entry is in the bucket for the old hash code, but the lookup goes to the new bucket. The entry is leaked (memory held, never findable, never collected as long as the dictionary lives). **Rule**: dictionary keys must be immutable. Records and `readonly record struct` make this trivially safe.

### Drill 6 — Liskov Substitution

> **Q**: What's a Liskov violation in `Square : Rectangle`?
>
> **A**: `Rectangle`'s contract allows width and height to vary independently. `Square` strengthens the precondition by forcing them to move together. Code that worked on every `Rectangle` (e.g., `r.Width = 5; r.Height = 10; assert(r.Area == 50)`) fails when given a `Square`.
>
> **Cross-Q**: How would you fix it?
>
> **A**: Don't model `Square` as a subtype of `Rectangle`. They share an abstraction (`IShape` with `Area`), but they're siblings, not parent-and-child. Mathematically a square *is* a rectangle, but mathematically immutable squares; in code, mutable squares break the rectangle contract. **The taxonomy of the real world doesn't always map to the type hierarchy that works in code.**
>
> **Cross-Q²**: Why does C# even let you compile `Square : Rectangle` with the broken behavior?
>
> **A**: The compiler enforces type compatibility (every `Square` IS a `Rectangle`-shaped reference), not semantic correctness. Liskov violations are *semantic* — about the contract intent, not the type signature. No compiler can catch them in general (would require full theorem proving). The defense is design review + integration tests that exercise base-class contracts on derived instances.

### Drill 7 — Reflection instantiation

> **Q**: Can `Activator.CreateInstance(typeof(IRepository))` create an instance?
>
> **A**: No — it throws `MissingMethodException`. Interfaces have no implementation, so there's nothing to allocate. Same for `Activator.CreateInstance(typeof(AbstractEntity))` — abstract classes can't be instantiated either.
>
> **Cross-Q**: How does ASP.NET Core's DI container then resolve `IRepository`?
>
> **A**: The container is **told** which concrete type to use: `services.AddScoped<IRepository, EfRepository>()`. When something asks for `IRepository`, the container looks up the registered concrete type, reflects on its constructors, picks the one with the most resolvable parameters, recursively resolves each parameter, and calls the chosen ctor.
>
> **Cross-Q²**: I have a class with a `private` ctor used by a static factory `Create()`. Can DI resolve it?
>
> **A**: Not by default — DI's reflection-based resolution requires a public ctor. You either (a) make the ctor public, (b) register a factory: `services.AddScoped<Locked>(_ => Locked.Create());`, or (c) use `ActivatorUtilities.CreateInstance` which can be configured to honor non-public ctors via `BindingFlags`. The factory approach is most idiomatic and keeps the ctor private.

### Drill 8 — Generic variance

> **Q**: Why is `IEnumerable<Dog>` assignable to `IEnumerable<Animal>` but `List<Dog>` isn't to `List<Animal>`?
>
> **A**: `IEnumerable<out T>` is **covariant** — `T` only appears in output positions (the `Current` property). Returning `Dog` where `Animal` is expected is safe (every Dog is an Animal). `List<T>` is **invariant** — `T` also appears in input positions (`Add(T)`). If `List<Dog>` were assignable to `List<Animal>`, you could `Add(new Cat())` through the `Animal`-typed reference. Type safety breaks. Compiler refuses.
>
> **Cross-Q**: When would you use `in T` (contravariance)?
>
> **A**: For interfaces that *consume* `T` only: `IComparer<in T>`, `Action<in T>`, predicates. An `IComparer<Animal>` can compare any two Animals — including Dogs. So `IComparer<Animal>` is assignable to `IComparer<Dog>` (contravariance: more general accepted where more specific is expected). The opposite of `out`/covariance.
>
> **Cross-Q²**: Arrays in C# are covariant — `Dog[]` is assignable to `Animal[]`. Is that safe?
>
> **A**: **No, and it's the classic .NET design wart.** `Animal[] a = new Dog[10]; a[0] = new Cat();` compiles but throws `ArrayTypeMismatchException` at runtime. Java has the same issue. Modern .NET added generics specifically to avoid it — generic collections (`List<T>`, `IList<T>`) are invariant, which is why `List<Dog>` to `List<Animal>` is correctly rejected at compile time.

### Drill 9 — `sealed`

> **Q**: What does `sealed override` mean?
>
> **A**: It overrides a virtual method **and** locks it — no further class in the chain can override it again. The class itself can still be subclassed; only that one method is final.
>
> **Cross-Q**: Why would the JIT care about that keyword?
>
> **A**: Because once the JIT knows no override is possible, it can **devirtualize** — replace the `callvirt` with a direct `call`, and potentially inline the method body. Without `sealed`, the JIT must assume any subclass could override and use vtable lookup.
>
> **Cross-Q²**: What's the perf delta in a hot loop calling a virtual method 100 million times?
>
> **A**: Roughly 1-3 nanoseconds per call saved by devirtualization, plus the gains from inlining (often 5-10× the dispatch cost). For 100M calls, that's ~0.3-1 second of CPU time. Not material for app code; very material for math libraries, parsers, game engines. **Modern PGO** (Profile-Guided Optimization, on in .NET 8+) does much of this speculatively even without `sealed`, but explicit `sealed` is a free hint.

### Drill 10 — Static constructors

> **Q**: When does the static constructor for `Dog` run, given `Dog : Animal`?
>
> **A**: Lazily, the first time `Dog` is touched: instance creation, static-field access, or static-method call. The runtime guarantees it runs exactly once per AppDomain and is thread-safe.
>
> **Cross-Q**: Does `Animal`'s static ctor run before `Dog`'s when I write `new Dog()`?
>
> **A**: Generally yes — `Animal`'s static ctor runs the first time anything triggers loading `Animal`'s type info, which happens when constructing `Dog` (the runtime needs the base type's metadata). The exact order depends on the `beforefieldinit` attribute: types without an explicit static ctor get optimized lazy initialization (might run later); types with an explicit static ctor run **before any access**.
>
> **Cross-Q²**: A static ctor throws. What's recoverable?
>
> **A**: Nothing. The exception is wrapped in `TypeInitializationException` and the type is **permanently broken for the rest of the AppDomain** — every subsequent attempt to use it (`new`, static access, even reflection on its members) re-throws the same `TypeInitializationException`. There is no API to "retry" the static ctor. This is why static ctors must be bulletproof — no I/O, no config access, no allocation paths that could OOM.

### Drill 11 — Default interface methods conflict

> **Q**: If `IReader` and `IBackup` both have a default method `void Save() => ...;` and `class Repo : IReader, IBackup` doesn't override it, what happens?
>
> **A**: Compile error CS8705 — diamond ambiguity. The compiler can't pick which default to inherit.
>
> **Cross-Q**: How do you fix it?
>
> **A**: Disambiguate via explicit interface implementation:
> ```csharp
> public class Repo : IReader, IBackup
> {
>     void IReader.Save() => Console.WriteLine("reading");
>     void IBackup.Save() => Console.WriteLine("backing up");
>     public void Save() => ((IReader)this).Save();   // optional public default
> }
> ```
> Each call site picks the meaning by casting to the interface: `((IReader)r).Save()` vs `((IBackup)r).Save()`.
>
> **Cross-Q²**: Why didn't C# inherit C++'s "use the leftmost ancestor" rule?
>
> **A**: C# was designed (1999-2001) explicitly to avoid C++'s implicit-resolution pitfalls. The diamond problem in C++ is one of the most-cited reasons to avoid multi-inheritance. C# enforces explicit disambiguation: if two paths exist, you must pick one. The trade-off is a small amount of friction in DIM scenarios for a large amount of clarity.

### Drill 12 — Records

> **Q**: What does `record` change about equality?
>
> **A**: Records auto-generate `Equals`, `GetHashCode`, and `==` for **value semantics** — two records with the same property values are equal, regardless of reference. For `record class` it's still a reference type with these auto-generated overrides; for `record struct` it's a value type with the same auto-generated semantics.
>
> **Cross-Q**: How does the `with` expression work?
>
> **A**: `var b = a with { Amount = 20 };` clones `a` and applies the property changes to the clone. Mechanically: the compiler generates a protected `<Clone>$()` method that does a memberwise copy via a synthesized copy ctor, then assigns the listed properties. The original `a` is unchanged (non-destructive mutation).
>
> **Cross-Q²**: What's the difference between `record class` and `record struct`?
>
> **A**: `record class` is a reference type with value-semantic equality (heap-allocated, but `==` compares contents). `record struct` is a value type with value-semantic equality (stack-friendly, but copied on assignment). Use `record class` for general DTOs and value objects; use `record struct` (especially `readonly record struct`) for small high-frequency values used as dictionary keys or in hot loops. **Tie-breaker**: if you're passing it around a lot through interfaces (boxing), prefer record class; if you're putting it in arrays/lists by value, prefer record struct.

### Drill 13 — The vtable

> **Q**: What's a vtable?
>
> **A**: A method table — an array of function pointers — that the runtime uses to resolve virtual method calls. Each class has one; derived classes inherit slots from the base and add their own.
>
> **Cross-Q**: Where does the runtime store the vtable pointer?
>
> **A**: In every object's header (the few bytes preceding the object's fields on the heap). On a 64-bit runtime, each object has ~16 bytes of header: 8 bytes sync block + 8 bytes method table pointer (which points to the vtable + type metadata). That's why every reference type allocation has a minimum ~24-byte footprint even for empty classes — header + a pointer + alignment.
>
> **Cross-Q²**: How does `new void Foo()` (hiding) affect the vtable?
>
> **A**: It adds a **separate slot** to the derived class's vtable for the hidden method, leaving the inherited slot untouched. The base's `Foo` is still at slot N (inherited); the derived's `Foo` lands at slot N+M (new). Dispatch through the base reference uses slot N → base method; dispatch through the derived reference uses slot N+M → derived method. This is why `new` causes "which one runs?" to depend on the static type of the variable.

### Drill 14 — Composition vs inheritance

> **Q**: When would you refactor an inheritance hierarchy to composition?
>
> **A**: When you find yourself wanting "two parents," when the hierarchy is more than 2 levels deep, when you need runtime-swappable behavior, or when a subclass uses only a fraction of the base's contract. Symptoms: cast-tests, `NotImplementedException` overrides, "is-a" relationships that feel forced.
>
> **Cross-Q**: Show me a 3-level inheritance refactored to composition.
>
> **A**: Logger → Decorator/Strategy. `class LoggerBase { abstract WriteRaw(); Info() => WriteRaw(...); }` → `class ConsoleLogger : LoggerBase`, `FileLogger : LoggerBase`. Composition version: `interface IWriter { Write(); }` + `class Logger(IWriter w)` + `CompositeWriter` to multiplex. Result: you can log to both console AND file simultaneously, which the inheritance version couldn't express.
>
> **Cross-Q²**: When is inheritance still the right call?
>
> **A**: Three places: (1) framework-mandated bases (Razor Pages `PageModel`, EF Core `DbContext`), (2) genuine state-carrying "is-a" relationships (domain `Entity` with Id and equality), and (3) closed hierarchies sealed at the leaves (DDD value objects). Everything else: prefer composition.

### Drill 15 — Modern C# changes

> **Q**: How do records, primary constructors, and `static abstract` change OOP interview answers from 2018?
>
> **A**: Records reduce the need to manually write `Equals`/`GetHashCode`/`==` for value-shaped types — fewer custom equality bugs. Primary constructors collapse boilerplate DI registration into one-liners. `static abstract` allows interfaces to require static members (operators, factories), which historically forced an abstract base class. Combined: fewer reasons to reach for abstract classes; "interface for capability, abstract class only for shared instance state" is now the default guidance.
>
> **Cross-Q**: With `record class`, `record struct`, primary constructors, `init` setters, and `required` members, when would you still write a plain class with explicit ctors?
>
> **A**: When the type has meaningful behavior (methods beyond data carriers), when it manages mutable state intentionally, when equality should be reference-based (entities with identity), or when you need fine-grained ctor logic (validation, normalization, side effects in the ctor). Pure data carriers — records. Mutable state with logic — class. Identity-based entities — class with `Id`-based `Equals`.
>
> **Cross-Q²**: Does using records prevent the need for `IEquatable<T>`?
>
> **A**: No — records implement `IEquatable<T>` for you. The generated `Equals(T)` IS the `IEquatable<T>` implementation. That's part of why records are the right choice in 2026 for value-typed reference equality: you get the strongly-typed non-boxing path automatically.

</details>
## Cheat Sheet

- **C# inheritance**: single base class, many interfaces — no diamond problem at the class level.
- **`virtual`/`override`**: vtable dispatch; **`new`** hides (warning without it) and breaks polymorphism.
- **`sealed` class**: no further subclassing; enables JIT devirtualization.
- **`abstract class`**: state + skeleton; one base; **interface**: capability; many.
- **DIM (C# 8)**: default interface method — callable only via interface reference.
- **`static abstract`** (C# 11): unlocks generic math via `where T : INumber<T>`.
- **Primary ctor (C# 12)**: header params captured into methods; *not* auto-properties.
- **`required`** (C# 11): caller must set in object initializer or pass via `[SetsRequiredMembers]` ctor.
- **Equals + GetHashCode**: override together; mismatch breaks `Dictionary`/`HashSet`.
- **Smell**: `if (x is Derived)` in many branches — switch to virtual or pattern dispatch.

## Walkthrough — Virtual call from base constructor

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A `ReportGenerator` base class calls `BuildHeader()` (virtual) in its constructor. The new `PdfReportGenerator` subclass overrides `BuildHeader()` to use a `_logoBytes` field initialized in its own constructor. In production, PDFs occasionally render with a blank header and the logs show `NullReferenceException` deep inside `BuildHeader`.

**Diagnosis**: Repro by running the constructor under a debugger with first-chance exceptions enabled (`Debug → Exceptions → Common Language Runtime Exceptions`). The stack shows `PdfReportGenerator.BuildHeader` accessing `_logoBytes` while `this.GetType() == typeof(PdfReportGenerator)` but `_logoBytes` is `null`. Roslyn analyzer `CA2214` (`Do not call overridable methods in constructors`) would have flagged this at compile time. Inspect the IL: the base ctor calls the virtual method, dispatch lands on the override, but the derived field initializers (which run *after* base ctor returns) haven't executed yet.

**Fix**: Three options. (1) Mark `BuildHeader` non-virtual or seal it on the path called from the ctor. (2) Move the call out of the constructor into an `Initialize()` method or a factory `static Create(...)`. (3) Mark the base class `sealed` if subclassing isn't required.

```csharp
// Recommended: factory pattern keeps the virtual call out of construction
public abstract class ReportGenerator {
    protected ReportGenerator() { /* no virtual calls */ }
    public static T Create<T>() where T : ReportGenerator, new() {
        var r = new T(); r.BuildHeader(); return r;
    }
    protected virtual void BuildHeader() { }
}
```

**Why it works**: In C#, the runtime type is set at the start of base construction so virtual calls dispatch to the most-derived override — but derived field initializers and constructor body run *after* base ctor returns. Calling virtuals before fields are initialized is the canonical fragile-base-class trap.

</details>
## Self-test

<details>
<summary>1. When would you choose an `abstract class` over an `interface`, even after C# 8 added default interface methods?</summary>

Choose abstract class when you need: (a) shared *state* — fields, constructors, finalizers; interfaces still cannot hold instance state; (b) one canonical lifecycle (`protected virtual void OnInitialize`); (c) constructor coordination (`base(...)` chaining). Default interface methods provide *behavior* sharing for evolution but require an interface-typed reference to invoke. Abstract classes also still beat interfaces for `protected` visibility — interfaces only have public members. Trade-off: a class can extend exactly one abstract base, but implement many interfaces.
</details>

<details>
<summary>2. Apply: a colleague writes `public class Cache(IDb db) { public Task RefreshAsync() => db.LoadAsync(); }` and is confused why `Cache.db` isn't visible in another partial class file. Explain.</summary>

Primary-constructor parameters in classes (C# 12) are captured into a hidden compiler-generated field *only when used* by an instance member. They're not properties, not auto-fields with public/protected access — they're locals scoped to the type body. They're invisible across partial-class files unless you explicitly project them: `public IDb Db { get; } = db;`. The compiler emits a backing field with an unspeakable name that callers cannot reach. For DI services where you want explicit visibility, declare an explicit `private readonly IDb _db = db;` field.
</details>

<details>
<summary>3. Trade-off: when do `static abstract` interface members beat plain instance methods?</summary>

When the operation logically belongs to the *type* not an instance — parsers (`T.Parse(string)`), constants (`T.Zero`, `T.One`), factories. Without `static abstract`, generic code couldn't say "any `T` that knows how to parse itself." With it, `where T : IParseable<T>` lets you write `T.Parse(s)` in generic code. Trade-off: you lose polymorphism — there's no "vtable" for static methods, so each generic instantiation dispatches at compile time, growing IL. Use sparingly: mostly numeric types and parser libraries.
</details>

<details>
<summary>4. Analyze: `class A { public virtual void M() => Console.Write("A"); } class B : A { public new void M() => Console.Write("B"); }` — what does `((A)new B()).M()` print, and why?</summary>

Prints `A`. `B.M` is declared `new`, not `override` — it *hides* `A.M` rather than overriding it. The vtable slot for `M` still points at `A.M` for any instance whose declared type is `A`. Calling through an `A` reference uses the vtable; calling through a `B` reference uses the hidden `B.M` directly. This is exactly the "fragile base class" problem `new` was designed to mitigate at the language level, and it's almost always a bug. Senior code review rule: every `new` modifier on a method needs justification.
</details>

<details>
<summary>5. You're designing a plugin system. Compare three polymorphism strategies: abstract base, interface, generic constraint with static abstract.</summary>

(1) Abstract base — one inheritance slot consumed; great for plugins that share lifecycle/state; rigid (can't compose). (2) Interface — composable (multiple plugins can wear multiple "hats"); no shared state; ideal for capability-style plugins. (3) Generic with `static abstract` — type-level dispatch, zero runtime overhead, but each plugin variant generates its own JIT'd code (IL bloat) and can't be discovered at runtime by reflection alone. Choose: interfaces by default; abstract base when sharing skeleton; static abstract for generic-math/parser-style plugins where the operation belongs to the type itself.
</details>

## Cross-references

- **Previous: [Type System Deep Dive](./02-type-system.md)** — `record class`, `record struct`, immutability primitives.
- **Next: [Generics & Variance](./04-generics-and-variance.md)** — generic types, constraints, static abstract members in depth.
- **[Modern C# Features](../01-net-core-deep-dive/12-modern-csharp.md)** — primary constructors, records, collection expressions reference.
- **[SOLID Principles](../02-solid-principles.md)** — design contracts that this file's mechanisms enforce.
- **[Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md)** — pattern-matching dispatch over a closed hierarchy.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [Object-oriented programming (C#)](https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/object-oriented/).
- Microsoft Learn — [Default interface methods](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/proposals/csharp-8.0/default-interface-methods).
- Microsoft Learn — [Generic math support](https://learn.microsoft.com/en-us/dotnet/standard/generics/math).
- Mads Torgersen — *"Why C# doesn't have multiple inheritance"* — language design rationale.
- Joseph Albahari — *C# 12 in a Nutshell*, OOP chapters.

</details>
<!-- nav-footer-start -->

---

[← Previous: Type System Deep Dive](02-type-system.md) · [↑ Back to top](#oop--polymorphism) · [Next: Generics & Variance →](04-generics-and-variance.md)

<!-- nav-footer-end -->
