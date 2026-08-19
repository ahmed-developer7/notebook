# Security & Authentication

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 4 — Auth & API Security | 2026-05-07 |

> 📘 **Main file**: Interview-ready summary, drills, and cheat sheet live in **[Authentication & Authorization](../../02-api-development/02-authentication-and-authorization.md)**. This file is the implementation deep-dive.

## Why It Matters

A single missing `[Authorize]` attribute, an unparameterized SQL string, or a forgotten HSTS header is the difference between a healthy production system and a Monday-morning incident. Security in .NET 10 is not a single library — it is a stack of small, layered defenses (TLS, authentication, authorization, anti-forgery, input validation, output encoding, secret management, rate limiting, security headers) and each layer assumes the others are doing their job. This document is the reference for what each layer does, why it exists, when to use it, and where the common foot-guns are buried.

## Contents

- [Security & Authentication](#19-security--authentication)
  - [Introduction: Without Security vs With Security](#introduction-without-security-vs-with-security)
  - [Real-World Analogy: The Castle](#real-world-analogy-the-castle)
  - [The Security Layer Cake](#the-security-layer-cake)
  - [JWT Authentication](#jwt-authentication)
  - [Cookie Authentication](#cookie-authentication)
  - [OpenID Connect (OIDC)](#openid-connect-oidc)
  - [Authorization: Roles, Claims, Policies](#authorization-roles-claims-policies)
  - [HTTPS, TLS 1.3, HSTS](#https-tls-13-hsts)
  - [Anti-Forgery (CSRF)](#anti-forgery-csrf)
  - [Content Security Policy & Security Headers](#content-security-policy--security-headers)
  - [Input Validation & Output Encoding (XSS)](#input-validation--output-encoding-xss)
  - [SQL Injection Prevention](#sql-injection-prevention)
  - [Secrets Management](#secrets-management)
  - [Rate Limiting (.NET 7+)](#rate-limiting-net-7)
  - [OWASP Top 10 in .NET](#owasp-top-10-in-net)
  - [Common Pitfalls](#common-pitfalls)
  - [Best Practices](#best-practices)
  - [Real-World Scenarios](#real-world-scenarios)
  - [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
  - [Self-Test](#self-test)
  - [Cross-References](#cross-references)
  - [Sources](#sources)

---

## 19. Security & Authentication

> **Difficulty:** Intermediate to Advanced | **Reading Time:** ~35 min

### Introduction: Without Security vs With Security

#### Without Security (a hypothetical naive API)

```
Request: POST /api/orders   { userId: 42, amount: 9999 }
        |
        v
+-------------------------------+
| HTTP server (no TLS)          |
| - Reads body                  |
| - INSERT INTO Orders ...      |  <- raw string concat
| - Returns 200                 |
+-------------------------------+

Attacker can:
  * Sniff the wire (no TLS) and read every token
  * Replay any user's request (no auth)
  * Pass userId=1 to act as someone else (no authorization)
  * Inject SQL via the amount field (' OR 1=1; DROP ...)
  * Embed your endpoint in a malicious page (no CSRF)
  * Hammer the endpoint forever (no rate limit)

Result: total compromise within minutes of going live.
```

#### With Security (the same API, hardened)

```
Request: POST /api/orders
         Authorization: Bearer eyJhbGciOiJIUzI1...
         X-CSRF-Token: ...
         (over TLS 1.3)
        |
        v
+--------------------------------------------------+
| 1. TLS termination (HSTS, TLS 1.3)               |
| 2. Rate limiter middleware (per IP / per user)   |
| 3. Authentication middleware (JWT validation)    |
| 4. Authorization middleware (policy: "PlaceOrder")|
| 5. Anti-forgery validation (state-changing verbs)|
| 6. Model binding + DataAnnotations validation     |
| 7. Endpoint logic (parameterized SQL via EF Core)|
| 8. Output encoding on response                   |
+--------------------------------------------------+
        |
        v
   200 OK + security headers
   (X-Content-Type-Options, X-Frame-Options, CSP, etc.)
```

Each layer is small. Skip one and an attacker has a foothold.

### Real-World Analogy: The Castle

```
+----------------------------------------------------------+
|                       THE CASTLE                         |
|                                                          |
|   Moat (TLS)                    -- can't even approach   |
|   Drawbridge guard (Rate limit) -- "you knock too much"  |
|   Gate (Authentication)         -- "show me your seal"   |
|   Inner door (Authorization)    -- "your seal says       |
|                                    'merchant', not       |
|                                    'royal vault'"        |
|   Wax-sealed letter (CSRF)      -- "is this YOUR order?" |
|   Royal scribe (Validation)     -- "this contract is     |
|                                    malformed"            |
|   Vault (Encryption at rest)    -- "even if you steal,   |
|                                    you can't read"       |
+----------------------------------------------------------+

Lose the moat -> visible secrets.
Lose the gate -> anyone walks in.
Lose the inner door -> peasant accesses crown jewels.
Lose the seal -> someone forges your signature.
```

### The Security Layer Cake

```
+----------------------------------------------------------+
| Layer                | Concern               | .NET tool  |
+----------------------+-----------------------+-----------+
| Transport            | Confidentiality       | Kestrel + HSTS, TLS 1.3
| Edge (rate/WAF)      | Availability          | RateLimiter, Front Door, AGW
| AuthN (who?)         | Identity              | JwtBearer, Cookies, OIDC
| AuthZ (what?)        | Permission            | [Authorize], Policies, Claims
| Anti-forgery         | Cross-site requests   | Antiforgery middleware
| Headers              | Browser hardening     | CSP, X-Frame-Options, etc.
| Input                | Untrusted data        | DataAnnotations, FluentValidation
| Output               | XSS                   | Razor encoding, AntiXSS encoder
| Storage              | Data at rest          | Data Protection API, Always Encrypted
| Secrets              | Config leakage        | User Secrets, Key Vault
| Audit                | Forensics             | ILogger, structured logs
+----------------------+-----------------------+-----------+
```

A request typically traverses every row in order. **Defense in depth** means one failed layer is contained by the next.

---

### JWT Authentication

#### What Is a JWT?

A **JSON Web Token** is a compact, signed (and optionally encrypted) string carrying claims about a user. The server validates the signature on every request — no DB lookup needed.

```
JWT structure:
+-----------+ . +--------+ . +-----------+
| header    |   | payload|   | signature |
| (alg/type)|   | (claims)|  | (HMAC/RSA)|
+-----------+ . +--------+ . +-----------+

Each segment is base64url(JSON).

Example decoded payload:
{
  "sub": "42",                  // subject (user id)
  "email": "ahmed@example.com",
  "role": "Admin",
  "iss": "https://auth.example.com",
  "aud": "api.example.com",
  "exp": 1700000000,            // expiration (seconds since epoch)
  "iat": 1699996400             // issued at
}
```

#### Properties Box

```
+-------------------------------------+
| JWT Properties                      |
+-------------------------------------+
| ✓ Stateless — no server-side store  |
| ✓ Self-contained — claims travel    |
| ✓ Cross-domain friendly             |
| ✓ Easy to validate at edge / in API |
| ✓ Compact (URL-safe base64)         |
| ✗ Cannot be revoked before expiry   |
| ✗ Larger than a session cookie      |
| ✗ Must NOT contain secrets in payload (it's only signed, not encrypted by default) |
| ✗ Vulnerable to key compromise      |
+-------------------------------------+
```

#### Login + Validation Flow

```
Client                           Auth Server                 API Server
  |  POST /login {email, pwd}        |                          |
  |--------------------------------->|                          |
  |                                  | Verify credentials       |
  |                                  | Sign JWT (HS256/RS256)   |
  |  200 { access_token, refresh }   |                          |
  |<---------------------------------|                          |
  |                                                             |
  |  GET /api/orders                                            |
  |  Authorization: Bearer eyJ...                               |
  |------------------------------------------------------------>|
  |                                  Validate signature, exp,   |
  |                                  iss, aud, nbf              |
  |                                  Build ClaimsPrincipal      |
  |  200 [orders]                                               |
  |<------------------------------------------------------------|
```

#### .NET 10 Setup

```csharp
// Program.cs
builder.Services
    .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer           = true,
            ValidateAudience         = true,
            ValidateLifetime         = true,
            ValidateIssuerSigningKey = true,
            ClockSkew                = TimeSpan.FromMinutes(2), // do not leave default 5min in security-sensitive systems
            ValidIssuer   = builder.Configuration["Jwt:Issuer"],
            ValidAudience = builder.Configuration["Jwt:Audience"],
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"]!))
        };
        options.MapInboundClaims = false; // keep "sub", don't rewrite to ClaimTypes.NameIdentifier
    });

builder.Services.AddAuthorization();
var app = builder.Build();
app.UseAuthentication();
app.UseAuthorization();
```

#### Token Generation

```csharp
public sealed class TokenService(IConfiguration config)
{
    public string GenerateToken(User user)
    {
        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub,   user.Id.ToString()),
            new(JwtRegisteredClaimNames.Email, user.Email),
            new(JwtRegisteredClaimNames.Jti,   Guid.NewGuid().ToString()),
            new(ClaimTypes.Role,               user.Role)
        };

        var key   = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(config["Jwt:Key"]!));
        var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

        var token = new JwtSecurityToken(
            issuer:             config["Jwt:Issuer"],
            audience:           config["Jwt:Audience"],
            claims:             claims,
            notBefore:          DateTime.UtcNow,
            expires:            DateTime.UtcNow.AddMinutes(15), // short-lived access token
            signingCredentials: creds);

        return new JwtSecurityTokenHandler().WriteToken(token);
    }
}
```

#### When to Use JWT

```
✅ Good fit:
├─ Public APIs consumed by SPAs / mobile / partner systems
├─ Microservices passing identity between hops
├─ Stateless horizontal scale (no sticky sessions)
└─ Federated auth (one issuer, many resources)

❌ Bad fit:
├─ Traditional server-rendered web apps (use cookies)
├─ Need instant revocation (use opaque tokens or short TTL + denylist)
├─ Storing sensitive payload (JWT is signed, not encrypted by default)
└─ Long-lived sessions (use refresh tokens, not 1-day access tokens)
```

#### Worked Example: Refresh Token Rotation

```csharp
// Issue a short access token (15 min) plus a longer refresh token (7 days, server-stored, single-use).
public sealed record TokenPair(string AccessToken, string RefreshToken);

[HttpPost("refresh")]
public async Task<IActionResult> Refresh([FromBody] string refreshToken)
{
    var stored = await _refreshTokens.FindActiveAsync(refreshToken);
    if (stored is null || stored.ExpiresAt < DateTime.UtcNow)
        return Unauthorized();

    // Single-use: invalidate old, issue new pair
    stored.RevokedAt = DateTime.UtcNow;
    var user = await _users.GetByIdAsync(stored.UserId);
    var pair = _tokens.IssuePair(user!);
    await _refreshTokens.SaveAsync(pair.RefreshToken, user!.Id);
    await _refreshTokens.SaveChangesAsync();
    return Ok(pair);
}
```

#### Worked Example: Logout / Revocation via Denylist

```csharp
// JWTs cannot be revoked by themselves. Maintain a short-lived denylist keyed by jti.
public sealed class JwtDenylist(IDistributedCache cache)
{
    public Task DenyAsync(string jti, DateTimeOffset exp) =>
        cache.SetStringAsync($"deny:{jti}", "1",
            new DistributedCacheEntryOptions { AbsoluteExpiration = exp });

    public async Task<bool> IsDeniedAsync(string jti) =>
        await cache.GetStringAsync($"deny:{jti}") is not null;
}

// Custom JwtBearer event:
options.Events = new JwtBearerEvents
{
    OnTokenValidated = async ctx =>
    {
        var jti = ctx.Principal!.FindFirstValue(JwtRegisteredClaimNames.Jti);
        if (jti is not null && await denylist.IsDeniedAsync(jti))
            ctx.Fail("Token revoked");
    }
};
```

---

### Cookie Authentication

For server-rendered apps (Razor Pages, MVC, Blazor Server) cookies are still the right answer. The cookie is HTTP-only, Secure, SameSite=Lax/Strict, and tied to a server-side ticket.

```
+-------------------------------------+
| Cookie Auth Properties              |
+-------------------------------------+
| ✓ Browser handles attachment        |
| ✓ HTTP-only -> JS cannot read it    |
| ✓ Trivial revocation (server clears)|
| ✓ Smaller than JWT on the wire      |
| ✗ Same-origin oriented (CSRF risk)  |
| ✗ Sticky for multi-server (or use   |
|    distributed ticket store / DPAPI)|
+-------------------------------------+
```

```csharp
builder.Services
    .AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.Cookie.HttpOnly  = true;
        options.Cookie.SecurePolicy = CookieSecurePolicy.Always;
        options.Cookie.SameSite  = SameSiteMode.Lax; // Strict for max isolation
        options.ExpireTimeSpan   = TimeSpan.FromHours(8);
        options.SlidingExpiration = true;
        options.LoginPath        = "/auth/login";
        options.AccessDeniedPath = "/auth/forbidden";
    });
```

When **not** to use cookies: pure SPA or mobile clients on cross-origin domains, where CSRF management plus CORS preflight makes JWTs simpler.

---

### OpenID Connect (OIDC)

OIDC is OAuth 2.0 + an identity layer. Use it for "Sign in with Google / Microsoft / Okta / Azure AD". The server never sees the password.

```
Browser            Your App            Identity Provider
   |  /login          |                          |
   |----------------->|  302 to /authorize?...   |
   |                  |------------------------->|
   |  user authenticates with IdP                |
   |                  | 302 with ?code=xxx       |
   |<----------------------------------------    |
   |  /callback?code=xxx                          |
   |----------------->| POST /token (code+secret)|
   |                  |------------------------->|
   |                  | { id_token, access_token}|
   |                  | validate id_token sig    |
   |                  | sign cookie              |
   |  302 to / (cookie set)                       |
```

```csharp
builder.Services.AddAuthentication(o =>
{
    o.DefaultScheme         = CookieAuthenticationDefaults.AuthenticationScheme;
    o.DefaultChallengeScheme = OpenIdConnectDefaults.AuthenticationScheme;
})
.AddCookie()
.AddOpenIdConnect(o =>
{
    o.Authority = "https://login.microsoftonline.com/<tenant>/v2.0";
    o.ClientId  = builder.Configuration["Oidc:ClientId"];
    o.ClientSecret = builder.Configuration["Oidc:ClientSecret"];
    o.ResponseType = "code"; // Authorization Code with PKCE — the secure flow
    o.UsePkce      = true;
    o.SaveTokens   = true;
    o.Scope.Add("openid"); o.Scope.Add("profile"); o.Scope.Add("email");
});
```

Use the **Authorization Code flow with PKCE**. Implicit flow is dead.

---

### Authorization: Roles, Claims, Policies

> Authentication = "Who are you?". Authorization = "What may you do?". Two distinct middlewares; both must run.

```
+----------------------------------------------+
| Approach    | Granularity     | When to use  |
+-------------+-----------------+--------------+
| Roles       | Coarse          | < 10 buckets, |
|             |                 | rarely change|
| Claims      | Medium          | Attributes   |
|             |                 | known at     |
|             |                 | login time   |
| Policies    | Fine            | Compose rules|
|             |                 | from claims/ |
|             |                 | requirements |
| Resource-   | Per-instance    | "owner of    |
| based       |                 | record" rules|
+----------------------------------------------+
```

#### Role-based

```csharp
[Authorize(Roles = "Admin,Manager")]
public IActionResult AdminPanel() => View();
```

#### Claim-based

```csharp
options.AddPolicy("PremiumOnly", p =>
    p.RequireClaim("subscription", "premium", "enterprise"));

[Authorize(Policy = "PremiumOnly")]
public IActionResult PremiumFeature() => View();
```

#### Policy with Custom Requirement

```csharp
public sealed class MinimumAgeRequirement(int minimumAge) : IAuthorizationRequirement
{
    public int MinimumAge { get; } = minimumAge;
}

public sealed class MinimumAgeHandler : AuthorizationHandler<MinimumAgeRequirement>
{
    protected override Task HandleRequirementAsync(
        AuthorizationHandlerContext ctx, MinimumAgeRequirement req)
    {
        var dob = ctx.User.FindFirst("dateOfBirth")?.Value;
        if (DateOnly.TryParse(dob, out var d) &&
            DateOnly.FromDateTime(DateTime.UtcNow).Year - d.Year >= req.MinimumAge)
        {
            ctx.Succeed(req);
        }
        return Task.CompletedTask;
    }
}

builder.Services.AddSingleton<IAuthorizationHandler, MinimumAgeHandler>();
builder.Services.AddAuthorization(o =>
    o.AddPolicy("Adult", p => p.Requirements.Add(new MinimumAgeRequirement(18))));
```

#### Resource-based (per-instance)

```csharp
// "Only the order's owner OR an admin can view it"
public sealed class OrderOwnerHandler : AuthorizationHandler<SameOwnerRequirement, Order>
{
    protected override Task HandleRequirementAsync(
        AuthorizationHandlerContext ctx, SameOwnerRequirement req, Order order)
    {
        var userId = ctx.User.FindFirstValue(JwtRegisteredClaimNames.Sub);
        if (order.OwnerId.ToString() == userId || ctx.User.IsInRole("Admin"))
            ctx.Succeed(req);
        return Task.CompletedTask;
    }
}

// In endpoint:
var auth = await _authService.AuthorizeAsync(User, order, "OrderOwner");
if (!auth.Succeeded) return Forbid();
```

---

### HTTPS, TLS 1.3, HSTS

```
Without HTTPS:
  Client --[plaintext]-- ISP/coffeeshop wifi --[plaintext]-- Server
              ^^^                                ^^^
              everyone with a packet capture sees the JWT

With HTTPS (TLS 1.3):
  Client ====[encrypted]==== Internet ====[encrypted]==== Server
                              + cert pinning
                              + Perfect Forward Secrecy
                              + HSTS forces future visits to https://
```

```csharp
// Program.cs
if (!app.Environment.IsDevelopment())
{
    app.UseHsts();   // Strict-Transport-Security: max-age=...; includeSubDomains
}
app.UseHttpsRedirection();

// kestrel hardening (appsettings.json)
"Kestrel": {
  "EndpointDefaults": { "Protocols": "Http1AndHttp2AndHttp3" },
  "Endpoints": {
    "Https": {
      "Url": "https://*:443",
      "SslProtocols": ["Tls12", "Tls13"]
    }
  }
}
```

**HSTS rules of thumb:**
- Max-age ≥ 31536000 (1 year) for production.
- Use `includeSubDomains` *only* after every subdomain is HTTPS-ready.
- `preload` registers your domain with browsers; you cannot easily un-preload.

---

### Anti-Forgery (CSRF)

CSRF tricks a *logged-in* user's browser into submitting a request to your site. The browser dutifully attaches the cookie. Your API thinks the user wanted to do it.

```
Without anti-forgery:
  Victim has cookie for bank.com.
  Victim visits evil.com which contains:
    <form action="https://bank.com/transfer" method="POST">
      <input name="amount" value="9999"><input name="to" value="attacker">
    </form>
    <script>document.forms[0].submit()</script>
  Browser sends cookie. Bank says "ah, the user wants to transfer". Done.

With anti-forgery token:
  Bank issues a per-session CSRF token, embedded in form/header.
  evil.com cannot read that token (Same-Origin Policy).
  POST without token -> 400 Bad Request.
```

```csharp
builder.Services.AddAntiforgery(o => o.HeaderName = "X-CSRF-TOKEN");
app.UseAntiforgery();

// Razor Pages / MVC: <form> auto-emits a hidden __RequestVerificationToken.
// SPAs: emit the token via a /antiforgery/token endpoint and send it in X-CSRF-TOKEN.

[ValidateAntiForgeryToken]
[HttpPost]
public IActionResult Transfer([FromForm] TransferDto dto) { /* ... */ }
```

> JWT-only APIs (no cookies) are not vulnerable to classic CSRF — the browser does not auto-attach an `Authorization` header. But cookie-bearing endpoints **must** validate anti-forgery on every state-changing request.

---

### Content Security Policy & Security Headers

```
+--------------------------+--------------------------------------+
| Header                   | Purpose                              |
+--------------------------+--------------------------------------+
| Content-Security-Policy  | Whitelist where scripts/styles load  |
| Strict-Transport-Security| Force HTTPS on future visits         |
| X-Content-Type-Options   | Block MIME sniffing                  |
| X-Frame-Options          | Prevent click-jacking (deprecated by |
|                          | frame-ancestors in CSP, but still ok)|
| Referrer-Policy          | Limit referer leakage                |
| Permissions-Policy       | Disable camera/mic/geolocation by    |
|                          | default                              |
| Cross-Origin-Opener-Policy| Isolate window references           |
| Cross-Origin-Resource-Policy| Block cross-site embedding         |
+--------------------------+--------------------------------------+
```

```csharp
app.Use(async (ctx, next) =>
{
    var h = ctx.Response.Headers;
    h["Content-Security-Policy"] =
        "default-src 'self'; " +
        "script-src 'self' 'nonce-" + ctx.Items["csp-nonce"] + "'; " +
        "style-src 'self' 'unsafe-inline'; " +
        "img-src 'self' data: https:; " +
        "frame-ancestors 'none'; " +
        "base-uri 'self'; " +
        "form-action 'self'";
    h["X-Content-Type-Options"] = "nosniff";
    h["X-Frame-Options"]        = "DENY";
    h["Referrer-Policy"]        = "strict-origin-when-cross-origin";
    h["Permissions-Policy"]     = "camera=(), microphone=(), geolocation=()";
    await next();
});
```

CSP is the single most effective XSS defense the browser gives you. Start in `Content-Security-Policy-Report-Only` mode, watch the violation reports, then promote to enforcing.

---

### Input Validation & Output Encoding (XSS)

#### Two-step rule

1. **Validate** input on the way in (allow-list, not deny-list).
2. **Encode** output on the way out (HTML, JS, URL contexts each need different encoding).

```csharp
public sealed class CreateUserDto
{
    [Required, StringLength(50, MinimumLength = 2)]
    public string Name { get; init; } = "";

    [Required, EmailAddress]
    public string Email { get; init; } = "";

    [Range(18, 120)]
    public int Age { get; init; }
}
```

Razor automatically HTML-encodes interpolated values:

```cshtml
<p>Hello @Model.Name</p>           @* safe *@
<p>@Html.Raw(Model.Name)</p>       @* DANGEROUS — only for trusted html *@
```

For SPAs returning JSON, the browser does not interpret the response body as HTML — but it **will** interpret the response if you echo user input into a server-rendered page or into `innerHTML`. Always encode at the rendering boundary.

```csharp
// Manual encoding
var encoder = HtmlEncoder.Default;
var safe    = encoder.Encode(userInput);
```

---

### SQL Injection Prevention

#### Without parameterization (DO NOT DO THIS)

```csharp
// VULNERABLE
var sql = $"SELECT * FROM Users WHERE Email = '{email}'";
var users = ctx.Users.FromSqlRaw(sql).ToList();

// Attacker provides email = ' OR '1'='1
// Resulting SQL: SELECT * FROM Users WHERE Email = '' OR '1'='1'
```

#### With parameterization (correct)

```csharp
// EF Core LINQ — always parameterized
var users = await ctx.Users.Where(u => u.Email == email).ToListAsync();

// Raw SQL — use FromSqlInterpolated or FromSql with parameters
var users2 = await ctx.Users
    .FromSql($"SELECT * FROM Users WHERE Email = {email}") // parameterized!
    .ToListAsync();

// ADO.NET
using var cmd = new SqlCommand("SELECT * FROM Users WHERE Email = @e", conn);
cmd.Parameters.Add("@e", SqlDbType.NVarChar, 256).Value = email;
```

> **Rule:** if you find yourself building SQL by string concatenation with user input, you are writing a vulnerability. Period.

---

### Secrets Management

```
+------------------------+----------------------------------------+
| Environment            | Mechanism                              |
+------------------------+----------------------------------------+
| Local development      | dotnet user-secrets                    |
| CI/CD                  | Pipeline secret variables (masked)     |
| Production (Azure)     | Key Vault + Managed Identity           |
| Production (AWS)       | Secrets Manager / SSM Parameter Store  |
| Production (k8s)       | Sealed Secrets / External Secrets Op.  |
| Anywhere               | NEVER commit to git                    |
+------------------------+----------------------------------------+
```

#### User Secrets (dev only)

```bash
dotnet user-secrets init
dotnet user-secrets set "Jwt:Key" "supersecret-min-32-bytes-please"
```

Stored at `%APPDATA%\Microsoft\UserSecrets\<id>\secrets.json` — never committed.

#### Azure Key Vault + Managed Identity

```csharp
builder.Configuration.AddAzureKeyVault(
    new Uri("https://my-vault.vault.azure.net/"),
    new DefaultAzureCredential());

// Now Configuration["Jwt:Key"] is fetched from Key Vault transparently.
```

Managed Identity = no secret to manage the secret store. The VM/Function/Container has an identity Azure issues; Key Vault grants `get` to that identity.

---

### Rate Limiting (.NET 7+)

```csharp
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;

    // Per-IP fixed window
    options.AddPolicy("ip", httpContext =>
        RateLimitPartition.GetFixedWindowLimiter(
            partitionKey: httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            factory: _ => new FixedWindowRateLimiterOptions
            {
                Window           = TimeSpan.FromSeconds(10),
                PermitLimit      = 100,
                QueueLimit       = 0,
                QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                AutoReplenishment = true
            }));

    // Per-user token bucket (bursty traffic, smooth refill)
    options.AddPolicy("user", httpContext =>
        RateLimitPartition.GetTokenBucketLimiter(
            partitionKey: httpContext.User.Identity?.Name ?? "anon",
            factory: _ => new TokenBucketRateLimiterOptions
            {
                TokenLimit      = 60,
                TokensPerPeriod = 60,
                ReplenishmentPeriod = TimeSpan.FromMinutes(1),
                AutoReplenishment   = true,
                QueueLimit          = 0
            }));
});

app.UseRateLimiter();

[EnableRateLimiting("ip")]
[HttpPost("login")]
public IActionResult Login(LoginDto dto) { /* ... */ }
```

```
Algorithm choice:
+----------------+----------------------------------------+
| Fixed window   | Simple, but bursts at boundary         |
| Sliding window | Smoother, more memory                  |
| Token bucket   | Allows bursts up to bucket size        |
| Concurrency    | Limit concurrent requests, not rate    |
+----------------+----------------------------------------+
```

Pair the in-process limiter with an upstream WAF / Front Door rate limit for defense in depth.

---

### OWASP Top 10 in .NET

```
+-----+---------------------------+------------------------------------------+
| #   | Vulnerability             | .NET Prevention                          |
+-----+---------------------------+------------------------------------------+
| A01 | Broken Access Control      | [Authorize], policy-based auth, resource-|
|     |                           | based handlers, deny-by-default          |
| A02 | Cryptographic Failures     | Data Protection API, HTTPS, HSTS, no    |
|     |                           | MD5/SHA1, no DES, AES-GCM/RSA-OAEP       |
| A03 | Injection (SQL/XSS/CMD)   | EF Core (parameterized), Razor encoding, |
|     |                           | never Process.Start with user input      |
| A04 | Insecure Design           | Threat modeling, DTOs not entities,      |
|     |                           | secure defaults                          |
| A05 | Security Misconfiguration  | Environment configs, no dev errors in   |
|     |                           | prod, default deny on CORS/CSP           |
| A06 | Vulnerable Components      | dotnet list package --vulnerable, SBOM,  |
|     |                           | Dependabot/Renovate                      |
| A07 | Auth Failures             | ASP.NET Identity, JWT validation, MFA,   |
|     |                           | account lockout, password hashing (PBKDF2|
|     |                           | / Argon2id)                              |
| A08 | Data Integrity Failures   | Signed JWTs, anti-forgery tokens,        |
|     |                           | package signing, deserialization safety  |
| A09 | Logging Failures          | Structured logging, audit trails,        |
|     |                           | redact PII, ship logs off-host           |
| A10 | SSRF                      | Validate/whitelist outbound URLs, deny   |
|     |                           | private IP ranges, separate egress proxy |
+-----+---------------------------+------------------------------------------+
```

---

### Common Pitfalls

1. **Storing JWT signing key in source control.** Anyone with the repo can mint tokens.
2. **Using `HS256` with a short, guessable key.** HMAC keys must be at least 32 random bytes; or use RSA/ECDSA.
3. **Defaulting `ClockSkew` to 5 minutes silently.** Tokens live up to 5 minutes past their `exp`. For short-lived flows, drop to 1–2 minutes.
4. **Disabling `ValidateLifetime` "for tests".** That config ships to prod sooner or later.
5. **Putting PII or secrets in JWT payload.** A JWT is *signed*, not *encrypted*. Anyone who intercepts it reads it.
6. **Forgetting `app.UseAuthentication()` before `UseAuthorization()`** (or omitting it). Authorization sees an anonymous principal and silently 401s every request — or worse, allows anonymous if the policy is poorly written.
7. **`[Authorize]` on the controller, anonymous endpoint added later.** Default to `[Authorize]` globally and require explicit `[AllowAnonymous]` opt-in.
8. **CORS `AllowAnyOrigin` + `AllowCredentials`.** The framework will throw — but devs work around it by reflecting the request origin, which is equivalent to allowing every origin and breaks the security model.
9. **Validating input at the controller but trusting it deeper.** Validate at the boundary; treat anything past the boundary as already-checked.
10. **Logging full request bodies including passwords / tokens.** Use a redacting logger; assert in CI that your log pipeline does not contain headers like `Authorization`.

---

### Best Practices

1. **Default deny.** Add `[Authorize]` globally; opt-in to anonymous with `[AllowAnonymous]`. Mistakes default to "locked" rather than "open".
2. **Short access tokens, longer refresh tokens.** 15 min access / 7 day refresh, refresh tokens single-use and server-tracked.
3. **Use Authorization Code flow with PKCE** for all browser-based OIDC. Implicit flow is deprecated.
4. **Centralize validation logic.** A `TokenValidationParameters` instance per environment, loaded from configuration — never hand-rolled per controller.
5. **Treat secrets as deployment artefacts, not source.** User Secrets locally; Key Vault / Secrets Manager in prod; Managed Identity to access them.
6. **Rotate keys with a grace window.** Maintain a list of acceptable signing keys with kid (key id) headers; introduce new keys before old ones expire.
7. **Threat-model before coding.** STRIDE the new endpoint; ask "spoofing, tampering, repudiation, info disclosure, DoS, elevation of privilege".
8. **Pin TLS to 1.2+ and prefer 1.3.** Disable protocols < TLS 1.2 in OS / Kestrel config; modern .NET defaults are good but verify.
9. **Layer rate limits.** WAF / Front Door at edge, ASP.NET RateLimiter per service, application-level throttles per business rule (e.g., 5 password resets / hour).
10. **Audit security-relevant events.** Log login success/fail with user id, IP, UA; ship to SIEM; alarm on anomalies (e.g., 100 failed logins from one IP).
11. **Hash passwords with a slow KDF.** Argon2id (preferred) or PBKDF2 with ≥ 600k iterations (2026 OWASP guidance). Never SHA-256, never MD5.
12. **Constant-time compare for tokens / hashes.** Use `CryptographicOperations.FixedTimeEquals`, not `==`, when comparing secrets.

---

### Real-World Scenarios

#### Scenario 1: Securing a Public API for Partner Integrations

**Need:** Third-party partners call your API on behalf of their customers; you must isolate one partner's traffic from another's.

```
Partner -> POST /oauth/token (client_credentials) -> Your auth server
       <- access_token (scope=orders:read, partner_id=42, exp=15min)

Partner -> GET /api/orders Authorization: Bearer ... -> API
       Validates: signature, exp, iss, aud
       Authorization policy: "ScopeOrdersRead" + tenant filter on partner_id

Defense in depth:
  - Per-partner rate limits (1000 rps each)
  - Per-partner row-level filter (every query joined to partner_id)
  - mTLS at the gateway (cert per partner)
  - Audit log keyed by partner_id
```

Implementation outline:

```csharp
options.AddPolicy("ScopeOrdersRead", p => p.RequireClaim("scope", "orders:read"));

app.MapGet("/api/orders", async (ClaimsPrincipal user, AppDb db) =>
{
    var partnerId = int.Parse(user.FindFirstValue("partner_id")!);
    return Results.Ok(await db.Orders.Where(o => o.PartnerId == partnerId).ToListAsync());
}).RequireAuthorization("ScopeOrdersRead").RequireRateLimiting("user");
```

#### Scenario 2: Multi-Tenant Data Isolation

```
+---------+    +--------------------------+    +---------------+
| Browser |--->| API (tenantId in claims) |--->| EF Core query |
+---------+    +--------------------------+    +---------------+
                          |                            |
                          |  global query filter:      |
                          |  builder.HasQueryFilter(   |
                          |    e => e.TenantId == _t)  |
                          v                            v
              every controller is automatically scoped — forgetting
              the WHERE clause cannot leak data across tenants.
```

```csharp
public sealed class TenantProvider(IHttpContextAccessor http)
{
    public int TenantId =>
        int.Parse(http.HttpContext!.User.FindFirstValue("tenantId")
            ?? throw new InvalidOperationException("No tenant claim"));
}

protected override void OnModelCreating(ModelBuilder b)
{
    b.Entity<Order>().HasQueryFilter(o => o.TenantId == _tenantProvider.TenantId);
}
```

Add an integration test that calls `/api/orders` as tenant A and asserts that no row from tenant B appears in any response — make this a CI gate.

#### Scenario 3: Defending Against Credential Stuffing

**Threat:** Attacker has 10M leaked email/password pairs from another breach. They try them all against your `/login`.

Layered defense:

```
1. CAPTCHA after N failures from IP (Cloudflare Turnstile, hCaptcha)
2. Rate limit /login per IP (10/min) and per email (5/min)
3. Account lockout after 5 failed logins (with exponential backoff)
4. Have-I-Been-Pwned check on registration / password change
   (k-Anonymity API: send first 5 chars of SHA-1 of password)
5. MFA available; required for admins
6. Alert on geographic / device anomalies
7. Login monitoring: same IP trying 1000 distinct emails -> auto-block
```

```csharp
[EnableRateLimiting("login-ip")]   // 10/min/IP
[EnableRateLimiting("login-user")] // 5/min/email
[HttpPost("login")]
public async Task<IActionResult> Login(LoginDto dto)
{
    var user = await _users.FindByEmailAsync(dto.Email);

    // Constant-time password verify even if user is null (prevents user enum)
    var dummy = "$argon2id$v=19$m=...$dummy"; // constant
    var hash  = user?.PasswordHash ?? dummy;
    var ok    = _hasher.Verify(dto.Password, hash);
    if (user is null || !ok)
    {
        await _failures.RecordAsync(dto.Email, HttpContext.Connection.RemoteIpAddress);
        return Unauthorized();
    }
    if (await _failures.IsLockedOutAsync(user.Id)) return StatusCode(423);

    return Ok(_tokens.IssuePair(user));
}
```

---

### Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

#### Drill 1 — JWT validation

> **Q**: Walk me through every step the server performs to validate an incoming JWT.
>
> **A**: (1) Parse header/payload/signature from base64url; (2) verify the signature with the configured key (or fetch from JWKS endpoint, cached) using the algorithm declared in the header — but enforce that algorithm matches the *expected* set, never trust the header alone; (3) check `exp` (not expired), `nbf` (not before now), with bounded `ClockSkew`; (4) check `iss` matches `ValidIssuer`; (5) check `aud` matches `ValidAudience`; (6) build `ClaimsPrincipal` from the payload claims.
>
> **Cross-Q**: What's the "alg = none" attack and how does .NET prevent it?
>
> **A**: An attacker submits a token whose header declares `"alg": "none"` and ships an unsigned payload. A naive validator that reads the algorithm from the header would accept anything. .NET's `JwtBearer` validates against the algorithms supported by the signing key — `IssuerSigningKey` is a `SymmetricSecurityKey` or `RsaSecurityKey`, not an algorithm string, so the alg field is constrained. Also: `TokenValidationParameters.ValidAlgorithms` lets you pin the allowed set explicitly. Never trust the header.
>
> **Cross-Q²**: I set `ClockSkew = TimeSpan.Zero` to be strict. What goes wrong?
>
> **A**: NTP drift between auth server and API server (or between client device and server) routinely causes 100ms-2s of clock skew. With zero tolerance, tokens issued at T=0 with `exp=15min` will fail validation around T=14:58 to T=15:02 depending on which side is fast — random 401s for legitimate users near token expiry. The default 5 minutes is too lax for short-lived tokens; 1-2 minutes is the right balance. Pair with refresh-token rotation so brief skew failures self-heal on next request.

#### Drill 2 — OAuth 2.0 Authorization Code + PKCE

> **Q**: Walk me through Authorization Code flow with PKCE for a single-page app signing in with Google.
>
> **A**: (1) SPA generates a random `code_verifier` (43-128 chars) and its SHA-256 hash `code_challenge`. (2) Redirects the browser to Google's `/authorize` with `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state`, `code_challenge`, `code_challenge_method=S256`. (3) User authenticates with Google; Google redirects back to `redirect_uri?code=xyz&state=...`. (4) SPA POSTs `/token` with the `code` *plus* the original `code_verifier`. (5) Google hashes the verifier, compares to the stored challenge — match means same client. (6) Google returns `access_token` + `id_token` + optional `refresh_token`.
>
> **Cross-Q**: Why PKCE? What attack does it prevent that plain Authorization Code doesn't?
>
> **A**: Authorization code interception. A malicious app on the same device (or a man-in-the-middle on a non-HTTPS redirect URI like `http://localhost`) captures the `code` in the redirect. Without PKCE, the attacker can exchange that code for tokens — auth server has no way to know it's not the legitimate client. PKCE binds the code to the original `code_verifier` that only the legitimate client knows. Without it, the token exchange fails. PKCE replaces the `client_secret` for public clients (SPAs, mobile apps) that can't keep secrets.
>
> **Cross-Q²**: Why has Implicit Flow been deprecated?
>
> **A**: Implicit returned tokens directly in the URL fragment after authentication — no code exchange step. The token was exposed in browser history, referer headers, JS-accessible URL, and there was no way to securely deliver a refresh token. Authorization Code + PKCE replaces it for SPAs in 2026: the code is exchanged server-to-server (or via fetch with CORS), tokens never appear in the URL, and refresh-token-with-rotation is supported. OAuth 2.1 / OAuth 2.0 Security BCP both prescribe PKCE for *all* OAuth clients now, not just public ones.

#### Drill 3 — OAuth 2.0 vs OIDC

> **Q**: What does OpenID Connect add that OAuth 2.0 doesn't have?
>
> **A**: Identity. OAuth 2.0 is an *authorization* framework — it gives you an access token to call APIs on a user's behalf, but it does not tell you *who the user is* in a standard way. OIDC adds an `id_token` (a signed JWT) with standardized claims (`sub`, `name`, `email`, `iss`, `aud`, `exp`, `auth_time`, `nonce`) and a `/userinfo` endpoint. The `id_token` is for the *client* to consume (proves who logged in); the `access_token` is for *resources* to consume (proves what the bearer can do).
>
> **Cross-Q**: If I get both an `id_token` and an `access_token`, which do I send to my API?
>
> **A**: The `access_token`, every time. The `id_token` is a single-use authentication assertion for the *client*, with claims about the user — the API should never validate it as a bearer token. Sending the `id_token` to an API is a common misconfiguration that "works" because both are JWTs signed by the same issuer, but the `aud` and `sub` semantics differ and you lose scope-based authorization. Audience-bind your access tokens, validate `aud` strictly.
>
> **Cross-Q²**: What's the `nonce` parameter in OIDC for?
>
> **A**: Replay protection for the `id_token`. The client generates a random `nonce`, sends it in the `/authorize` request, the IdP includes it in the returned `id_token`. The client validates `nonce` matches what it sent — if an attacker replays a stolen `id_token`, it won't have the new `nonce` for the current login. Distinct from `state` (CSRF protection between the redirects) and from PKCE (code interception protection during code exchange). All three are needed for a hardened flow.

#### Drill 4 — JWT vs session cookies

> **Q**: It's 2026 — when should I use JWT and when should I use a session cookie?
>
> **A**: **Session cookie**: server-rendered apps (Razor Pages, MVC, Blazor Server) with a single domain, when you need easy revocation and trust the browser to handle attachment. **JWT**: cross-origin clients (SPAs on a different domain, mobile, partners), microservices passing identity hop-to-hop, federated auth. **Both**: SPA-with-BFF pattern — the BFF holds the OIDC session cookie, the SPA never sees a token directly, the BFF forwards calls to APIs with JWTs.
>
> **Cross-Q**: JWTs can't be revoked — isn't that a deal-breaker?
>
> **A**: Mitigated, not solved. Standard answer: keep access tokens *short* (5-15 min) so the revocation window is small, plus maintain a server-side denylist keyed by `jti` for high-value revocations (admin logout, security incident). Refresh tokens are long-lived but server-stored, so they can be revoked instantly — and rotation + reuse detection invalidates a whole token family if a stolen refresh token is replayed. The combination gets you fast-enough revocation without giving up the statelessness benefit on the read path.
>
> **Cross-Q²**: BFF pattern — why is it considered the safe SPA architecture in 2026?
>
> **A**: BFF (Backend-for-Frontend) keeps the OIDC session as an HTTP-only cookie *between the browser and the BFF*. The browser never sees access or refresh tokens — XSS can't steal them, no `localStorage` exposure. The BFF stores tokens server-side, forwards API calls with `Authorization: Bearer ...`, handles refresh transparently. Trade-off: you operate a stateful component (the BFF) and lose pure-static-SPA deployability. OWASP and Duende both recommend BFF for any SPA touching sensitive data.

#### Drill 5 — CSRF

> **Q**: Explain CSRF and when you need anti-forgery tokens.
>
> **A**: Cross-Site Request Forgery: a malicious site causes a *logged-in* user's browser to submit a state-changing request to your site. The browser auto-attaches the user's session cookie; your server thinks the user intended the action. Anti-forgery tokens (per-session unique values embedded in your forms/headers) defeat this — the attacker's page can't read your token due to same-origin policy, so the request arrives without it and gets rejected.
>
> **Cross-Q**: My API is JWT-only with no cookies. Do I still need CSRF protection?
>
> **A**: Generally no for classic CSRF — the browser does not auto-attach `Authorization: Bearer` headers, so a cross-site form post lands at your API without the token. But: (1) if you also accept cookie auth on the same endpoints, you're vulnerable; (2) WebSocket / SignalR upgrade requests carry cookies even with token auth, so the upgrade endpoint may need protection; (3) sensitive POST forms with `<form action="https://api.example.com">` from a hostile site won't carry the token, but if your CORS is misconfigured (`Access-Control-Allow-Origin: *` with credentials), things get bad. Belt and braces: SameSite=Strict cookies + JWT in headers + strict CORS.
>
> **Cross-Q²**: What's the relationship between SameSite cookies and CSRF?
>
> **A**: `SameSite=Lax` (modern browser default) means cookies aren't sent on cross-site *POST* requests, only on top-level GET navigations. This kills most classic CSRF without any token at all. `SameSite=Strict` is even stricter — no cookies on any cross-site request, including following an external link. The catch: legacy clients (old browsers, embedded webviews) don't honor SameSite, and some legitimate cross-site flows (federated auth callbacks) require Lax not Strict. Anti-forgery tokens remain the belt; SameSite is the braces.

#### Drill 6 — XSS prevention

> **Q**: How does ASP.NET Core's Razor engine prevent XSS by default, and where can it still go wrong?
>
> **A**: Razor's `@expression` syntax automatically HTML-encodes the output using `HtmlEncoder.Default` — `<script>alert(1)</script>` becomes `&lt;script&gt;...&lt;/script&gt;`. The escape hatch is `@Html.Raw(...)` which trusts the string as-is. XSS still happens when (1) you pass user content to `Html.Raw`, (2) you build HTML strings server-side and write them through `Html.Raw`, (3) you inject user data into JavaScript context (`var x = '@Model.Name';`) — HTML encoding doesn't escape JS context.
>
> **Cross-Q**: How do you safely inject server data into JavaScript?
>
> **A**: Use `JavaScriptEncoder.Default.Encode` for JS string context, or — far better — serialize via JSON and parse in JS: `<script>var x = @Html.Raw(JsonSerializer.Serialize(model));</script>`. `System.Text.Json` escapes characters that could break out of a JS string by default. Even safer: emit data into a `<script type="application/json" id="data">{...}</script>` block, parse in JS with `JSON.parse(document.getElementById('data').textContent)` — full HTML encoding still applies and no JS execution happens until you explicitly parse.
>
> **Cross-Q²**: How does Content-Security-Policy fit in as XSS defense?
>
> **A**: CSP is the last line — even if some encoding gap lets an attacker inject `<script>`, CSP can refuse to execute it. `script-src 'self'` blocks inline scripts and external script tags except from your origin. Use a nonce (`script-src 'self' 'nonce-r4nd0m'`) for inline scripts you control. CSP doesn't *fix* XSS, it *contains* it. Treat CSP as defense in depth: encode *and* set CSP. Start in `Content-Security-Policy-Report-Only` mode, fix violations, then enforce.

#### Drill 7 — HTTPS / HSTS

> **Q**: What does `Strict-Transport-Security` do, and why isn't `UseHttpsRedirection` enough?
>
> **A**: `UseHttpsRedirection` returns a 301/307 from HTTP to HTTPS — but the *first* request to your site is still over HTTP. An attacker on the same network can intercept that initial HTTP request and never let the redirect happen (SSL strip). `Strict-Transport-Security: max-age=31536000; includeSubDomains` tells the browser "for the next year, always use HTTPS to this domain — even if the user types `http://`." After the first HTTPS visit, the browser refuses to make HTTP requests to your domain.
>
> **Cross-Q**: What about the very first visit? HSTS only kicks in after the first HTTPS response.
>
> **A**: The "trust on first use" gap. Mitigation: **HSTS preload** — submit your domain to `hstspreload.org`, browsers ship with your domain on a preloaded list, *no* HTTP attempt is ever made even on the first visit. Catch: removing yourself from the preload list takes months and propagates slowly. Only preload when every subdomain (including future ones) is HTTPS-ready. Don't preload a domain you might want to roll back.
>
> **Cross-Q²**: I set `max-age=31536000; includeSubDomains; preload`. What's the failure mode if `internal.example.com` doesn't support HTTPS?
>
> **A**: After the first visit to `example.com`, the browser refuses to load `http://internal.example.com` at all — and there's no cert to fall back to, so HTTPS fails too. Users see "site can't be reached" with no workaround. Worse, once preloaded, this hits users who've never visited any subdomain. The fix is to roll out HSTS *without* `includeSubDomains` first, verify every subdomain works on HTTPS, then add `includeSubDomains`, *then* (much later) consider `preload`.

#### Drill 8 — Secrets management

> **Q**: Local User Secrets vs Azure Key Vault vs environment variables — when each?
>
> **A**: **User Secrets** (`dotnet user-secrets set`): *local development only*. Stored outside the repo at `%APPDATA%\Microsoft\UserSecrets\<id>\secrets.json`. Never deployed. **Environment variables**: containers, CI/CD pipelines, simple deployments. Easy but visible to anyone with shell access to the host; not auditable per-secret. **Key Vault / AWS Secrets Manager**: production. Auditable access, rotation, fine-grained RBAC, separation of "who can deploy" vs "who can read secrets." The app authenticates via Managed Identity / IAM role — no bootstrap secret on disk.
>
> **Cross-Q**: What's the bootstrap problem and how does Managed Identity solve it?
>
> **A**: "How does my app authenticate to Key Vault to read secrets without a secret to authenticate with?" In the bad old days you stored a Key Vault client ID + secret in `appsettings.json` — defeating the purpose. **Managed Identity**: Azure assigns the VM/Function/Container an identity at the platform level. The token is fetched from `http://169.254.169.254/metadata/identity/oauth2/token` (the IMDS endpoint, only reachable from inside the VM). Key Vault grants the Managed Identity read access. No secret on disk, ever. AWS equivalent: IAM roles + STS.
>
> **Cross-Q²**: Someone commits a connection string to git. What's the response?
>
> **A**: (1) Rotate the credential *immediately* — assume it's compromised the moment it hit GitHub, regardless of whether the repo is public. (2) Force-push or use `git filter-branch` / BFG to remove from history (but the leak still exists in any clone made between commit and rewrite — rotation is the real fix). (3) Add a `git-secrets` or `gitleaks` pre-commit hook so it can't happen again. (4) Audit access logs on the credential's resource for the time it was exposed. (5) Move the secret to Key Vault. Don't skip rotation: secrets in public git get scraped by bots within minutes.

#### Drill 9 — OWASP Top 10 in ASP.NET Core

> **Q**: Name the OWASP Top 10 vulnerability most commonly mishandled in ASP.NET Core, and how to prevent it.
>
> **A**: **A01 — Broken Access Control**. The classic miss: an authenticated user can fetch *anyone's* order by guessing IDs (`GET /api/orders/42`) because the controller only checks `[Authorize]`, not "does this user own order 42?" Fix: resource-based authorization via `IAuthorizationService.AuthorizeAsync(User, order, "OrderOwner")` or query-time filters (`db.Orders.Where(o => o.OwnerId == userId)`). Default deny; explicit allow per resource.
>
> **Cross-Q**: How does `A03 — Injection` map to .NET? Isn't EF Core safe by default?
>
> **A**: EF Core LINQ is parameterized — safe. The escape hatches are dangerous: `FromSqlRaw($"SELECT * FROM Users WHERE Email = '{email}'")` (string interpolation into raw SQL) and `ExecuteSqlRaw($"...")`. Use `FromSql` (formattable interpolated string, parameterized) or `FromSqlInterpolated` instead. Also: `Process.Start` with user input is command injection, `XmlDocument` with `XmlResolver` set is XXE, `BinaryFormatter` is deserialization injection (removed in .NET 9). Injection isn't just SQL.
>
> **Cross-Q²**: What's the modern stand-in for `A07 — Authentication Failures`?
>
> **A**: Most app teams don't write auth from scratch anymore — they use ASP.NET Identity, Auth0, Azure AD B2C, Cognito. The failure mode shifts to *configuration*: weak password policy, missing rate limit on `/login`, no account lockout, no MFA enforcement, password reset tokens that don't expire or are predictable. The 2026 OWASP guidance (NIST SP 800-63B): allow long passwords (no max < 64 chars), no forced rotation, check against breach databases (Have I Been Pwned k-Anonymity API), MFA required for admins, Argon2id for hashing (PBKDF2 with ≥600k iter as fallback).

#### Drill 10 — Rate limiting

> **Q**: Fixed window, sliding window, token bucket, concurrency — pick one for each: login endpoint, public API, internal RPC.
>
> **A**: **Login**: token bucket per-IP — bursts allowed (legitimate user retries on typo), refilled slowly (5 attempts per 5 min). **Public API**: sliding window per-API-key — smooth rate enforcement without boundary bursts, predictable for partners. **Internal RPC**: concurrency limiter — limit *concurrent* in-flight requests rather than rate, protects downstream DB/external services from sudden parallelism spikes.
>
> **Cross-Q**: What's the "boundary burst" problem with fixed-window?
>
> **A**: Fixed window resets at, say, every minute boundary. A client can hammer 100 requests in the last second of minute 0 and another 100 in the first second of minute 1 — 200 requests in 2 seconds, but each window saw "only" 100. From the client's view, the rate limit is 200/min on average but they can spike 100x your intended throughput at boundaries. Sliding window slides the count across time and prevents this; token bucket smooths via the refill rate.
>
> **Cross-Q²**: An in-process rate limiter — what does it miss in a multi-instance deployment?
>
> **A**: Each instance enforces independently. 10 pods × 100 req/min = 1000 req/min reaching the backend through one client. Fixes: (1) shared distributed state (Redis-backed limiter — `RedLockNet` or custom INCR-with-TTL), (2) upstream limiter (API gateway, Front Door, Cloudflare) that sees all traffic, (3) accept the per-instance limit as a coarse circuit breaker and let upstream do precise rate control. .NET's built-in `RateLimiter` is process-local by default; distributed variants exist as community packages.

#### Drill 11 — Authentication vs Authorization

> **Q**: Draw the bright line between authentication and authorization.
>
> **A**: **Authentication** = "who are you?" — verifying identity via credentials (password, token, certificate). Output: a `ClaimsPrincipal`. **Authorization** = "what may you do?" — checking the authenticated principal against a policy. Output: yes/no. ASP.NET Core enforces this separation via two middlewares: `UseAuthentication()` populates `HttpContext.User`, `UseAuthorization()` evaluates `[Authorize]` attributes against it. Both must run; order matters (authentication first).
>
> **Cross-Q**: What happens if you `UseAuthorization()` without `UseAuthentication()`?
>
> **A**: `HttpContext.User` is anonymous (an empty `ClaimsPrincipal`). Every `[Authorize]` policy fails — every endpoint returns 401. Worse, if you have a default policy that allows anonymous access conditionally, it might unintentionally grant access. The framework emits a warning in development; production silently 401s. Always: `UseRouting → UseAuthentication → UseAuthorization → UseEndpoints`.
>
> **Cross-Q²**: A request has a valid token but the user doesn't have the required role. What's the HTTP response — 401 or 403?
>
> **A**: **403 Forbidden**. 401 means "I don't know who you are, authenticate"; 403 means "I know who you are and you can't do this." `[Authorize]` returns 401 when no/invalid credentials are present, 403 when credentials are valid but the policy fails. Clients use the distinction: 401 triggers a refresh-token attempt or re-login; 403 triggers "you don't have permission" UI without re-authenticating.

#### Drill 12 — Policy vs role vs claim

> **Q**: When do you use `[Authorize(Roles=...)]`, `[Authorize(Policy=...)]`, claim requirements? Compare.
>
> **A**: **Roles**: simple, coarse buckets (`Admin`, `User`, `Manager`) — fewer than ~10, rarely change. Stringly-typed, no parameterization. **Policy**: composable named rule built from claims, requirements, custom handlers. The right answer for almost anything beyond "is this user an admin." **Claims requirement** (`RequireClaim(...)`): one-off check inside a policy. Modern guidance: define policies, even simple ones — `AddPolicy("AdminOnly", p => p.RequireRole("Admin"))`. Gives you a single place to change the rule.
>
> **Cross-Q**: A policy needs to check "user owns the resource" — that's not a claim. How do you implement it?
>
> **A**: Resource-based authorization. Define an `IAuthorizationRequirement` (e.g., `SameOwnerRequirement`), a handler `AuthorizationHandler<SameOwnerRequirement, Order>` that inspects both the user and the resource, register the handler. In the endpoint, call `await _auth.AuthorizeAsync(User, order, "OwnerOrAdmin")` — this is *imperative* authorization because the resource isn't known until you've loaded it. Declarative `[Authorize]` can't express "owner of this specific record."
>
> **Cross-Q²**: How do you keep roles/permissions consistent across services in a microservices setup?
>
> **A**: Two patterns. (1) **Claims in the JWT**: at login, the identity provider embeds roles/permissions as claims. Every service reads them from the token — no extra calls. Trade-off: token bloat, stale claims (a permission revoked won't propagate until token expires). (2) **Permission API call**: each service calls a central "authorization service" with the user ID + resource — always fresh, but every request pays the round-trip. Hybrid: claims for coarse roles, API call for fine-grained per-resource permissions. Cache aggressively with short TTLs.

#### Drill 13 — Refresh tokens

> **Q**: Why rotation, and what is "reuse detection"?
>
> **A**: A long-lived refresh token (7-30 days) is high-value — if stolen, attacker can mint access tokens indefinitely. **Rotation**: every time the client uses a refresh token, the server invalidates it and issues a fresh one. The stolen token is now single-use. **Reuse detection**: if the same refresh token is presented *twice* (meaning either a replay or the attacker beat the legitimate client to it), the server invalidates the entire token family — the user is logged out everywhere, forcing re-authentication. This bounds the blast radius from a stolen refresh token.
>
> **Cross-Q**: How do you store refresh tokens server-side?
>
> **A**: Hashed (not plaintext) in a database table keyed by the hash, with `UserId`, `IssuedAt`, `ExpiresAt`, `RevokedAt`, `ReplacedByTokenHash` (for chaining rotations), and `FamilyId` (for invalidating a whole family on reuse detection). On refresh: hash the incoming token, look it up, check unrevoked + unexpired, mark this row revoked, insert the new token's hash, return the new token. Hash so a database leak doesn't hand attackers usable tokens; chain so audit trails work; family so reuse detection cascades.
>
> **Cross-Q²**: I'm running on multiple instances behind a load balancer. Where does the refresh-token store live?
>
> **A**: A shared, durable store — typically the relational database or Redis with persistence. *Not* in-memory on a single instance (every other instance would 401 on refresh) and *not* in a non-durable cache (a Redis restart would log everyone out). The refresh-token table is small, write-heavy on login/refresh, and tolerates a low-latency DB. Some teams use Redis with `AOF everysec` for low-latency reads with bounded loss tolerance.

#### Drill 14 — Bearer token storage in the browser

> **Q**: A junior asks where to store the access token in their SPA: `localStorage` or HTTP-only cookie. What's your answer?
>
> **A**: Neither, ideally — use the **BFF pattern** so the SPA never sees a token. If you must store it client-side, **HTTP-only Secure SameSite=Strict cookie** with a CSRF token for state-changing requests. `localStorage` is JS-accessible — any XSS (a single unencoded user comment) exfiltrates every user's token. HTTP-only cookies are JS-invisible, so an XSS can still *use* the cookie via fetch, but can't *steal* it for offline use.
>
> **Cross-Q**: Why is the "XSS can still use the cookie" point important?
>
> **A**: Because HTTP-only cookies aren't a magic XSS fix. An XSS payload can `fetch('/api/secret-data')` from the user's browser with the cookie auto-attached — same effective access as a stolen token, but bounded to the duration of the XSS. Stolen `localStorage` tokens work from the attacker's machine, indefinitely (until expiry). HTTP-only cookies raise the cost of XSS substantially; they don't reduce it to zero. Pair with CSP, output encoding, and short token lifetimes.
>
> **Cross-Q²**: Is `localStorage` ever acceptable for tokens?
>
> **A**: When the trade-offs are understood and the risk is bounded — internal tools with strict CSP and no user-generated content, short-lived tokens (5 min), no PII access, and an environment where XSS would be catastrophic anyway. The 2026 industry consensus is "no, default to BFF or HTTP-only cookies." OWASP, NIST, and OAuth 2.0 Security BCP all converge on this. If `localStorage` is on the table, default to "find a way to remove it."

#### Drill 15 — mTLS

> **Q**: When does mutual TLS beat JWT bearer for authenticating clients?
>
> **A**: Service-to-service in a controlled network (gateway-to-microservice, partner integrations with a known list of clients), where you need *proof of client identity at the transport layer* rather than at the application layer. The client presents a certificate; the server validates the cert chain against a known CA. No tokens to steal, no token expiry to coordinate, no bearer token in logs — and certificates can be pinned, rotated, revoked via CRL/OCSP.
>
> **Cross-Q**: What about user authentication — can mTLS replace JWT for users?
>
> **A**: Rarely in 2026. Client certificate enrollment on consumer devices is operationally painful (lost certs, device migration, no recovery flow). mTLS for users works in tightly-controlled environments (corporate-managed devices, smartcards in government/finance). For everyone else, JWT (with the user's auth flow being password + MFA + OIDC) is the right answer. mTLS shines for *machines*; JWT for *humans*.
>
> **Cross-Q²**: How do you implement mTLS in ASP.NET Core?
>
> **A**: Configure Kestrel to require client certificates: `services.Configure<KestrelServerOptions>(o => o.ConfigureHttpsDefaults(h => { h.ClientCertificateMode = ClientCertificateMode.RequireCertificate; }))`. Validate the cert in `AddCertificate()` authentication handler — typically by checking the issuer thumbprint against an allow-list or by matching the cert's `Subject` against a known partner identity. The cert validation result populates `HttpContext.User` with claims from the cert, then your normal `[Authorize]` policies work on top. Pair with cert rotation: rotate before expiry, distribute new certs via your secret store, accept overlap.

</details>

---

### Self-Test

<details>
<summary>1. Token validation succeeds, but <code>User.FindFirstValue(JwtRegisteredClaimNames.Sub)</code> returns null inside <code>OrderOwnerHandler</code>. Why, and how does it present in production?</summary>

Because `JwtBearerOptions.MapInboundClaims` defaults to **true**. Before the `ClaimsPrincipal` is built, the token handler rewrites known short JWT claim names to the legacy WS-\* claim types — `sub` becomes `ClaimTypes.NameIdentifier` (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier`), `email` becomes `ClaimTypes.Email`. The claim is renamed, not duplicated, so a lookup by `"sub"` finds nothing.

Production shape: nothing fails validation, nothing logs an error. The handler compares `order.OwnerId.ToString()` against `null`, never calls `ctx.Succeed`, and every legitimate owner gets a **403** — while admins still sail through, because `IsInRole("Admin")` reads a different claim. It looks like a permissions bug, not an auth-config bug, which is why it survives triage for days.

The fix is the line in the setup snippet: `options.MapInboundClaims = false` per scheme (or clear `JsonWebTokenHandler.DefaultInboundClaimTypeMap` globally). It isn't free — `User.Identity.Name` and `IsInRole` read `TokenValidationParameters.NameClaimType` / `RoleClaimType`, which still default to the long `ClaimTypes.Name` / `ClaimTypes.Role`. Turn mapping off without repointing those at the short names your issuer emits and role checks start failing the same silent way.
</details>

<details>
<summary>2. <code>FromSqlRaw($"… WHERE Email = '{email}'")</code> and <code>FromSql($"… WHERE Email = {email}")</code> are the same C# interpolation. Why is only one safe?</summary>

Different parameter types. `FromSqlRaw` takes a plain `string`, so C# has already pasted the user's value into the text before EF Core sees it — what arrives is one opaque SQL statement with the payload baked in. `FromSql` and `FromSqlInterpolated` take a `FormattableString`: EF keeps the holes separate from the format, substitutes a generated placeholder (`@p0`) and sends each value as a `DbParameter`. Microsoft's wording is that `FromSql` and `FromSqlInterpolated` "are safe against SQL injection, and always integrate parameter data as a separate SQL parameter", while `FromSqlRaw` "can be vulnerable to SQL injection attacks, if improperly used." Same split for `ExecuteSql` vs `ExecuteSqlRaw`. (`FromSql` arrived in EF Core 7; before that, `FromSqlInterpolated` is the equivalent.)

Two things to add out loud. The compiler will not help you — `FromSqlRaw($"…")` compiles clean, so this is caught by review, an analyzer, or not at all. And parameters bind *values*, never *identifiers*: a user-chosen sort column or table name cannot be a `DbParameter`, so dynamic-shape SQL puts you back on `FromSqlRaw` with an allow-list of legal column names — an allow-list, not escaping.
</details>

<details>
<summary>3. In the credential-stuffing login, why verify the password against a constant dummy hash when the user doesn't exist?</summary>

To keep the two failure paths indistinguishable. Skipping the hash for an unknown email is a "quick exit": that path returns immediately while the real path pays the KDF's full work factor. The gap is a user-enumeration oracle — an attacker replays 10M leaked addresses and, without guessing a single password, learns which ones have accounts here. Those confirmed addresses are then worth more everywhere else (phishing, reset abuse, targeted stuffing). OWASP's authentication guidance names both halves: a generic failure message regardless of whether the account exists, and no quick-exit logic, so the processing time doesn't differ either.

Hence the shape in the code: identical `Unauthorized()` for "no such user" and "wrong password", and a constant dummy hash so both branches do the same work. Note where the 423 sits — lockout is only reported *after* the password verified, because "this account is locked" is itself an existence disclosure. Timing parity is one layer, not the defense: it is paired with per-IP and per-email rate limits, lockout with exponential backoff, CAPTCHA after N failures, and MFA, since an enumeration-proof endpoint that accepts unlimited attempts is still stuffable.
</details>

<details>
<summary>4. A new action ships without <code>[Authorize]</code>. What structural change makes that fail closed — and what does it still not cover?</summary>

Default deny in the pipeline instead of opt-in per endpoint: set a fallback policy — `AddAuthorizationBuilder().SetFallbackPolicy(new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build())`, i.e. `AuthorizationOptions.FallbackPolicy` — so anything carrying no authorization metadata still requires an authenticated user. The forgotten attribute now 401s instead of serving data. Semantics worth stating precisely: the fallback applies *only* when an endpoint has no authorization attributes at all; `[Authorize]` (even with no policy name) uses `DefaultPolicy` instead, and `[AllowAnonymous]` opts out — so login and health endpoints stay reachable but have to say so explicitly. `FallbackPolicy` is `null` by default; nothing changes until you set it.

What it does not cover is A01. Broken access control is what happens *after* authentication succeeds: `GET /api/orders/42` with a perfectly valid token belonging to somebody else. No fallback policy, role or claim check catches that, because the rule depends on the row you just loaded. That needs resource-based authorization (`AuthorizeAsync(User, order, "OrderOwner")`) or a query-time filter that makes the row unreachable at all — `Where(o => o.PartnerId == partnerId)`, or a global query filter on `TenantId` so forgetting the `WHERE` cannot leak across tenants. Default deny closes the anonymous hole; ownership rules close the horizontal one.
</details>

<details>
<summary>5. Why is <code>dotnet user-secrets</code> development-only, and what does Key Vault + Managed Identity buy that it cannot?</summary>

Two independent reasons. First, it is not a secure store — Microsoft's wording is that Secret Manager "doesn't encrypt the stored secrets and shouldn't be treated as a trusted store. It's for development purposes only." The values sit in plain JSON at `%APPDATA%\Microsoft\UserSecrets\<id>\secrets.json` (`~/.microsoft/usersecrets/<id>/secrets.json` on Linux/macOS); the only guarantee is that they live outside the project tree, so they can't be committed. Second, the provider isn't registered outside development at all: `WebApplication.CreateBuilder` adds user secrets only when the environment is `Development`. Deploy something that depends on it and `Configuration["Jwt:Key"]` is `null` in prod — which, in this page's setup code, surfaces as an `ArgumentNullException` out of `Encoding.UTF8.GetBytes` rather than a readable "missing configuration", and because options-configure delegates run lazily it typically fires on the first request through the authentication middleware, not at `Build()`.

Key Vault + Managed Identity adds what a file cannot: per-secret access auditing, rotation without a redeploy, RBAC that separates "can deploy" from "can read secrets" — and it removes the bootstrap secret. The platform issues the VM/container/function an identity, the app fetches a token for it, and Key Vault grants that identity `get`; there is no credential on disk whose job is to protect the other credentials. Environment variables sit in between: fine for CI and containers, but plain text to anyone with shell access on the host and not auditable per secret.
</details>

---
### Cross-References

- [Cryptography, Hashing & Encoding](./19-cryptography-hashing-and-encoding.md) — the primitives underneath this page: password hashing work factors, HMAC and timing-safe comparison, AES-GCM, and the Data Protection key ring.
- [Authentication & Authorization (API)](../../02-api-development/02-authentication-and-authorization.md) — API-layer how-to.
- [API Security](../../02-api-development/04-api-security.md) — endpoint-level checklist.
- [Advanced Auth](../../02-api-development/17-advanced-auth.md) — refresh rotation, mTLS, federation.
- [Configuration](./15-configuration.md) — Data Protection API config, secrets management, Key Vault integration.
- [Logging & Serilog](../../06-distributed-and-observability/01-logging-and-serilog.md) — auditing security events.
- [Caching Strategies](./10-caching.md) — JTI denylist via distributed cache.
- [Modern C# Features](./12-modern-csharp.md) — record DTOs, required members for safe deserialization.

### Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- OWASP Top 10 — 2021 (refreshed for 2025) — <https://owasp.org/Top10/>
- OWASP ASVS 4 — Application Security Verification Standard.
- OWASP Cheat Sheet Series — Authentication, JWT, CSRF, CSP.
- ASP.NET Core Security docs — <https://learn.microsoft.com/aspnet/core/security/>
- RFC 7519 (JWT), RFC 8725 (JWT BCP), RFC 6749 (OAuth 2.0), RFC 8252 (OAuth for Native Apps), RFC 7636 (PKCE).
- NIST SP 800-63B — Digital Identity Guidelines (password hashing, MFA).
- Microsoft Threat Modeling Tool / STRIDE.

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Hash Tables, Best Practices & Design Patterns](08-patterns-and-best-practices.md) · [↑ Back to top](#security--authentication) · [Next: Caching Strategies →](10-caching.md)

<!-- nav-footer-end -->
