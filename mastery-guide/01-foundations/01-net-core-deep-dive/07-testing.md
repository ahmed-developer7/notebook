# Unit Testing

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 6 — API Mastery | 2026-05-07 |

> 📘 **Main file**: Interview-ready summary, drills, and cheat sheet live in **[Unit Testing Foundations](../../09-testing/01-unit-testing-foundations.md)**. This file is the implementation deep-dive.

> .NET-specific intro on this page (xUnit + Moq basics). For broader testing — integration with **TestContainers**, E2E with **Playwright**, contract testing with **Pact**, performance testing, mutation testing, test strategy + CI/CD — see the [Testing chapter](../../09-testing/README.md).

---

## Why It Matters

Tests are not "extra work" — they are how you ship software at speed without fear. A team without tests measures progress in lines of code; a team with good tests measures it in *features safely delivered per sprint*. The .NET ecosystem has industrial-strength tooling (xUnit, NUnit, MSTest, Moq, NSubstitute, FluentAssertions, WebApplicationFactory, TestContainers, Verify) that turns testing from a chore into a productivity multiplier — but only if you understand *what* to test, *at what level*, and *how* to keep tests cheap to maintain.

The cost of a bug grows by an order of magnitude at every stage: $1 to fix in a unit test, $10 in CI, $100 in staging, $1,000+ in production. Yet over-testing is just as bad — a 30-minute test suite no one runs is worth less than a 30-second one everyone runs. This guide is about hitting the right balance: where to put unit tests, where integration tests, where end-to-end, and the patterns that keep all three fast and trustworthy.

This chapter focuses on **unit and integration testing in .NET 10** — xUnit fundamentals, AAA, lifecycles, mocking, `WebApplicationFactory`, TestContainers, test data builders. End-to-end (Playwright), contract testing (Pact), performance testing, and mutation testing live in the broader [Testing chapter](../../09-testing/README.md).

---

## Table of Contents

1. [Why It Matters](#why-it-matters)
2. [Real-World Analogy: Inspecting a Car](#real-world-analogy-inspecting-a-car)
3. [The Test Pyramid](#the-test-pyramid)
4. [Unit Testing](#14-unit-testing)
5. [xUnit Fundamentals](#xunit-fundamentals)
6. [The AAA Pattern](#the-aaa-pattern)
7. [Test Fixtures and Lifecycles](#test-fixtures-and-lifecycles)
8. [Mocking — Moq vs NSubstitute vs FakeItEasy](#mocking--moq-vs-nsubstitute-vs-fakeiteasy)
9. [When to Mock vs Use the Real Thing](#when-to-mock-vs-use-the-real-thing)
10. [Test Data Builders](#test-data-builders)
11. [Integration Testing with WebApplicationFactory](#integration-testing-with-webapplicationfactory)
12. [TestContainers — Real Databases in Tests](#testcontainers--real-databases-in-tests)
13. [Common Pitfalls](#common-pitfalls)
14. [Best Practices](#best-practices)
15. [Real-World Scenarios](#real-world-scenarios)
16. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
17. [Self-Test](#self-test)
18. [Cross-References](#cross-references)
19. [Sources](#sources)

---

## Real-World Analogy: Inspecting a Car

Think of testing as inspecting a car at three depths.

```
┌─────────────────────────────────────────────────────────┐
│  END-TO-END TESTS  (drive the car)                      │
│  ┌───────────────────────────────────────────────┐      │
│  │ Take it on the freeway. Real fuel, real road. │      │
│  │ "Does the car actually transport me?"          │      │
│  │ Few tests. Slow. High confidence. Brittle.     │      │
│  └───────────────────────────────────────────────┘      │
│                                                         │
│  INTEGRATION TESTS (run the engine on a stand)          │
│  ┌───────────────────────────────────────────────┐      │
│  │ Engine + transmission + fuel pump together.   │      │
│  │ "Do the parts work in concert?"                │      │
│  │ Some tests. Medium speed. Real-ish components. │      │
│  └───────────────────────────────────────────────┘      │
│                                                         │
│  UNIT TESTS (test each part on a workbench)             │
│  ┌───────────────────────────────────────────────┐      │
│  │ Spark plug fires. Fuel injector sprays right. │      │
│  │ "Does each component meet its spec?"           │      │
│  │ Many tests. Fast. Easy to write and maintain.  │      │
│  └───────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

You wouldn't ship a car after only freeway-driving it (slow, expensive, can't isolate failures), and you wouldn't ship a car after only bench-testing parts (the spark plug works, but does it work *together with* the fuel injector?). You need all three layers — but in different ratios.

---

## The Test Pyramid

```
           ▲
          / \                  E2E / UI
         /   \                  ~5%
        / E2E \                 - Slow (minutes)
       /-------\                - Brittle (UI changes)
      /         \               - High confidence
     / Integration\             - Use Playwright/Selenium
    /-------------\             
   /               \           Integration
  /  Integration    \           ~25%
  /                  \          - Real DB, real HTTP
 /----------------    \         - Slower (seconds)
/                      \        - WebApplicationFactory
/        Unit           \       - TestContainers
/                        \      
/--------------------------\   Unit
                                ~70%
                                - Pure logic, no I/O
                                - Fast (ms)
                                - High volume, easy to maintain
```

```
┌──────────────┬──────────────┬──────────────┬───────────────┐
│ Layer        │ Speed        │ Volume       │ Confidence    │
├──────────────┼──────────────┼──────────────┼───────────────┤
│ Unit         │ 1-10ms       │ Many (1000s) │ Per-component │
│ Integration  │ 100ms - 5s   │ Some (100s)  │ Per-feature   │
│ E2E          │ 10s - 5min   │ Few (10s)    │ User-journey  │
└──────────────┴──────────────┴──────────────┴───────────────┘
```

### Without a Pyramid Strategy (anti-shape)

```
INVERTED PYRAMID — common in legacy projects
              ▲
            ╱E2E╲                ← lots of slow E2E
          ╱──────╲                  Build is 45 min
        ╱  Integ  ╲                 Flaky failures
      ╱────────────╲                Devs avoid running them
    ╱      Unit     ╲              ← few unit tests
                                     Most bugs caught late
```

```
ICE-CREAM CONE — even worse
              ▲
            ╱manual╲              ← QA team clicks through UI
          ╱─E2E────╲                "We test by hand"
        ╱──Integ────╲               
      ╱────Unit──────╲              No regression confidence
                                    Releases take a week
```

The healthy pyramid has a wide unit base — fast, cheap feedback — narrowing through integration to a thin E2E tip. .NET 10's tooling makes this shape achievable.

---

## 14. Unit Testing

```csharp
// Using xUnit + Moq
public class OrderServiceTests
{
    private readonly Mock<IOrderRepository> _mockRepo;
    private readonly Mock<IPaymentGateway> _mockPayment;
    private readonly OrderService _service;

    public OrderServiceTests()
    {
        _mockRepo = new Mock<IOrderRepository>();
        _mockPayment = new Mock<IPaymentGateway>();
        _service = new OrderService(_mockRepo.Object, _mockPayment.Object);
    }

    [Fact]
    public async Task ProcessOrder_ValidOrder_ReturnsSuccess()
    {
        // Arrange
        var order = new Order { Id = 1, Total = 100 };
        _mockRepo.Setup(r => r.ValidateAsync(order))
                 .ReturnsAsync(ValidationResult.Valid);
        _mockPayment.Setup(p => p.ChargeAsync(100))
                    .ReturnsAsync(new PaymentResult { Success = true });
        _mockRepo.Setup(r => r.SaveAsync(order))
                 .ReturnsAsync(order);

        // Act
        var result = await _service.ProcessOrderAsync(order);

        // Assert
        Assert.True(result.IsSuccess);
        _mockPayment.Verify(p => p.ChargeAsync(100), Times.Once);
        _mockRepo.Verify(r => r.SaveAsync(order), Times.Once);
    }

    [Fact]
    public async Task ProcessOrder_InvalidOrder_ReturnsFailure()
    {
        // Arrange
        var order = new Order { Id = 1, Total = -50 };
        _mockRepo.Setup(r => r.ValidateAsync(order))
                 .ReturnsAsync(ValidationResult.Invalid("Negative total"));

        // Act
        var result = await _service.ProcessOrderAsync(order);

        // Assert
        Assert.False(result.IsSuccess);
        _mockPayment.Verify(p => p.ChargeAsync(It.IsAny<decimal>()), Times.Never);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(1_000_001)]
    public async Task ProcessOrder_InvalidAmounts_ReturnsFailure(decimal amount)
    {
        var order = new Order { Total = amount };
        _mockRepo.Setup(r => r.ValidateAsync(order))
                 .ReturnsAsync(ValidationResult.Invalid("Invalid amount"));

        var result = await _service.ProcessOrderAsync(order);

        Assert.False(result.IsSuccess);
    }
}
```

### What "Unit" Means

A *unit test* exercises **one logical class or function** with all external dependencies replaced by test doubles. No DB. No file I/O. No network. No clock. Pure CPU.

```
┌─────────────────────────────────────────────────────────┐
│ UNIT TEST Properties                                    │
├─────────────────────────────────────────────────────────┤
│ ✓ Fast (1-10 ms each)                                   │
│ ✓ Deterministic — same input, same output, every run    │
│ ✓ Independent — order doesn't matter                    │
│ ✓ Self-contained — no shared global state               │
│ ✓ Readable — failure message tells you what broke       │
│ ✗ NOT a substitute for integration tests                │
│ ✗ NOT meant to test framework code                      │
│ ✗ NOT meant to test "trivial" getters/setters          │
└─────────────────────────────────────────────────────────┘
```

---

## xUnit Fundamentals

xUnit is the de-facto choice for new .NET projects. NUnit and MSTest are valid alternatives, but xUnit has the cleanest design (no `[SetUp]`/`[TearDown]` magic — it's just constructors and `IDisposable`).

```
┌──────────────┬──────────────────────────────────────────┐
│ Attribute    │ Meaning                                  │
├──────────────┼──────────────────────────────────────────┤
│ [Fact]       │ Single test case                         │
│ [Theory]     │ Parameterised test — runs once per data  │
│ [InlineData] │ Hard-coded params for [Theory]           │
│ [MemberData] │ Pull params from a static member         │
│ [ClassData]  │ Pull params from an IEnumerable<object[]>│
│ [Trait]      │ Tag tests for filtering (Category=Slow)  │
│ [Skip]       │ Skip with reason (.NET 9+ first-class)   │
└──────────────┴──────────────────────────────────────────┘
```

### Theory with MemberData

```csharp
public static IEnumerable<object[]> InvalidAmounts =>
    new[]
    {
        new object[] { 0m,         "zero" },
        new object[] { -1m,        "negative" },
        new object[] { 1_000_001m, "exceeds limit" },
    };

[Theory]
[MemberData(nameof(InvalidAmounts))]
public async Task Process_RejectsInvalidAmount(decimal amount, string reason)
{
    var result = await _service.ProcessAsync(new Order { Total = amount });
    Assert.False(result.IsSuccess);
    Assert.Contains(reason, result.Error, StringComparison.OrdinalIgnoreCase);
}
```

### Assertions

```csharp
// xUnit built-in
Assert.Equal(expected, actual);
Assert.NotNull(thing);
Assert.Throws<InvalidOperationException>(() => DoBadThing());
await Assert.ThrowsAsync<TaskCanceledException>(() => svc.WaitAsync(ct));

// FluentAssertions (most popular addition)
result.Should().BeTrue();
order.Should().BeEquivalentTo(expected, opts => opts.Excluding(o => o.UpdatedAt));
act.Should().ThrowAsync<DomainException>().WithMessage("*invalid*");
```

FluentAssertions makes failure messages dramatically clearer ("Expected order.Total to be 100.00m, but found 99.99m") and is worth the dependency.

---

## The AAA Pattern

Every test, no matter the framework, follows three phases:

```
┌─────────────────────────────────────────────────────────┐
│ AAA Structure                                           │
├─────────────────────────────────────────────────────────┤
│ ARRANGE — set up the world the unit will operate in    │
│   ├─ Create the system under test (SUT)                 │
│   ├─ Configure mocks / stubs                            │
│   └─ Build input data                                   │
│                                                         │
│ ACT — invoke the single behaviour under test            │
│   └─ One line, ideally                                  │
│                                                         │
│ ASSERT — verify the outcome                             │
│   ├─ Return value matches expectation                   │
│   └─ Side effects (mock calls, state changes) verified  │
└─────────────────────────────────────────────────────────┘
```

### Naming: One Test = One Sentence

```
Method_Scenario_ExpectedResult

✓ ProcessOrder_ValidOrder_ReturnsSuccess
✓ ProcessOrder_NegativeTotal_ReturnsValidationFailure
✓ Withdraw_AmountExceedsBalance_ThrowsInsufficientFundsException

✗ Test1                        ← useless on failure
✗ TestProcessOrder              ← what about it?
✗ ProcessOrderShouldWork        ← shouldn't every test "work"?
```

A failing test name should answer "what was this checking?" without opening the file.

### One Assertion (Conceptually) Per Test

You can have multiple `Assert` lines, but they should test **one logical behaviour**:

```csharp
// ✅ One behaviour — multiple lines acceptable
[Fact]
public void Add_Item_IncreasesCountAndTotal()
{
    var cart = new Cart();
    cart.Add(new Item { Price = 10 });

    Assert.Equal(1, cart.Count);
    Assert.Equal(10m, cart.Total);
}

// ❌ Multiple unrelated behaviours — split into two tests
[Fact]
public void CartTests()
{
    var cart = new Cart();
    cart.Add(new Item { Price = 10 });
    Assert.Equal(1, cart.Count);

    cart.Remove(item);
    Assert.Equal(0, cart.Count);

    cart.Clear();
    Assert.Empty(cart.Items);
}
```

---

## Test Fixtures and Lifecycles

```
┌──────────────────┬──────────────────────────────────────┐
│ xUnit Lifecycle  │ When                                 │
├──────────────────┼──────────────────────────────────────┤
│ Constructor      │ Before EACH test (per-test setup)    │
│ IDisposable.Dispose │ After EACH test (per-test cleanup)│
│ IClassFixture<T> │ Once per class — shared across tests │
│ ICollectionFixture<T> │ Once per collection — across multiple test classes │
│ IAsyncLifetime   │ Async setup/teardown (.InitializeAsync, .DisposeAsync) │
└──────────────────┴──────────────────────────────────────┘
```

### Per-Test (default)

```csharp
public class CartTests : IDisposable
{
    private readonly Cart _cart;

    public CartTests()                  // runs before EACH test
    {
        _cart = new Cart();
    }

    public void Dispose() { /* runs after EACH test */ }

    [Fact] public void Empty_NewCart() => Assert.Empty(_cart.Items);
}
```

### Class Fixture — Shared Setup Across Tests in One Class

```csharp
public class DbFixture : IAsyncLifetime
{
    public AppDbContext Db { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        var opts = new DbContextOptionsBuilder<AppDbContext>()
                       .UseInMemoryDatabase("test-db").Options;
        Db = new AppDbContext(opts);
        await SeedAsync(Db);
    }

    public async Task DisposeAsync() => await Db.DisposeAsync();
}

public class UserRepoTests : IClassFixture<DbFixture>
{
    private readonly DbFixture _fx;
    public UserRepoTests(DbFixture fx) => _fx = fx;

    [Fact] public async Task Find_Existing_ReturnsUser() { /* uses _fx.Db */ }
}
```

### Collection Fixture — Shared Across Multiple Test Classes

```csharp
[CollectionDefinition("Database")]
public class DatabaseCollection : ICollectionFixture<DbFixture> { }

[Collection("Database")]
public class UserRepoTests { /* uses DbFixture */ }

[Collection("Database")]
public class OrderRepoTests { /* uses the SAME DbFixture instance */ }
```

```
┌──────────────────────────────────────────────────────────────┐
│  Lifecycle visualisation for [Collection("Database")]        │
├──────────────────────────────────────────────────────────────┤
│  Test run starts                                             │
│   │                                                          │
│   ├─ DbFixture.InitializeAsync()  (DB starts ONCE)           │
│   │                                                          │
│   ├─ UserRepoTests instance #1                               │
│   │    ├─ test 1                                             │
│   │    └─ test 2                                             │
│   ├─ OrderRepoTests instance #1                              │
│   │    └─ test 3                                             │
│   │                                                          │
│   └─ DbFixture.DisposeAsync()    (DB stops ONCE)             │
└──────────────────────────────────────────────────────────────┘
```

Use collection fixtures for *expensive* shared resources (TestContainers, real Kafka). For cheap resources (in-memory DB), per-test setup is fine.

---

## Mocking — Moq vs NSubstitute vs FakeItEasy

Three mocking libraries dominate in .NET. They achieve the same goal with different syntactic philosophies.

```
┌──────────────────┬──────────────────┬──────────────────┐
│ Feature          │ Moq              │ NSubstitute      │
├──────────────────┼──────────────────┼──────────────────┤
│ Setup syntax     │ Lambda-heavy     │ Direct call      │
│                  │ .Setup(x => ...) │ sub.Method()...  │
│ Verify syntax    │ .Verify(...)     │ Received().Method │
│ Strict by default│ Yes (no setup =  │ No (returns      │
│                  │ throws)          │ default)         │
│ Async support    │ Yes              │ Yes              │
│ Auto-properties  │ Yes              │ Yes              │
│ Maintenance      │ Active (4.20+)   │ Active           │
│ License concerns │ SponsorLink saga │ Clean            │
│ Learning curve   │ Steeper          │ Gentler          │
│ Generated mocks  │ Castle.Proxy     │ Castle.Proxy     │
└──────────────────┴──────────────────┴──────────────────┘
```

(FakeItEasy is similar to NSubstitute in style — `A.CallTo(() => fake.Method(...)).Returns(...)`.)

### Moq

```csharp
var mockRepo = new Mock<IOrderRepository>();
mockRepo.Setup(r => r.GetByIdAsync(42))
        .ReturnsAsync(new Order { Id = 42, Total = 100m });

var svc = new OrderService(mockRepo.Object);
var order = await svc.GetAsync(42);

mockRepo.Verify(r => r.GetByIdAsync(42), Times.Once);
mockRepo.Verify(r => r.GetByIdAsync(It.IsAny<int>()), Times.AtLeastOnce);
```

### NSubstitute (gentler syntax)

```csharp
var repo = Substitute.For<IOrderRepository>();
repo.GetByIdAsync(42).Returns(new Order { Id = 42, Total = 100m });

var svc = new OrderService(repo);
var order = await svc.GetAsync(42);

await repo.Received(1).GetByIdAsync(42);
await repo.Received().GetByIdAsync(Arg.Any<int>());
```

### Properties Box

```
┌─────────────────────────────────────────────────────────┐
│ MOCK Properties                                         │
├─────────────────────────────────────────────────────────┤
│ ✓ Verify interactions (was the method called?)          │
│ ✓ Configure return values per scenario                  │
│ ✓ Inspect arguments after the fact                      │
│ ✓ Throw on unexpected calls (Strict mode)               │
│ ✗ Cannot mock sealed/static/non-virtual without TypeMock│
│ ✗ Mocking concrete classes is brittle                   │
│ ✗ Over-mocking → tests verify implementation, not behaviour │
└─────────────────────────────────────────────────────────┘
```

> Pick **one** library per repo and stick with it. Mixing Moq and NSubstitute makes onboarding harder. New projects in 2026 often pick NSubstitute (gentler, no licensing drama).

---

## When to Mock vs Use the Real Thing

```
┌─────────────────────────┬─────────────────────────────┐
│ Dependency              │ Mock or Real?               │
├─────────────────────────┼─────────────────────────────┤
│ DbContext / repository  │ Real (in-memory) or         │
│                         │ TestContainers — never mock │
│ HttpClient (external)   │ Mock (or WireMock)          │
│ ILogger<T>              │ Real (NullLogger.Instance)  │
│ Time (DateTime.UtcNow)  │ Mock (TimeProvider in .NET 8+) │
│ File I/O                │ Mock (System.IO.Abstractions)│
│ Pure-CPU calculator     │ Real — no need to mock      │
│ MediatR / event bus     │ Mock (verify Send/Publish)  │
│ Domain entities         │ Real (build with builders)  │
└─────────────────────────┴─────────────────────────────┘
```

### Rule of thumb

> Mock at the **edges** (I/O, time, randomness, third-party APIs). Use the **real implementation** for everything inside your domain.

```
WITHOUT this rule (over-mocking):
┌────────────────────────────────────────────────────┐
│ Test mocks every dependency — even pure logic      │
│ → Test reads like the implementation               │
│ → Refactoring a private method breaks 50 tests     │
│ → Tests give false confidence                      │
└────────────────────────────────────────────────────┘

WITH this rule:
┌────────────────────────────────────────────────────┐
│ Test the real OrderService with real domain logic │
│ Only IPaymentGateway (external HTTP) is mocked    │
│ → Test reads like the spec                         │
│ → Internal refactor doesn't break the test         │
│ → Confidence is honest                             │
└────────────────────────────────────────────────────┘
```

### TimeProvider (.NET 8+) — the End of `DateTime.UtcNow` Pain

```csharp
// ❌ Old: untestable
public bool IsExpired(DateTime expiresAt) => DateTime.UtcNow > expiresAt;

// ✅ New: inject TimeProvider
public class TokenService(TimeProvider time)
{
    public bool IsExpired(DateTime expiresAt) => time.GetUtcNow() > expiresAt;
}

// Test:
var fakeTime = new FakeTimeProvider();
fakeTime.SetUtcNow(new DateTimeOffset(2026, 5, 8, 12, 0, 0, TimeSpan.Zero));
var svc = new TokenService(fakeTime);
fakeTime.Advance(TimeSpan.FromHours(2));
Assert.True(svc.IsExpired(DateTime.UtcNow.AddHours(1)));
```

`Microsoft.Extensions.TimeProvider.Testing` (FakeTimeProvider) ships with .NET 8+.

---

## Test Data Builders

A **builder** is a fluent helper that produces realistic test entities without bloating each test with object initialisation.

```csharp
public class OrderBuilder
{
    private int    _id     = 1;
    private decimal _total = 100m;
    private string _status = "Pending";
    private List<OrderLine> _lines = new();

    public OrderBuilder WithId(int id)          { _id = id; return this; }
    public OrderBuilder WithTotal(decimal t)    { _total = t; return this; }
    public OrderBuilder WithStatus(string s)    { _status = s; return this; }
    public OrderBuilder WithLine(string sku, int qty, decimal price)
    {
        _lines.Add(new OrderLine(sku, qty, price)); return this;
    }
    public OrderBuilder Cancelled() => WithStatus("Cancelled");
    public OrderBuilder Paid()      => WithStatus("Paid");

    public Order Build() => new()
    {
        Id     = _id,
        Total  = _total,
        Status = _status,
        Lines  = _lines
    };

    public static implicit operator Order(OrderBuilder b) => b.Build();
}
```

```csharp
[Fact]
public async Task CancelPaidOrder_ReturnsError()
{
    Order order = new OrderBuilder().Paid().WithTotal(500m);
    var result  = await _svc.CancelAsync(order);
    result.IsSuccess.Should().BeFalse();
}
```

### Properties

```
┌─────────────────────────────────────────────────────────┐
│ TEST DATA BUILDER Properties                            │
├─────────────────────────────────────────────────────────┤
│ ✓ Each test states only what's RELEVANT                 │
│ ✓ Defaults supply the rest of a valid object            │
│ ✓ Refactoring entity = one builder change, not 200 tests│
│ ✓ Reads like English ("Cancelled order with total 500") │
│ ✗ Yet another file to maintain                          │
│ ✗ Easy to over-engineer (don't build for unused fields) │
└─────────────────────────────────────────────────────────┘
```

For complex graphs, **AutoFixture** generates random-but-valid data automatically — `var order = new Fixture().Create<Order>();`.

---

## Integration Testing with WebApplicationFactory

`WebApplicationFactory<TEntryPoint>` (in `Microsoft.AspNetCore.Mvc.Testing`) spins up your real ASP.NET Core app in-process and gives you an `HttpClient`. No port binding, no real network — but the full pipeline (auth, routing, model binding, EF) is exercised.

```csharp
public class OrdersApiTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly WebApplicationFactory<Program> _factory;

    public OrdersApiTests(WebApplicationFactory<Program> factory)
    {
        _factory = factory.WithWebHostBuilder(builder =>
        {
            builder.UseEnvironment("Testing");
            builder.ConfigureServices(services =>
            {
                // Replace real payment gateway with a fake
                services.RemoveAll<IPaymentGateway>();
                services.AddSingleton<IPaymentGateway, InMemoryPaymentGateway>();
            });
        });
    }

    [Fact]
    public async Task Post_ValidOrder_Returns201()
    {
        var client = _factory.CreateClient();
        var resp = await client.PostAsJsonAsync("/api/orders",
            new CreateOrderDto { Total = 100m });

        resp.StatusCode.Should().Be(HttpStatusCode.Created);
        resp.Headers.Location.Should().NotBeNull();
    }

    [Fact]
    public async Task Get_NonExistent_Returns404()
    {
        var client = _factory.CreateClient();
        var resp = await client.GetAsync("/api/orders/99999");
        resp.StatusCode.Should().Be(HttpStatusCode.NotFound);
    }
}
```

```
┌─────────────────────────────────────────────────────────┐
│ INTEGRATION TEST Properties                             │
├─────────────────────────────────────────────────────────┤
│ ✓ Exercises the FULL HTTP pipeline                      │
│ ✓ Catches DI misconfiguration, routing bugs, JSON quirks│
│ ✓ Replaces only what you NEED to (auth, payments)       │
│ ✓ ~100ms per test once factory warmed up                │
│ ✗ Slower than unit tests                                │
│ ✗ Shared state via singletons can leak between tests    │
│ ✗ Class fixture rebuilds the host once — be aware       │
└─────────────────────────────────────────────────────────┘
```

### Replacing Authentication for Tests

```csharp
builder.ConfigureServices(s =>
{
    s.AddAuthentication("Test")
     .AddScheme<AuthenticationSchemeOptions, TestAuthHandler>("Test", _ => { });
});

// TestAuthHandler always issues a "test-user" identity with claims
// driven by the request — see Microsoft.AspNetCore.TestHost samples.
```

---

## TestContainers — Real Databases in Tests

In-memory EF Core (`UseInMemoryDatabase`) is *not* a real database. It doesn't enforce constraints, doesn't have transactions, doesn't support real SQL. It's fine for early-stage tests; for confidence, you want the *actual* database engine.

**TestContainers for .NET** (`Testcontainers.MsSql`, `Testcontainers.PostgreSql`, `Testcontainers.Redis`, etc.) spins up Docker containers programmatically.

```csharp
public class DbFixture : IAsyncLifetime
{
    private readonly MsSqlContainer _container = new MsSqlBuilder()
        .WithPassword("yourStrongPassword123!")
        .Build();

    public AppDbContext Db { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        await _container.StartAsync();

        var opts = new DbContextOptionsBuilder<AppDbContext>()
            .UseSqlServer(_container.GetConnectionString())
            .Options;

        Db = new AppDbContext(opts);
        await Db.Database.MigrateAsync();
    }

    public async Task DisposeAsync()
    {
        await Db.DisposeAsync();
        await _container.DisposeAsync();
    }
}

[Collection("Database")]
public class OrderRepoIntegrationTests : IClassFixture<DbFixture>
{
    private readonly DbFixture _fx;
    public OrderRepoIntegrationTests(DbFixture fx) => _fx = fx;

    [Fact]
    public async Task Save_ThenLoad_RoundTripsCorrectly()
    {
        var repo  = new OrderRepository(_fx.Db);
        var order = new OrderBuilder().WithTotal(123m).Build();

        await repo.SaveAsync(order);
        var loaded = await repo.GetByIdAsync(order.Id);

        loaded.Should().BeEquivalentTo(order);
    }
}
```

```
┌─────────────────────────────────────────────────────────┐
│ TESTCONTAINERS Properties                               │
├─────────────────────────────────────────────────────────┤
│ ✓ REAL database engine — same as production             │
│ ✓ Constraints, transactions, dialects — all exercised   │
│ ✓ Auto-cleanup on test exit                             │
│ ✓ Parallel-safe (each container gets a unique port)     │
│ ✗ Requires Docker on dev machines and CI agents         │
│ ✗ Container startup adds ~3-10s to test run             │
│ ✗ Resource hungry — limit parallelism                   │
└─────────────────────────────────────────────────────────┘
```

> Use TestContainers for the **repository layer** and any test where SQL behaviour matters. For business-logic tests with no SQL specifics, in-memory is fine — speed beats fidelity when fidelity isn't tested.

---

## Common Pitfalls

### 1. Tests That Pass Locally and Fail in CI (or Vice Versa)

```
Symptoms: "It works on my machine"
Causes:
├─ Hidden dependency on local file paths or env vars
├─ Tests assume a specific time zone, locale, or culture
├─ Order-dependent tests (test A leaves state for test B)
└─ Race conditions in async tests

Fix:
├─ Use InvariantCulture in tests when locale isn't the SUT
├─ Reset shared state in IDisposable.Dispose
└─ Treat test order as random (xUnit does by default)
```

### 2. Async Tests That Don't Await

```csharp
// ❌ Returns Task immediately — never asserts
[Fact]
public Task Foo() => _svc.DoAsync().ContinueWith(t => Assert.True(false));

// ✅ Await it
[Fact]
public async Task Foo()
{
    await _svc.DoAsync();
    Assert.True(false);
}
```

If the framework sees a returned `Task`, it awaits — but only if the method *returns* it. `.Wait()` and `.Result` deadlock under sync contexts; never use them in tests.

### 3. Mocking What You Don't Own

Mocking `HttpClient`, `DbContext`, or `Stream` directly is brittle (their interfaces change, methods are non-virtual). Wrap them behind your *own* interface and mock that.

### 4. Verifying Implementation Instead of Behaviour

```csharp
// ❌ Couples test to call order — refactor breaks test
mockRepo.Verify(r => r.Validate(), Times.Once);
mockRepo.Verify(r => r.Save(),     Times.Once);
mockRepo.Verify(r => r.Audit(),    Times.Once);

// ✅ Verify only the OUTCOME the consumer cares about
result.IsSuccess.Should().BeTrue();
result.OrderId.Should().BePositive();
```

### 5. Shared Mutable State Between Tests

```csharp
private static List<Order> _orders = new(); // ❌ leaks across tests
```

xUnit creates a new test class instance per test, so instance fields are safe. Static fields are not — never put mutable state on a static.

### 6. Tests That Assert Multiple Unrelated Things

Already covered: each test = one logical behaviour.

### 7. "Test-Induced Damage" — Public API for Tests Only

```csharp
// ❌ Method exists ONLY so a test can poke it
public void __ResetForTests() { ... }
internal int InternalCounter; // exposed via InternalsVisibleTo

// ✅ If a test needs internal state, your design has a smell — refactor
```

### 8. Asserting on Logs

Logging is observability, not a contract. If you assert "logger received 'order created'", any change to the log message breaks the test. Use structured logging + integration tests over a log sink instead.

### 9. Sleeping in Tests

```csharp
await Task.Delay(1000);   // ❌ flaky, slow
```

Use `FakeTimeProvider` (real abstraction over time), `await` on a `TaskCompletionSource`, or polling with timeout — never raw delays.

### 10. Unit-Testing the Framework

```csharp
[Fact]
public void Add_ReturnsSum() => Assert.Equal(3, 1 + 2); // ❌ tests the JIT, not your code
```

You don't need to test that EF Core saves data, that `int.Parse` parses, that the framework's serializer round-trips. Test *your* logic.

### 11. WebApplicationFactory Database Pollution

If two integration tests share the same fixture and one leaves data behind, the second sees it. Either reset between tests (transaction-rollback or re-create DB), or write tests that *expect* the seeded state.

### 12. Snapshot Tests on Volatile Output

Snapshot/Verify tests are powerful but fragile if output includes timestamps, GUIDs, or floating-point. Scrub volatile fields before comparison.

---

## Best Practices

1. **Pyramid shape: ~70% unit, ~25% integration, ~5% E2E.** Adjust by team and product, but never invert.
2. **Test behaviour, not implementation.** A test should survive any refactor that doesn't change the public contract.
3. **One logical assertion per test.** Multiple `Assert` lines for one behaviour is fine; multiple unrelated behaviours is not.
4. **Name tests as full sentences.** `Method_Scenario_ExpectedResult`.
5. **Mock at I/O boundaries; use real domain code.** Internal classes don't need mocks.
6. **Inject `TimeProvider`, never call `DateTime.UtcNow` directly.** (.NET 8+ standard.)
7. **Use FluentAssertions** for readable failures.
8. **Use builders or AutoFixture** to keep tests focused on what's relevant.
9. **For HTTP, use `WebApplicationFactory`** — never spin up a real Kestrel host in tests.
10. **For SQL, use TestContainers** when DB behaviour matters; in-memory otherwise.
11. **Run tests in parallel** by default; use `[Collection]` only when state must be serialised.
12. **Treat test code as production code** — review it, refactor it, keep it clean.
13. **CI: fail fast on flaky tests.** Quarantine and fix; never `[Skip]` indefinitely.
14. **Coverage is a *lagging* indicator.** Don't chase 100%; chase confident refactors.
15. **A red test is a *gift*.** Never silence a failing test — fix the bug or fix the test.

---

## Real-World Scenarios

### Scenario 1: Testing a Controller (Integration Style)

**Question:** Where do I draw the line — unit-test the controller, or integration-test the API?

**Recommendation:** *Integration test the route.* A controller is mostly thin glue (model binding, DI resolution, returning `IActionResult`). Unit-testing it means mocking everything around it and asserting "this controller calls this service" — low value. An integration test against `WebApplicationFactory` exercises *the same things* a unit test would, plus the framework wiring, for ~10x the value at ~3x the time.

```csharp
[Fact]
public async Task Post_ValidOrder_PersistsAndReturns201()
{
    var client = _factory.CreateClient();
    var resp = await client.PostAsJsonAsync("/api/orders",
        new CreateOrderDto { Total = 50m });

    resp.StatusCode.Should().Be(HttpStatusCode.Created);
    var loc = resp.Headers.Location!.ToString();
    loc.Should().StartWith("/api/orders/");

    // Verify side effect via the real DB (TestContainers fixture)
    using var scope = _factory.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Orders.Should().HaveCount(1);
}
```

If a controller has *complex logic* (rare and a smell), unit-test that logic in a separate class.

### Scenario 2: Testing a BackgroundService

**Question:** A worker drains a queue and processes messages. How do I test it?

**Approach:**

```csharp
[Fact]
public async Task ExecuteAsync_OnMessage_InvokesHandler()
{
    // Arrange — fake queue with a single message
    var queue   = Substitute.For<IOrderQueue>();
    queue.DequeueAsync(Arg.Any<CancellationToken>())
         .Returns(new OrderMessage { Id = 1 }, _ => throw new OperationCanceledException());

    var handler = Substitute.For<IOrderHandler>();

    // Real ServiceProvider with our fakes
    var sp = new ServiceCollection()
        .AddSingleton(queue)
        .AddScoped(_ => handler)
        .BuildServiceProvider();

    var worker = new OrderProcessingWorker(
        sp.GetRequiredService<IServiceScopeFactory>(),
        NullLogger<OrderProcessingWorker>.Instance);

    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));

    // Act — start, let it run one iteration, stop
    await worker.StartAsync(cts.Token);

    // Assert
    await handler.Received(1).HandleAsync(
        Arg.Is<OrderMessage>(m => m.Id == 1), Arg.Any<CancellationToken>());
}
```

**Key idea:** You're not testing `BackgroundService`'s lifecycle — Microsoft tested that. You're testing *your code inside `ExecuteAsync`*. Provide a way to make the loop terminate (cancellation, throw on second `Dequeue`).

### Scenario 3: Testing Data Access (Repository + EF Core)

**Question:** In-memory DB or real DB?

**Recommendation:**
- **For repositories with non-trivial SQL** (joins, raw SQL, stored procs, JSON columns, computed columns, triggers): **real DB via TestContainers.** In-memory will lie to you.
- **For business services that just persist and reload entities**: **in-memory** is fine — the SQL semantics aren't what you're testing.

```csharp
// Mixed approach: same repository tested two ways
[Collection("Database")]   // shared real-DB fixture
public class OrderRepoIntegrationTests : IClassFixture<DbFixture> { /* TestContainers */ }

public class OrderRepoLogicTests
{
    private static AppDbContext NewInMemoryDb() =>
        new(new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString()).Options);

    [Fact]
    public async Task Save_AssignsId()
    {
        await using var db = NewInMemoryDb();
        var repo  = new OrderRepository(db);
        var order = new OrderBuilder().Build();

        await repo.SaveAsync(order);

        order.Id.Should().BePositive();
    }
}
```

### Scenario 4: A Flaky Test in CI

**Symptom:** Test passes 9/10 runs in CI, fails 1/10 in a way that can't be reproduced locally.

**Diagnosis checklist:**

```
1. Is the test order-dependent?         → randomise order, use isolated fixtures
2. Async race?                          → search for missing await, fire-and-forget
3. Time/clock drift?                    → mock TimeProvider
4. External dependency (DNS, network)?  → mock at the boundary
5. Static / shared state?               → reset between tests
6. CI agent under load?                 → reduce parallelism or extend timeouts
7. Test relies on a specific port?      → use ephemeral ports
```

**Action:** Quarantine the test (move to a "flaky" trait), file a ticket, fix or delete within the sprint. Never let flaky tests poison the green-build culture.

### Scenario 5: Testing a Resilience Pipeline

**Question:** I've added Polly retry/circuit-breaker. How do I test it without waiting real seconds?

**Approach:** Inject `TimeProvider` (Polly v8 supports this), fake the underlying handler, and verify the number of attempts.

```csharp
[Fact]
public async Task Retries_ThreeTimes_OnTransientFailure()
{
    var calls = 0;
    var handler = new FakeHandler(_ =>
    {
        calls++;
        return new HttpResponseMessage(HttpStatusCode.ServiceUnavailable);
    });

    var time = new FakeTimeProvider();
    var pipeline = new ResiliencePipelineBuilder<HttpResponseMessage>()
        .AddRetry(new() { MaxRetryAttempts = 3, Delay = TimeSpan.FromSeconds(1), TimeProvider = time })
        .Build();

    var task = pipeline.ExecuteAsync(async _ =>
        await handler.SendAsync(new HttpRequestMessage(HttpMethod.Get, "http://x"), default));

    // advance virtual time past every backoff window
    time.Advance(TimeSpan.FromSeconds(5));
    await task;

    calls.Should().Be(4); // initial + 3 retries
}
```

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Test pyramid

> **Q**: What's the rough proportion of tests in a healthy pyramid?
>
> **A**: ~70% unit, ~25% integration, ~5% end-to-end. Unit tests are the wide fast base; integration tests verify components together (DB, HTTP); E2E exercises full user journeys but is slow and brittle, so it's the thin tip.
>
> **Cross-Q**: Why not just write more integration tests — they catch more bugs per test?
>
> **A**: Because they're slow and they obscure failures. A failing integration test tells you "something in this 10-component path is broken"; a failing unit test tells you "this method's input X returns Y when it should return Z." Diagnosis time skyrockets when you over-rely on integration. Plus they're harder to run during refactor (5min suite vs 30 seconds), so devs run them less, and the feedback loop collapses.
>
> **Cross-Q²**: An "ice-cream cone" team has 80% manual E2E. Why is that the worst shape?
>
> **A**: Because manual tests scale linearly with people, not features. Every new feature requires more QA time on every release. They're flaky (humans are inconsistent), they're slow (a release week is the test cycle), and they have no version control (institutional knowledge walks out when QAs leave). The fix is brutal: invest in unit + integration aggressively, accept that for 6-12 months velocity drops, then enjoy a sustainable shape.

### Drill 2 — Unit test isolation

> **Q**: How strict is "isolation" in a unit test?
>
> **A**: No I/O — no DB, no file system, no network, no real time, no real randomness. The SUT runs against test doubles for every external dependency. Other classes in your own domain can be real (don't over-mock).
>
> **Cross-Q**: My unit test instantiates a real `Order` and `Customer` from my domain. Is that still a unit test?
>
> **A**: Yes. The "unit" is a logical behaviour, not a single class. If `OrderService` collaborates with `Order` and `Customer` (pure domain objects with no I/O), exercising all three in one test is still unit-level. The boundary is **I/O**, not **class count**. Over-mocking the domain ("mock the Customer to return a Customer") makes tests fragile to refactor and gives false confidence.
>
> **Cross-Q²**: What about `DateTime.UtcNow` inside the SUT — does my unit test break isolation?
>
> **A**: Yes — calling `DateTime.UtcNow` ties the test to real time, making it non-deterministic (a test about "is the token expired?" depends on when the test runs). Fix: inject `TimeProvider` (built into .NET 8+) and use `FakeTimeProvider` in tests to set/advance time. Same for `Random` (inject `IRandomProvider`), `Guid.NewGuid()` (inject `IGuidProvider`), and ambient context like `HttpContext` (inject `IHttpContextAccessor` and fake it).

### Drill 3 — Integration vs unit boundary

> **Q**: Where's the line between an integration test and a unit test?
>
> **A**: **A unit test has no real I/O; an integration test has at least one real I/O boundary.** Real DB, real HTTP client to a test server, real file system, real message broker (test container) — anything that takes more than CPU. Speed is the side effect: unit is 1-10ms, integration is 100ms-5s.
>
> **Cross-Q**: Is a test using EF Core's in-memory provider a unit or integration test?
>
> **A**: Gray area. The provider is in-process, so "no real I/O" is technically true. But you're crossing the EF Core boundary (LINQ → query compiler → in-memory store) — there's framework code being exercised. Most teams call it integration-style (because it tests EF integration, even if fake) but classify under unit speed. Either label works as long as you don't think it tests real SQL semantics (it doesn't — see Drill 6).
>
> **Cross-Q²**: I use `WebApplicationFactory` with mocked dependencies — unit or integration?
>
> **A**: Integration. You're exercising the real ASP.NET Core pipeline (routing, model binding, filters, middleware), even if your domain services are fakes. The framework wiring is the *integration* being tested. Calling it "unit" would mislead reviewers about what the test proves.

### Drill 4 — `WebApplicationFactory<TStartup>`

> **Q**: What does `WebApplicationFactory<TEntryPoint>` actually create?
>
> **A**: A full in-process ASP.NET Core host using `TestServer` instead of Kestrel — no port binding, no real socket — and an `HttpClient` that talks to it via an in-memory `HttpMessageHandler`. The full pipeline runs (auth, routing, middleware, EF), giving you an integration test without network overhead.
>
> **Cross-Q**: When does the factory build the host — per test, per class, or per test run?
>
> **A**: Once per `IClassFixture<WebApplicationFactory<Program>>` instance. The factory is the fixture, and xUnit creates it once for the class, reusing across `[Fact]`s in that class. To get a fresh host per test, instantiate `new WebApplicationFactory<Program>()` in each test (slower but isolated). Per test run requires `ICollectionFixture<>` to share across multiple test classes.
>
> **Cross-Q²**: I'm replacing `IPaymentGateway` with a fake via `ConfigureServices`. Why does my replacement only work sometimes?
>
> **A**: Because `services.RemoveAll<IPaymentGateway>()` only removes if it was already registered. If the production registration happens *after* your `ConfigureServices` override (e.g., a startup extension method runs later in the host builder), your removal predates the registration and the real one wins. Fix: register your fake using `services.Replace(ServiceDescriptor.Singleton<IPaymentGateway, FakeGateway>())` *or* ensure your `WithWebHostBuilder` runs after the host's default registration (it does by default, but verify with a breakpoint).

### Drill 5 — TestContainers

> **Q**: When do you use TestContainers over EF Core's in-memory provider?
>
> **A**: When the test needs **real SQL semantics**: constraints, transactions, JSON columns, computed columns, triggers, stored procedures, raw SQL, dialect-specific behavior (e.g., Postgres array types). In-memory is a LINQ-to-Objects facade — it doesn't enforce uniqueness constraints, doesn't honor transactions, doesn't validate FK references.
>
> **Cross-Q**: What's the cost of TestContainers?
>
> **A**: ~3-10 seconds per container startup (depends on image, machine, Docker layer cache). Image pulls on first run can be minutes. Plus ~50-200MB memory per running container. Mitigated by sharing one container across many tests with `ICollectionFixture<>`, and by using lightweight images (alpine variants, Testcontainers' own minimized images). Docker must be on every dev machine and CI agent — a real ops requirement.
>
> **Cross-Q²**: My tests work locally with TestContainers but fail in CI with "Cannot connect to Docker daemon." Why?
>
> **A**: CI agent doesn't have Docker, or doesn't grant the test process access to it (rootless Docker, permissions). The fix depends on CI: GitHub Actions and Azure DevOps have official Docker support on ubuntu-latest images. Self-hosted agents need Docker installed and the agent user in the docker group. Or: use a Docker-in-Docker sidecar; or run tests in containers themselves with a shared Docker socket. Always: validate Docker availability in CI before relying on TestContainers.

### Drill 6 — EF Core in-memory danger

> **Q**: Why is the EF Core In-Memory provider dangerous?
>
> **A**: It doesn't enforce database semantics. Unique constraints don't apply (you can insert two rows with the same "unique" key). Foreign keys aren't enforced. Transactions are no-ops. `SaveChanges` always succeeds. Raw SQL fails. JSON column queries fail. It's a LINQ-to-Objects store wearing a DbContext costume. Tests pass; production breaks on the first INSERT with a real constraint.
>
> **Cross-Q**: What about SQLite as a test database — same trap?
>
> **A**: SQLite is a real database, so transactions and constraints work. But its dialect differs from SQL Server/Postgres — different DATE arithmetic, no schemas, looser type system (integer column accepts strings). For testing logic that doesn't touch dialect-specific SQL, SQLite is fine. For testing your actual prod-dialect SQL, only TestContainers matches.
>
> **Cross-Q²**: Microsoft says "for testing your own logic, in-memory is fine." When is that actually true?
>
> **A**: When the test exercises **business logic only**, with the DB as a simple "save object, load object" passthrough. If your business rule is "Order.IsValid() returns false when Lines is empty," that's pure C# — the DB doesn't matter. In-memory works. But if your repository has "Where(o => o.CreatedAt > @yesterday)," and your prod DB stores dates differently, in-memory's date semantics may pass while prod fails. Rule: in-memory for application service tests; real DB (TestContainers) for repository/persistence tests.

### Drill 7 — Mocking concretes

> **Q**: Why mock interfaces and not concrete classes?
>
> **A**: Because Moq, NSubstitute, etc. use runtime proxy generation (Castle.DynamicProxy) — they intercept virtual methods on classes you give them. **Interfaces are 100% virtual**, so every method is mockable. **Concrete classes** have non-virtual methods by default; the proxy can only override `virtual` and `abstract` ones — sealed methods, static methods, and non-virtual methods are not interceptable.
>
> **Cross-Q**: What if my class has a virtual method — can I mock just that?
>
> **A**: Yes, but it's brittle. The mock can override the virtual method; non-virtual methods on the same class still call real logic. The mock's behavior is a hybrid: some methods mocked, others real, with no clear boundary. This is the "partial mock" antipattern — usually a sign the class should have been an interface or composed differently.
>
> **Cross-Q²**: What about `sealed` classes from third-party libraries (HttpClient, DateTime)?
>
> **A**: You can't mock them. The solution: **wrap them in your own interface** (`IClock { DateTime UtcNow {get;} }`, `IHttpExecutor { Task<HttpResponse> SendAsync(...) }`) and mock the wrapper. .NET 8 fixed this for time specifically (`TimeProvider`, mockable via `FakeTimeProvider`) and for HTTP via `IHttpClientFactory` + `HttpMessageHandler` mocking. For other sealed types: wrap, don't fight.

### Drill 8 — AAA pattern

> **Q**: What does the AAA pattern require and forbid?
>
> **A**: **Arrange** — set up state and dependencies. **Act** — invoke the single behavior under test (ideally one line). **Assert** — verify the outcome. Forbidden: mixing — no setting up new mocks between asserts, no asserting partway through the act, no acting twice.
>
> **Cross-Q**: My test has 30 lines of arrange — bad smell?
>
> **A**: Often yes. Either the SUT has too many dependencies (refactor to fewer collaborators or smaller scope), or the arrange should move to a `TestDataBuilder` (`OrderBuilder().Cancelled().WithTotal(50).Build()`). 30 lines means a future reader spends most of their time understanding setup, not the actual behavior being tested. Builders make tests state "give me a cancelled order with total 50" — the irrelevant defaults stay invisible.
>
> **Cross-Q²**: Where do edge-case assertions like "no side effects" fit in AAA?
>
> **A**: In Assert. "Verify SendEmail was never called" is part of the outcome — the test asserts "given an invalid order, the email service was NOT invoked." Pattern: `_emailMock.Verify(e => e.Send(It.IsAny<Email>()), Times.Never)` after the Act line. The structure stays clean: three phases, all verifications in the third.

### Drill 9 — Async test deadlock

> **Q**: How do you avoid deadlocks in async tests?
>
> **A**: Always `await`. Never `.Result`, never `.Wait()`, never `.GetAwaiter().GetResult()`. In a unit test runner, there's no SynchronizationContext to deadlock (xUnit's default test execution is on the thread pool), but mixing sync-over-async in code-under-test still risks deadlocks in production. So even though the test might pass with `.Result`, you're testing broken patterns.
>
> **Cross-Q**: My test method is `async void`. Why is that wrong?
>
> **A**: `async void` is fire-and-forget — exceptions are raised on the synchronization context, not awaited. The test runner sees the method "complete" immediately when it hits the first `await`, and reports success even if the test would have failed. Use `async Task` for test methods; xUnit awaits them.
>
> **Cross-Q²**: I have `[Fact] public Task Foo() => _svc.DoAsync().ContinueWith(t => Assert.True(false));` — bug?
>
> **A**: Yes, subtle. The returned Task is the *continuation* — Assert.True(false) runs after DoAsync completes. But the inner Assert exception is wrapped in `AggregateException` by `ContinueWith`, and xUnit unwraps differently. Worse: if DoAsync throws, you never reach Assert and the test reports the original exception, not your intended assertion. Use `await` and explicit assertion: `await _svc.DoAsync(); Assert.True(false);`.

### Drill 10 — Test data builders

> **Q**: When is a test data builder worth the ceremony?
>
> **A**: When the same entity is built in 10+ tests with slight variations. The builder centralizes the "valid baseline" and lets each test state only what differs. Below ~5 usages, inline construction is cheaper than maintaining a builder. Past 10, the builder pays for itself in readability and refactor safety.
>
> **Cross-Q**: How do builders compare to AutoFixture?
>
> **A**: Builders are explicit and named: `new OrderBuilder().Cancelled().Build()` reads like a spec. AutoFixture is implicit and random: `fixture.Create<Order>()` returns a "valid" Order with random fields. AutoFixture wins for tests where field values don't matter (just need *some* Order); builders win for tests where field values are part of the scenario. Often both in the same codebase: AutoFixture for "throwaway" objects, builders for domain-significant ones.
>
> **Cross-Q²**: I see `public static implicit operator Order(OrderBuilder b) => b.Build();` — why?
>
> **A**: Syntactic sugar — lets callers write `Order order = new OrderBuilder().Paid();` without the explicit `.Build()`. Some teams love it (less noise); others hate it (hidden conversion, surprises readers). Both work. The conversion is one-directional (Builder → Order), so there's no risk of misuse going the other way.

### Drill 11 — `[Theory]` vs `[Fact]`

> **Q**: When should I prefer `[Theory]` over multiple `[Fact]`s?
>
> **A**: When the test body is identical and only inputs vary — parameter validation, boundary conditions, arithmetic edge cases. `[InlineData(0)] [InlineData(-1)] [InlineData(int.MaxValue)]` plus one `[Theory]` body is far cleaner than three near-duplicate `[Fact]`s. Keeps DRY without hiding test names — each row becomes its own test case in output.
>
> **Cross-Q**: When does `[Theory]` become wrong?
>
> **A**: When the cases share *inputs* but have *different assertion logic*. Forcing them into one theory body with `if (input == "x") Assert.Foo() else Assert.Bar()` is worse than two `[Fact]`s — the test body becomes a switch statement. Theory shines for "same assertion, different inputs"; not "different inputs, different outcomes."
>
> **Cross-Q²**: `[InlineData]` vs `[MemberData]` vs `[ClassData]` — pick when?
>
> **A**: **`[InlineData]`** for small, hardcoded primitives — 2-10 simple cases. **`[MemberData]`** for cases referencing complex objects, computed values, or shared across multiple theories (`public static IEnumerable<object[]> Invalid => ...`). **`[ClassData]`** for very large datasets where a separate class organizes test data (think: a hundred locale-specific test cases). Default to `[InlineData]`; reach for `[MemberData]` when you need to share or compute.

### Drill 12 — xUnit vs NUnit vs MSTest

> **Q**: How do xUnit, NUnit, and MSTest compare on collection/shared fixtures?
>
> **A**: **xUnit**: per-test class instance by default (no shared state by accident), `IClassFixture<T>` for class-level sharing, `ICollectionFixture<T>` + `[Collection("name")]` for cross-class sharing. **NUnit**: instance reused across tests in the class by default (must reset state in `[SetUp]`), `[OneTimeSetUp]`/`[OneTimeTearDown]` for class-level. **MSTest**: similar to NUnit, `[TestInitialize]`/`[ClassInitialize]`/`[AssemblyInitialize]` for tiered setup.
>
> **Cross-Q**: Which is the best fit for a new .NET 8+ project?
>
> **A**: xUnit, by team consensus. Its design forces good habits (new instance per test = no shared state surprises, constructors instead of magic attributes). NUnit is more flexible (`[TestCase]`, theories, action attributes) but the default behavior favors shared state. MSTest has Microsoft backing and good IDE integration but is least feature-rich. Most new projects pick xUnit; legacy MSTest/NUnit teams stay with what they have.
>
> **Cross-Q²**: Can I run xUnit tests in parallel by default?
>
> **A**: Yes — xUnit parallelizes across test classes by default. Within a class, tests run sequentially. To force serial across classes, use `[Collection("name")]` to group them (collection members run serially, classes outside any collection run in parallel). To go further: `[CollectionDefinition("name", DisableParallelization = true)]`. The trade-off: parallel exposes shared-state bugs (good!) but can saturate CI agents (set `dotnet test --max-parallel-threads` if needed).

### Drill 13 — Test naming

> **Q**: When does `MethodName_State_Expected` beat plain English test names?
>
> **A**: When tests are auto-listed alphabetically in CI output and you scan failures by name. `Withdraw_AmountExceedsBalance_ThrowsInsufficientFundsException` tells you at a glance: which method, which scenario, what should happen. Plain English ("should not allow over-drawing") makes failures harder to triage at scale.
>
> **Cross-Q**: When does plain English win?
>
> **A**: When tests are read in narrative order, not alphabetical (e.g., behavior-spec style, BDD-flavored teams). "Given a cancelled order, when I try to ship it, then I get an error" reads like spec. Tools like SpecFlow or Reqnroll make this natural via Gherkin. The naming style is a culture fit, not a hard rule.
>
> **Cross-Q²**: What about `Should_ThrowException_WhenBalanceTooLow`?
>
> **A**: The "Should" prefix is divisive. Pro: emphasizes intent ("the system should..."). Con: every test name starts with "Should," wasting scanning bandwidth and making alphabetical sort useless. Most modern .NET teams drop the prefix and use `MethodName_State_Expected`. Whichever you pick, **be consistent across the codebase** — mixing styles is the actual problem.

### Drill 14 — Flaky tests

> **Q**: What are the common sources of test flakiness?
>
> **A**: **Time-dependent code** (test passes when run "fast enough"). **Shared state** (test A leaves data, test B reads it). **Async races** (test asserts before background work completes). **External dependencies** (DNS, network, real DB). **Order dependency** (test passes only if A runs before B). **Resource exhaustion** (port collisions, file locks, container limits).
>
> **Cross-Q**: What's the triage process?
>
> **A**: (1) Reproduce: run the test in a loop locally. If it passes 100/100, it's environmental; if it fails sometimes, it's a code issue. (2) Quarantine: tag with a `Flaky` trait so CI doesn't fail on it. (3) Diagnose: time? state? async? — pick one hypothesis, instrument, retest. (4) Fix or delete within the sprint. **Never** indefinitely-skip a flaky test — it's a bug surface that gets ignored.
>
> **Cross-Q²**: Is there a category of test that's inherently flaky, no matter what?
>
> **A**: End-to-end browser tests against real systems can be inherently flaky — network blips, browser quirks, animation timing. Mitigations: Playwright's auto-retry with smart waits (waits for elements, not arbitrary timeouts), record-and-replay for video debugging, run in headless on consistent hardware. Accept ~5-10% flake rate as baseline and budget retries. Below that rate: brittleness; above: re-evaluate the test value.

### Drill 15 — Contract testing

> **Q**: What does contract testing (Pact) solve that integration testing doesn't?
>
> **A**: Cross-service compatibility *without* deploying both services together. Integration test of service A against service B requires running B in test mode and hitting it — expensive, brittle, slow. Contract test: A records its expectations of B's API (the "consumer contract"); B verifies the contract against its real implementation in B's own test suite. Both can deploy independently with confidence.
>
> **Cross-Q**: How does Pact share contracts between teams?
>
> **A**: Via a Pact Broker (a server that stores contract versions and verification results). Consumer's CI publishes contracts after running consumer tests. Provider's CI fetches the contract, verifies against its API, publishes the result. The broker shows compatibility matrices: "consumer v3 is compatible with provider v7." `Can I deploy?` API answers "given consumer v3 and provider v7, are they compatible?" before a release.
>
> **Cross-Q²**: When does contract testing NOT help?
>
> **A**: When the contract is fully captured by an OpenAPI/gRPC schema and you validate at build time (schema-driven testing). Contract testing adds value when contracts have behavioral expectations beyond schema — "if I POST this, I expect a 201 with a Location header" — that schema-only tools miss. Also: contract testing requires both sides to participate (publish + verify); if you don't own the provider's CI, it doesn't work. Public APIs use OpenAPI + integration; internal microservices use Pact.

---

</details>

---

## Self-Test

<details>
<summary>1. Why is <code>UseInMemoryDatabase</code> almost always the wrong test double for a repository test?</summary>

Because the in-memory provider is not a relational database — it is a LINQ-over-objects store wearing a `DbContext` costume, and the guarantees a repository leans on are exactly the ones it drops. Microsoft's own EF Core testing guidance calls using it as a database fake "highly discouraged" and supported only for legacy applications. Concretely: raw SQL is completely unsupported; transactions are not supported (starting one raises `InMemoryEventId.TransactionIgnoredWarning`, which throws by default — and the usual "fix" is to silence that warning, after which a rollback rolls nothing back); provider-specific translations such as `EF.Functions.*` do not exist; alternate-key/unique and foreign-key constraints are not enforced; and query results can differ from production because the operators execute in .NET, not in your engine — SQL Server compares strings case-insensitively under the default collation, in-memory does not.

The failure shape is a green suite followed by a production incident: the first insert is rejected by a real constraint, the raw-SQL path throws, or a compensating rollback silently compensates nothing. Use TestContainers — a real engine, same as production — wherever SQL behaviour *is* the thing under test: constraints, transactions, joins, JSON and computed columns, raw SQL. Microsoft's preferred cheap fake is SQLite in-memory, which at least gives real transactions and constraints, though its dialect still differs from SQL Server or Postgres. In-memory is defensible only when the database is a pass-through and the assertion is about business logic.
</details>

<details>
<summary>2. My integration tests pass one at a time and fail when the whole class runs. What is the mechanism?</summary>

`IClassFixture<WebApplicationFactory<Program>>` builds the factory **once**, before the first test in the class, and disposes it after the last. xUnit hands every test a brand-new instance of the *test class* — so instance fields are safe — but the *fixture* is shared, and with it the host, its DI container, every singleton in it, and whatever database that host is wired to. Test A's writes are still there when test B runs, and xUnit does not execute tests in source order, so "one at a time" and "all together" are genuinely different worlds. Anything cached inside a fake collaborator behaves the same way: it is a singleton in a host that outlives the test.

The tell is an assertion about global state — `db.Orders.Should().HaveCount(1)` passes alone and fails second. Two fixes: reset between tests (open a transaction per test and roll it back in `Dispose`, or recreate and reseed the database), or write assertions that only reference the entity the test itself created, so a seeded baseline is irrelevant. If you need real isolation, `new WebApplicationFactory<Program>()` inside the test gives a fresh host per test at the cost of rebuilding it every time. Push the other way for genuinely expensive resources: `ICollectionFixture<T>` shares one TestContainers database across several classes — which makes disciplined resetting more important, not less.
</details>

<details>
<summary>3. Trade-off: unit-testing a controller with mocked collaborators vs integration-testing the route through <code>WebApplicationFactory</code>.</summary>

In a well-factored app a controller is glue: model binding, DI resolution, mapping a service result onto an `IActionResult`. Unit-testing it means mocking every collaborator and then asserting that the controller called them — verifying implementation rather than behaviour. The test restates the method body, so a refactor that changes the call sequence turns it red while the HTTP contract never moved. Worse, it is blind to what actually breaks controllers in production: a route template that no longer matches, a missing DI registration, a model-binding or serializer rule, a filter, an auth policy. All of that is the framework wiring the unit test replaced with mocks.

`WebApplicationFactory` runs the real pipeline in-process, so the assertion becomes a statement about the contract — "POST this body, get 201 with a `Location` header" — which survives any internal refactor. What you pay: a host to start and a full pipeline per request instead of a constructor call, shared-fixture state to manage, and a coarser failure signal — red tells you the route is broken, not which line broke it. That is the whole argument for the pyramid: integration tests for the route, unit tests for the logic underneath, so diagnosis stays cheap. The exception is a controller carrying real branching logic — a smell in itself; extract it into a class you can unit-test directly, then integration-test the route around it.
</details>

<details>
<summary>4. Analyze: a test that issues a token, calls <code>await Task.Delay(2000)</code>, then asserts the token has expired. Refactor it.</summary>

Two defects, one in the test and one in the design. The test sleeps: it burns two real seconds on every run, and it is a race — it only passes while the expiry window stays shorter than the delay, on every machine, including a loaded CI agent. That is the canonical passes-nine-runs-out-of-ten flake, and it gets slower as you add cases. The deeper problem is that it *had* to be written this way, because the service reads the ambient clock through `DateTime.UtcNow`: time is an undeclared dependency, so the only lever the test has is real time.

Refactor: inject `TimeProvider` (an abstract class in the BCL since .NET 8) and read `time.GetUtcNow()` instead. In the test, use `FakeTimeProvider` — namespace `Microsoft.Extensions.Time.Testing`, from the `Microsoft.Extensions.TimeProvider.Testing` package — which derives from `TimeProvider`: `SetUtcNow(...)` pins the starting instant and `Advance(TimeSpan.FromHours(2))` jumps virtual time forward at no wall-clock cost. The test is now deterministic, runs in milliseconds, and states the actual rule ("expired two hours after issue") instead of "expired after the test slept." The same move covers the other ambient inputs — `Random`, `Guid.NewGuid()`, `HttpContext` — and when production code itself needs to wait, the fakeable replacements are `Task.Delay(delay, timeProvider, ct)` and `new CancellationTokenSource(delay, timeProvider)`, both `TimeProvider`-aware overloads added in .NET 8, plus `TimeProvider.CreateTimer(...)`. Watch the shape there: `CreateTimer` is a member of `TimeProvider`, but there is no `TimeProvider.Delay` and no `TimeProvider.CreateCancellationTokenSource` — those exist only as extension methods in the `Microsoft.Bcl.TimeProvider` package, whose own docs say it is for building against pre-.NET 8 surface area and should not be used from .NET 8 or higher.
</details>

<details>
<summary>5. Explain why <code>IOrderRepository</code> mocks cleanly while the concrete <code>OrderRepository</code> does not, and name one risk of doing it anyway.</summary>

Moq, NSubstitute and FakeItEasy all build the double at runtime with Castle DynamicProxy, and DynamicProxy's rule is that only virtual members can be intercepted. On an interface that costs nothing: the proxy *implements* the interface, so every member routes through the interceptor. On a class the proxy is a *subclass*, so it can only override members declared `virtual` or `abstract`; everything else keeps its real implementation, the base constructor still runs, and a `sealed` class cannot be subclassed at all. Static members are never dispatched virtually, so they are out too — as are value types like `DateTime`.

The risk is not the outright failure, it is the partial success. Mock a class with one virtual method and you get a hybrid: that method faked, the rest executing production code, and nothing in the test marking the boundary. Someone later drops `virtual` during a refactor and the "mock" silently starts running real logic — possibly real I/O — while the test stays green for the wrong reason. Escape hatch: own the seam. Define your own interface over the type you cannot control (`IClock`, `IFileStore`, `IPaymentGateway`) and mock that instead of fighting the proxy. .NET already ships two of these: `TimeProvider` for the clock, and for HTTP the fakeable seam is `HttpMessageHandler` — its `SendAsync` is protected and overridable — plumbed in via `IHttpClientFactory`, which is why you fake the handler and never `HttpClient` itself.
</details>

---

## Cross-References

- **[Testing Chapter (broader)](../../09-testing/README.md)** — strategy, mutation testing, contract testing, performance testing.
- **[Unit Testing Foundations](../../09-testing/01-unit-testing-foundations.md)** — deeper xUnit / NUnit / MSTest comparison.
- **[API Testing](../../02-api-development/06-api-testing.md)** — Postman collections, Bruno, Pact contract tests.
- **[Dependency Injection](02-dependency-injection.md)** — `WebApplicationFactory.WithWebHostBuilder` overrides DI registrations.
- **[APIs and Microservices](06-apis-and-microservices.md)** — controllers and Minimal APIs covered here are tested via `WebApplicationFactory`.
- **[Background Services](../../05-microservices-and-messaging/02-background-services.md)** — worker testing patterns.
- **[Async & Threading](03-async-and-threading.md)** — async testing and cancellation patterns.
- **[Interview Prep](16-interview-prep.md)** — testing-related interview questions.

---

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- [xUnit documentation](https://xunit.net/docs/)
- [Microsoft Docs: Integration tests in ASP.NET Core](https://learn.microsoft.com/aspnet/core/test/integration-tests)
- [Microsoft Docs: TimeProvider in .NET 8](https://learn.microsoft.com/dotnet/standard/datetime/timeprovider-overview)
- [TestContainers for .NET](https://dotnet.testcontainers.org/)
- [Moq on GitHub](https://github.com/moq/moq)
- [NSubstitute documentation](https://nsubstitute.github.io/)
- [FluentAssertions documentation](https://fluentassertions.com/)
- [AutoFixture on GitHub](https://github.com/AutoFixture/AutoFixture)
- [Mark Seemann — *Dependency Injection Principles, Practices, and Patterns*](https://www.manning.com/books/dependency-injection-principles-practices-patterns)
- [Vladimir Khorikov — *Unit Testing Principles, Practices, and Patterns*](https://www.manning.com/books/unit-testing)
- [Martin Fowler — Test Pyramid](https://martinfowler.com/bliki/TestPyramid.html)
- [Andrew Lock — series on testing in ASP.NET Core](https://andrewlock.net/)

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Microservices, APIs & Minimal APIs](06-apis-and-microservices.md) · [↑ Back to top](#unit-testing) · [Next: Hash Tables, Best Practices & Design Patterns →](08-patterns-and-best-practices.md)

<!-- nav-footer-end -->
