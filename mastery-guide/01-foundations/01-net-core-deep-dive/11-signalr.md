# SignalR — Real-Time Communication

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 8 — Microservices & Messaging | 2026-05-07 |

> 📘 **Main file**: Interview-ready summary, drills, and cheat sheet live in **[SignalR](../../05-microservices-and-messaging/07-signalr.md)**. This file is the implementation deep-dive.

> **Difficulty:** Intermediate to Advanced | **Reading Time:** ~35 min | **Baseline:** .NET 10 (2025-11) / 2026

---

## Why It Matters

Most apps speak HTTP request/response: client asks, server answers, conversation ends. That model breaks down the moment the *server* needs to push something — a chat message arriving, a build job finishing, a stock price ticking, another user editing the same document. Polling works but burns CPU, network, and database for the 99% of polls that find nothing changed.

SignalR is ASP.NET Core's official real-time abstraction. It hides the messy details of WebSocket negotiation, transport fallback, reconnect, framing, and scale-out behind a hub-style RPC API where you just call `Clients.User("u-42").OrderShipped(orderId)` from anywhere in your server code and the right browsers light up.

This guide treats SignalR as a first-class .NET 10 building block: hubs, lifecycle, groups, streaming, the Redis and Azure SignalR Service backplanes, authentication, scale-out, and how it compares to plain WebSockets and Server-Sent Events.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Real-World Analogy](#real-world-analogy)
3. [Hubs](#hubs)
4. [Connection Lifecycle](#connection-lifecycle)
5. [Groups and Users](#groups-and-users)
6. [Server → Client Invocation](#server--client-invocation)
7. [Client → Server Invocation](#client--server-invocation)
8. [Streaming with IAsyncEnumerable](#streaming-with-iasyncenumerable)
9. [Backplane and Scale-Out](#backplane-and-scale-out)
10. [Authentication and Authorization](#authentication-and-authorization)
11. [Reconnection Strategies](#reconnection-strategies)
12. [SignalR vs WebSockets vs SSE](#signalr-vs-websockets-vs-sse)
13. [Common Pitfalls](#common-pitfalls)
14. [Best Practices](#best-practices)
15. [Real-World Scenarios](#real-world-scenarios)
16. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
17. [Self-Test](#self-test)
18. [Cross-References](#cross-references)
19. [Sources](#sources)

---

## Introduction

### What Is SignalR?

SignalR is a library that gives an ASP.NET Core server the ability to push messages to connected clients in real time, and to receive RPC-style calls from those clients. It abstracts the underlying transport — preferring WebSockets, falling back to Server-Sent Events, and finally to long polling — and gives you a single API that works the same on all three.

- **Without SignalR:** Clients poll an HTTP endpoint every few seconds. 95% of polls return "nothing new." Database is hammered, latency is whatever your interval is, and as users grow you watch your bill scale linearly with idle traffic.
- **With SignalR:** Server holds a persistent connection per client. When something interesting happens, the server pushes it directly. Latency drops to milliseconds, the database is only touched when there is real work, and idle users cost almost nothing.

### Without SignalR vs With SignalR

```
WITHOUT SIGNALR (polling)
=========================
Client                                 Server
  |---- GET /api/notifications ------->|  (every 5s)
  |<------------ [] (empty) -----------|
  |---- GET /api/notifications ------->|
  |<------------ [] (empty) -----------|
  |---- GET /api/notifications ------->|
  |<--- [{ "id": 7, "type": "msg" }] --|
  |---- GET /api/notifications ------->|
  |<------------ [] (empty) -----------|

100 users × 12 polls/min × 60 min = 72,000 requests/hr
99% return nothing. Latency = up to 5 seconds.

WITH SIGNALR (WebSocket)
========================
Client                                 Server
  |==== HTTP Upgrade: websocket ======>|
  |<====== 101 Switching Protocols ====|
  |                                    |
  |   (idle, no traffic, ~0 cost)      |
  |                                    |
  |<-- ReceiveNotification(7, "msg") --|  (server pushes
  |                                    |   immediately)
  |                                    |

100 users × 1 persistent connection = 100 sockets
Idle cost ~ kernel TCP keepalive only. Latency < 50ms.
```

### Why It Matters in 2026

- Web apps are increasingly multi-user, multi-tab, multi-device. Live state is a baseline expectation, not a luxury.
- HTTP/2 and HTTP/3 make persistent connections cheap; the server-cost argument against push has largely evaporated.
- .NET 10 ships SignalR as part of `Microsoft.AspNetCore.SignalR`, with a stable hub protocol, native client packages for JS, .NET, Java, and Swift, and first-class Azure SignalR Service support for serverless scale-out.

---

## Real-World Analogy

```
WITHOUT SIGNALR — The "Are we there yet?" Kid
=============================================
Kid : Are we there yet?     Parent: No.
Kid : Are we there yet?     Parent: No.
Kid : Are we there yet?     Parent: No.
Kid : Are we there yet?     Parent: Yes.

100 questions to learn one fact. Most of the conversation
is wasted breath. The latency of the answer is bounded by
how often the kid asks.

WITH SIGNALR — The Walkie-Talkie
================================
Parent (channel open): "Arriving in 5 minutes." (over)
Kid (listens, no asking needed)

One channel, opened once, used only when there is news.
The kid finds out the instant the parent has something to say.
```

A SignalR hub is the walkie-talkie base station. Every connected client tunes in. The server can broadcast to *all* radios, to a *group* of radios (everyone in `tenant-42`), or to a *single* radio (just user `u-99`). Clients can also push the talk button and call back into the server.

---

## Hubs

### What Is a Hub?

A hub is a server class that exposes methods callable by clients and provides an API to push messages back to one client, a group of clients, or all clients. It is the heart of SignalR's RPC model.

```
+-----------------------------------------------+
|  HUB Properties                                |
+-----------------------------------------------+
|  ✓ Server-side class extending Hub or Hub<T>   |
|  ✓ Public methods callable by clients          |
|  ✓ Has Clients, Groups, Context properties     |
|  ✓ One instance per invocation (transient)     |
|  ✓ DI-friendly — inject services in ctor       |
|  ✓ Mapped to a URL via app.MapHub<T>("/url")   |
|  ✗ Not for long-running work (use Hub Context) |
|  ✗ Cannot hold per-connection state in fields  |
+-----------------------------------------------+
```

### Basic Hub

```csharp
public class ChatHub : Hub
{
    // Client calls: connection.invoke("SendMessage", "alice", "hi")
    public async Task SendMessage(string user, string message)
    {
        // Push to every connected client
        await Clients.All.SendAsync("ReceiveMessage", user, message);
    }
}

// Program.cs
builder.Services.AddSignalR();
var app = builder.Build();
app.MapHub<ChatHub>("/hubs/chat");
```

### Strongly-Typed Hubs (`Hub<T>`)

Plain `Hub` uses string method names — a typo on either side is silent at compile time and fails at runtime. `Hub<T>` ties the server's "what I can call on the client" to a C# interface so both sides agree on the contract.

```csharp
// Shared contract
public interface IChatClient
{
    Task ReceiveMessage(string user, string message);
    Task UserJoined(string user);
    Task UserLeft(string user);
}

public class ChatHub : Hub<IChatClient>
{
    public async Task SendMessage(string user, string message)
    {
        // No magic strings. Refactor-safe. Compile-time checked.
        await Clients.All.ReceiveMessage(user, message);
    }
}
```

```
HUB vs HUB<T>
+----------------------+----------------------+----------------------+
| Aspect               | Hub                  | Hub<T>               |
+----------------------+----------------------+----------------------+
| Client method names  | string at call site  | interface members    |
| Refactor safety      | low (typos silent)   | high (compile error) |
| Discovery            | grep code            | "Find usages"        |
| Verbosity            | shorter              | one extra interface  |
| Recommendation       | quick demos          | production code      |
+----------------------+----------------------+----------------------+
```

### When to Use Hubs

- Bi-directional events: chat, presence, collaborative cursors.
- Server-driven UI updates that should arrive faster than polling can deliver.
- Per-user notifications scoped by authentication.
- Live dashboards that fan out a single change to many viewers.

### When NOT to Use Hubs

- One-way server-to-client streams with no client → server calls (Server-Sent Events is simpler).
- Pure binary, latency-critical workloads (raw WebSocket or gRPC streaming may be a better fit).
- Stateful long-running compute on a single connection (use a background service + hub context).

---

## Connection Lifecycle

### The Lifecycle Hooks

```
                Client connects
                     |
                     v
     +-------------------------------+
     |   OnConnectedAsync()          |  <- override here
     |   - Context.ConnectionId set  |
     |   - Context.User available    |
     +-------------------------------+
                     |
                     v
        Client invokes hub methods,
        server pushes to client
                     |
                     v
     +-------------------------------+
     |   OnDisconnectedAsync(ex)     |  <- override here
     |   - ex == null on clean close |
     |   - ex != null on error       |
     +-------------------------------+
```

### Override Pattern

```csharp
public class PresenceHub(IPresenceTracker tracker, ILogger<PresenceHub> log)
    : Hub<IPresenceClient>
{
    public override async Task OnConnectedAsync()
    {
        var userId = Context.UserIdentifier!;
        await tracker.AddAsync(userId, Context.ConnectionId);
        await Clients.Others.UserOnline(userId);
        log.LogInformation("Connected: {User} ({Conn})", userId, Context.ConnectionId);
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        var userId = Context.UserIdentifier!;
        var stillOnline = await tracker.RemoveAsync(userId, Context.ConnectionId);
        if (!stillOnline)
            await Clients.Others.UserOffline(userId);

        if (exception is not null)
            log.LogWarning(exception, "Dirty disconnect: {User}", userId);

        await base.OnDisconnectedAsync(exception);
    }
}
```

### Lifecycle Pitfalls

```
+--------------------------------------------------------+
|  ⚠ A user can have MANY ConnectionIds simultaneously   |
|     - Multiple browser tabs                            |
|     - Phone + laptop                                   |
|     - A reconnect creates a NEW ConnectionId           |
|                                                        |
|  ⇒ "OnDisconnected" does NOT mean the user is offline. |
|     Track a count or a Set<ConnectionId> per user, and |
|     only emit "UserOffline" when the count hits zero.  |
+--------------------------------------------------------+
```

### When to Use Lifecycle Hooks

- Presence tracking (who is online).
- Group auto-join based on identity (a tenant user auto-joins their tenant group).
- Audit logging for security-sensitive sessions.
- Cleanup of per-connection resources stored in a side store.

---

## Groups and Users

### The Three Routing Primitives

```
+---------+----------------------------------------------------------+
| Target  | Description                                              |
+---------+----------------------------------------------------------+
| All     | Every connection on this hub (across all servers w/      |
|         | backplane). Use sparingly — fan-out cost is real.        |
+---------+----------------------------------------------------------+
| Group   | Named bucket of connections. Add/remove at runtime.      |
|         | Perfect for rooms, tenants, document sessions.           |
+---------+----------------------------------------------------------+
| User    | All connections owned by a logged-in user (resolved by   |
|         | Context.UserIdentifier). Spans all their tabs/devices.   |
+---------+----------------------------------------------------------+
```

### Joining and Leaving a Group

```csharp
public async Task JoinRoom(string roomId)
{
    await Groups.AddToGroupAsync(Context.ConnectionId, $"room:{roomId}");
    await Clients.Group($"room:{roomId}").UserJoined(Context.UserIdentifier!);
}

public async Task LeaveRoom(string roomId)
{
    await Groups.RemoveFromGroupAsync(Context.ConnectionId, $"room:{roomId}");
    await Clients.Group($"room:{roomId}").UserLeft(Context.UserIdentifier!);
}
```

### Sending to Specific Targets

```csharp
// To everyone in the room except the sender
await Clients.GroupExcept($"room:{roomId}", Context.ConnectionId)
             .ReceiveMessage(text);

// To a specific user (all their connections)
await Clients.User(userId).PrivateMessage(text);

// To a specific connection
await Clients.Client(connectionId).ReceiveMessage(text);

// To a list of connections
await Clients.Clients(new[] { conn1, conn2 }).ReceiveMessage(text);
```

### Group Lifetime

```
+-------------------------------------------------------------+
|  GROUP MEMBERSHIP IS PER-CONNECTION, NOT PER-USER           |
|                                                             |
|  When a connection ends:                                    |
|    - SignalR removes that ConnectionId from all groups      |
|    - User's OTHER connections stay in their groups          |
|    - On reconnect, a new ConnectionId starts in NO groups   |
|                                                             |
|  ⇒ Re-add to groups in OnConnectedAsync or after reconnect  |
+-------------------------------------------------------------+
```

### Mapping `User` to a Real Identity

By default `Context.UserIdentifier` is `ClaimTypes.NameIdentifier`. To use a custom claim (for example `sub` from a JWT), implement `IUserIdProvider`:

```csharp
public class SubjectUserIdProvider : IUserIdProvider
{
    public string? GetUserId(HubConnectionContext connection)
        => connection.User?.FindFirst("sub")?.Value;
}

builder.Services.AddSingleton<IUserIdProvider, SubjectUserIdProvider>();
```

---

## Server → Client Invocation

### From Inside a Hub Method

```csharp
public class OrderHub : Hub<IOrderClient>
{
    public Task Watch(int orderId)
        => Groups.AddToGroupAsync(Context.ConnectionId, $"order:{orderId}");
}
```

### From Outside a Hub (the most common case)

Hubs are transient and only live for the duration of one invocation. Background services, controllers, and message-bus consumers cannot — and must not — instantiate a hub directly. Use `IHubContext<THub, TClient>` instead.

```csharp
public class OrderShippedHandler(
    IHubContext<OrderHub, IOrderClient> hub,
    ILogger<OrderShippedHandler> log) : IConsumer<OrderShipped>
{
    public async Task HandleAsync(OrderShipped evt, CancellationToken ct)
    {
        // Push to everyone watching this order
        await hub.Clients
                 .Group($"order:{evt.OrderId}")
                 .OrderUpdated(new OrderStatusDto(evt.OrderId, "Shipped", evt.At));

        // Plus a personal toast to the buyer
        await hub.Clients
                 .User(evt.BuyerId.ToString())
                 .Toast($"Order #{evt.OrderId} has shipped!");

        log.LogInformation("Pushed shipped event for order {OrderId}", evt.OrderId);
    }
}
```

### Push Patterns

```
+--------------------+----------------------------------------+
| Pattern            | Example                                |
+--------------------+----------------------------------------+
| Broadcast          | Maintenance banner to all users        |
| Group fan-out      | Document edited, notify other editors  |
| User fan-out       | "You have a new message" toast         |
| Single connection  | Cancel a stream by ConnectionId        |
| Caller-only        | Confirm receipt back to one client     |
+--------------------+----------------------------------------+
```

---

## Client → Server Invocation

### .NET Client

```csharp
var connection = new HubConnectionBuilder()
    .WithUrl("https://api.example.com/hubs/chat", o =>
    {
        o.AccessTokenProvider = () => Task.FromResult(accessToken);
    })
    .WithAutomaticReconnect()
    .Build();

connection.On<string, string>("ReceiveMessage", (user, msg) =>
    Console.WriteLine($"{user}: {msg}"));

await connection.StartAsync();

// Fire-and-forget invoke (returns when server method completes)
await connection.InvokeAsync("SendMessage", "alice", "hi");

// With a return value
var count = await connection.InvokeAsync<int>("GetActiveUserCount");
```

### JavaScript Client

```javascript
const connection = new signalR.HubConnectionBuilder()
    .withUrl("/hubs/chat", { accessTokenFactory: () => token })
    .withAutomaticReconnect()
    .build();

connection.on("ReceiveMessage", (user, msg) => render(user, msg));

await connection.start();
await connection.invoke("SendMessage", "alice", "hi");
```

### Invoke vs Send

```
+----------+--------------------------+--------------------------+
|          | invoke                   | send                     |
+----------+--------------------------+--------------------------+
| Awaits?  | Yes — round-trip ack     | No — fire and forget     |
| Returns  | Server method's result   | void / completed Task    |
| Errors   | Surface as exception     | Lost / logged only       |
| Use for  | Anything you care about  | Telemetry, metrics, etc. |
+----------+--------------------------+--------------------------+
```

---

## Streaming with IAsyncEnumerable

### Why Streaming?

When the server has a long sequence of values to deliver — log lines, build progress, market ticks — buffering them all into one response is wasteful and adds latency. SignalR supports both *server-to-client* and *client-to-server* streaming with idiomatic `IAsyncEnumerable<T>`.

### Server-to-Client Streaming

```csharp
public class BuildHub : Hub<IBuildClient>
{
    public async IAsyncEnumerable<BuildLogLine> StreamLogs(
        Guid buildId,
        [EnumeratorCancellation] CancellationToken ct)
    {
        await foreach (var line in buildLogReader.ReadAsync(buildId, ct))
        {
            yield return line;
        }
    }
}

// .NET client
await foreach (var line in connection
    .StreamAsync<BuildLogLine>("StreamLogs", buildId, ct))
{
    Console.WriteLine($"[{line.Level}] {line.Message}");
}
```

### Client-to-Server Streaming

```csharp
// Hub method
public async Task UploadTelemetry(IAsyncEnumerable<TelemetryPoint> stream)
{
    await foreach (var point in stream)
        await store.AppendAsync(point);
}

// .NET client uses a Channel<T>
var channel = Channel.CreateBounded<TelemetryPoint>(100);
_ = connection.SendAsync("UploadTelemetry", channel.Reader);
await channel.Writer.WriteAsync(new TelemetryPoint(...));
channel.Writer.Complete();
```

### Streaming Properties

```
+-----------------------------------------------------+
|  STREAMING                                           |
+-----------------------------------------------------+
|  ✓ Bounded memory — values flow as produced        |
|  ✓ Cancellation token honored end-to-end           |
|  ✓ Backpressure via Channel bounds                 |
|  ✓ Composes with await foreach naturally           |
|  ✗ One stream per invocation — not multiplexed     |
|  ✗ All values must be the same DTO type            |
+-----------------------------------------------------+
```

### When to Use Streaming

- The server has more than one value to send and you want them progressively.
- Total result is large enough that buffering is expensive.
- Cancelling mid-flight is a real requirement (user closes a tab during a build log tail).

### When NOT to Use Streaming

- Result fits in one message; just return it.
- You need fan-out — streams are point-to-point. Use `IHubContext` push instead.

---

## Backplane and Scale-Out

### The Problem with Multiple Servers

```
WITHOUT BACKPLANE
=================
   Server A                     Server B
+-----------+                +-----------+
| User U1   |                | User U2   |  <- each connected to
|  conn=a1  |                |  conn=b1  |     a different server
+-----------+                +-----------+

U1 sends "hello":
  Server A receives, calls Clients.All.ReceiveMessage(...)
  Only connections on Server A are notified.
  U2 never hears it.        ← bug
```

### Redis Backplane

```
WITH REDIS BACKPLANE
====================
   Server A     <-- pub/sub -->     Server B
       \                              /
        \         +---------+        /
         +------> |  Redis  | <-----+
                  +---------+

Every Clients.* call is published to Redis.
Every server subscribes and forwards to its local
connections. All servers act as one logical hub.
```

```csharp
builder.Services.AddSignalR()
    .AddStackExchangeRedis("redis:6379", o =>
    {
        o.Configuration.ChannelPrefix = RedisChannel.Literal("signalr:chat:");
    });
```

### Azure SignalR Service

For production at scale, hosting your own backplane gets old fast. Azure SignalR Service is a managed service that holds the WebSocket connections for you — your app servers stay stateless and scale on CPU, not on socket count.

```csharp
builder.Services.AddSignalR()
    .AddAzureSignalR(builder.Configuration.GetConnectionString("SignalR"));
```

### Backplane Comparison

```
+----------------------+--------------+--------------+--------------+
| Aspect               | None         | Redis        | Azure SignalR|
+----------------------+--------------+--------------+--------------+
| Multi-server fan-out | NO           | YES          | YES          |
| Connection capacity  | Per-host     | Per-host     | Service tier |
| Ops burden           | None         | Run Redis    | None         |
| Latency overhead     | 0            | ~1-5 ms      | ~5-15 ms     |
| Cost                 | Free         | Redis cost   | Per unit     |
| Best for             | Single host  | Self-hosted  | Cloud / SaaS |
+----------------------+--------------+--------------+--------------+
```

### Sticky Sessions

When using a self-hosted backplane behind a load balancer, **sticky sessions are required** for transports other than WebSockets. Long polling and SSE depend on the same server seeing successive HTTP requests for one connection. Azure SignalR Service removes this requirement entirely.

---

## Authentication and Authorization

### Authenticating the Connection

SignalR rides on the standard ASP.NET Core auth pipeline. JWT bearer is the typical choice for SPAs and mobile clients.

```csharp
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o =>
    {
        o.TokenValidationParameters = new() { /* ... */ };
        // Hubs use ?access_token= because browsers cannot set headers on WS handshakes
        o.Events = new JwtBearerEvents
        {
            OnMessageReceived = ctx =>
            {
                var token = ctx.Request.Query["access_token"];
                var path = ctx.HttpContext.Request.Path;
                if (!string.IsNullOrEmpty(token) && path.StartsWithSegments("/hubs"))
                    ctx.Token = token;
                return Task.CompletedTask;
            }
        };
    });

builder.Services.AddSignalR();
```

### Authorizing Hub Methods

```csharp
[Authorize]                                     // require any authenticated user
public class OrdersHub : Hub<IOrdersClient>
{
    [Authorize(Roles = "Admin")]                // require Admin
    public Task DeleteOrder(int id) { /* ... */ }

    [Authorize(Policy = "TenantMatches")]       // custom policy
    public Task SwitchTenant(string tenantId) { /* ... */ }
}
```

### Authentication Properties

```
+--------------------------------------------------------+
|  ✓ Reuses the app's existing AuthN/AuthZ pipeline      |
|  ✓ Context.User reflects the authenticated principal   |
|  ✓ [Authorize] works at hub class and method level     |
|  ✓ Per-method policies enable fine-grained checks      |
|  ✗ Token expiry mid-connection requires reconnect      |
|  ✗ Browsers can't set Authorization header on WS       |
+--------------------------------------------------------+
```

### When to Use Authorization

- Always for non-public hubs.
- Per-method `[Authorize(Policy = ...)]` when different operations require different rights.
- Combine with `IUserIdProvider` so `Clients.User(...)` targets the correct identity.

---

## Reconnection Strategies

### Why Reconnect?

Networks drop. Phones switch from Wi-Fi to LTE. Laptops sleep. SignalR's design assumes the connection is *not* permanent — your code has to gracefully resume.

### Built-in Auto-Reconnect

```csharp
var connection = new HubConnectionBuilder()
    .WithUrl(url)
    .WithAutomaticReconnect(new[]
    {
        TimeSpan.Zero,
        TimeSpan.FromSeconds(2),
        TimeSpan.FromSeconds(10),
        TimeSpan.FromSeconds(30)
    })
    .Build();

connection.Reconnecting += err =>
{
    /* show "Reconnecting..." UI */
    return Task.CompletedTask;
};

connection.Reconnected += newConnId =>
{
    /* re-join groups, re-subscribe, resync state */
    return Task.CompletedTask;
};

connection.Closed += err =>
{
    /* exhausted retries — surface to user */
    return Task.CompletedTask;
};
```

### Reconnect Flow

```
+---------+   network drop   +-------------+   timer   +-----------+
| Connected|---------------->|Reconnecting |---------->|Connecting |
+---------+                  +-------------+           +-----------+
     ^                                                      |
     |                                                      |
     +---<--- Reconnected (new ConnectionId) ----<----------+
     |
     |     If all attempts fail:
     +-->  Closed (terminal — must call StartAsync again)
```

### State After Reconnect

```
+----------------------------------------------------------+
|  WHAT YOU GET BACK ON RECONNECT                          |
|    - A NEW ConnectionId                                  |
|    - Your authenticated identity (if token still valid)  |
|                                                          |
|  WHAT YOU LOSE                                           |
|    - All group memberships                               |
|    - In-flight invocations not yet acknowledged          |
|    - Any per-connection state on the server              |
|                                                          |
|  ⇒ Reconcile in OnConnectedAsync or in Reconnected.      |
+----------------------------------------------------------+
```

---

## SignalR vs WebSockets vs SSE

```
+--------------------+--------------+-------------+---------------+
| Aspect             | SignalR      | WebSocket   | SSE           |
+--------------------+--------------+-------------+---------------+
| Direction          | Bi-directional| Bi-directional| Server→Client|
| Transport          | WS / SSE / LP | WS only    | HTTP/1.1+     |
| Auto fallback      | YES          | NO          | NO            |
| Reconnect built-in | YES          | NO          | YES (browser) |
| RPC / hub model    | YES          | NO          | NO            |
| Backplane support  | YES          | DIY         | DIY           |
| Binary frames      | YES (MsgPack)| YES         | NO (text)     |
| Browser support    | All modern   | All modern  | All except IE |
| Best for           | Apps with    | Custom      | Pure server-  |
|                    | rich client  | protocols,  | to-client     |
|                    | events       | game traffic| feeds         |
+--------------------+--------------+-------------+---------------+
```

```
WHEN TO PICK WHAT
=================
  Need RPC + groups + scale-out + auth          -> SignalR
  Custom binary protocol you fully own          -> Raw WebSocket
  One-way notifications, no client→server calls -> SSE
  Periodic info (every >30s) and you don't care -> Polling
```

See also [WebSockets](../../02-api-development/10-websockets.md) and [Server-Sent Events](../../02-api-development/15-server-sent-events.md) for protocol-level deep dives.

---

## Common Pitfalls

### 1. Storing Per-Connection State in Hub Fields

Hubs are transient — a new instance is created for *every* invocation. Anything you store in a field is gone the moment the method returns.

```csharp
// WRONG: gone next call
public class ChatHub : Hub
{
    private readonly List<string> _history = new();
    public Task Send(string m) { _history.Add(m); return Clients.All.SendAsync("M", m); }
}

// RIGHT: store in DI singleton or external store
public class ChatHub(IMessageStore store) : Hub { /* ... */ }
```

### 2. Calling `Clients.All` Without Considering Fan-Out

`Clients.All` on a hub with 50,000 connections sends 50,000 frames. Across a backplane, that's 50,000 fan-out messages. Use groups whenever possible.

### 3. Treating `OnDisconnectedAsync` as "User Logged Out"

A user with three tabs disconnects three separate times — once per tab. Track connection counts per user before declaring them offline.

### 4. Forgetting to Re-Join Groups After Reconnect

Group membership is per-connection. A reconnect gives you a *new* ConnectionId in *no* groups. Re-subscribe in `OnConnectedAsync` or in your client's `Reconnected` handler.

### 5. Blocking Inside a Hub Method

A hub method that does `Thread.Sleep`, runs a synchronous DB call, or holds a lock blocks the hub's serialized invocation pipeline for that connection. Always go fully async.

### 6. Using `SendAsync` When You Need an Ack

`Clients.X.SendAsync(...)` returns when the message is *queued*, not when the client has received it. If you need confirmation, model it as a return value via `Hub<T>` and `InvokeAsync`.

### 7. No Backplane in a Multi-Replica Deployment

Two pods, two sets of connections, and `Clients.All` only reaches half. Symptom: "messages disappear randomly." Add Redis or Azure SignalR.

### 8. Tokens That Expire Mid-Connection

A long-lived WebSocket survives token expiry — auth is checked at connect time. For sensitive operations, re-validate inside the hub method (`Context.User`) or force periodic reconnects.

### 9. Sticky-Session Misconfiguration

Long polling without sticky sessions will silently break behind a round-robin load balancer. WebSockets-only deployments avoid this; mixed transports do not.

### 10. Sending Huge Payloads Through SignalR

Streaming a multi-MB image through `SendAsync` forces the entire server-side outbound buffer to grow. Send a URL to a blob store and let the client fetch it directly.

---

## Best Practices

1. **Use `Hub<T>` with a shared interface.** Stops typos, gives Find Usages, and forces a deliberate contract.
2. **Push from `IHubContext`, not from hub instances held in fields.** Hubs are transient; the context is the safe long-lived handle.
3. **Default to groups, not `All`.** Groups are O(group size), `All` is O(total connections × replicas).
4. **Track presence via connection counts, not individual disconnects.** A user is online iff they have ≥ 1 active connection.
5. **Re-join groups in `OnConnectedAsync`.** Idempotent — safe both on first connect and after reconnect.
6. **Configure `WithAutomaticReconnect` on every client.** Pair with a UI indicator so users see what's happening.
7. **Authorize at the method level for sensitive operations.** Hub-level `[Authorize]` is necessary; per-method policies are sufficient for fine-grained control.
8. **Use streaming (`IAsyncEnumerable<T>`) for progressively-produced sequences.** Keeps memory bounded and lets users cancel.
9. **Size for fan-out, not just connections.** A hub with 1k connections that broadcasts at 10 Hz is 10k msgs/sec — easy to underestimate.
10. **Pick the right backplane early.** Redis for self-hosted, Azure SignalR for managed. Adding it later means a careful traffic migration.
11. **Send identifiers, not state.** "Order 42 changed" + a fresh fetch is cheaper, simpler, and more correct than serializing a 50-field object on every change.
12. **Log connect/disconnect events with correlation IDs.** Production debugging is much easier when you can join a hub log to a request log.

---

## Real-World Scenarios

### Scenario 1: Team Chat Application

```
+-----------------------------------------------------------+
|  Requirement: 10k tenants, ~50 users avg per tenant,      |
|  rooms, presence, typing indicators, read receipts.       |
+-----------------------------------------------------------+

Design:
  Hub<IChatClient> with one group per room: "room:{tenantId}:{roomId}"
  IHubContext used from message-saved domain event handler
  Presence: Redis hash {user: count} updated in OnConnected/Disconnected
  Typing: throttled client→server SendAsync, fanned to room group
  Read receipts: stored in DB, broadcast to room group on update

Push path:
  POST /messages → save to DB → publish "MessageSaved" event →
    handler: hub.Clients.Group("room:T:R").MessageReceived(dto)
```

### Scenario 2: Live Operations Dashboard

```
+-----------------------------------------------------------+
|  Requirement: 200 ops engineers watching a metrics       |
|  dashboard. CPU/RPS/error-rate cards must update <1s.    |
+-----------------------------------------------------------+

Design:
  BackgroundService polls metrics every 1s
  Pushes via IHubContext<DashboardHub> to group "tier:{tier}"
  Engineers join their tier in OnConnectedAsync based on claims
  Heavy charts request a snapshot via InvokeAsync<Snapshot>
  Then receive deltas via streamed updates

Why SignalR (not SSE)?
  Engineers also click "Drill into pod X" → client→server invoke
  Streaming logs back via IAsyncEnumerable<LogLine>
```

### Scenario 3: CI Build Progress

```
+-----------------------------------------------------------+
|  Requirement: live console output while a 20-minute      |
|  build runs. Multiple viewers per build.                 |
+-----------------------------------------------------------+

Design:
  StreamLogs(buildId) hub method returns IAsyncEnumerable<LogLine>
  Reader tails build's log file (or a Kafka topic) and yields lines
  Cancellation token propagates client tab close → reader stops
  Status changes (queued/running/success/failed) pushed via
    IHubContext from the build orchestrator

Multi-viewer:
  Each viewer opens their own stream — no group needed.
  Backpressure handled by the IAsyncEnumerable contract.
  Server CPU stays bounded because the reader does the I/O once
  and a fan-out wrapper publishes to subscribed streams.
```

---

## 21. SignalR - Real-Time Communication

This section preserves the original anchor (`#21-signalr---real-time-communication`) used by upstream documents. The full content above is the deep-dive; the snippet below is the original quick-reference.

```csharp
// Hub
public class NotificationHub : Hub
{
    public async Task JoinGroup(string groupName)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, groupName);
        await Clients.Group(groupName).SendAsync("UserJoined",
            Context.User?.Identity?.Name);
    }

    public async Task SendToGroup(string groupName, string message)
    {
        await Clients.Group(groupName).SendAsync("ReceiveMessage", message);
    }
}

// Program.cs
builder.Services.AddSignalR();
app.MapHub<NotificationHub>("/hubs/notifications");

// Push from any service (not just Hub):
public class OrderService(IHubContext<NotificationHub> hubContext)
{
    public async Task PlaceOrder(Order order)
    {
        // ... save order ...
        await hubContext.Clients.User(order.UserId.ToString())
            .SendAsync("OrderUpdate", new { orderId = order.Id, status = "Placed" });
    }
}
```

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Hub lifecycle

> **Q**: Walk me through `OnConnectedAsync` and `OnDisconnectedAsync` — what's available in each, and what gotchas do they have?
>
> **A**: `OnConnectedAsync` runs after authentication and transport negotiation — `Context.ConnectionId` is set, `Context.User` holds the authenticated principal (if any), `Context.UserIdentifier` is resolved. Use it for presence tracking, auto-joining groups, audit logging. `OnDisconnectedAsync(Exception? exception)` runs on close — `exception == null` means clean disconnect, non-null means error. Use it to clean up per-connection state and update presence. Always call `await base.OnConnectedAsync()` / `await base.OnDisconnectedAsync(exception)`.
>
> **Cross-Q**: A user has three tabs open, closes one. `OnDisconnectedAsync` fires. Is the user "offline"?
>
> **A**: No — they still have two active connections. The "user is offline" decision is per-*user*, not per-*connection*. Track a count or `HashSet<ConnectionId>` per user; in `OnDisconnectedAsync`, decrement; only emit `UserOffline` when the count hits zero. Treating disconnect = offline is the classic SignalR bug — produces flickering presence indicators in chat apps.
>
> **Cross-Q²**: If `OnConnectedAsync` throws, what happens to the client?
>
> **A**: The client receives a disconnection (the connection never completes). On the .NET client with `WithAutomaticReconnect`, it will retry per the schedule. The exception propagates to SignalR's logging — be careful with throwing in `OnConnectedAsync` because reconnect loops can mask the error. Wrap fragile logic (DB calls, distributed cache reads) in try/catch and decide whether to abort or continue degraded. A failed connection log line per reconnect attempt floods production logs.

### Drill 2 — Groups vs Users vs Clients.All

> **Q**: Groups, Users, Clients.All — when each?
>
> **A**: **Group**: named bucket of connection IDs you manage explicitly — rooms, tenant scopes, document sessions. Add/remove at runtime. **User**: all connections of a logged-in user (resolved by `Context.UserIdentifier`) — spans all their tabs/devices. Auto-tracked by SignalR. **Clients.All**: every connection on the hub, across all servers if backplane is configured — maintenance banners, global broadcasts. Use sparingly; cost scales linearly with total connections.
>
> **Cross-Q**: A user has 5 tabs. I call `Clients.User("u-42").SendAsync(...)`. How many sockets get the message?
>
> **A**: 5. SignalR maintains a user-to-connections mapping internally; targeting a user fans out to every connection owned by that user. This is exactly the behavior you want for "notify the user" semantics (every device/tab they have). If you only want one specific tab, target the `ConnectionId` directly — but that's rarely what you want.
>
> **Cross-Q²**: I'm broadcasting to a 50k-connection group every second. What's the cost?
>
> **A**: 50k frames written per broadcast, per server. Across a Redis backplane: 50k messages published to Redis, 50k forwarded per subscriber server. On a 4-server fleet broadcasting once per second: 200k Redis pub/sub messages per second, plus 50k socket writes per server per second. Mitigations: (1) reduce frequency — diff-based updates instead of full snapshots; (2) batch — accumulate messages, send every 100ms; (3) reduce membership — narrower groups; (4) push identifiers, let clients fetch on demand. Don't underestimate fan-out cost on persistent connections.

### Drill 3 — Backplane

> **Q**: What is a SignalR backplane, when do you need one, and what are the options?
>
> **A**: A backplane is the mechanism by which multiple SignalR server instances coordinate fan-out — when Server A calls `Clients.All.SendAsync(...)`, the message must reach connections on Servers B and C too. Without one, multi-instance deployments silently drop fan-out across servers. Options: (1) **Redis backplane** (`AddStackExchangeRedis`) — self-hosted, pub/sub; (2) **Azure SignalR Service** (`AddAzureSignalR`) — managed, holds connections too. Single-instance apps don't need a backplane.
>
> **Cross-Q**: Redis backplane vs Azure SignalR Service — what's the architectural difference?
>
> **A**: **Redis backplane**: your app servers still hold the WebSocket connections. Redis only pub/subs fan-out messages. Your servers scale on socket count. **Azure SignalR Service**: Azure holds the WebSocket connections. Your servers handle business logic only and *push* via the service. Stateless servers; scale on CPU. Trade-off: Redis is cheaper but you operationally own connection count limits; Azure is more expensive but removes the socket-management burden entirely.
>
> **Cross-Q²**: I add Redis backplane and `Clients.All` still doesn't reach all servers. What did I miss?
>
> **A**: Common causes: (1) Servers connect to *different* Redis instances (misconfigured connection string), (2) `ChannelPrefix` differs between servers (they pub/sub on different channels), (3) Redis pub/sub isn't enabled or is filtered by a proxy, (4) Servers' system clocks drift wildly (subtle issue with reconnection ordering). Validate by directly running `SUBSCRIBE signalr:*` on Redis and watching messages flow from Server A — if Server B isn't subscribed there, the bug is upstream.

### Drill 4 — Reconnection

> **Q**: Reconnection — what does SignalR do automatically, and what do you have to do?
>
> **A**: With `.WithAutomaticReconnect(...)`, the client retries the connection per a configurable schedule (default 0s, 2s, 10s, 30s). On success the `Reconnected` event fires with a *new* `ConnectionId`. SignalR doesn't restore group memberships, in-flight invocations, or per-connection state — you do that. Subscribe to `Reconnecting`, `Reconnected`, `Closed` events to show UI state and re-subscribe. After all retries exhaust, the client enters `Closed` state and you must call `StartAsync()` again manually.
>
> **Cross-Q**: A reconnect succeeds. What state is lost server-side, and what do you have to rebuild?
>
> **A**: A new `ConnectionId` is allocated — all group memberships are gone (groups are per-ConnectionId). Any per-connection state stored in DI singletons keyed by ConnectionId is orphaned. Any in-flight `InvokeAsync` calls are abandoned (their TCS never completes — clients should treat them as failed). Rebuild: re-join groups, re-subscribe to streams, reconcile state (refetch what you missed). Idempotency is key — call `JoinRoom` again, server should handle "already in group" gracefully.
>
> **Cross-Q²**: Sticky sessions — when are they required, and why does Azure SignalR Service not need them?
>
> **A**: With a self-hosted SignalR setup using Long Polling or Server-Sent Events transports, multiple HTTP requests share a "connection" — they must hit the same server. Without sticky sessions (load balancer pins client to one backend), polling clients break randomly. WebSocket is a single TCP connection so sticky isn't needed once upgraded — but the initial handshake involves multiple requests, so it can still matter. **Azure SignalR Service** holds the connection itself; your backends are stateless RPC callers and any backend can push via the service. Sticky disappears as a requirement.

### Drill 5 — Scaling SignalR horizontally

> **Q**: I need to support 100k concurrent connections. Walk me through the scaling path.
>
> **A**: (1) Start single-pod with a reasonable Kestrel config — 10-30k connections per pod is realistic depending on memory and message rate. (2) Past one pod, add Redis backplane *and* sticky sessions for transport fallback. (3) Past ~100k, the operational cost of running Redis + managing pod-level socket caps starts to bite — switch to Azure SignalR Service. (4) Past ~1M, you're sharding the service across regions or using a dedicated event distribution layer (Kafka + custom protocol).
>
> **Cross-Q**: Why does Azure SignalR Service hold the connections instead of your pods?
>
> **A**: To decouple socket count from compute. Holding 100k WebSockets on your API pods means each pod must hold tens of thousands of TCP sockets, memory for buffers, and a heartbeat task per socket — even when idle. The pod's CPU could be 5% but its memory is fully consumed. Azure SignalR Service takes the connections off your pods entirely; your pods scale on CPU/request rate, not socket count. Trade-off: per-connection cost is a line item in your bill instead of in your infrastructure bill.
>
> **Cross-Q²**: A connection sends a message; my hub receives it, but the response goes to the wrong client. What happened?
>
> **A**: Mostly impossible if you use `Clients.Caller`. But it can happen when (a) you store `ConnectionId`s in a long-lived cache keyed by user, and reconnections rotate ConnectionIds — old ID points to a dead connection or has been reassigned; (b) you parallelize hub work and accidentally swap connection contexts. The defensive pattern: always derive the target from `Context.UserIdentifier` (stable across reconnects) or pass the target explicitly. Don't cache ConnectionIds — they're ephemeral.

### Drill 6 — SignalR vs SSE vs WebSocket

> **Q**: When would you pick SSE over SignalR?
>
> **A**: Pure server-to-client streams with no client → server messaging — feed updates, dashboard tickers, log streaming. SSE runs over HTTP/1.1 (or HTTP/2 multiplexed), browsers handle reconnect natively, and there's no protocol negotiation overhead. Simpler than SignalR for one-way push: no hub class, no groups infrastructure, no backplane decision. SignalR is the right answer when you need bi-directional RPC, groups, or scale-out abstractions — SSE doesn't have those.
>
> **Cross-Q**: When is raw WebSocket better than SignalR?
>
> **A**: When you have a custom binary protocol you own end-to-end and SignalR's hub framing is overhead, when you need extreme latency control (game engines, trading systems with microsecond budgets), or when you're integrating with an existing WebSocket-based protocol (MQTT-over-WS, AMQP-over-WS). SignalR adds ~5-50 bytes per message of framing and one round-trip of negotiation — for high-frequency tiny messages, that adds up. For most apps, the productivity wins of SignalR (groups, RPC, reconnect, backplane) outweigh the overhead.
>
> **Cross-Q²**: gRPC streaming vs SignalR — when each?
>
> **A**: **gRPC streaming**: server-to-server, internal microservice communication, language-agnostic via protobuf, fully strongly-typed. Best for backend fan-out where browsers don't connect directly. **SignalR**: browser/mobile/desktop clients connecting to ASP.NET Core servers, with JS/.NET/Java/Swift client SDKs handling reconnection and transport fallback. Browser support for gRPC requires gRPC-Web (HTTP/1.1 fallback with protocol bridge) and doesn't support bi-directional streaming. For "frontend connecting to backend," SignalR; for "backend services exchanging streams," gRPC.

### Drill 7 — Streaming with IAsyncEnumerable

> **Q**: How does server-to-client streaming work in SignalR with `IAsyncEnumerable<T>`?
>
> **A**: A hub method returns `IAsyncEnumerable<T>`. The client calls `connection.StreamAsync<T>("MethodName", ...)` and consumes via `await foreach`. Each yielded value becomes a SignalR message frame. Cancellation is end-to-end — the client cancellation token closes the stream, the server's `[EnumeratorCancellation] CancellationToken ct` is signalled, the `await foreach` exits cleanly. Memory bounded — values flow as produced, no buffering required.
>
> **Cross-Q**: Backpressure — if the client consumes slowly, what happens?
>
> **A**: SignalR uses Channels under the hood with a default bounded buffer. If the buffer fills, the server's `yield return` blocks waiting for room. This propagates backpressure naturally — a slow client slows down the server enumerator. Without bounded channels you'd OOM by producing faster than consuming. The buffer size is tunable via `HubOptions.StreamBufferCapacity` (default 10) — set higher for bursty producers, lower for memory-sensitive scenarios.
>
> **Cross-Q²**: I want to send a 1GB build log via SignalR streaming. Bad idea?
>
> **A**: Generally yes. SignalR streaming is for progressive *production* — the server doesn't have the values yet, they arrive over time. For "I have 1GB of data sitting in a file, send it to the client," use HTTP streaming (Range requests, chunked transfer) — that's what HTTP is good at, and CDNs/proxies handle it for free. SignalR streaming shines for "build is running, emit lines as they're produced, allow cancellation." If the data is already finalized, send a URL and let the client fetch it directly.

### Drill 8 — Authentication on hubs

> **Q**: SignalR + JWT bearer — what's the gotcha with browsers?
>
> **A**: Browsers can't set `Authorization` headers on WebSocket upgrade requests — only on regular HTTP requests. SignalR's JS client sends the token as `?access_token=` query string instead, and the server's JWT Bearer middleware must be configured to read it from there for hub paths: in `JwtBearerEvents.OnMessageReceived`, check if `path.StartsWithSegments("/hubs")` and assign `ctx.Token = ctx.Request.Query["access_token"]`. Without this, the upgrade is anonymous and `[Authorize]` rejects it.
>
> **Cross-Q**: Tokens in the URL are logged in nginx/CloudFront/proxy logs. How dangerous is this?
>
> **A**: Tokens in URLs do leak to access logs, referer headers (mitigated by `Referrer-Policy`), and browser history. For SignalR specifically: the URL is only used during the upgrade handshake — after upgrade to WebSocket, all data flows in frames (not URLs). The token still appears in *one* access log line per connection. Mitigations: (1) short-lived tokens (15 min) so log retention windows matter less, (2) configure proxies to scrub `access_token` from logged URLs, (3) `Referrer-Policy: no-referrer` on the page initiating the connection.
>
> **Cross-Q²**: A WebSocket connection lives 8 hours. The JWT inside it expires after 15 min. What happens?
>
> **A**: The connection stays open — authentication is checked at upgrade, not on every frame. The user remains "authenticated" by the original token long after it would normally have expired. For sensitive operations, re-check `Context.User` validity inside hub methods (e.g., call a permission-check that hits a fresh source), or implement periodic forced reconnect (server pushes "please reconnect" every N minutes; client re-handshakes with a fresh token). Don't trust long-lived hub connections for high-security ops.

### Drill 9 — Client-side reconnect handling

> **Q**: A client reconnects. What does the client-side code need to do?
>
> **A**: (1) Subscribe to `Reconnecting` event — show "connection lost" UI. (2) Subscribe to `Reconnected` event — re-join all groups (`connection.invoke("JoinRoom", roomId)`), re-subscribe to streams, optionally re-fetch any missed state from a REST endpoint. (3) Subscribe to `Closed` event — exhausted retries; show "disconnected" UI and offer manual reconnect. (4) Idempotency on the server side: `JoinRoom` should handle "already a member" without erroring.
>
> **Cross-Q**: How do you reconcile state on reconnect — what did the client miss?
>
> **A**: SignalR doesn't replay missed messages. Two patterns: (1) **Refetch on reconnect** — call a REST endpoint to get current state, ignoring whatever the client thinks is current. Simple but expensive. (2) **Sequence numbers** — server stamps each message with a monotonic ID per group/user. Client tracks the last received ID; on reconnect, calls `/api/messages/since/{lastId}` to fetch missed messages. More complex but bandwidth-efficient. For chat apps, sequence numbers; for live dashboards, refetch.
>
> **Cross-Q²**: The user closes their laptop for 6 hours. On wake, the client reconnects. What's a likely problem?
>
> **A**: The reconnect schedule (`0, 2, 10, 30s`) exhausted hours ago — connection is in `Closed` state. The client must call `StartAsync()` explicitly. Failure mode: app silently shows stale data because nobody re-initiated the connection. Fix: in `Closed` handler, attempt full restart with backoff (mark connection dead, show UI, retry every minute or on user action). Pair with visibility detection (`document.visibilitychange`) — when tab becomes visible, force a reconnect check.

### Drill 10 — Message size limits

> **Q**: What's the SignalR message size limit, and what happens at the boundary?
>
> **A**: Default is 32KB per message (`HubOptions.MaximumReceiveMessageSize`). Configurable up to 1MB by default. Send a larger message → server logs an error and closes the connection with `InvalidDataException`. Tune via `services.AddSignalR(o => o.MaximumReceiveMessageSize = 1024 * 1024)`. Streaming with `IAsyncEnumerable<T>` doesn't have a single-message limit — each yielded value is its own frame, each bound by the per-message limit.
>
> **Cross-Q**: My large payload is mostly base64'd image data. What do I do?
>
> **A**: Don't send blobs through SignalR. Pattern: client uploads image to blob storage (S3/Azure Blob/etc.), gets back a URL, sends *only the URL* via SignalR. Other clients receive the URL and fetch directly. Blob storage is built for large objects; SignalR is built for small messages. Sending megabytes through SignalR works but pegs your server's memory and bandwidth as a fan-out multiplier (50k subscribers × 5MB = 250GB outbound — at SignalR cost).
>
> **Cross-Q²**: I increased `MaximumReceiveMessageSize` to 100MB to support large payloads. What can go wrong?
>
> **A**: Memory exhaustion under load — each in-flight large message holds 100MB. 100 concurrent connections sending peaks → 10GB memory pressure → OOM or GC pauses. Plus longer per-message processing blocks the hub's serialized invocation queue. Plus malicious clients can send 100MB garbage and saturate your server cheaply. Treat the limit as a security boundary; raise it only when you've also added rate limiting per connection and bounded the buffering. The right answer is almost always "use blob storage and pass URLs."

### Drill 11 — Hub method dispatch

> **Q**: Client calls `connection.invoke("SendMessage", ...)`. How does SignalR find and call the right hub method?
>
> **A**: SignalR uses reflection at startup to enumerate hub methods, builds a method dispatcher keyed by method name. Method names match *case-insensitively* by default (`SendMessage`, `sendMessage`, `sendmessage` all resolve to the same method). Arguments are deserialized from the message payload (JSON or MessagePack) and bound to method parameters by position. Async methods are awaited; the return value is sent back as the invocation result.
>
> **Cross-Q**: Two methods with the same name but different parameter types — what happens?
>
> **A**: SignalR doesn't support method overloading. Hub method registration by name conflicts at startup — the second registration wins or throws (depends on version). Always give hub methods unique names. If you need polymorphism, use one method with a union/discriminated type parameter, or expose multiple distinctly-named methods.
>
> **Cross-Q²**: Case-sensitivity — JS clients use camelCase, .NET uses PascalCase. Does this work transparently?
>
> **A**: Yes — SignalR's method matching is case-insensitive. `connection.invoke("sendMessage", ...)` from JS resolves to `public Task SendMessage(...)` in C#. Symmetrically, `Clients.All.SendAsync("receiveMessage", ...)` from C# fires a JS handler registered as `connection.on("receiveMessage", ...)` or `connection.on("ReceiveMessage", ...)`. Conventional naming: C# uses PascalCase for server methods, camelCase or PascalCase for client method names in `SendAsync` calls — pick one and stick to it.

### Drill 12 — Strongly-typed hubs

> **Q**: When is `Hub<T>` worth the extra interface vs plain `Hub`?
>
> **A**: Whenever the project will live past prototype. `Hub<IChatClient>` ties server-to-client method names to a compile-checked interface — typos in `Clients.All.ReceiveMessage(...)` become build errors instead of silent runtime no-ops. Refactor support (Rename across solution), Find Usages, IntelliSense. Cost: one interface definition, ~5 extra lines. For any non-trivial project, mandatory. Plain `Hub` survives only in demos and one-off internal tools.
>
> **Cross-Q**: The interface is shared between server and client (e.g., Blazor Server, .NET MAUI client). What goes in the shared library?
>
> **A**: Only the interfaces — `IChatClient` (server-to-client methods) and `IChatHubServer` (client-to-server methods, if you go fully bidirectional with `IClientProxy<T>`). DTOs go in the same shared library. The hub *implementation* and the hub *client wiring* live in their respective projects. This gives you compile-time guarantee that client and server agree on the contract, similar to gRPC's `.proto` files but in C#.
>
> **Cross-Q²**: Can the client also be strongly-typed in calling server methods?
>
> **A**: Partially. The .NET SignalR client uses dynamic dispatch by default (`connection.InvokeAsync("SendMessage", ...)`). Source generators (`Microsoft.AspNetCore.SignalR.Client.SourceGenerator`, or community ones) generate strongly-typed proxies from a hub interface — `connection.GetHubProxy<IChatHubServer>().SendMessageAsync(...)`. For JS clients, you use TypeScript declaration files (manual or generated) — the runtime call is still `connection.invoke("SendMessage", ...)` but typed at compile time. End-to-end strong typing is increasingly achievable in 2026 but still requires source-generator setup.

### Drill 13 — Connection ID

> **Q**: What is `ConnectionId`, how stable is it, and what are the security implications?
>
> **A**: A unique opaque identifier per WebSocket connection, regenerated on every reconnect. *Not stable* across reconnects — same user, new ConnectionId. Generated server-side, returned to the client in the handshake response. Security: ConnectionIds are visible to the client and could be leaked via logs/screenshots — treat them as *identifiers, not secrets*. Authorization should be based on `Context.User` (authenticated principal), never on `ConnectionId` alone.
>
> **Cross-Q**: A junior wants to use `ConnectionId` as the key for user-specific cached state. What goes wrong?
>
> **A**: (1) Reconnect creates a new ConnectionId — cached state is orphaned, the user appears to "lose" their state. (2) A user with 3 tabs has 3 ConnectionIds — state is fragmented. (3) Server restart: all ConnectionIds invalidate; cache is full of stale keys. The right key is `UserId` (or `UserIdentifier`) — stable across reconnects, aggregates all of a user's connections. Caching by ConnectionId is for *connection-specific* state (current stream subscriptions, in-flight invocations) — and even then, prefer DI-scoped state managed by the hub.
>
> **Cross-Q²**: An attacker submits another user's ConnectionId in a hub method call. Can they hijack the session?
>
> **A**: No — they can't impersonate just by claiming a ConnectionId. SignalR derives `Context.ConnectionId` from the connection's own server-side state, not from anything the client sends. The attacker can guess a ConnectionId, but their hub method calls still execute under *their own* connection's context. The attack vector would be calling `Clients.Client(victim_ConnectionId).EvilMessage(...)` from a hub method — which is why hub methods that target specific clients must validate authorization before forwarding (e.g., "only the owner or admin can send messages to a connection").

### Drill 14 — Performance under high fan-out

> **Q**: A live dashboard has 10k connected users; you push an update every second. CPU on the SignalR server spikes. What's happening?
>
> **A**: 10k frame writes per second × serialization cost × backplane forwarding (if multi-server) × keepalive overhead. Each `SendAsync` to a group is a serialize + write per connection. At 10k connections × 1Hz × 10ms per frame send (typical for JSON serialization + socket write), you're looking at significant CPU. Mitigations: (1) reduce frequency (batch updates, send every 5s instead of 1s), (2) reduce payload (send diffs not snapshots), (3) use MessagePack instead of JSON (faster serialize, smaller frames), (4) split into smaller groups so most updates only fan out to interested subscribers.
>
> **Cross-Q**: I switch from JSON to MessagePack. What does that get me?
>
> **A**: ~30-50% smaller frame size, ~2-5× faster serialize/deserialize on the server side, lower allocation pressure (less GC). Trade-off: harder to debug (binary frames don't show readable content in network inspectors), client libraries must support MessagePack (JS SignalR client supports it; some custom clients may not), schema evolution requires care (adding fields is fine, removing/renaming is breaking). For high-fan-out scenarios, often worth it; for low-volume hubs, JSON is fine.
>
> **Cross-Q²**: My SignalR pod's CPU is fine, but message latency is rising. Where do I look?
>
> **A**: Possible causes: (1) Garbage collection — JSON serialization allocates per message; high allocation rate → gen0 GC frequency rises → message-write latency jitters. Check with dotnet-counters / dotnet-trace. (2) TCP buffer backpressure — slow clients fill their socket send buffer; SignalR waits per connection. Fix by tuning `MaxParallelInvocationsPerClient` or by accepting that slow clients should be disconnected. (3) Backplane latency (Redis under load, network blip). (4) Thread pool starvation — sync work in async paths. Use ETW / dotnet-trace to isolate.

### Drill 15 — SignalR clients

> **Q**: SignalR clients available — JS, .NET, Blazor, Java, Swift. When each?
>
> **A**: **JavaScript** (`@microsoft/signalr`): browsers, React/Vue/Angular SPAs, Node.js servers. **.NET** (`Microsoft.AspNetCore.SignalR.Client`): WPF, console apps, .NET MAUI mobile, background services calling other servers. **Blazor**: both Server (uses SignalR internally for UI sync — you don't write client code) and WebAssembly (uses the JS or .NET client). **Java**: Android, JVM-based servers. **Swift**: iOS native. Each official client supports the same hub protocol — you implement the hub once on the server, multiple clients consume.
>
> **Cross-Q**: Blazor Server uses SignalR for its entire UI sync. What's the implication?
>
> **A**: Every Blazor Server page is a SignalR connection. UI events (button clicks) round-trip to the server, server diffs the render tree, sends DOM updates back via SignalR. Implications: (1) latency — every click is a network call (~50-200ms RTT), unsuitable for high-frequency interactions. (2) scale — each user = one SignalR connection, so connection count = concurrent users. (3) backplane requirement — Blazor Server multi-pod *must* have a SignalR backplane configured. Blazor WebAssembly avoids this — full app runs client-side, SignalR is optional for live updates.
>
> **Cross-Q²**: TypeScript client — how do you get type-safe `connection.on` handlers?
>
> **A**: Write a TypeScript interface mirroring your server's `IChatClient`, then a thin wrapper around `HubConnection`. Or use a generator (e.g., `TypedSignalR.Client.TypeScript`) that reads the server's hub interface and emits TS types. Or define DTOs as TypeScript types in a shared package (if you publish a contracts package) and cast in `connection.on<MessageDto>("ReceiveMessage", ...)`. The official SignalR TS client doesn't enforce method-name typing — you have to layer it. Modern teams adopt code generation or hand-written wrappers for this exact reason.

---

</details>

---

## Self-Test

<details>
<summary>1. A message-bus consumer needs to push to clients. A teammate constructor-injects <code>OrderHub</code> and calls <code>hub.Clients.Group(...)</code>. What breaks?</summary>

It doesn't even resolve — hub types aren't registered in the container, and SignalR's hub activator asks the provider first and falls back to `ActivatorUtilities` when it gets nothing back. "Fixing" that with `AddSingleton<OrderHub>()` makes it worse: `Clients`, `Context` and `Groups` are plain settable properties on `Hub` that SignalR assigns per dispatched invocation, so on a hand-resolved instance they are still null and the first `hub.Clients.Group(...)` throws `NullReferenceException`. Microsoft's guidance is blunt — hubs are transient, "don't instantiate a hub directly via dependency injection," and each hub method call executes on a new hub instance. That transience is also why per-connection state stored in a hub field vanishes the moment the method returns.

Fix: inject `IHubContext<OrderHub, IOrderClient>`, the long-lived handle. What you give up is caller context — `IHubContext` exposes only `Clients` and `Groups`, so there is no `Caller`, no `Others`, no `Context.ConnectionId`. You name the target yourself: `.Group("order:42")`, `.User(buyerId)`, `.Client(connectionId)`.
</details>

<details>
<summary>2. Chat works on your laptop. Behind three pods and a round-robin load balancer, some clients connect fine and others fail or drop constantly. Why, and what is the fix?</summary>

`StartAsync` is not one request. The client first POSTs to `[hub-url]/negotiate`; the server replies with a connection id/token and the `availableTransports` it supports. *Then* the client opens the transport itself — a WebSocket upgrade, an SSE stream, or long polling — in a **separate** HTTP request, which round-robin happily hands to a pod that has never heard of that connection. Long polling is the worst case: every poll is another request that must land on the same pod.

SignalR requires that one server process handle every HTTP request for a given connection, so the fix is sticky sessions (session affinity — ARR affinity on Azure App Service, `ip_hash` or a `sticky` cookie on Nginx). Microsoft documents exactly three exemptions: a single server in a single process; the Azure SignalR Service, which redirects clients to itself and handles affinity there; or all clients configured for WebSockets **only** with `SkipNegotiation` enabled, which removes the separate negotiate request. Everything else — Redis backplane included — needs affinity, and `SkipNegotiation` can't be combined with the Azure service, so those two escape hatches are mutually exclusive. Fallback order, for the record: WebSockets → Server-Sent Events → long polling.
</details>

<details>
<summary>3. Trade-off: Redis backplane vs Azure SignalR Service, once you go from one pod to three.</summary>

Why either is needed: a server only knows its own connections, so `Clients.All` across three pods with no backplane reaches only the third of users attached to the pod that sent it. The ticket reads "messages disappear randomly."

**Redis** (`AddStackExchangeRedis`): your pods still hold every socket. Redis pub/sub forwards each send to the other servers, which deliver to their own local connections. Consequences: you scale on connection count even when sending few messages, sticky sessions remain required, and groups are kept in server memory so a restart drops membership. It is Microsoft's recommended option for self-hosted infrastructure, and the pragmatic one when latency to an Azure region would be prohibitive.

**Azure SignalR Service** (`AddAzureSignalR`): clients are redirected to the service on connect, so the service holds the sockets and each app server keeps only a small constant number of connections to it. Your servers then scale on messages sent rather than clients connected, sticky sessions stop being a requirement, and it is the documented answer when group membership has to survive a server restart. The cost moves from your infrastructure into a per-unit bill.
</details>

<details>
<summary>4. A wifi blip. The client's <code>Reconnected</code> handler fires and the UI says Connected — but the user gets no more room messages, and everyone else saw them blink offline. Explain both symptoms.</summary>

Both fall out of one fact: by default a reconnect is a *new* connection with a new `ConnectionId`, not a resumed one.

The silence: group membership is per-connection and isn't preserved when a connection reconnects, so the client is in no groups and `Clients.Group("room:42")` no longer includes it. It genuinely is connected — it just belongs to nothing. Rejoin in `OnConnectedAsync` or in the client's `Reconnected` handler, and do it unconditionally: adding a connection that is already in the group is safe and throws nothing.

The blink: the old connection closed, so its `OnDisconnectedAsync` ran, and code that reads one disconnect as "user is offline" broadcasts offline for someone who is already back. The same bug fires when a user with three tabs closes one — one user, many simultaneous connections, one per tab or device. Keep a per-user set or count keyed on `Context.UserIdentifier` (`ClaimTypes.NameIdentifier` by default, overridable with `IUserIdProvider`) and emit `UserOffline` only when it hits zero. The rule: `ConnectionId` is a send target within one invocation, never the key of anything that must outlive the connection.

The version gate to name before an interviewer does: .NET 8 added **stateful reconnect**, the one case where a brief drop is a resumed connection rather than a replaced one. It buffers data on both server and client, ACKs received messages, and replays whatever was sent while the link was down. It is off by default and must be opted into at *both* ends — `options.AllowStatefulReconnects = true` on `MapHub`, `.WithStatefulReconnect()` on the client — so everything above is still the default behaviour. Group membership is documented as not preserved across a reconnect regardless, so rejoining stays your job either way.
</details>

<details>
<summary>5. <code>await Clients.Group("room:42").ReceiveMessage(dto)</code> returned without throwing. What has that proved, and what did it cost?</summary>

Very little about the client. The send API is documented as "does not wait for a response from the receiver" — the `Task` completes when the message has been handed to the transport, not when a browser received it, deserialized it, or ran the handler. The group may have been empty. Reading a completed send as delivery confirmation is exactly where "we sent the notification but the user never saw it" comes from.

For a real answer you need *client results*: `ISingleClientProxy.InvokeAsync<T>` on `Clients.Caller` or `Clients.Client(connectionId)` (also reachable through `IHubContext`), with the client returning a value from its `.On` handler. It is single-client by design — there is no "invoke a group and collect the replies" — so a group-wide ack is something you model yourself as an explicit client→server call.

Cost: one socket write per member connection (the payload is serialized once per hub protocol and cached, not once per connection), and behind a backplane the message is also published and re-fanned by every other server. Levers, in that order: narrow the target — a group per room, not `Clients.All` — then cut the rate or batch, then send an identifier plus a fetch ("order 42 changed") instead of serializing state on every change.
</details>

---

## Cross-References

- **Microservices messaging deep-dive:** [SignalR in microservices](../../05-microservices-and-messaging/07-signalr.md)
- **Protocol comparison:** [WebSockets](../../02-api-development/10-websockets.md), [Server-Sent Events](../../02-api-development/15-server-sent-events.md)
- **Networking foundation:** [Networking Protocols](../../06-distributed-and-observability/04-networking-protocols.md)
- **Auth pipeline:** [Security & Authentication](./09-security.md)
- **HTTP client side:** [HttpClient & Resilience](./14-httpclient-resilience.md)
- **Async fundamentals:** [Async/Await & Threading](./03-async-and-threading.md)

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — *ASP.NET Core SignalR* (`https://learn.microsoft.com/aspnet/core/signalr/introduction`)
- Microsoft Learn — *SignalR scale-out with Redis* and *Azure SignalR Service*
- ASP.NET Core source: `dotnet/aspnetcore` — `src/SignalR`
- RFC 6455 — *The WebSocket Protocol*
- RFC 8441 — *Bootstrapping WebSockets with HTTP/2*

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Caching Strategies](10-caching.md) · [↑ Back to top](#signalr--real-time-communication) · [Next: Modern C# Features →](12-modern-csharp.md)

<!-- nav-footer-end -->
