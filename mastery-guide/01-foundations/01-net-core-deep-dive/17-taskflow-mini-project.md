# Hands-On Mini Project — TaskFlow API

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | Medium | Phase 11 — Craft & Interview Prep | 2026-05-07 |

## Contents
- [Hands-On Mini Project: TaskFlow API](#29-hands-on-mini-project-taskflow-api)
  - [Project Overview](#project-overview)
  - [Step 1: Project Setup](#step-1-project-setup)
  - [Step 2: Models (Value Types, Reference Types, Structs)](#step-2-models-value-types-reference-types-structs)
  - [Step 3: DbContext (EF Core, Change Tracking, LINQ)](#step-3-dbcontext-ef-core-change-tracking-linq)
  - [Step 4: Repository + Service Layer (DI, Interfaces, async/await)](#step-4-repository--service-layer-di-interfaces-asyncawait)
  - [Step 5: Caching Service (Dictionary, Singleton, Thread Safety)](#step-5-caching-service-dictionary-singleton-thread-safety)
  - [Step 6: Custom Middleware (Logging, Rate Limiting, Error Handling)](#step-6-custom-middleware-logging-rate-limiting-error-handling)
  - [Step 7: Background Service (IHostedService)](#step-7-background-service-ihostedservice)
  - [Step 8: Controller (REST API, Routing)](#step-8-controller-rest-api-routing)
  - [Step 9: Program.cs (Everything Wired Together)](#step-9-programcs-everything-wired-together)
  - [Step 10: Unit Tests (xUnit + Moq)](#step-10-unit-tests-xunit--moq)
  - [Concept Coverage Checklist](#concept-coverage-checklist)

---

## 29. Hands-On Mini Project: TaskFlow API

### Project Overview

A complete Task Management REST API covering **every concept** from this guide.

```
┌─────────────────────────────────────────────────────────┐
│               TaskFlow API — Concept Coverage            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Project: Task management system with:                  │
│  • User authentication                                  │
│  • Task CRUD operations                                 │
│  • Background task cleanup                              │
│  • Rate limiting                                        │
│  • Real-time notifications (optional)                   │
│                                                         │
│  Concepts covered:                                      │
│  ✅ .NET 10 / Program.cs minimal hosting               │
│  ✅ DI (all 3 lifetimes + keyed services)              │
│  ✅ EF Core (DbContext, LINQ, migrations)              │
│  ✅ Middleware (custom logging, error handling)         │
│  ✅ Async/await throughout                              │
│  ✅ BackgroundService (stale task cleanup)              │
│  ✅ Health checks                                       │
│  ✅ CORS                                                │
│  ✅ Structured logging (Serilog)                        │
│  ✅ Unit testing (xUnit + Moq)                          │
│  ✅ Dictionary caching                                  │
│  ✅ SemaphoreSlim (rate limiting)                       │
│  ✅ Global exception handling                           │
│  ✅ IOptions<T> configuration                           │
│  ✅ Data Protection (token encryption)                  │
│  ✅ Environment management                              │
└─────────────────────────────────────────────────────────┘
```

### Step 1: Project Setup

```bash
dotnet new webapi -n TaskFlowApi --framework net10.0
cd TaskFlowApi
dotnet add package Microsoft.EntityFrameworkCore.SqlServer
dotnet add package Microsoft.EntityFrameworkCore.Tools
dotnet add package Serilog.AspNetCore
dotnet add package Moq
dotnet add package xunit
```

### Step 2: Models (Value Types, Reference Types, Structs)

```csharp
// Models/TaskItem.cs — Reference type (class, stored on heap)
public class TaskItem
{
    public int Id { get; set; }                    // Value type property
    public string Title { get; set; } = "";        // Reference type property
    public string? Description { get; set; }       // Nullable reference type
    public TaskPriority Priority { get; set; }     // Enum (value type)
    public TaskStatus Status { get; set; }
    public DateTime CreatedAt { get; set; }        // Struct (value type)
    public DateTime? CompletedAt { get; set; }     // Nullable value type
    public int AssignedUserId { get; set; }

    // Navigation property (EF Core relationship)
    public User AssignedUser { get; set; } = null!;
}

// Enum — Value type
public enum TaskPriority { Low = 0, Medium = 1, High = 2, Critical = 3 }
public enum TaskStatus { Todo = 0, InProgress = 1, Done = 2, Archived = 3 }

// Models/User.cs
public class User
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string Email { get; set; } = "";
    public List<TaskItem> Tasks { get; set; } = [];
}

// DTOs — Separate from entity models
public record CreateTaskRequest(string Title, string? Description, TaskPriority Priority, int AssignedUserId);
public record TaskResponse(int Id, string Title, string Status, string Priority, string AssignedTo);
```

### Step 3: DbContext (EF Core, Change Tracking, LINQ)

```csharp
// Data/AppDbContext.cs
public class AppDbContext : DbContext
{
    public DbSet<TaskItem> Tasks { get; set; }
    public DbSet<User> Users { get; set; }

    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<TaskItem>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Title).HasMaxLength(200).IsRequired();
            entity.HasOne(e => e.AssignedUser)
                  .WithMany(u => u.Tasks)
                  .HasForeignKey(e => e.AssignedUserId);

            // Global query filter — soft delete pattern
            entity.HasQueryFilter(e => e.Status != TaskStatus.Archived);
        });

        // Seed data
        modelBuilder.Entity<User>().HasData(
            new User { Id = 1, Name = "Ahmed", Email = "ahmed@example.com" },
            new User { Id = 2, Name = "Sara", Email = "sara@example.com" }
        );
    }
}
```

### Step 4: Repository + Service Layer (DI, Interfaces, async/await)

```csharp
// Interfaces — Abstraction for DI and testing
public interface ITaskRepository
{
    Task<List<TaskItem>> GetAllAsync(CancellationToken ct = default);
    Task<TaskItem?> GetByIdAsync(int id, CancellationToken ct = default);
    Task<TaskItem> CreateAsync(TaskItem task, CancellationToken ct = default);
    Task UpdateAsync(TaskItem task, CancellationToken ct = default);
    Task<int> CleanupStaleTasksAsync(int daysOld, CancellationToken ct = default);
}

// Repository — Scoped (one per request, shares DbContext)
public class TaskRepository : ITaskRepository
{
    private readonly AppDbContext _db;

    public TaskRepository(AppDbContext db) => _db = db;

    // IQueryable → SQL runs on DB server, not in memory
    public async Task<List<TaskItem>> GetAllAsync(CancellationToken ct = default)
    {
        return await _db.Tasks
            .AsNoTracking()                      // ✅ Read-only = faster
            .Include(t => t.AssignedUser)         // ✅ Eager load (avoid N+1)
            .OrderByDescending(t => t.Priority)   // Deferred — adds to SQL
            .ThenByDescending(t => t.CreatedAt)   // Deferred — adds to SQL
            .ToListAsync(ct);                     // ✅ Immediate execution
    }

    public async Task<TaskItem?> GetByIdAsync(int id, CancellationToken ct = default)
    {
        return await _db.Tasks
            .Include(t => t.AssignedUser)
            .FirstOrDefaultAsync(t => t.Id == id, ct);
    }

    public async Task<TaskItem> CreateAsync(TaskItem task, CancellationToken ct = default)
    {
        _db.Tasks.Add(task);                     // State: Added
        await _db.SaveChangesAsync(ct);           // INSERT INTO Tasks ...
        return task;                              // task.Id now populated
    }

    public async Task UpdateAsync(TaskItem task, CancellationToken ct = default)
    {
        // ChangeTracker detects modifications automatically
        await _db.SaveChangesAsync(ct);           // UPDATE Tasks SET ...
    }

    // Bulk operation — EF Core 7+
    public async Task<int> CleanupStaleTasksAsync(int daysOld, CancellationToken ct = default)
    {
        return await _db.Tasks
            .Where(t => t.Status == TaskStatus.Done
                && t.CompletedAt < DateTime.UtcNow.AddDays(-daysOld))
            .ExecuteUpdateAsync(
                s => s.SetProperty(t => t.Status, TaskStatus.Archived), ct);
    }
}

// Service — Scoped (business logic layer)
public class TaskService : ITaskService
{
    private readonly ITaskRepository _repo;
    private readonly ICacheService _cache;       // Singleton
    private readonly ILogger<TaskService> _logger;

    public TaskService(
        ITaskRepository repo,                    // Scoped
        ICacheService cache,                      // Singleton — OK to inject
        ILogger<TaskService> logger)              // Singleton — OK to inject
    {
        _repo = repo;
        _cache = cache;
        _logger = logger;
    }

    public async Task<TaskResponse> CreateTaskAsync(CreateTaskRequest request)
    {
        var task = new TaskItem
        {
            Title = request.Title,
            Description = request.Description,
            Priority = request.Priority,
            AssignedUserId = request.AssignedUserId,
            Status = TaskStatus.Todo,
            CreatedAt = DateTime.UtcNow
        };

        var created = await _repo.CreateAsync(task);
        _cache.InvalidateTaskCache();

        _logger.LogInformation(
            "Task {TaskId} created: {Title} assigned to user {UserId}",
            created.Id, created.Title, created.AssignedUserId);

        return MapToResponse(created);
    }

    private static TaskResponse MapToResponse(TaskItem t) =>
        new(t.Id, t.Title, t.Status.ToString(), t.Priority.ToString(),
            t.AssignedUser?.Name ?? "Unassigned");
}
```

### Step 5: Caching Service (Dictionary, Singleton, Thread Safety)

```csharp
// Services/CacheService.cs — Singleton (thread-safe!)
public interface ICacheService
{
    TaskResponse? GetTask(int id);
    void SetTask(int id, TaskResponse task);
    void InvalidateTaskCache();
}

public class InMemoryCacheService : ICacheService
{
    // Dictionary for O(1) lookups
    private readonly Dictionary<int, TaskResponse> _taskCache = new();
    private readonly object _lock = new();         // Thread safety for Dictionary

    public TaskResponse? GetTask(int id)
    {
        lock (_lock)                               // ✅ Protect shared state
        {
            return _taskCache.TryGetValue(id, out var task) ? task : null;
        }
    }

    public void SetTask(int id, TaskResponse task)
    {
        lock (_lock)
        {
            _taskCache[id] = task;                 // O(1) insert/update
        }
    }

    public void InvalidateTaskCache()
    {
        lock (_lock)
        {
            _taskCache.Clear();
        }
    }
}
```

### Step 6: Custom Middleware (Logging, Rate Limiting, Error Handling)

```csharp
// Middleware/RequestLoggingMiddleware.cs
public class RequestLoggingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<RequestLoggingMiddleware> _logger;

    public RequestLoggingMiddleware(RequestDelegate next,
        ILogger<RequestLoggingMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var stopwatch = Stopwatch.StartNew();
        var requestId = Guid.NewGuid().ToString("N")[..8];

        _logger.LogInformation("[{RequestId}] {Method} {Path}",
            requestId, context.Request.Method, context.Request.Path);

        await _next(context);

        stopwatch.Stop();
        _logger.LogInformation("[{RequestId}] {StatusCode} in {Elapsed}ms",
            requestId, context.Response.StatusCode, stopwatch.ElapsedMilliseconds);
    }
}

// Middleware/RateLimitMiddleware.cs — Using SemaphoreSlim
public class RateLimitMiddleware
{
    private readonly RequestDelegate _next;
    private static readonly SemaphoreSlim _semaphore = new(50);  // Max 50 concurrent

    public RateLimitMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext context)
    {
        if (!await _semaphore.WaitAsync(TimeSpan.FromSeconds(5)))
        {
            context.Response.StatusCode = 429;   // Too Many Requests
            await context.Response.WriteAsync("Rate limit exceeded");
            return;                               // ← Short-circuit!
        }

        try
        {
            await _next(context);
        }
        finally
        {
            _semaphore.Release();
        }
    }
}

// Middleware/GlobalExceptionMiddleware.cs
public class GlobalExceptionMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<GlobalExceptionMiddleware> _logger;

    public GlobalExceptionMiddleware(RequestDelegate next,
        ILogger<GlobalExceptionMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unhandled exception on {Path}", context.Request.Path);

            context.Response.StatusCode = ex switch
            {
                KeyNotFoundException => 404,
                UnauthorizedAccessException => 401,
                ArgumentException => 400,
                _ => 500
            };

            await context.Response.WriteAsJsonAsync(new
            {
                error = ex.Message,
                timestamp = DateTime.UtcNow
            });
        }
    }
}
```

### Step 7: Background Service (IHostedService)

```csharp
// Services/StaleTaskCleanupService.cs
public class StaleTaskCleanupService : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;  // ✅ Not ITaskRepo directly!
    private readonly ILogger<StaleTaskCleanupService> _logger;

    public StaleTaskCleanupService(
        IServiceScopeFactory scopeFactory,                // ✅ Singleton-safe
        ILogger<StaleTaskCleanupService> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Stale task cleanup service started");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                // ✅ Create scope for scoped services (DbContext, Repository)
                using var scope = _scopeFactory.CreateScope();
                var repo = scope.ServiceProvider.GetRequiredService<ITaskRepository>();

                var archived = await repo.CleanupStaleTasksAsync(30, stoppingToken);
                if (archived > 0)
                    _logger.LogInformation("Archived {Count} stale tasks", archived);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Stale task cleanup failed");
            }

            await Task.Delay(TimeSpan.FromHours(6), stoppingToken);
        }
    }
}
```

### Step 8: Controller (REST API, Routing)

```csharp
[ApiController]
[Route("api/[controller]")]
public class TasksController : ControllerBase
{
    private readonly ITaskService _taskService;

    public TasksController(ITaskService taskService) => _taskService = taskService;

    [HttpGet]
    public async Task<ActionResult<List<TaskResponse>>> GetAll(CancellationToken ct)
    {
        var tasks = await _taskService.GetAllAsync(ct);
        return Ok(tasks);
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<TaskResponse>> GetById(int id, CancellationToken ct)
    {
        var task = await _taskService.GetByIdAsync(id, ct);
        return task is null ? NotFound() : Ok(task);
    }

    [HttpPost]
    public async Task<ActionResult<TaskResponse>> Create(
        CreateTaskRequest request, CancellationToken ct)
    {
        var created = await _taskService.CreateTaskAsync(request);
        return CreatedAtAction(nameof(GetById), new { id = created.Id }, created);
    }
}
```

### Step 9: Program.cs (Everything Wired Together)

```csharp
var builder = WebApplication.CreateBuilder(args);

// ─── Configuration (IOptions<T>) ───
builder.Services.Configure<CleanupOptions>(
    builder.Configuration.GetSection("Cleanup"));

// ─── Logging (Serilog) ───
builder.Host.UseSerilog((ctx, config) =>
    config.ReadFrom.Configuration(ctx.Configuration)
          .WriteTo.Console()
          .WriteTo.File("logs/taskflow-.log", rollingInterval: RollingInterval.Day));

// ─── DI Registration ───
// Scoped: one per request
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(builder.Configuration.GetConnectionString("Default")));
builder.Services.AddScoped<ITaskRepository, TaskRepository>();
builder.Services.AddScoped<ITaskService, TaskService>();

// Singleton: one for app lifetime (must be thread-safe!)
builder.Services.AddSingleton<ICacheService, InMemoryCacheService>();

// Transient: new each time
builder.Services.AddTransient<ITaskValidator, TaskValidator>();

// Background service
builder.Services.AddHostedService<StaleTaskCleanupService>();

// ─── Health Checks ───
builder.Services.AddHealthChecks()
    .AddSqlServer(builder.Configuration.GetConnectionString("Default")!,
        name: "database");

// ─── CORS ───
builder.Services.AddCors(options =>
    options.AddPolicy("Frontend", policy =>
        policy.WithOrigins("http://localhost:4200")
              .AllowAnyHeader()
              .AllowAnyMethod()));

// ─── Data Protection ───
builder.Services.AddDataProtection();

builder.Services.AddControllers();

var app = builder.Build();

// ─── Middleware Pipeline (ORDER MATTERS!) ───
app.UseMiddleware<GlobalExceptionMiddleware>();     // 1. Catch all errors
app.UseMiddleware<RequestLoggingMiddleware>();       // 2. Log requests

if (app.Environment.IsDevelopment())                // 3. Dev-only
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();                          // 4. HTTPS
app.UseCors("Frontend");                            // 5. CORS
app.UseMiddleware<RateLimitMiddleware>();            // 6. Rate limiting
app.UseAuthentication();                            // 7. Auth
app.UseAuthorization();                             // 8. Authz
app.MapControllers();                               // 9. Endpoints

app.MapHealthChecks("/health");                     // Health endpoint

app.Run();
```

### Step 10: Unit Tests (xUnit + Moq)

```csharp
public class TaskServiceTests
{
    private readonly Mock<ITaskRepository> _mockRepo;
    private readonly Mock<ICacheService> _mockCache;
    private readonly Mock<ILogger<TaskService>> _mockLogger;
    private readonly TaskService _service;

    public TaskServiceTests()
    {
        _mockRepo = new Mock<ITaskRepository>();
        _mockCache = new Mock<ICacheService>();
        _mockLogger = new Mock<ILogger<TaskService>>();
        _service = new TaskService(
            _mockRepo.Object, _mockCache.Object, _mockLogger.Object);
    }

    [Fact]
    public async Task CreateTask_ValidRequest_ReturnsTaskResponse()
    {
        // Arrange
        var request = new CreateTaskRequest("Fix Bug", "Critical bug", 
            TaskPriority.High, 1);
        _mockRepo.Setup(r => r.CreateAsync(It.IsAny<TaskItem>(), default))
                 .ReturnsAsync((TaskItem t, CancellationToken _) =>
                 {
                     t.Id = 42;
                     t.AssignedUser = new User { Name = "Ahmed" };
                     return t;
                 });

        // Act
        var result = await _service.CreateTaskAsync(request);

        // Assert
        Assert.Equal(42, result.Id);
        Assert.Equal("Fix Bug", result.Title);
        Assert.Equal("Ahmed", result.AssignedTo);
        _mockCache.Verify(c => c.InvalidateTaskCache(), Times.Once);
    }

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    public async Task CreateTask_EmptyTitle_ThrowsArgumentException(string? title)
    {
        var request = new CreateTaskRequest(title!, null, TaskPriority.Low, 1);

        await Assert.ThrowsAsync<ArgumentException>(
            () => _service.CreateTaskAsync(request));
    }
}
```

### Concept Coverage Checklist

```
┌────┬────────────────────────────────┬──────────────────────────────────┐
│ #  │ Concept                        │ Where It Appears                 │
├────┼────────────────────────────────┼──────────────────────────────────┤
│  1 │ .NET 10 / Program.cs           │ Step 9: Program.cs               │
│  2 │ Value vs Reference types       │ Step 2: Models (int vs class)    │
│  3 │ var / record / enum            │ Step 2: DTOs, enums              │
│  4 │ Interfaces                     │ Step 4: ITaskRepository          │
│  5 │ GC awareness                   │ Step 5: Object pooling in cache  │
│  6 │ DI — Transient                 │ Step 9: ITaskValidator           │
│  7 │ DI — Scoped                    │ Step 9: Repository, Service      │
│  8 │ DI — Singleton                 │ Step 9: CacheService             │
│  9 │ Captive dependency fix         │ Step 7: IServiceScopeFactory     │
│ 10 │ async/await                    │ Step 4: All repository methods   │
│ 11 │ CancellationToken              │ Step 8: Controller actions       │
│ 12 │ Task / ValueTask               │ Step 4: Repository methods       │
│ 13 │ BackgroundService              │ Step 7: StaleTaskCleanupService  │
│ 14 │ lock (thread safety)           │ Step 5: CacheService             │
│ 15 │ SemaphoreSlim                  │ Step 6: RateLimitMiddleware      │
│ 16 │ Custom middleware              │ Step 6: Logging, Error, Rate     │
│ 17 │ Short-circuiting               │ Step 6: Rate limit returns 429   │
│ 18 │ Middleware ordering            │ Step 9: Pipeline setup           │
│ 19 │ EF Core DbContext              │ Step 3: AppDbContext             │
│ 20 │ LINQ (deferred + immediate)    │ Step 4: GetAllAsync              │
│ 21 │ IQueryable                     │ Step 4: Repository queries       │
│ 22 │ AsNoTracking                   │ Step 4: Read-only queries        │
│ 23 │ Include (eager loading)        │ Step 4: Avoid N+1                │
│ 24 │ ExecuteUpdateAsync (bulk)      │ Step 4: CleanupStaleTasksAsync   │
│ 25 │ Global query filter            │ Step 3: Soft delete              │
│ 26 │ Dictionary<K,V> (hash table)   │ Step 5: InMemoryCacheService     │
│ 27 │ Health checks                  │ Step 9: AddHealthChecks          │
│ 28 │ CORS                           │ Step 9: AddCors                  │
│ 29 │ IOptions<T>                    │ Step 9: CleanupOptions           │
│ 30 │ Serilog logging                │ Step 9: Structured logging       │
│ 31 │ Environment management         │ Step 9: IsDevelopment check      │
│ 32 │ Data Protection                │ Step 9: AddDataProtection        │
│ 33 │ Global exception handling      │ Step 6: GlobalExceptionMiddleware│
│ 34 │ Unit testing (xUnit + Moq)     │ Step 10: TaskServiceTests        │
│ 35 │ REST API / Controllers         │ Step 8: TasksController          │
│ 36 │ Change tracking                │ Step 4: UpdateAsync              │
│ 37 │ Navigation properties          │ Step 2: User.Tasks relationship  │
│ 38 │ Seed data                      │ Step 3: OnModelCreating          │
│ 39 │ Record types (DTOs)            │ Step 2: CreateTaskRequest        │
│ 40 │ Nullable reference types       │ Step 2: string? Description      │
└────┴────────────────────────────────┴──────────────────────────────────┘
```

---

## Self-Test

<details>
<summary>1. Step 7 injects <code>IServiceScopeFactory</code> and opens a scope inside the loop. Inject <code>ITaskRepository</code> directly instead — what breaks, and when would you find out?</summary>

`AddHostedService<StaleTaskCleanupService>()` registers the worker as a **singleton** — internally `TryAddEnumerable(ServiceDescriptor.Singleton<IHostedService, THostedService>())`. `ITaskRepository` is `AddScoped`, and it holds `AppDbContext`, which `AddDbContext` also registers scoped. A singleton constructor-injecting a scoped service is a captive dependency: one `AppDbContext` for the whole process lifetime.

What that looks like in production: the context is never disposed until the process exits. Be precise about the failure mode here, because the folk version of this answer is wrong — a long-lived `DbContext` does *not* pin a pooled connection. EF "opens and closes database connections as needed - every time a query is executed - to avoid keeping connection for unnecessarily long times." What it does hold onto is the change tracker: every entity a *tracking* query loads stays referenced and stale for the life of the process, so the working set climbs and later reads hand back the cached instance instead of fresh database state. On this page that bites the moment the loop touches `GetByIdAsync` or `CreateAsync` — the current `CleanupStaleTasksAsync` uses `ExecuteUpdateAsync`, which tracks nothing (see Q4), so don't claim tracker growth from the cleanup query itself. Two consequences do land immediately: `DbContext` is documented as **not thread-safe**, so anything else resolving that same root-captured repository shares one instance and hits `A second operation started on this context before a previous operation completed`; and EF documents an `InvalidOperationException` as putting the context "into an unrecoverable state" — with a per-iteration scope you throw that context away, with a captive one you keep it for the life of the app.

When you find out depends entirely on environment. The generic host sets `ValidateScopes` and `ValidateOnBuild` to `isDevelopment`, so locally it fails fast at startup with a message of the form `Cannot consume scoped service 'ITaskRepository' from singleton 'Microsoft.Extensions.Hosting.IHostedService'`. In Production both default to off, so the app starts clean and rots over hours — which is the argument for setting both flags explicitly in every environment.

Note also that the scope is created *inside* the `while` loop, not outside it. Hoisting it out reproduces the same bug with extra ceremony. The unit of scope is the unit of work: `using` disposes it at the end of each iteration, which disposes the `DbContext` and drops its change tracker with it.
</details>

<details>
<summary>2. In <code>RateLimitMiddleware</code>, why is <code>WaitAsync</code> outside the <code>try</code> and <code>Release()</code> inside the <code>finally</code> — and what does this middleware actually limit?</summary>

`Release()` must run only on the path where a permit was actually taken. Move `await _semaphore.WaitAsync(...)` inside the `try` and the `finally` fires on the timeout path too, releasing a permit that was never acquired. `new SemaphoreSlim(50)` is the single-argument constructor, which Microsoft documents as defining no maximum: an instance built this way "doesn't throw a `SemaphoreFullException` exception if a call to the `Release` method increases the value of the `CurrentCount` property beyond `initialCount`." So the over-release is silent — every timed-out request ratchets the permit count upward and the limiter quietly stops limiting, with no exception and no log line, under exactly the load it exists for. (`new SemaphoreSlim(50, 50)` would at least make it fail loudly.)

The `return` after writing 429 is the short-circuit: `_next` is never invoked, so nothing downstream runs for that request.

What it limits is **concurrent in-flight requests** — a bulkhead, not a rate limiter; it says nothing about requests per second. Three consequences worth saying out loud. The permit count lives in the process — the field is `static`, and `UseMiddleware<T>` builds a single middleware instance for the app anyway, so dropping `static` would not change that — which means four replicas behind a load balancer have a real cap of 200. It is global rather than per-client or per-route, so one caller in a loop can hold all 50 permits and starve everyone else. And the 5-second `WaitAsync` timeout means a rejected caller waits five seconds for its 429 while holding a connection — you queue instead of shedding. `WaitAsync` at least doesn't block a thread-pool thread the way `Wait()` would. For real policy, ASP.NET Core's built-in rate limiting middleware (`AddRateLimiter` / `UseRateLimiter`, .NET 7+) gives you partitioned per-key limits.
</details>

<details>
<summary>3. <code>GlobalExceptionMiddleware</code> is registered first. What stops working if you move it below <code>app.UseCors(...)</code>, and what happens when the exception is thrown after the response has started?</summary>

The pipeline is nested, so a middleware can only catch exceptions thrown by components registered *after* it. Registered first, it wraps everything. Move it below `UseCors` and failures in `RequestLoggingMiddleware`, `UseHttpsRedirection` and the CORS middleware escape past it entirely: no `LogError`, no JSON body, and the caller gets whatever the host produces. The `switch` mapping `KeyNotFoundException → 404` and friends simply never runs for those.

The second half is the one candidates miss. The handler sets `context.Response.StatusCode` *after* `await _next(context)` has thrown. If anything downstream already flushed headers — a partially streamed result, a `WriteAsync` before the failure — that assignment throws `InvalidOperationException: StatusCode cannot be set because the response has already started.` — Kestrel's `HttpProtocol.StatusCode` setter checks `HasResponseStarted` and formats `CoreStrings.ParameterReadOnlyAfterResponseStarted`. Microsoft's error-handling guidance states the constraint plainly: once the headers for a response are sent, the app can't change the response's status code, exception pages or handlers can't run, and the response must be completed or the connection aborted. The original exception is lost and replaced by a second one, and the client sees a truncated response carrying whatever status was already on the wire. The production-grade version guards first:

```csharp
if (context.Response.HasStarted) throw;   // nothing useful left to do
```

One more thing to flag on this handler: it writes `ex.Message` straight into the response body. That leaks connection strings, table names and schema detail to callers. Return a problem-details payload with a correlation ID and keep the message in the log.
</details>

<details>
<summary>4. The repository has two write paths — <code>UpdateAsync</code> relies on change tracking, <code>CleanupStaleTasksAsync</code> uses <code>ExecuteUpdateAsync</code>. Where does each one silently do the wrong thing?</summary>

`UpdateAsync` never touches its `task` parameter; it just calls `SaveChangesAsync`. That works only when `task` is still tracked by *this repository's* `AppDbContext` — loaded earlier in the same scope via `GetByIdAsync` (a tracking query) and mutated in place, so the tracker can diff it against its snapshot. It silently does nothing for an entity that came from `GetAllAsync`, because that query is `AsNoTracking()`, and the docs are unambiguous: "The change tracker will not track any of the entities that are returned from a LINQ query. If the entity instances are modified, this will not be detected by the change tracker and `SaveChanges()` will not persist those changes to the database." Same for an entity model-bound from a request body, or loaded in a different scope. `SaveChangesAsync` returns 0, throws nothing, the controller reports success, and the write vanishes. Fix the signature's lie: either attach the argument (`_db.Tasks.Update(task)` or `_db.Entry(task).State = EntityState.Modified` — both mark every property modified, so the UPDATE writes all columns), or drop the parameter and document the tracked-entity contract.

`ExecuteUpdateAsync` fails the other way. It is the right tool here — a single `UPDATE … WHERE` at the database, no rows materialised, no per-entity tracker work, which is what archiving a potentially large slice of the table needs. But EF's docs are explicit that these methods "take effect immediately, at the point in which they are invoked" and are "completely unaware of EF's change tracker, and have no interaction with it whatsoever." So any `TaskItem` already loaded in that same context keeps its stale in-memory `Status` and a later `SaveChanges` will happily overwrite the archive; nothing living in a `SaveChanges` override or interceptor runs (audit stamps, domain events, soft-delete conversion); and because it never touches the tracker it "cannot automatically apply concurrency control" — no `RowVersion` check, it is a blind overwrite. It also starts no transaction of its own, and each call is its own round trip. The `int` it returns is the rows-affected count, which is exactly what the cleanup service logs.

On this page the two paths don't collide, because the cleanup runs in its own scope with its own `AppDbContext` — that isolation is the second thing `CreateScope()` buys you.
</details>

<details>
<summary>5. <code>InMemoryCacheService</code> is a singleton wrapping a <code>Dictionary</code> in a <code>lock</code>. Justify the lock over <code>ConcurrentDictionary</code>, then name the bug this class ships with as written.</summary>

Why synchronise at all: it is registered `AddSingleton`, so one instance serves every concurrent request. `Dictionary<TKey,TValue>` supports multiple concurrent *readers* only as long as nothing modifies it; Microsoft's remarks are that to access it "by multiple threads for reading and writing, you must implement your own synchronization." Remove the `lock` and you don't get a clean exception — you get corrupted internal state, so the symptoms are lost or wrong entries and hard faults inside a lookup, on one server, under load, never reproducible locally.

`lock` vs `ConcurrentDictionary`: `ConcurrentDictionary` uses fine-grained locking for writes and performs reads lock-free, so a read-heavy cache scales far better than this design, where every `GetTask` serialises behind one monitor shared by every request in the process. The explicit `lock` earns its place only when you need *several* operations to be atomic together — read one key and conditionally write another, say — which `ConcurrentDictionary` cannot give you. (And note its `GetOrAdd`/`AddOrUpdate` delegates are invoked outside the lock, so a factory can run more than once for the same key.)

The bug as written: nothing evicts. `SetTask` grows the dictionary with no size cap and no expiry, and only `InvalidateTaskCache()` — called on create — clears it. A singleton lives for the process lifetime, so this is an unbounded cache in a long-running server: working set climbing until the container hits its memory limit and gets OOM-killed. That is what `IMemoryCache` with `SizeLimit` and an expiration policy exists for. A second smell in the same wiring: `TaskService.CreateTaskAsync` only ever invalidates, and nothing on this page calls `GetTask` or `SetTask` — as assembled, the cache costs a lock and memory and returns nothing.
</details>

<!-- nav-footer-start -->

---

[← Previous: Interview Prep — Quick Reference, Revision Sheet & Mind Map](16-interview-prep.md) · [↑ Back to top](#hands-on-mini-project--taskflow-api) · [Next: .NET Version History (.NET 7 → .NET 10) →](18-version-history.md)

<!-- nav-footer-end -->
