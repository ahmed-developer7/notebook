# Cryptography, Hashing and Encoding in .NET 10

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 4 — Auth & API Security | 2026-08-18 |

> 🔐 **Security material.** Every API on this page was checked against learn.microsoft.com or the runtime source before it was written down. Where a claim could not be verified it was left out rather than softened. If you are reading this more than six months after the review date, re-check the OWASP work factors — they move.

---

## Why It Matters

Interviewers open this topic with one question, and it is almost never "explain AES". It is some variant of:

> "What's the difference between encoding, hashing and encryption?"

They ask it because the industry gets it wrong constantly. Base64 is called "encryption" in bug reports, in code comments, in vendor documentation, and in production incident write-ups. A senior candidate who cannot draw the line cleanly — reversible without a key, one-way, reversible with a key — has just told the interviewer that the rest of the security conversation is going to be shallow.

The second question is "how do you store a password", and the third is "how do you generate a secure token". Both have a standard wrong answer that sounds competent: `SHA256.HashData(password)` for the first, `Guid.NewGuid().ToString()` for the second. Both are wrong for reasons you can state precisely, and the precision is the point. "Use bcrypt" is a memorised answer. "A password hash must be *slow* because the threat model is an offline attacker with the dumped table and a GPU farm, and SHA-256 is designed to be fast" is an *understood* answer, and it survives the follow-up.

This page is the mechanism behind those answers: what each primitive actually guarantees, which .NET API implements it, what the framework already does for you (ASP.NET Core Identity and Data Protection do more than most candidates realise), and where "we use HTTPS" stops being an answer.

One framing to carry through the whole page: **cryptography fails at the joins, not at the algorithms.** Nobody in a normal engineering career breaks AES. They reuse a GCM nonce, compare an HMAC with `==`, encrypt with CBC and forget the MAC, ship a container with no shared Data Protection key ring, or store a password with a fast hash. Every one of those is a joinery mistake, and every one of them is an interview question.

---

## Table of Contents

1. [Introduction](#introduction) — including [The Three-Way Distinction](#the-three-way-distinction)
2. [Real-World Analogy: The Shipping Depot](#real-world-analogy-the-shipping-depot)
3. [Encoding — and Why It Is Not a Security Control](#encoding--and-why-it-is-not-a-security-control)
4. [Hashing — One-Way, No Key](#hashing--one-way-no-key)
5. [Hashing for Integrity vs Hashing for Passwords](#hashing-for-integrity-vs-hashing-for-passwords)
6. [Password Hashing](#password-hashing) — including [What ASP.NET Core Identity Actually Uses](#what-aspnet-core-identity-actually-uses)
7. [HMAC and Timing-Safe Comparison](#hmac-and-timing-safe-comparison)
8. [Symmetric Encryption](#symmetric-encryption) — including [Why Raw AES-CBC Is a Mistake](#why-raw-aes-cbc-without-a-mac-is-a-mistake)
9. [Asymmetric Cryptography](#asymmetric-cryptography)
10. [Randomness: RandomNumberGenerator vs Random](#randomness-randomnumbergenerator-vs-random)
11. [Storing Tokens and API Keys at Rest](#storing-tokens-and-api-keys-at-rest)
12. [ASP.NET Core Data Protection](#aspnet-core-data-protection)
13. [Where TLS Fits](#where-tls-fits)
14. [Choosing a Primitive — Decision Table](#choosing-a-primitive--decision-table)
15. [Common Pitfalls](#common-pitfalls)
16. [Best Practices](#best-practices)
17. [Real-World Scenarios](#real-world-scenarios)
18. [Interview-Ready Summary](#interview-ready-summary)
19. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
20. [Cheat Sheet](#cheat-sheet)
21. [Walkthrough](#walkthrough)
22. [Self-Test](#self-test)
23. [Cross-References](#cross-references)
24. [Sources](#sources)

---

## Introduction

### The Three-Way Distinction

This is the question. Answer it in one breath, then expand.

| | **Encoding** | **Hashing** | **Encryption** |
|---|---|---|---|
| **Reversible?** | Yes, by anyone | No, by anyone | Yes, with the key |
| **Key involved?** | No | No (plain hash) / yes (HMAC) | Yes — always |
| **Output size** | Grows with input | Fixed, regardless of input | Grows with input (+ IV/nonce/tag) |
| **What it is for** | Making bytes survive a transport that can't carry them | Fingerprinting, verification, storage of things you never need back | Confidentiality |
| **Is it a security control?** | **No** | Only within a protocol | Yes |
| **.NET example** | `Convert.ToBase64String`, `Base64Url.EncodeToString` | `SHA256.HashData`, `Rfc2898DeriveBytes.Pbkdf2` | `AesGcm`, `RSA`, `IDataProtector` |

The three sentences to lead with:

- **Encoding is a transport concern.** It has no key and no secret. Anyone who can see the encoded value can decode it, and that is the *intended* behaviour, not a weakness. Base64 exists because SMTP, HTTP headers, URLs and XML attributes are not binary-safe.
- **Hashing is one-way by construction.** There is no key and no "unhash". You verify by re-computing the hash of a candidate and comparing.
- **Encryption is reversible and keyed.** The security lives entirely in the key. Everything else — algorithm, mode, ciphertext — is assumed public. (This is Kerckhoffs's principle, and it is worth saying out loud: an algorithm whose security depends on nobody knowing how it works is not a cryptosystem.)

```
                    Can you get the original back?
                              │
              ┌───────────────┴────────────────┐
             NO                               YES
              │                                │
          HASHING                    Do you need a key to do it?
    ┌─────────┴──────────┐            ┌────────┴─────────┐
   Fast                Slow          NO                 YES
    │                    │            │                   │
 INTEGRITY          PASSWORDS     ENCODING           ENCRYPTION
 SHA-256            PBKDF2 /      Base64, hex,       AES-GCM,
 HMAC-SHA256        bcrypt /      URL-encoding       RSA, ECDH,
                    Argon2id      (NOT security)     IDataProtector
```

### Why Base64 Keeps Getting Called Encryption

Three reasons, and naming them shows you have met the confusion in the wild rather than only in a textbook:

1. **It looks like ciphertext.** `cGFzc3dvcmQxMjM=` is unreadable to a human. Unreadable-to-a-human and unreadable-to-an-attacker are completely different properties, and the eye does not distinguish them.
2. **It shows up next to real security.** JWTs are three base64url segments. HTTP Basic auth is `Authorization: Basic ` plus base64 of `user:password`. Both *appear* in security contexts, so the encoding gets credit for the security around it.
3. **It is trivially reversible and nobody bothers.** No tool prompts you for a key, so the absence of a key never registers.

> 🌍 **In the real world**: a fintech integration ships credentials to a partner in a config file, base64-encoded, with a code comment reading `// encrypted connection string`. The reviewer sees an unreadable blob and approves. Eighteen months later the repository is made internal-public for a hackathon and someone runs `base64 -d` on the file out of curiosity. The decision that cost them was not "we chose weak encryption" — it was "we never checked whether there was a key". The fix, once found, was two lines: move the value to the secret store and inject it from configuration. The audit that followed took three weeks.

> 🌍 **In the real world**: an incident review of a token-leak concludes "the tokens were encrypted in the log, so exposure is limited." The tokens were JWTs. A JWT is signed, not encrypted — the payload is base64url and any log reader can decode the claims, including the subject, tenant, roles and expiry. The signature stops *forgery*, not *reading*. The team had conflated the two and downgraded the incident severity on the strength of it. Signed means "you can't change it"; encrypted means "you can't read it". The severity was re-raised the next day.

### The Three Guarantees, Named

When an interviewer pushes past the definitions, they are usually fishing for the CIA-style vocabulary attached to the right primitive:

| Guarantee | What it means | Primitive that provides it |
|---|---|---|
| **Confidentiality** | The adversary cannot read it | Encryption (AES-GCM, RSA-OAEP) |
| **Integrity** | The adversary cannot change it undetected | MAC / signature / AEAD tag |
| **Authenticity** | It came from who it claims to have come from | HMAC (shared key) or digital signature (private key) |
| **Non-repudiation** | The sender cannot later deny sending it | Digital signature **only** — an HMAC cannot provide it |

That last row is a genuinely good cross-question. **An HMAC cannot give you non-repudiation** because both parties hold the same key: either could have produced the tag, so neither can prove the other did. A signature can, because only the holder of the private key can produce it. This is exactly why webhook providers use HMAC (you only need to know it came from the provider, and you both share the secret) while code signing and JWT issuance in a federated system use asymmetric signatures.

---

## Real-World Analogy: The Shipping Depot

```
┌──────────────────────────────────────────────────────────────┐
│                      THE SHIPPING DEPOT                      │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ENCODING = the barcode label                                │
│  ┌────────────────────────────────────────────────┐          │
│  │ ║│║││┃║│┃║  →  "ORDER-88213-LHR"                │          │
│  │ Anyone with a scanner reads it. That's the      │          │
│  │ POINT. It exists so the conveyor belt can       │          │
│  │ handle the address, not to hide the address.    │          │
│  └────────────────────────────────────────────────┘          │
│                                                              │
│  HASHING = the tamper-evident seal                           │
│  ┌────────────────────────────────────────────────┐          │
│  │ A number derived from the exact contents.       │          │
│  │ You can CHECK it matches by re-weighing and     │          │
│  │ re-deriving. You CANNOT rebuild the parcel      │          │
│  │ from the seal. Change one item → new seal.      │          │
│  └────────────────────────────────────────────────┘          │
│                                                              │
│  HMAC = the depot's own stamp on the seal                    │
│  ┌────────────────────────────────────────────────┐          │
│  │ Same seal, but only someone holding the depot's │          │
│  │ die can make one. Now the seal proves ORIGIN,   │          │
│  │ not just "unchanged since somebody sealed it".  │          │
│  └────────────────────────────────────────────────┘          │
│                                                              │
│  ENCRYPTION = the locked container                           │
│  ┌────────────────────────────────────────────────┐          │
│  │ Contents unreadable without the key. The lock   │          │
│  │ design is public; the key is not.               │          │
│  │ AEAD = a locked container that is ALSO sealed.  │          │
│  └────────────────────────────────────────────────┘          │
│                                                              │
│  ❌ The classic mistake: a locked container with NO seal.    │
│     Someone can't read it — but they can swap panels and     │
│     you'll never know. That is AES-CBC without a MAC.        │
└──────────────────────────────────────────────────────────────┘
```

| Depot concept | Crypto concept |
|---|---|
| Barcode label | Base64 / hex / URL encoding |
| Tamper-evident seal | Hash (SHA-256) |
| Depot's stamp on the seal | HMAC / signature |
| Locked container | Encryption (AES, RSA) |
| Locked *and* sealed container | AEAD (AES-GCM) |
| A different key per customer, rotated quarterly, held in the safe | Key management (Data Protection key ring, Key Vault) |
| The armoured van between depots | TLS |
| The warehouse the container sits in overnight | **At rest** — the van does not help here |

That last row is the whole of [Where TLS Fits](#where-tls-fits) in one line.

---

## Encoding — and Why It Is Not a Security Control

### The APIs

```csharp
using System;
using System.Buffers.Text;   // Base64Url — .NET 9+
using System.Text;

byte[] bytes = Encoding.UTF8.GetBytes("hello");

// Base64 — RFC 4648 standard alphabet, '+' and '/', '=' padding
string b64 = Convert.ToBase64String(bytes);     // "aGVsbG8="
byte[] back = Convert.FromBase64String(b64);

// Hex — uppercase; .NET 5+
string hex = Convert.ToHexString(bytes);        // "68656C6C6F"
byte[] fromHex = Convert.FromHexString(hex);

// Base64Url — '-' and '_', no padding; .NET 9+ (System.Buffers.Text)
string url = Base64Url.EncodeToString(bytes);
byte[] fromUrl = Base64Url.DecodeFromChars(url);
```

Version gates that matter if you target more than one TFM:

| API | Available from |
|---|---|
| `Convert.ToBase64String` / `FromBase64String` | Long-standing (.NET Framework era) |
| `Convert.ToHexString` / `FromHexString` | **.NET 5** |
| `System.Buffers.Text.Base64Url` | **.NET 9** (also via the `Microsoft.Bcl.Memory` package for older TFMs) |

Before `Base64Url` existed, the ASP.NET Core answer was `WebEncoders.Base64UrlEncode` / `Base64UrlDecode` from `Microsoft.AspNetCore.WebUtilities`. If you are on a shared library targeting .NET 8 or earlier, that is still the reach.

### Why Base64Url Exists

Standard Base64 emits `+`, `/` and `=`. All three are meaningful in a URL: `+` decodes to a space in `application/x-www-form-urlencoded`, `/` is a path separator, `=` is a query-string assignment. Put a raw Base64 token in a query string and you have a bug that fires only for the subset of tokens that happen to contain one of those characters — which is why it survives every manual test and then breaks intermittently in production. Base64url swaps `+`→`-`, `/`→`_` and drops the padding. This is why JWT segments are base64url and not base64 — and it is why a hand-rolled JWT parser that calls `Convert.FromBase64String` on a segment throws `FormatException` intermittently.

```
Base64      alphabet:  A–Z a–z 0–9 + / with = padding
Base64Url   alphabet:  A–Z a–z 0–9 - _ with padding omitted

"?token=abc+def/ghi="   →  server sees  "abc def/ghi"    ← broken
"?token=abc-def_ghi"    →  server sees  "abc-def_ghi"    ← fine
```

### Size, Not Security

Encoding costs bytes, and that is the only trade-off it has. Base64 emits 4 output characters for every 3 input bytes; hex emits 2 characters per byte. Those are definitional ratios, not measurements — you can derive them from the alphabet size (6 bits per Base64 char, 4 bits per hex char). It matters when you base64 a payload into a header, a cookie or a database column and then discover the size limit.

> 🌍 **In the real world**: a team stores a signed session payload in a cookie. Locally it fits. In production, tenants with many role claims push the encoded cookie past the browser's per-cookie size limit and the cookie is silently dropped — users appear logged out at random, only in one region, only for admins. Nothing errors. The fix was to stop putting the claim set in the cookie and put an opaque identifier there instead, with the claims server-side. The lesson they wrote down: **encoding inflates, and the inflation is where your capacity planning breaks**, long before any security question arises.

### The Rule

> Encoding never appears in a threat model as a mitigation. If the sentence "we base64-encode it" is offered as the answer to "how is this protected", the answer is "it isn't".

Two legitimate uses that sound like security but are not:

- **Obfuscation for accident-avoidance.** Base64-ing a value so it does not get eyeballed by someone shoulder-surfing a log. Fine as a courtesy; worthless against an attacker; must never be counted as a control.
- **Transport safety for something already protected.** Base64 of a ciphertext or a signature is completely correct — the security came from the layer underneath.

---

## Hashing — One-Way, No Key

### The Properties You Are Expected to Name

```
┌──────────────────────────────────────────────────────────────┐
│ CRYPTOGRAPHIC HASH — Required Properties                     │
├──────────────────────────────────────────────────────────────┤
│ ✓ Deterministic       same input → same output, always       │
│ ✓ Fixed output size   1 byte or 1 GB in → 32 bytes out       │
│ ✓ Preimage resistant  given h, infeasible to find any m      │
│                       with H(m) = h                          │
│ ✓ Second-preimage     given m₁, infeasible to find m₂ ≠ m₁   │
│   resistant           with H(m₂) = H(m₁)                     │
│ ✓ Collision resistant infeasible to find ANY m₁ ≠ m₂ with    │
│                       H(m₁) = H(m₂)                          │
│ ✓ Avalanche           flip one input bit → ~half the output  │
│                       bits change                            │
│ ✗ NOT a secret        no key: anyone can compute H(m)        │
│ ✗ NOT reversible      there is no "unhash" operation         │
└──────────────────────────────────────────────────────────────┘
```

Collision resistance is the property that dies first, and the distinction between it and second-preimage resistance is a standard follow-up. MD5 and SHA-1 are **collision-broken** — an attacker can construct two documents with the same digest — which kills them for signatures and certificates. That is not the same as being able to recover a password from a SHA-1 hash. Both are dead for new work; know *why* each is dead, because "it's old" is not an answer.

### The .NET API Shape

Since .NET 5 the one-shot static `HashData` methods are the idiomatic form. They allocate less and remove the `using` dance:

```csharp
using System.Security.Cryptography;

// One-shot statics — SHA256.HashData is .NET 5+
byte[] digest = SHA256.HashData(fileBytes);                 // 32 bytes
byte[] digest2 = SHA256.HashData(someReadOnlySpan);
int written = SHA256.HashData(someSpan, destination);       // into a caller buffer

// Stream overloads — .NET 7+
await using var fs = File.OpenRead(path);
byte[] fileDigest = SHA256.HashData(fs);

// The old instance form still works and is still correct:
using var sha = SHA256.Create();
byte[] d = sha.ComputeHash(fileBytes);
```

**.NET 9** added an algorithm-agnostic entry point on `CryptographicOperations` (moniker list is net-9.0 onward, so it is available on .NET 10 but is not new there). It is useful when the algorithm comes from configuration rather than being fixed at compile time:

```csharp
// CryptographicOperations.HashData(HashAlgorithmName, ...) — .NET 9+. Takes the
// algorithm as a value instead of forcing a switch over SHA256/SHA384/SHA512.
byte[] h = CryptographicOperations.HashData(HashAlgorithmName.SHA256, data);
```

> ⚠️ `HashAlgorithmName` is a struct wrapping a *string*. `new HashAlgorithmName("SHA256")` and `HashAlgorithmName.SHA256` are equal, but `new HashAlgorithmName("sha256")` is a different value and will fail at the point of use. Use the static properties.

### Non-Cryptographic Hashes Are a Different Tool

`Object.GetHashCode()` is a hash and is not a cryptographic hash. It exists to bucket items in a `Dictionary`, it has no preimage or collision resistance worth the name, and — importantly for anyone tempted to persist one — **string hash codes in .NET Core are randomised per process by default**, so the same string yields different values across runs. Persisting a `GetHashCode()` result is a bug that only manifests after a restart.

> 🌍 **In the real world**: a caching layer keys entries by `key.GetHashCode()` to save space in a distributed cache. It works in every test, in every local run, and in the first pod. Deployed across a replica set, the pods disagree about the key for the same string, so each pod caches independently and cache hit rate collapses to the reciprocal of the replica count — but nothing errors, and the only symptom is a database that gets busier every time they scale out. The fix was to key on the string, or on a stable hash. The rule to carry: **`GetHashCode` is an in-process, single-run implementation detail.** Anything crossing a process boundary or a restart needs a stable hash.

---

## Hashing for Integrity vs Hashing for Passwords

This is the section where the same primitive is right for one job and catastrophically wrong for the other, and being able to explain *why* is the difference between a memorised answer and an understood one.

```
┌───────────────────────────┬──────────────────────────────────┐
│      INTEGRITY            │           PASSWORDS              │
├───────────────────────────┼──────────────────────────────────┤
│ Input: high-entropy or    │ Input: LOW-entropy, human-chosen,│
│ arbitrary data you        │ drawn from a small, predictable  │
│ already have              │ distribution                     │
│                           │                                  │
│ Threat: accidental        │ Threat: OFFLINE attacker with    │
│ corruption, or an         │ the whole table and a GPU farm,  │
│ attacker who can change   │ guessing candidates              │
│ the data but not the      │                                  │
│ stored digest             │                                  │
│                           │                                  │
│ Speed: a FEATURE.         │ Speed: a BUG. Every doubling of  │
│ You may hash gigabytes    │ hash throughput doubles the      │
│ on the request path.      │ attacker's guess rate.           │
│                           │                                  │
│ ✅ SHA-256 (or HMAC-      │ ❌ SHA-256                       │
│    SHA-256 if the digest  │ ✅ Argon2id / bcrypt / scrypt /  │
│    is attacker-reachable) │    PBKDF2 with a work factor     │
└───────────────────────────┴──────────────────────────────────┘
```

**Say the mechanism, not the rule.** SHA-256 is engineered to be fast and to parallelise — it is used to checksum multi-gigabyte artefacts and to secure block chains where throughput is the product. Those same properties, pointed at a table of password digests, let an attacker test candidate passwords at whatever rate their hardware allows. Human-chosen passwords come from a distribution small enough that this matters: the attacker is not searching 2²⁵⁶, they are searching a wordlist plus mutations. A password KDF deliberately spends CPU (and, for Argon2/scrypt, *memory*) per guess so that the attacker's rate collapses, while the honest server pays that cost exactly once per login.

The memory-hardness point is worth having ready. GPUs and ASICs are wildly good at parallel SHA-256 and much worse at algorithms that demand a large working set per guess, because memory does not parallelise as cheaply as arithmetic. That is the entire design goal of scrypt and Argon2 and the reason OWASP's Argon2id recommendation is stated as a *memory* figure first.

> 🌍 **In the real world**: a legacy system stores passwords as unsalted SHA-1 because "SHA-1 was fine in 2011". After a breach, the recovery team measures how far the attacker got by seeing which accounts were re-used elsewhere. Accounts with passwords in the top few million of any public wordlist were compromised essentially at breach time. The interesting detail: because the hashes were *unsalted*, the attacker did not need to crack per-user at all — identical hashes revealed identical passwords across accounts, so cracking one common password unlocked every account that shared it in a single pass. Salting alone would not have made the hashes strong, but it would have forced per-user work and removed the "these 40,000 users all chose the same password" signal for free.

### Where a Plain Hash *Is* the Right Answer

Do not over-correct. A fast unkeyed hash is correct for:

- **File / artefact integrity.** Publishing SHA-256 checksums next to a download, verifying a package after transfer.
- **Content addressing and deduplication.** Blob stores keyed by digest, git object IDs.
- **ETags and change detection.** "Has this document changed since I last saw it?"
- **Hashing a high-entropy secret you generated.** See [Storing Tokens and API Keys at Rest](#storing-tokens-and-api-keys-at-rest) — a 256-bit random token is not guessable, so slowing the hash buys nothing.

And the caveat that turns integrity into a *security* control: an unkeyed hash proves nothing about origin. If the attacker can modify the data, they can usually modify the stored digest alongside it. A checksum published on the same compromised server as the file is theatre. The moment the digest itself is attacker-reachable, you need a key — an HMAC or a signature. That is the bridge into the next two sections.

---

## Password Hashing

### The Four Things a Password Store Must Do

```
┌──────────────────────────────────────────────────────────────┐
│ 1. BE SLOW (tunable)   — a work factor you can raise as       │
│                          hardware improves                    │
│ 2. BE SALTED           — unique random salt per password,     │
│                          stored beside the hash               │
│ 3. BE UPGRADEABLE      — the stored value records its own     │
│                          parameters so you can re-hash        │
│ 4. VERIFY IN CONSTANT  — comparison must not leak how many    │
│    TIME                  bytes matched                        │
└──────────────────────────────────────────────────────────────┘
```

### What a Work Factor Is

A work factor is a *tuning parameter that buys time*. It has a different shape per algorithm, and knowing the shape is the cross-question:

| Algorithm | Work factor is… | Scaling |
|---|---|---|
| **PBKDF2** | iteration count | linear in CPU time |
| **bcrypt** | `cost` (log₂ of rounds) | **each +1 doubles the work** |
| **scrypt** | `N` (CPU/memory), `r` (block size), `p` (parallelism) | memory-hard |
| **Argon2id** | `m` (memory KiB), `t` (time/passes), `p` (parallelism) | memory-hard |

The bcrypt one catches people out, and the arithmetic is the answer: the cost parameter is a base-2 exponent, so going from 10 to 12 is 2² = **four times** the work, not "a bit more". Say "log scale" and you have answered it.

**How to choose one.** The honest method is not a number from a blog post, it is a measurement plus a policy:

1. Decide a per-verification latency budget on your *production* hardware — the largest cost a login can absorb without feeling slow, given your concurrency. State it as a number your team agreed, not one you read somewhere.
2. Measure the algorithm on that hardware at candidate parameters — this is the one place you must benchmark rather than quote.
3. Floor it at the current OWASP minimum. Never go below the published floor even if your hardware is slow.
4. Write the parameters into the stored hash and re-tune on a schedule.

Step 3's floors, from the OWASP Password Storage Cheat Sheet as of this review:

| Algorithm | OWASP minimum configuration |
|---|---|
| **Argon2id** | `m=19456` (19 MiB), `t=2`, `p=1` (with higher-memory / lower-time variants listed as equivalents) |
| **scrypt** | `N=2^17` (128 MiB), `r=8`, `p=1` (down to `N=2^13`, `r=8`, `p=10` as an equivalent trade) |
| **bcrypt** | work factor **10** or higher; "as large as verification server performance will allow" |
| **PBKDF2-HMAC-SHA256** | **600,000** iterations |
| **PBKDF2-HMAC-SHA512** | **220,000** iterations |
| **PBKDF2-HMAC-SHA1** | 1,400,000 iterations — legacy only |

> ⚠️ Re-check these before you quote them in an interview conducted long after 2026-08. OWASP revises them; the *method* above does not change.

Two bcrypt details worth carrying, both from the same OWASP source: bcrypt has a **maximum input length of 72 bytes** (longer passwords are silently truncated, so a "128-character passphrase" may be no stronger than its first 72 bytes), and if you pre-hash to work around that, OWASP's recommended construction is `bcrypt(base64(hmac-sha384(data:$password, key:$pepper)), $salt, $cost)` — the base64 step exists because a raw binary pre-hash can contain a null byte, which some bcrypt implementations treat as a terminator.

### Why the Salt Is Stored Beside the Hash

The most common misconception is that the salt is a secret. It is not, and the interviewer will ask.

A salt is a **uniqueness** device, not a secrecy device. Its job is to make sure that two users with the same password produce two different stored values. That single property buys three things:

1. **Precomputation dies.** A rainbow table (or any precomputed hash→password map) is built for *unsalted* hashes. Add a unique per-user salt and the attacker would need one table per salt, which is precisely the precomputation they were trying to avoid.
2. **Cross-account correlation dies.** Without a salt, identical hashes advertise identical passwords, so cracking one password unlocks every account that shares it. With salts, every account costs a full attack independently.
3. **Cross-*site* correlation dies.** A hash of `password123` from your dump can no longer be matched against a hash of `password123` from someone else's dump.

None of those benefits require the salt to be hidden. The attacker who has your salt has, by definition, already got your database — and the salt only helps them attack *that one user*. If you tried to keep it secret you would have created a second key-management problem for no gain, and you would have to solve "where does the salt live" for every verification. Storing it beside the hash is the correct design, not a compromise. Every modern password-hash format is self-describing for exactly this reason: the stored string carries the algorithm, the parameters and the salt, so verification needs nothing but the stored value and the candidate password.

**A pepper is the thing people are reaching for when they want a secret.** A pepper is a site-wide secret mixed in *in addition to* the salt, and OWASP's framing is the useful one: it is "shared between stored passwords" and "should not be stored along with the generated hash". It lives in a KMS/HSM or an environment secret, so a pure database dump (SQL injection, backup leak) is not enough to start cracking. It is a defence-in-depth layer, not a substitute for a KDF, and it brings its own rotation problem — so treat it as an optional extra you can justify, not a default.

```
STORED ROW (conceptually — every good format is self-describing)

┌────────────┬──────────┬──────────┬─────────────────────────┐
│ algorithm  │ params   │ salt     │ derived key (subkey)    │
│  "pbkdf2"  │ sha512,  │ 16 bytes │ 32 bytes                │
│            │ 100000   │ random   │                         │
└────────────┴──────────┴──────────┴─────────────────────────┘
      ▲            ▲          ▲
      │            │          └─ per-user, from a CSPRNG, NOT secret
      │            └───────────── so you can raise them later
      └────────────────────────── so you can migrate algorithms later
```

### What ASP.NET Core Identity Actually Uses

This is the concrete-knowledge question, and most candidates cannot answer it. The type is `PasswordHasher<TUser>`, implementing `IPasswordHasher<TUser>`, from `Microsoft.Extensions.Identity.Core`.

Two documented formats, straight from the `PasswordHasher.cs` header comment in `dotnet/aspnetcore`:

```
Version 2:
  PBKDF2 with HMAC-SHA1, 128-bit salt, 256-bit subkey, 1000 iterations.
  Format: { 0x00, salt, subkey }

Version 3:
  PBKDF2 with HMAC-SHA512, 128-bit salt, 256-bit subkey, 100000 iterations.
  Format: { 0x01, prf (UInt32), iter count (UInt32), salt length (UInt32),
            salt, subkey }
```

So the answers to the questions you will actually be asked:

- **Algorithm:** PBKDF2. Not bcrypt, not Argon2.
- **PRF:** HMAC-**SHA512** in V3 (V2 used SHA1).
- **Salt:** 128-bit, generated with `RandomNumberGenerator`, stored inside the encoded value.
- **Subkey:** 256-bit.
- **Default iterations:** `PasswordHasherOptions.IterationCount` — the docs state "Gets or sets the number of iterations used when hashing passwords using PBKDF2. **Default is 100,000**."
- **Default compatibility mode:** `PasswordHasherOptions.CompatibilityMode` "Defaults to 'ASP.NET Identity version 3'."
- **Comparison:** on .NET Core the verification path uses `CryptographicOperations.FixedTimeEquals`.
- **The version byte is the first byte of the payload**, which is what makes silent migration from V2 to V3 possible.

```csharp
builder.Services.Configure<PasswordHasherOptions>(o =>
{
    o.CompatibilityMode = PasswordHasherCompatibilityMode.IdentityV3;
    o.IterationCount    = 220_000;   // at/above the OWASP floor for HMAC-SHA512,
                                     // and above the 100,000 default
});
```

> ⚠️ **The number that makes this interesting.** Identity's default is 100,000 PBKDF2-HMAC-SHA512 iterations. OWASP's current floor for PBKDF2-HMAC-SHA512 is 220,000. The framework default is therefore **below the current OWASP recommendation**, and raising `IterationCount` is a one-line change. Being able to say that — with both numbers attributed — is a very strong answer, because it shows you read the guidance rather than trusting the default.

**The rehash path.** `VerifyHashedPassword` returns a `PasswordVerificationResult` with three members: `Failed` (0), `Success` (1), and `SuccessRehashNeeded` (2) — documented as "password verification was successful however the password was encoded using a deprecated algorithm and should be rehashed and updated". That third state is how you migrate an entire user base without a mass reset: the only moment you ever hold the plaintext password is a successful login, so that is the only moment you can re-hash it.

```csharp
var result = hasher.VerifyHashedPassword(user, user.PasswordHash!, submitted);

switch (result)
{
    case PasswordVerificationResult.Failed:
        return SignInResult.Failed;

    case PasswordVerificationResult.SuccessRehashNeeded:
        // We have the plaintext exactly here and nowhere else. Take the chance.
        user.PasswordHash = hasher.HashPassword(user, submitted);
        await store.UpdateAsync(user, ct);
        goto case PasswordVerificationResult.Success;

    case PasswordVerificationResult.Success:
        return SignInResult.Success;
}
```

`UserManager<TUser>` already does this for you when you go through `CheckPasswordAsync`; the code above is what to write when you have your own store.

> 🌍 **In the real world**: a team raises `IterationCount` from the default to a modern value and deploys. Login latency for existing users does not change at all, because every stored hash still carries its *own* iteration count in the payload and is verified with that count. Only new and re-hashed passwords use the new value. They initially read the unchanged latency as "the config didn't take" and rolled back. The mechanism they had missed: **the stored format is self-describing, so a parameter change is forward-only by design.** The correct move was to keep the change and let `SuccessRehashNeeded` migrate the base over the following weeks.

### Argon2 and bcrypt in .NET

Neither is in the BCL. Argon2 support has been requested since January 2017 and remains an open API idea on [dotnet/runtime#19933](https://github.com/dotnet/runtime/issues/19933) rather than a shipped feature. The structural reason is worth knowing: .NET's `System.Security.Cryptography` largely delegates to the platform (CNG on Windows, OpenSSL on Linux, Apple's frameworks on macOS), and Argon2 is not uniformly available across those, so shipping it would mean either a managed implementation or an uneven cross-platform story.

Practically, that leaves you three defensible positions:

1. **Use Identity's PBKDF2 with a raised iteration count.** Boring, in-box, FIPS-friendly, no third-party dependency. Entirely acceptable and OWASP-listed.
2. **Take a third-party Argon2id or bcrypt package** and plug it in behind `IPasswordHasher<TUser>`. Say out loud that you are adding an unaudited-by-Microsoft dependency to the authentication path and that you will pin and monitor it.
3. **Delegate the whole problem** to an identity provider (Entra ID, Auth0, Okta, Cognito) and never store a password.

Answering "Argon2id, obviously" without knowing it is not in the BCL is the trap. Answering "PBKDF2-HMAC-SHA512 at or above the OWASP floor, because it is what Identity ships and it is on the approved list; I'd move to Argon2id if the threat model justified the dependency" is the senior answer.

### If You Are Rolling the Storage Format Yourself

```csharp
using System.Security.Cryptography;

// Rfc2898DeriveBytes.Pbkdf2 — the one-shot static, .NET 6+.
// Supported hash algorithms: SHA1, SHA256, SHA384, SHA512.
const int SaltSize = 16;      // 128-bit
const int KeySize  = 32;      // 256-bit
const int Iterations = 220_000;

static (byte[] salt, byte[] key) HashPassword(string password)
{
    byte[] salt = RandomNumberGenerator.GetBytes(SaltSize);
    byte[] key  = Rfc2898DeriveBytes.Pbkdf2(
        password:      password,                 // UTF-8 encoded internally
        salt:          salt,
        iterations:    Iterations,
        hashAlgorithm: HashAlgorithmName.SHA512,
        outputLength:  KeySize);
    return (salt, key);
}

static bool Verify(string candidate, byte[] salt, byte[] expectedKey, int iterations)
{
    byte[] actual = Rfc2898DeriveBytes.Pbkdf2(
        candidate, salt, iterations, HashAlgorithmName.SHA512, expectedKey.Length);

    // NOT ==, NOT SequenceEqual
    return CryptographicOperations.FixedTimeEquals(actual, expectedKey);
}
```

Two API notes you should be able to state:

- The `string` and `ReadOnlySpan<char>` overloads convert the password using **UTF-8**. If you must match a legacy store that used a different encoding, encode yourself and use the `ReadOnlySpan<byte>` overload.
- The old `new Rfc2898DeriveBytes(password, salt)` constructors are obsolete (**SYSLIB0041**) because they defaulted to SHA-1 and a low iteration count. Use the static `Pbkdf2` one-shots.

### Timing and User Enumeration

If your login handler returns immediately when the user does not exist, but runs a deliberately-expensive KDF when the user does exist, you have built a user-enumeration oracle out of a stopwatch — and the better your work factor, the louder the signal. The mitigation is to always do the work:

```csharp
// A constant, well-formed hash generated once at startup for a throwaway password.
private static readonly string DummyHash = _hasher.HashPassword(_dummyUser, "not-a-real-password");

public async Task<SignInResult> SignInAsync(string email, string password, CancellationToken ct)
{
    var user = await _users.FindByEmailAsync(email, ct);

    // Verify against a real hash even when the user is null, so both paths
    // pay the same KDF cost. Then decide.
    var stored = user?.PasswordHash ?? DummyHash;
    var result = _hasher.VerifyHashedPassword(user ?? _dummyUser, stored, password);

    if (user is null || result == PasswordVerificationResult.Failed)
        return SignInResult.Failed;   // identical message and shape either way
    // ...
}
```

Note what else has to match: the **response body and status code** must be identical too. "Invalid email or password" for both cases, not "no such user" and "wrong password".

---

## HMAC and Timing-Safe Comparison

### What HMAC Adds

A plain hash answers "has this changed since *somebody* hashed it". An HMAC answers "has this changed since *someone holding the key* hashed it". The key turns integrity into authenticity.

```
        H(message)                    HMAC(key, message)
             │                                │
   Anyone can compute it.          Only key-holders can compute it.
   Attacker rewrites message       Attacker rewrites message → cannot
   AND digest → undetected.        produce a matching tag → detected.
```

```csharp
using System.Security.Cryptography;
using System.Text;

byte[] key = Convert.FromHexString(secretHex);        // 32 bytes for HMAC-SHA256
byte[] body = await ReadRawBodyAsync(request);

// One-shot static — .NET 6+
byte[] tag = HMACSHA256.HashData(key, body);          // 32 bytes
string header = Convert.ToHexString(tag).ToLowerInvariant();
```

**Why HMAC and not `H(key || message)`.** This is the classic follow-up. The naive "secret prefix" construction is vulnerable to a **length-extension attack** against Merkle–Damgård hashes such as SHA-256: because the hash's internal state at the end of the message *is* the output, an attacker who knows `H(key || m)` and `len(key)` can compute `H(key || m || padding || m')` for a suffix `m'` of their choosing, without knowing the key. HMAC's nested `H(K⊕opad || H(K⊕ipad || message))` structure is specifically designed to close that.

### Timing-Safe Comparison Is Not Optional

```csharp
// ❌ WRONG — short-circuits on the first differing byte
if (computedTag.SequenceEqual(providedTag)) { ... }
if (computedHex == providedHex) { ... }

// ✅ RIGHT
if (CryptographicOperations.FixedTimeEquals(computedTag, providedTag)) { ... }
```

`CryptographicOperations.FixedTimeEquals(ReadOnlySpan<byte>, ReadOnlySpan<byte>)` is documented as determining "the equality of two byte sequences in an amount of time that depends on the length of the sequences, but not their values". It has been in the BCL since .NET Core 2.1.

**The mechanism**, because "it's constant time" alone is not an answer. `==` on strings and `SequenceEqual` on arrays return as soon as they find a mismatch. An attacker who can submit many signatures and measure response time can therefore learn *how many leading bytes were correct*, and can then discover the tag one byte at a time. That turns a 2²⁵⁶ search into roughly 32 × 256 attempts. `FixedTimeEquals` XORs every byte and accumulates, then checks the accumulator once, so the loop always runs to completion.

**Read the guarantee precisely** — this is the cross-question. The documented property is that the time depends on the *length* but not the *values*. So:

- It does **not** hide the length. If your comparison returns early because the lengths differ, you have leaked the length. In practice this is fine for fixed-size tags (an HMAC-SHA256 tag is always 32 bytes) — but if you compare variable-length secrets, hash both sides to a fixed length first and compare the hashes.
- It protects the comparison only. If you decoded the attacker's hex with something that early-exits on invalid input, or looked the API key up in a dictionary before comparing, you may have leaked elsewhere.

**.NET 11 note (not available on .NET 10):** the docs list `CryptographicOperations.VerifyHmac(HashAlgorithmName, ReadOnlySpan<byte> key, ReadOnlySpan<byte> source, ReadOnlySpan<byte> hash)` returning `bool`, with the moniker list showing **net-11.0 only**. It packages compute-then-fixed-time-compare into one call. On .NET 10 you write the two steps yourself.

### Webhook Signature Verification, End to End

```csharp
app.MapPost("/webhooks/payments", async (HttpRequest req, IOptions<WebhookOptions> opt) =>
{
    // 1. Read the RAW body. Never re-serialise a deserialised object and
    //    sign that — property order, whitespace and number formatting will
    //    differ from what the sender signed.
    req.EnableBuffering();
    using var reader = new StreamReader(req.Body, leaveOpen: true);
    string raw = await reader.ReadToEndAsync();
    req.Body.Position = 0;

    if (!req.Headers.TryGetValue("X-Signature", out var sigHeader) ||
        !req.Headers.TryGetValue("X-Timestamp", out var tsHeader))
        return Results.Unauthorized();

    // 2. Reject stale requests BEFORE verifying, to bound replay.
    if (!long.TryParse(tsHeader, out var unix)) return Results.Unauthorized();
    var age = DateTimeOffset.UtcNow - DateTimeOffset.FromUnixTimeSeconds(unix);
    if (age > opt.Value.MaxAge || age < -opt.Value.Skew) return Results.Unauthorized();

    // 3. Sign timestamp + body together, or the timestamp is not protected.
    byte[] signed = Encoding.UTF8.GetBytes($"{unix}.{raw}");
    byte[] expected = HMACSHA256.HashData(opt.Value.Secret, signed);

    // 4. Decode the provided signature defensively.
    byte[] provided;
    try { provided = Convert.FromHexString(sigHeader.ToString()); }
    catch (FormatException) { return Results.Unauthorized(); }

    // 5. Fixed-time compare.
    if (!CryptographicOperations.FixedTimeEquals(expected, provided))
        return Results.Unauthorized();

    return Results.Accepted();
});
```

Five things a reviewer should look for, all of them present above: raw body, timestamp inside the signed payload, freshness window, defensive decode, fixed-time compare.

> 🌍 **In the real world**: a payments webhook handler verifies the signature over `JsonSerializer.Serialize(dto)` after model binding. It passes every test against the provider's sample payload, because the sample happens to round-trip identically. In production, the provider emits `"amount": 10.00` and .NET's serializer re-emits `10`, so the recomputed HMAC differs and every real webhook is rejected as a forgery. The team's first fix was to disable signature verification "temporarily". **Sign and verify the exact bytes on the wire** — the moment you deserialise, you have lost the thing that was signed.

> 🌍 **In the real world**: an internal service compares an API key with `if (provided == expected)`. It sits behind the corporate VPN, so nobody worries about timing. A compromised laptop on the same network gives an attacker a low-latency, low-jitter path to the service — exactly the conditions under which a byte-at-a-time timing attack becomes practical rather than theoretical. The remediation was a one-line change to `FixedTimeEquals`. The lesson the team recorded: **"it's internal" removes network noise, which makes timing attacks easier, not harder.**

---

## Symmetric Encryption

### Default to AEAD

**AEAD** — Authenticated Encryption with Associated Data — gives you confidentiality *and* integrity in a single primitive, with one key and no way to forget the second half. In .NET the in-box AEAD for AES is `System.Security.Cryptography.AesGcm`.

```csharp
using System.Security.Cryptography;

// AesGcm implements IDisposable. IsSupported tells you whether the platform
// provides it (it is not available on browser/wasm).
if (!AesGcm.IsSupported) throw new PlatformNotSupportedException();

const int NonceSize = 12;   // AesGcm.NonceByteSizes: 12 bytes (96 bits)
const int TagSize   = 16;   // full-length GCM tag

byte[] key = /* 32 bytes for AES-256, from a KMS — never a literal */;

// Note the tag size in the constructor: the no-tag-size overloads are
// obsolete as SYSLIB0053 from .NET 8.
using var gcm = new AesGcm(key, TagSize);

byte[] nonce      = RandomNumberGenerator.GetBytes(NonceSize);
byte[] plaintext  = Encoding.UTF8.GetBytes(secretValue);
byte[] ciphertext = new byte[plaintext.Length];   // GCM: same length as plaintext
byte[] tag        = new byte[TagSize];

// Associated data is authenticated but NOT encrypted. Bind the ciphertext
// to its context so it cannot be replayed into a different one.
byte[] aad = Encoding.UTF8.GetBytes($"tenant:{tenantId};field:ssn;v1");

gcm.Encrypt(nonce, plaintext, ciphertext, tag, aad);

// Store nonce ‖ tag ‖ ciphertext. The nonce and tag are not secret.
```

```csharp
// Decrypt — throws CryptographicException if the tag does not verify.
using var gcm = new AesGcm(key, TagSize);
byte[] plaintext = new byte[ciphertext.Length];
try
{
    gcm.Decrypt(nonce, ciphertext, tag, plaintext, aad);
}
catch (CryptographicException)
{
    // Authentication failed: wrong key, wrong AAD, or tampered ciphertext.
    // Do NOT distinguish these to the caller.
    throw new InvalidOperationException("Decryption failed.");
}
```

Facts to have ready:

- **`AesGcm.NonceByteSizes`** is documented as "12 bytes (96 bits)" — a single supported size, not a range.
- **Tag size** is 12–16 bytes depending on platform; GCM natively produces 16 and shorter tags are truncations. Use 16.
- **`AesGcm(byte[])` and `AesGcm(ReadOnlySpan<byte>)` are obsolete from .NET 8** (SYSLIB0053). The reason is genuinely interesting and is a good thing to be able to explain: the old constructors inferred the tag size from whatever tag you passed to `Decrypt`, so an attacker who could supply a short tag effectively reduced the authentication strength. The new constructors make you declare the expected size up front, and `Encrypt`/`Decrypt` then enforce it.
- **`TagSizeInBytes`** exposes what the instance was constructed with.

### Nonce Reuse Is the Catastrophic Failure

Say this plainly, because it is the number one AEAD interview trap. **Reusing a (key, nonce) pair in GCM is not a small weakness — it is a break.** Two messages encrypted under the same key and nonce let an attacker XOR the ciphertexts to cancel the keystream and recover the XOR of the plaintexts; worse, it enables recovery of GCM's authentication subkey, which lets the attacker *forge* tags for that key from then on. Integrity is gone, not just confidentiality.

```
NEVER:
  nonce = new byte[12];                        // all zeros, every time
  nonce = BitConverter.GetBytes(recordId);     // repeats after a reseed/restore
  nonce = Encoding.UTF8.GetBytes("nonce123456"); // constant

CORRECT (pick one, per key):
  ✅ RandomNumberGenerator.GetBytes(12)   — random 96-bit nonce; safe for a
                                            very large number of messages per
                                            key, and the default choice
  ✅ a strictly-increasing counter        — only if you can GUARANTEE it never
                                            repeats or rewinds across restarts,
                                            replicas, restores and rollbacks
```

The counter approach fails in exactly the environments where it is most tempting. A pod restart that resets an in-memory counter, a database restored from a snapshot, two replicas both starting at zero — all of them reuse nonces. Random-per-message needs no coordination, which is why it is the default advice.

> 🌍 **In the real world**: a team encrypts stored payment tokens with AES-GCM and derives the nonce from the row's primary key so decryption "doesn't need to store the nonce". A later migration re-seeds the identity column after a table rebuild, and new rows reuse primary keys that already existed in an archive table encrypted with the same key. The archive and the live table now share (key, nonce) pairs. They discovered it not through an attack but during a routine crypto review. Remediation was a full re-encryption under a new key. **The nonce is not a secret — store it next to the ciphertext.** Twelve extra bytes per row was always the cheap option.

### Why Raw AES-CBC Without a MAC Is a Mistake

`Aes.Create()` gives you a block cipher with a mode, and CBC is the mode most people reach for. It provides confidentiality **and nothing else**. Two concrete consequences:

**1. Malleability.** In CBC, each ciphertext block is XORed into the *next* block's decryption. Flip a bit in ciphertext block *n* and you flip the corresponding bit in plaintext block *n+1* (while turning block *n* into garbage). An attacker who knows the plaintext structure can therefore make targeted, predictable edits to it without the key. `{"role":"user"}` becoming `{"role":"admin"}` is the toy example; the real ones look like flipping an amount's sign or a boolean flag.

**2. Padding oracles.** CBC needs padding. If your decrypt path distinguishes "padding was invalid" from "padding was fine but the content was wrong" — by exception type, by error message, by status code, or **by response time** — you have built a padding oracle, and an attacker can decrypt arbitrary ciphertext one byte at a time without ever learning the key. This is a real, repeatedly-exploited class of bug, not a theoretical one, and it is very hard to close by careful error handling alone because timing counts as a signal.

Both problems have the same root: **CBC has no way to answer "did someone change this?"** The fix is a MAC, and specifically **encrypt-then-MAC** — encrypt the plaintext, then MAC the *ciphertext* (plus the IV and any context), and on the way back verify the MAC *before* you attempt to decrypt. If verification fails you never run the decryption code at all, so there is no oracle to probe.

```
❌ AES-CBC alone            → malleable, padding-oracle-prone
❌ MAC-then-encrypt         → you must decrypt before you can check → oracle
❌ encrypt-and-MAC          → the MAC of plaintext can leak plaintext equality
✅ encrypt-then-MAC         → verify first, decrypt only on success
✅ AES-GCM                  → encrypt-then-MAC, correctly, in one API
```

The practical guidance: **do not hand-roll encrypt-then-MAC if you can use `AesGcm`.** You would be re-implementing, with two keys and a comparison you must remember to make timing-safe, something the BCL already does correctly. Reach for `Aes` in CBC mode only when an external format forces it — and then MAC it, with a separate key, over IV ‖ ciphertext, and verify with `FixedTimeEquals`.

Worth knowing for the follow-up: **ASP.NET Core Data Protection's default is AES-256-CBC for confidentiality with HMACSHA256 for authenticity** — encrypt-then-MAC, assembled correctly, by the framework. That is the shape you would otherwise be building by hand, and it is a good argument for using Data Protection instead.

### Key Length and Key Management

AES-128 and AES-256 are both fine; AES-256 is the common default and costs a little more work per block. The interesting part is never the key length — it is where the key lives.

```
┌──────────────────────────────────────────────────────────────┐
│ WHERE THE KEY LIVES — worst to best                          │
├──────────────────────────────────────────────────────────────┤
│ ❌ A string literal in source                                │
│ ❌ appsettings.json in the repo                              │
│ ⚠️  An environment variable set by the deploy pipeline       │
│ ✅ A secret store the app reads at startup (Key Vault,       │
│    Secrets Manager, Vault) via a managed identity            │
│ ✅ An HSM / KMS that performs the operation and never        │
│    releases the key at all                                   │
└──────────────────────────────────────────────────────────────┘
```

And the question that follows: **how do you rotate?** The answer that works is a **key ID stored with the ciphertext**. Prefix every payload with the identifier of the key that encrypted it; keep old keys available for decryption; encrypt new data with the current key. Without a key ID you cannot rotate without re-encrypting the entire corpus in one transaction, which is why "we'll rotate later" so often becomes "we never rotated". Data Protection's key ring is exactly this pattern, productised.

`CryptographicOperations.ZeroMemory(Span<byte>)` will overwrite a key buffer when you are done with it. Use it — but do not oversell it in an interview: it does not help with `string` (immutable, copied by the GC), and the honest framing is "it shortens the window in which the key sits in a heap buffer", not "the key is now unrecoverable from memory".

---

## Asymmetric Cryptography

### The Split

| | **Symmetric** | **Asymmetric** |
|---|---|---|
| Keys | One shared secret | Key pair: private + public |
| Speed | Fast; suitable for bulk data | Slow; suitable for small payloads |
| Distribution problem | Both parties must already share the secret | Publish the public key freely |
| Non-repudiation | No — either party could have produced it | Yes — only the private key holder could sign |
| Typical use | Encrypting data at rest, session traffic | Signing, key exchange, certificates |

The one-line version: **symmetric solves confidentiality cheaply once you have a shared key; asymmetric solves the problem of not having one.** Real systems use both — this is what "hybrid encryption" means, and it is what TLS does: an asymmetric handshake establishes a symmetric session key, and every byte of application data after that is symmetric.

> ⚠️ Never encrypt bulk data with RSA. RSA can only encrypt a payload smaller than its modulus minus padding overhead, and it is orders of magnitude slower per byte. If you find yourself chunking data through RSA, stop: generate a random symmetric key, encrypt the data with AES-GCM, and encrypt *the key* with RSA. That is hybrid encryption and it is the correct shape.

### Signing: RSA vs ECDSA

```csharp
using System.Security.Cryptography;

// ── RSA ────────────────────────────────────────────────────────────────
using RSA rsa = RSA.Create(3072);          // 2048 is the common floor; 3072+ for new work

byte[] signature = rsa.SignData(
    data,
    HashAlgorithmName.SHA256,
    RSASignaturePadding.Pss);              // PSS for new applications

bool ok = rsa.VerifyData(data, signature, HashAlgorithmName.SHA256,
                         RSASignaturePadding.Pss);

// ── ECDSA ──────────────────────────────────────────────────────────────
using ECDsa ec = ECDsa.Create(ECCurve.NamedCurves.nistP256);

byte[] ecSig = ec.SignData(data, HashAlgorithmName.SHA256);
bool ecOk    = ec.VerifyData(data, ecSig, HashAlgorithmName.SHA256);

// ECDsa also has overloads taking DSASignatureFormat, which matters for interop:
byte[] derSig = ec.SignData(data, HashAlgorithmName.SHA256,
                            DSASignatureFormat.Rfc3279DerSequence);
```

**`RSASignaturePadding` has exactly two values:** `Pkcs1` ("PKCS #1 v1.5 padding mode") and `Pss` ("PSS padding mode"). PKCS#1 v1.5 is the older, deterministic scheme and remains everywhere for compatibility — JWT's `RS256` is RSASSA-PKCS1-v1_5 with SHA-256. PSS is randomised and has a modern security proof; JWT's `PS256` is RSA-PSS. **Prefer PSS when you control both ends; use PKCS#1 v1.5 when a protocol or peer requires it.** Do not describe PKCS#1 v1.5 *signatures* as broken — the badly-broken one is PKCS#1 v1.5 *encryption* padding (Bleichenbacher), which is a different construction. Getting that distinction right is a strong signal.

**`DSASignatureFormat` is the ECDSA interop trap.** An ECDSA signature is a pair (r, s), and there are two ways to write it down: a DER-encoded SEQUENCE (what OpenSSL and X.509 use, variable length) and a fixed-length concatenation of r ‖ s (what JOSE/JWT `ES256` uses). .NET's default for `ECDsa.SignData(byte[], HashAlgorithmName)` is not interchangeable with the other format, and "my ES256 JWT validates in .NET but not in the Node service" is almost always this. The `DSASignatureFormat` overloads exist to let you say which one you want.

### Choosing Between Them

| | **RSA** | **ECDSA** |
|---|---|---|
| Key size for comparable strength | Large (2048/3072/4096-bit) | Small (P-256 / P-384) |
| Signature size | Large — proportional to key size | Small |
| Signing cost | Slow | Fast |
| Verification cost | **Fast** — often faster than ECDSA | Moderate |
| Can also encrypt? | Yes (RSA-OAEP, small payloads) | No — ECDSA signs only; use ECDH for key agreement |
| Hardware/legacy support | Universal | Excellent but slightly less universal |
| Failure mode to fear | Small keys; PKCS#1 v1.5 *encryption* padding | Nonce reuse or bias in signing leaks the private key |

The asymmetry in the cost rows is the good detail: **RSA verification is cheap and RSA signing is expensive; ECDSA is the other way round.** So the choice can be driven by which side you do more of. A JWT issuer signs once per login and every downstream service verifies on every request — that workload shape favours RSA verification cost, which is part of why `RS256` is so entrenched. A system where every device signs constantly and a central service verifies favours ECDSA.

The ECDSA failure mode is worth naming because it is famous: ECDSA requires a per-signature random value, and if that value is ever repeated or predictable across two signatures with the same key, the private key can be recovered algebraically from the two signatures. This is how several high-profile key compromises happened. It is a reason to use the platform's implementation and never a hand-rolled one.

### Certificates, Briefly

An X.509 certificate is a public key plus identity claims, signed by a CA. It solves the *distribution* problem: you can now trust a public key you have never seen before because someone you already trust vouched for it. For loading, prefer `X509CertificateLoader` over the `X509Certificate2` file and byte-array constructors — those constructors carry an obsoletion, and Microsoft's own Data Protection samples now call `X509CertificateLoader.LoadCertificateFromFile`. Check the diagnostic ID against your target framework before you change existing code.

> 🌍 **In the real world**: a service signs JWTs with `HS256` and shares the signing secret with eleven downstream services so they can validate tokens. Any one of those eleven can now *mint* tokens for any user, because with a shared symmetric key verification and signing are the same capability. A single compromised service is a full authentication bypass across the estate. Moving to `RS256` — issuer holds the private key, everyone else fetches the public key from a JWKS endpoint — reduced the blast radius from eleven services to one, and made key rotation a matter of publishing a new JWKS entry rather than coordinating an eleven-way secret change.

---

## Randomness: RandomNumberGenerator vs Random

### The Two Classes

```
┌──────────────────────────────┬───────────────────────────────┐
│ System.Random                │ System.Security.Cryptography  │
│                              │   .RandomNumberGenerator      │
├──────────────────────────────┼───────────────────────────────┤
│ Deterministic PRNG           │ CSPRNG — OS entropy source    │
│ Reproducible from a seed     │ Not reproducible              │
│ Observe enough output → you  │ Observing output tells you    │
│ can predict the rest         │ nothing about future output   │
│ FAST                         │ Fast enough; not the          │
│                              │ bottleneck for token minting  │
│ ✅ simulations, sampling,    │ ✅ tokens, keys, salts,       │
│    jitter, shuffling a UI    │    nonces, IVs, session ids,  │
│    list, test data           │    password reset codes, MFA  │
│                              │    codes, CSRF tokens         │
└──────────────────────────────┴───────────────────────────────┘
```

Microsoft's own note on the `Random` class page is the citation to use: *"To generate a cryptographically secure random number, such as one that's suitable for creating a random password, use one of the static methods in the `RandomNumberGenerator` class."*

The mechanism behind that note: `Random` is a deterministic algorithm advanced by internal state. Its entire future output is a function of that state. An attacker who can observe enough outputs can, for a known algorithm, recover the state and predict everything that follows — including values you never showed them. A CSPRNG is designed so that observing output gives no computational advantage in predicting further output.

### The API Surface

`RandomNumberGenerator`'s remarks say it plainly: *"Using the static members of this class is the preferred way to generate random values."* You almost never need `RandomNumberGenerator.Create()`.

```csharp
using System.Security.Cryptography;

byte[] key   = RandomNumberGenerator.GetBytes(32);        // allocate + fill
Span<byte> b = stackalloc byte[16];
RandomNumberGenerator.Fill(b);                            // fill a span
int  n       = RandomNumberGenerator.GetInt32(0, 1_000_000);  // unbiased range

// .NET 8+ conveniences
string hex   = RandomNumberGenerator.GetHexString(64);            // 64 hex CHARS
string hexLo = RandomNumberGenerator.GetHexString(64, lowercase: true);
char[] pick  = RandomNumberGenerator.GetItems<char>("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 8);
string code  = RandomNumberGenerator.GetString("0123456789", 6);  // e.g. an OTP
RandomNumberGenerator.Shuffle(cards.AsSpan());
```

Version gates, checked against the member pages: `GetBytes`, `Fill`, `GetInt32` and `GetNonZeroBytes` are long-standing; **`GetHexString` and `GetItems<T>` are documented from .NET 8**, and `GetString` and `Shuffle<T>` sit in the same group — check the moniker list on the member page before relying on one from a library that multi-targets.

Two API details worth noticing:

- **`GetHexString(int stringLength, bool lowercase = false)` takes a length in *characters*, not bytes.** `GetHexString(32)` gives you 32 hex characters, which is 16 bytes = 128 bits of entropy. If you wanted 256 bits, you want `GetHexString(64)`. This off-by-two is an easy way to ship a token that is half as strong as you think.
- **`GetInt32(int toExclusive)` is unbiased.** Writing `RandomNumberGenerator.GetBytes(4)` and taking `% range` yourself introduces modulo bias, because the byte range does not divide evenly by the target range. Use the provided method.

### Guid.NewGuid() as a Secret — Why Not

This is a standard question with a standard wrong answer, and the .NET documentation answers it for you in remarkably direct language. From the `Guid.NewGuid` remarks:

> "On Windows, this function wraps a call to the `CoCreateGuid` function. The generated GUID contains 122 bits of strong entropy."
>
> "On non-Windows platforms, starting with .NET 6, this function calls the OS's underlying cryptographically secure pseudo-random number generator (CSPRNG) to generate 122 bits of strong entropy. In previous versions of .NET, the entropy is not guaranteed to be generated by a CSPRNG."
>
> "It is recommended that applications **not** use the *NewGuid* method for cryptographic purposes. First, since a Version 4 UUID has a partially predictable bit pattern, the *NewGuid* function cannot serve as a proper cryptographic pseudo-random function (PRF)... Second, *NewGuid* utilizes at most 122 bits of entropy, regardless of platform. Some cryptographic components set a minimum entropy level on their inputs as a matter of policy. Such policies often set the minimum entropy level at 128 bits or higher."
>
> "If an application requires random data for cryptographic purposes, consider using a static method on the `RandomNumberGenerator` class."

Unpack that into four points you can deliver:

1. **The type does not carry a CSPRNG guarantee across its history.** On non-Windows platforms the CSPRNG guarantee only holds from .NET 6 onward; before that, the docs say the entropy "is not guaranteed to be generated by a CSPRNG". A library targeting older runtimes cannot assume it.
2. **A v4 UUID has a partially predictable bit pattern.** Six bits are fixed as version and variant markers, so 128 bits of GUID carry at most 122 bits of entropy — and those 6 bits are in known positions.
3. **122 < 128.** Many policies and primitives set a 128-bit floor. A GUID cannot meet a 128-bit-minimum requirement no matter what the platform does.
4. **The docs tell you to use `RandomNumberGenerator` instead.** You are not offering an opinion; you are quoting the API reference.

Add the specification-level version if you want to close it hard. RFC 9562, which supersedes RFC 4122 for UUIDs, states in its Security Considerations: *"Implementations SHOULD NOT assume that UUIDs are hard to guess. For example, they MUST NOT be used as security capabilities (identifiers whose mere possession grants access)."* A password-reset link with a GUID in it is precisely a security capability.

**And `Guid.CreateVersion7()` (.NET 9+) is worse, not better, for this.** A v7 UUID embeds a Unix-epoch timestamp so that IDs sort by creation time — excellent for database index locality, actively harmful for secrecy, because a large, structured, guessable chunk of the value is derived from the clock. RFC 9562 makes the same point: *"If UUIDs are required for use with any security operation within an application context in any shape or form, then UUIDv4 SHOULD be utilized"* — and even then, per the paragraph above, not as a capability.

> 🌍 **In the real world**: a password-reset flow emails a link containing `Guid.NewGuid()`, valid for 24 hours, with no rate limit on the reset-consume endpoint. The team's reasoning was "there are 2¹²² of them". The actual exposure came from somewhere else entirely: the GUID was also written to an access log that a third-party log-shipping integration could read, and it appeared in the `Referer` header when the reset page loaded an external font. Neither of those is a guessing attack — but both were only exploitable *because the token in the URL was the entire authorisation*. The redesign generated the token with `RandomNumberGenerator.GetBytes(32)`, stored only its SHA-256 in the database, scoped it to a single user id, expired it in 15 minutes, invalidated it on use, and stopped logging URLs with query strings.

### How Much Entropy, and How to Encode It

```csharp
// 256 bits of entropy, URL-safe, no padding, ~43 characters.
byte[] raw = RandomNumberGenerator.GetBytes(32);
string token = Base64Url.EncodeToString(raw);        // .NET 9+
```

Rules of thumb you can defend: **128 bits is the floor for anything long-lived** (API keys, session identifiers), **256 bits for anything you would rather over-provision** (they cost 16 extra bytes). Short human-typed codes — OTPs, device-pairing codes — deliberately have low entropy and must therefore be defended by *rate limiting and short expiry*, not by the code's length. A 6-digit code has a search space of 10⁶, i.e. log₂(10⁶) ≈ 20 bits; the only reason that is acceptable is the attempt ceiling and the short window around it. Get the rate limit wrong and a 6-digit code is guessable by brute force, which is a real and repeatedly-exploited failure of MFA implementations.

---

## Storing Tokens and API Keys at Rest

A question that separates candidates: *"You issue API keys. How do you store them?"*

The wrong answers are "encrypted in the database" (better than plaintext, but you now have a key that decrypts every customer's credential, and an application compromise reveals all of them) and "hashed with bcrypt" (defensible, but you have to run a slow KDF on every single API request, which is a self-inflicted performance problem).

The right answer distinguishes **low-entropy secrets** from **high-entropy secrets**:

```
PASSWORD (low entropy, human-chosen)
  → slow KDF, per-user salt.
    The attacker's advantage is that the search space is tiny;
    you fight it by making each guess expensive.

API KEY / SESSION TOKEN / RESET TOKEN (256-bit, machine-generated)
  → plain SHA-256 is correct.
    There is no wordlist for a 256-bit random value. Making the hash
    slow buys nothing, and costs you a KDF on every request.
```

```csharp
// ── Issue ──────────────────────────────────────────────────────────────
byte[] raw     = RandomNumberGenerator.GetBytes(32);
string display = "sk_live_" + Base64Url.EncodeToString(raw);   // shown ONCE
byte[] lookup  = SHA256.HashData(raw);                          // stored

await db.ApiKeys.AddAsync(new ApiKey
{
    Id          = Guid.CreateVersion7(),      // fine as an ID — it is not the secret
    Prefix      = display[..12],              // for the UI: "sk_live_a7Fq…"
    LookupHash  = lookup,                     // indexed
    TenantId    = tenantId,
    CreatedUtc  = DateTimeOffset.UtcNow,
    ExpiresUtc  = DateTimeOffset.UtcNow.AddDays(365),
});

// ── Verify ─────────────────────────────────────────────────────────────
// Hash the presented key and look up by hash: one indexed read, no scan,
// and no need to compare secrets in application code at all.
byte[] presentedHash = SHA256.HashData(presentedRaw);
var key = await db.ApiKeys.SingleOrDefaultAsync(k => k.LookupHash == presentedHash, ct);
if (key is null || key.ExpiresUtc < DateTimeOffset.UtcNow || key.RevokedUtc is not null)
    return Unauthorized();
```

Notice what falls out of hashing rather than encrypting: **the lookup is an indexed equality search on the hash**, so you get O(1)-ish verification and you never hold the plaintext key at all. You cannot email a lost key back to a customer — which is the correct behaviour, and is exactly why every provider you have ever used shows an API key once and then only its prefix.

> 🌍 **In the real world**: a platform stores API keys encrypted with a single application-wide AES key so support staff can read a key back to a customer who lost it. The convenience feature becomes the incident: a read-only database export shared with a vendor is combined with a key that turned up in a container image layer, and every customer's live key is recoverable. Rotating meant contacting every integrator. The design that avoids it is not more encryption, it is **hashing plus "you can't have it back, generate a new one"** — a support process change that eliminates a class of breach.

---

## ASP.NET Core Data Protection

### What It Is, and Why "Don't Roll Your Own" Has an Address

Everything in the previous sections — pick an algorithm, generate a key, store it somewhere, rotate it, keep old keys for decryption, bind the ciphertext to a context, authenticate as well as encrypt — is work you should not be doing by hand for the common case of "protect a short-lived payload inside my own application". ASP.NET Core's Data Protection stack does it, and the framework already uses it for authentication cookies, antiforgery tokens, and TempData.

```csharp
builder.Services.AddDataProtection();

// Consume it
public class ShareLinkService(IDataProtectionProvider provider)
{
    // The purpose string is part of the security model, not a label.
    private readonly IDataProtector _protector =
        provider.CreateProtector("Contoso.Sharing.DocumentLink.v1");

    public string Create(Guid documentId) => _protector.Protect(documentId.ToString());

    public bool TryRead(string payload, out Guid documentId)
    {
        documentId = default;
        try   { return Guid.TryParse(_protector.Unprotect(payload), out documentId); }
        catch (CryptographicException) { return false; }   // tampered, expired key, wrong purpose
    }
}
```

### Purposes Are Isolation, Not Naming

From the purpose-strings documentation: *"The purposes parameter is inherent to the security of the data protection system, as it provides isolation between cryptographic consumers, even if the root cryptographic keys are the same."* The purpose string is fed into subkey derivation, so two protectors with different purposes cannot read each other's payloads even though they share a key ring.

```csharp
// A payload minted here...
provider.CreateProtector("Contoso.Sharing.DocumentLink.v1").Protect(data);

// ...cannot be read here. Unprotect throws.
provider.CreateProtector("Contoso.Security.BearerToken.v1").Unprotect(payload);
```

Three rules from the docs, each of which is a potential cross-question:

- **The purpose need not be secret** — only unique. The recommended convention is the namespace and type name of the consuming component, with a version suffix (`Contoso.Security.BearerToken.v1`) so a future format change is automatically isolated from the old one.
- **Purposes are an array and are hierarchical.** `CreateProtector(["Contoso.Messaging.SecureMessage", $"User: {username}"])` gives per-user isolation for free — a payload minted for user A cannot be unprotected for user B. This is the clean multi-tenant pattern.
- **Never let untrusted input be the *sole* source of the purposes chain.** The docs' own example: a component that calls `CreateProtector([username])` can be tricked by a user registering the name `Contoso.Security.BearerToken` into minting payloads that another component will accept as bearer tokens. Always anchor the chain with a component-owned constant first.

### The Key Ring

```
KEY LIFECYCLE (from the key-management documentation)

Created ──2 days──▶ Active ──90 days──▶ Expired
   │                   │                    │
   │                   │                    └─ can still UNPROTECT
   │                   └─ used for all new PROTECT operations
   └─ exists but not yet used, so it can propagate to every
      instance before anything starts protecting with it

Revoked ─── compromised; will not unprotect by default
            (an explicit "dangerous unprotect" override exists)

Created, Active and Expired keys may ALL be used to unprotect.
```

The documented specifics:

- A new key gets an activation date of **now + 2 days** and an expiration of **now + 90 days**. The 2-day delay exists so the key can propagate to every machine reading the same store before it goes live.
- **Default key lifetime is 90 days**, configurable via `SetDefaultKeyLifetime`, and **cannot be shorter than 7 days**.
- Rolling is automatic: if the default key will expire within 2 days and no successor exists, the system persists a new key activating at the old key's expiry.
- The key ring is cached in memory and **re-read approximately every 24 hours, or when the current default key expires, whichever comes first.**
- The default payload algorithms are **AES-256-CBC for confidentiality and HMACSHA256 for authenticity**, with a 512-bit master key from which per-payload subkeys are derived.
- **Deleting a key is destructive and permanent** — the docs' word is "truly destructive behavior" — because there is no override the way there is for revoked keys. A `IDeletableKeyManager.DeleteKeys` API exists for extreme cases; the guidance is not to.

### What Breaks in a Multi-Instance Deployment

This is the highest-value part of the topic, because the failure is common, the symptom is confusing, and the cause is a default.

Data Protection *guesses* where to put keys. From the documented heuristic, in order:

1. **Azure App Service** → `%HOME%\ASP.NET\DataProtection-Keys`, network-backed and synchronised across all machines hosting the app. Not protected at rest. **Deployment slots do not share a key ring** — swapping Staging into Production means the new slot cannot decrypt what the old one protected.
2. **User profile available** → `%LOCALAPPDATA%\ASP.NET\DataProtection-Keys`, encrypted at rest with DPAPI on Windows.
3. **IIS-hosted** → the HKLM registry, ACLed to the worker process account, DPAPI-encrypted.
4. **None of the above** → *"keys aren't persisted outside of the current process. When the process shuts down, all generated keys are lost."*

Case 4 is the container case, and it is where teams get hurt. A plain Linux container with no writable user profile hits the fallback, so **every replica generates its own in-memory key ring, and every restart throws it away.**

```
┌──────────────────────────────────────────────────────────────┐
│ SYMPTOMS OF NO SHARED KEY RING                               │
├──────────────────────────────────────────────────────────────┤
│ • Users randomly logged out — the auth cookie was protected  │
│   by pod A and the next request landed on pod B.             │
│ • Antiforgery validation fails intermittently: the token was │
│   issued by one instance and posted back to another.         │
│ • Everyone is logged out on every deploy, and on every       │
│   restart or autoscale event.                                │
│ • Sticky sessions "fix" it — which is the tell. If turning   │
│   on session affinity fixes your logout bug, you have a key  │
│   ring problem, not a load-balancer problem.                 │
│ • Logs fill with warnings about unprotecting payloads and    │
│   with "key ring does not contain a valid default key".      │
└──────────────────────────────────────────────────────────────┘
```

Two things must be true for multiple instances to share protected payloads:

```csharp
builder.Services.AddDataProtection()
    // 1. A shared, durable key store every instance can read and write.
    .PersistKeysToAzureBlobStorage(new Uri(blobUri), credential)
    // 2. The same application discriminator, so the apps are the same "app".
    .SetApplicationName("contoso-storefront")
    // 3. Because you named an explicit store, at-rest encryption of the keys
    //    was DEREGISTERED. Put it back.
    .ProtectKeysWithAzureKeyVault(new Uri(keyIdentifier), credential);
```

Point 3 is the one nobody expects, and the docs warn about it twice: *"If you specify an explicit key persistence location, the data protection system deregisters the default key encryption at rest mechanism, so keys are no longer encrypted at rest."* You fixed the sharing problem and silently created an at-rest problem. Always pair `PersistKeysTo*` with `ProtectKeysWith*`.

Point 2 matters because `SetApplicationName` sets `DataProtectionOptions.ApplicationDiscriminator`, and *"for the apps to be able to read each other's cryptographic payloads, they must have the same application discriminator."* Without it, the discriminator is derived from the content root path — which differs between a container and a dev box, and can differ between two deployments of the same app.

Storage options, all documented: `PersistKeysToFileSystem` (a shared volume or UNC path), `PersistKeysToAzureBlobStorage`, `PersistKeysToStackExchangeRedis`, `PersistKeysToDbContext<T>` (EF Core, requires `IDataProtectionKeyContext`), `PersistKeysToRegistry` (Windows only), or a custom `IXmlRepository`.

> ⚠️ **The Redis footgun**, straight from the docs: *"Redis doesn't persist data by default when restarting. This can cause Data Protection to issue new keys, invalidating previously protected data."* You chose Redis to solve the shared-key-ring problem and got a key ring that evaporates on a cache restart. Enable Redis persistence, or pick a store that is durable by nature.

> 🌍 **In the real world**: a team moves an ASP.NET Core app from a single VM to a three-replica Kubernetes deployment. Users start reporting random logouts. Because the failures are intermittent and correlate with load, the team spends a week on the load balancer, then enables session affinity, which makes the symptom disappear. Six months later a rolling deploy logs everyone out anyway, because affinity cannot help when the pod itself is replaced. The actual cause was there from day one: no shared key ring, so each pod's authentication cookies were unreadable by its peers. **Session affinity masking a logout bug is a diagnostic, not a fix.**

> 🌍 **In the real world**: a team on Azure App Service uses slot swapping for zero-downtime deploys and cannot understand why every swap signs out their whole user base for a few minutes. The documented behaviour is that separate deployment slots do not share a key ring — Staging protected cookies with Staging's keys, and after the swap those keys are no longer the ones the Production slot reads. The documented fix is an external key ring provider (Blob Storage, Key Vault, SQL, Redis) so the key ring is slot-independent. They had been treating a configuration default as an unavoidable cost of slot swapping.

### Time-Limited Payloads

For a payload that must expire — a share link, a magic login link, a signed download URL — there is a purpose-built interface rather than a timestamp you have to remember to check:

```csharp
using Microsoft.AspNetCore.DataProtection;   // Microsoft.AspNetCore.DataProtection.Extensions

ITimeLimitedDataProtector tl = provider
    .CreateProtector("Contoso.Sharing.MagicLink.v1")
    .ToTimeLimitedDataProtector();

string payload = tl.Protect(userId.ToString(), TimeSpan.FromMinutes(15));

// Unprotect throws once the payload has expired, and can hand back the expiry.
try
{
    string value = tl.Unprotect(payload, out DateTimeOffset expiration);
}
catch (CryptographicException) { /* expired, tampered, or wrong purpose */ }
```

The expiry is inside the authenticated payload, so a user cannot extend it by editing anything. Note the documented scope limit: *"It is intended that payload lifetimes be somewhat short. Payloads protected via this mechanism are not intended for long-term persistence (e.g., longer than a few weeks)."*

### What Data Protection Is Not For

Being able to state the boundary is as valuable as knowing the API:

- **Not for long-term data at rest.** Keys roll every 90 days and old keys can be deleted or lost; the whole design assumes short-lived payloads. Encrypting a column of customer records with `IDataProtector` and expecting to read it in five years is a data-loss plan. Use envelope encryption with a KMS and an explicit key ID.
- **Not for data shared with something outside your application boundary.** The format is a .NET implementation detail with no cross-platform consumer.
- **Not a substitute for a secret store.** It protects payloads *your app produces*; it does not manage your database password.
- **Not for passwords.** Data Protection is reversible. Passwords must not be.

---

## Where TLS Fits

### One Sentence

**TLS protects data in transit between two endpoints. It says nothing about data at rest, and nothing about what happens to the data once it arrives.**

```
┌──────────────────────────────────────────────────────────────┐
│  Browser ══════ TLS ══════▶ Load balancer ────?────▶ App     │
│                                    │                   │     │
│                             TLS ENDS HERE         plaintext  │
│                             (termination)         in memory  │
│                                                        │     │
│                                                        ▼     │
│                                               ┌──────────────┤
│                                               │  Database    │
│                                               │  Log files   │
│                                               │  Backups     │
│                                               │  Cache       │
│                                               │  Message bus │
│                                               └──────────────┤
│                                                              │
│  TLS covered exactly ONE of the arrows above.                │
└──────────────────────────────────────────────────────────────┘
```

### What TLS Gives You

| Guarantee | How |
|---|---|
| **Confidentiality in transit** | Symmetric encryption of the session (keys agreed in the handshake) |
| **Integrity in transit** | The record-layer AEAD — a tampered record fails to authenticate |
| **Server authentication** | The certificate chain, validated against a trust store |
| **Client authentication** | Only with mTLS, which is opt-in and rarely on by default |

### What It Does Not Give You

- **Anything at rest.** The database file, the backup, the log, the S3 bucket, the cache — TLS never touched any of them.
- **Anything after termination.** Most production TLS terminates at a load balancer, CDN or ingress controller. Traffic from there to your app is a separate hop that must be secured separately, and frequently is not.
- **Protection from your own logging.** A request body arrives decrypted. If you log it, the secret is now in plaintext in your log pipeline, your log vendor, and your log backups.
- **Protection from the endpoints.** TLS protects the wire, not the parties. A compromised server sees everything.
- **Field-level access control.** TLS is all-or-nothing for the connection; it cannot encrypt one column so that the DBA cannot read it.

### Why "We Use HTTPS" Does Not Answer "How Do You Store This at Rest"

Because they are answers to different questions, and the interviewer is checking whether you notice. Line them up:

| Question | Control |
|---|---|
| Can someone on the network read this? | TLS |
| Can someone with a database backup read this? | Encryption at rest / hashing / tokenisation |
| Can someone with production log access read this? | Redaction at the logging boundary |
| Can a DBA read this column? | Application-level or field-level encryption |
| Can an attacker who dumped the users table log in as someone? | Password hashing with a KDF |
| Can someone who steals this token replay it? | Short expiry, binding, revocation |

The senior move when handed "we use HTTPS" as an answer is to ask **where TLS terminates and what happens after**. In practice the answer is a load balancer, and the next question — "is the hop from the load balancer to the pod encrypted?" — is often the first time anyone has thought about it.

> 🌍 **In the real world**: an audit finding says customer national-insurance numbers must be encrypted. The team's response is that the site is HTTPS-only with HSTS. The auditor asks to see a database backup, opens it in a text editor, and reads the numbers. HTTPS was never the control in question. The remediation was field-level encryption with AES-GCM and a KMS-held key, with the tenant id and column name as associated data so a ciphertext could not be moved between rows or columns. Total change: one value converter and a key policy. The week it took to agree that HTTPS was not the answer was longer than the week it took to build.

> 🌍 **In the real world**: a team enables TLS 1.3 everywhere and closes the security ticket. Two months later a support engineer finds full request bodies — including card-holder names and a `password` field from the signup endpoint — in the log aggregator, retained for a year, searchable by anyone with a read seat. The request had been decrypted the instant it reached the application, and structured logging serialised the whole model. **TLS ends where your code begins**, and the logging boundary is where most plaintext leaks actually happen.

### Practical Notes

- Prefer TLS 1.2 as a floor and TLS 1.3 where available. In .NET, leave `SslProtocols` at the system default rather than pinning a list — the platform's default moves forward with OS policy, and a hard-coded list becomes a liability the moment a protocol version is deprecated.
- `UseHsts()` and `UseHttpsRedirection()` in ASP.NET Core handle the browser side. HSTS is a browser instruction and does nothing for API-to-API traffic.
- **Certificate pinning** is a real control and a real operational hazard: pin the wrong thing and a routine CA rotation takes your mobile fleet offline. Mention it as a trade-off, never as an unconditional recommendation.
- **mTLS** is where you go when you need to authenticate the *client* at the transport layer — service-to-service inside a mesh is the common case.

---

## Choosing a Primitive — Decision Table

| Requirement | Use | Do **not** use |
|---|---|---|
| Make binary safe for a URL / header / JSON | `Base64Url` (.NET 9+) or `Convert.ToBase64String` | Anything, as a *security* control |
| Verify a downloaded file is intact | `SHA256.HashData` | MD5, SHA-1 |
| Verify a payload came from a known partner | `HMACSHA256.HashData` + `FixedTimeEquals` | Unkeyed hash |
| Store a user password | `PasswordHasher<TUser>` (raise `IterationCount`) or Argon2id via a package | `SHA256.HashData`, `MD5`, encryption |
| Store an API key you generated | `SHA256.HashData` of a 256-bit random value | Encryption; plaintext; a slow KDF |
| Encrypt a field in your own database | `AesGcm` + a KMS-held key + key ID + AAD | `Aes` in CBC with no MAC |
| Protect a short-lived payload inside one app | `IDataProtector` | Hand-rolled AES |
| Expire a share link cryptographically | `ITimeLimitedDataProtector` | A timestamp in the URL |
| Generate a session id / token / salt / nonce | `RandomNumberGenerator` | `Random`, `Guid.NewGuid`, `Guid.CreateVersion7` |
| Sign a JWT for many verifiers | RSA (`RS256`/`PS256`) or ECDSA (`ES256`) | `HS256` with a widely-shared secret |
| Sign where only two parties are involved | HMAC | Asymmetric, if you don't need non-repudiation |
| Prove *who* sent something, undeniably | Digital signature | HMAC — both sides can produce it |
| Protect data on the wire | TLS | Application-layer encryption *instead of* TLS |
| Protect data in a backup | Encryption at rest with managed keys | TLS |

---

## Common Pitfalls

### 1. Calling Base64 Encryption

Covered at length above; it remains the single most common error in this area. The tell in a code review is a variable named `encrypted` assigned from `Convert.ToBase64String`.

### 2. `SHA256.HashData(password)`

Fast by design, therefore wrong by design. Often accompanied by "but we salted it" — salting a fast hash removes precomputation but does nothing about the attacker's guess *rate*, which is the actual threat.

### 3. Comparing Secrets with `==` or `SequenceEqual`

```csharp
// ❌
if (computedSignature == providedSignature) { ... }
// ✅
if (CryptographicOperations.FixedTimeEquals(computed, provided)) { ... }
```

### 4. Reusing a GCM Nonce

A zero nonce, a nonce derived from a database identifier, a counter that resets on restart. Any of these is a full break of both confidentiality and integrity for that key. Random 12 bytes per message.

### 5. AES-CBC With No MAC

Malleable, and a padding-oracle candidate. If you must use CBC, encrypt-then-MAC with a separate key and verify before decrypting. Prefer `AesGcm`.

### 6. Verifying a Signature Over Re-Serialised JSON

Sign and verify the exact bytes received. Model binding and re-serialisation change whitespace, property order and number formatting.

### 7. `Guid.NewGuid()` as a Secret

At most 122 bits, a partially predictable bit pattern, and the .NET docs explicitly recommend against it for cryptographic purposes. `Guid.CreateVersion7()` is worse because it embeds a timestamp.

### 8. No Shared Data Protection Key Ring

Multi-replica deployment with the default key storage heuristic. Symptom: random logouts, antiforgery failures, everyone signed out on deploy. Fix: `PersistKeysTo*` + `SetApplicationName` + `ProtectKeysWith*`.

### 9. Adding `PersistKeysTo*` and Forgetting `ProtectKeysWith*`

Specifying an explicit key repository deregisters the default at-rest key encryption. You solved sharing and quietly created a plaintext key ring.

### 10. Hard-Coding a Key Anywhere in the Repository

Including "just for the test environment" and "it's only base64'd". Git remembers. Rotating a leaked key means rotating everything it ever protected.

### 11. Distinguishing Failure Reasons to the Caller

"Invalid padding" vs "invalid MAC", "no such user" vs "wrong password", "expired token" vs "invalid token" — each distinction is an oracle. One generic failure, one status code, one message, and comparable timing.

### 12. Encrypting What Should Be Hashed

Passwords, API keys, reset tokens. If you never need the original value back, do not keep the ability to get it back. Reversibility you do not need is a liability you do not need.

### 13. Rolling Your Own KDF or MAC Construction

`H(key || message)` is length-extension-vulnerable. A loop calling SHA-256 "a lot of times" is not PBKDF2. Use `HMACSHA256`, use `Rfc2898DeriveBytes.Pbkdf2`.

### 14. No Key ID in the Ciphertext

Without an identifier saying which key encrypted a payload, rotation requires re-encrypting everything atomically — so rotation never happens. Prefix the key id.

### 15. Treating "It's Internal" as a Mitigation

Internal networks reduce network noise, which makes timing attacks easier. They also do nothing about a compromised service, a misconfigured mesh, or an insider. Verify signatures and use fixed-time comparison on internal endpoints too.

### 16. Obsolete APIs Left in Place

`SYSLIB0041` (`Rfc2898DeriveBytes` constructors defaulting to SHA-1 and a low iteration count) and `SYSLIB0053` (`AesGcm` constructors that infer the tag size). Both are obsoletions with a security rationale, not tidy-ups — do not suppress them with `NoWarn` and move on.

---

## Best Practices

1. **Name the primitive before the algorithm.** Decide whether you need encoding, hashing, a MAC, or encryption. The algorithm choice is downstream of that and usually obvious once the primitive is settled.
2. **Use the highest-level API that solves the problem.** `IDataProtector` over `AesGcm` over `Aes`. Every level you descend is another chance to make a joinery mistake.
3. **Default to AEAD.** `AesGcm` with a 12-byte random nonce and a 16-byte tag, and use associated data to bind ciphertext to its context.
4. **Never reuse a (key, nonce) pair.** Random nonce per message unless you can prove a counter cannot repeat across restarts, replicas and restores.
5. **Password storage: a KDF with a tuned work factor, a per-user salt stored beside the hash, and a self-describing format.** Raise Identity's `IterationCount` above the 100,000 default and re-hash on `SuccessRehashNeeded`.
6. **Compare every secret with `CryptographicOperations.FixedTimeEquals`.** Make it a review checklist item and a lint rule if you can.
7. **Generate every secret with `RandomNumberGenerator`.** 128 bits minimum, 256 bits when you can afford the width. Never `Random`, never a `Guid`.
8. **Hash high-entropy secrets at rest with SHA-256; hash low-entropy secrets with a KDF.** Do not slow-hash an API key and do not fast-hash a password.
9. **Store a key ID with every ciphertext** so rotation is possible without a global re-encryption.
10. **Keys live in a KMS or secret store, never in source, config files, or images.** Grant access with a managed identity.
11. **Data Protection in production: `PersistKeysTo*` + `SetApplicationName` + `ProtectKeysWith*`.** All three, always. Verify the key ring is shared before you scale out, not after.
12. **Use distinct, versioned purpose strings**, anchored with a component-owned constant, with untrusted input only ever appended.
13. **Fail uniformly.** One error shape for all cryptographic failures, and comparable timing on both paths.
14. **Redact at the logging boundary.** TLS ends at your code; the log pipeline is where plaintext escapes.
15. **Never suppress a `SYSLIB` crypto obsoletion.** Read the diagnostic page — each one exists because the old API had a security-relevant defect.
16. **Write down where TLS terminates.** If you cannot say, that is the first thing to find out.

---

## Real-World Scenarios

### Scenario 1: Encrypting a PII Column with Rotation Support

**Problem:** national-insurance numbers must be encrypted at rest, searchable by exact match, with key rotation possible without a big-bang re-encryption.

**Solution:**

```csharp
// Two derived values per row, doing two different jobs.
public sealed class PersonRecord
{
    public Guid Id { get; set; }
    public byte[] NinoCiphertext { get; set; } = [];  // nonce ‖ tag ‖ ciphertext
    public string NinoKeyId      { get; set; } = "";  // which key encrypted it
    public byte[] NinoBlindIndex { get; set; } = [];  // HMAC for exact-match lookup
}

public sealed class NinoProtector(IKeyRing keys)   // keys resolves ids → key material
{
    public (byte[] payload, string keyId) Encrypt(string nino, Guid tenantId)
    {
        var (keyId, key) = keys.Current;
        using var gcm = new AesGcm(key, 16);

        byte[] nonce      = RandomNumberGenerator.GetBytes(12);
        byte[] plaintext  = Encoding.UTF8.GetBytes(nino);
        byte[] ciphertext = new byte[plaintext.Length];
        byte[] tag        = new byte[16];

        // AAD binds the ciphertext to this tenant AND this field. A ciphertext
        // copied into another tenant's row, or into a different column, fails
        // to authenticate.
        byte[] aad = Encoding.UTF8.GetBytes($"{tenantId}|nino|v1");

        gcm.Encrypt(nonce, plaintext, ciphertext, tag, aad);
        return ([.. nonce, .. tag, .. ciphertext], keyId);
    }

    // A blind index: a keyed hash of the normalised value, so exact-match
    // search works without decrypting. Keyed (not a plain hash) so an
    // attacker with the database cannot brute-force the small NINO space.
    public byte[] BlindIndex(string nino) =>
        HMACSHA256.HashData(keys.BlindIndexKey, Encoding.UTF8.GetBytes(nino.ToUpperInvariant()));
}
```

Decisions and why: **AES-GCM** because the field must be tamper-evident as well as unreadable; **AAD** so a ciphertext cannot be relocated between tenants or columns; **a key id column** so rotation is lazy — new writes use the current key, reads look up the key that was used; **a keyed blind index** because a plain SHA-256 of a NINO is brute-forceable (the format constrains the space to something small) whereas an HMAC is not without the key.

### Scenario 2: Migrating a Legacy Password Store

**Problem:** an acquired system stores unsalted SHA-1 password hashes. You cannot force a reset for 400,000 users on day one.

**Solution:** dual-format storage plus opportunistic upgrade.

```csharp
public async Task<bool> VerifyAndUpgradeAsync(User user, string password, CancellationToken ct)
{
    if (user.HashFormat == HashFormat.LegacySha1)
    {
        byte[] legacy = SHA1.HashData(Encoding.UTF8.GetBytes(password));
        if (!CryptographicOperations.FixedTimeEquals(legacy, user.LegacyHash!))
            return false;

        // Correct password, weak storage. This is the only moment we hold the
        // plaintext, so upgrade now.
        user.PasswordHash = _hasher.HashPassword(user, password);
        user.LegacyHash   = null;
        user.HashFormat   = HashFormat.IdentityV3;
        await _store.UpdateAsync(user, ct);
        return true;
    }

    var result = _hasher.VerifyHashedPassword(user, user.PasswordHash!, password);
    if (result == PasswordVerificationResult.SuccessRehashNeeded)
    {
        user.PasswordHash = _hasher.HashPassword(user, password);
        await _store.UpdateAsync(user, ct);
    }
    return result != PasswordVerificationResult.Failed;
}
```

The part people forget: **set a deadline**. Track the percentage still on the legacy format, and force a reset for the remainder at a fixed date. Otherwise dormant accounts keep SHA-1 hashes forever, and dormant accounts are exactly the ones nobody notices being taken over.

An alternative worth knowing for the cross-question: **wrap rather than migrate**. Store `PBKDF2(SHA1(password))` for every legacy row in a single offline pass, so the whole table is strengthened immediately without anyone logging in — at the cost of a slightly odd composite format you must carry until each user next signs in.

### Scenario 3: Signed, Expiring Download Links

**Problem:** authenticated users generate share links to private documents. The link must work without a session, expire in 15 minutes, and be unforgeable.

**Solution:**

```csharp
public sealed class DownloadLinkService(IDataProtectionProvider provider)
{
    private readonly ITimeLimitedDataProtector _protector = provider
        .CreateProtector("Contoso.Documents.DownloadLink.v1")
        .ToTimeLimitedDataProtector();

    public string Create(Guid documentId, Guid grantedToUserId) =>
        _protector.Protect($"{documentId}|{grantedToUserId}", TimeSpan.FromMinutes(15));

    public bool TryResolve(string token, out Guid documentId, out Guid userId)
    {
        documentId = userId = default;
        try
        {
            var parts = _protector.Unprotect(token).Split('|');
            return Guid.TryParse(parts[0], out documentId)
                && Guid.TryParse(parts[1], out userId);
        }
        catch (CryptographicException) { return false; }   // expired, tampered, wrong purpose
    }
}
```

Decision: `ITimeLimitedDataProtector` rather than a hand-rolled `?expires=...&sig=...`, because the expiry travels *inside* the authenticated payload and the framework handles the key ring. Note that the token still identifies who it was granted to, so revoking a user's access can be enforced at redemption time — a purely cryptographic link with no server-side check cannot be revoked before it expires.

### Scenario 4: Verifying Inbound Webhooks from Three Providers

**Problem:** three payment providers, three signature schemes: one HMAC-SHA256 hex, one HMAC-SHA256 base64 over `timestamp.body`, one RSA-SHA256 over the raw body.

**Solution:** one abstraction, three implementations, one shared discipline.

```csharp
public interface IWebhookVerifier
{
    string Provider { get; }
    bool Verify(ReadOnlySpan<byte> rawBody, IHeaderDictionary headers);
}

// All three implementations obey the same three rules:
//   1. Operate on the RAW body bytes, never a re-serialised object.
//   2. Enforce a freshness window before or alongside verification.
//   3. Compare with FixedTimeEquals (HMAC) or the platform verifier (RSA).
```

Decision: keyed services (see [Dependency Injection](02-dependency-injection.md#keyed-services-net-8)) to resolve the verifier by provider name, so adding a fourth provider is a registration rather than a `switch`. The shared discipline lives in a test suite that runs the same three adversarial cases — tampered body, replayed old timestamp, truncated signature — against every implementation.

---

## Interview-Ready Summary

- **Encoding is reversible without a key and is not a security control.** Base64 is encoding. Hashing is one-way with no key. Encryption is reversible *with* a key. If the sentence has no key in it and claims confidentiality, it is wrong.
- **A JWT is signed, not encrypted.** Anyone can read the claims; nobody can change them without the key.
- **SHA-256 is right for integrity and wrong for passwords, for the same reason: it is fast.** Speed is a feature when you are checksumming a file and a bug when an attacker is guessing candidates from a wordlist.
- **Password storage needs a tunable work factor, a unique per-user salt stored beside the hash, and a self-describing format.** The salt is not secret; it kills precomputation and cross-account correlation. A pepper is the site-wide secret and lives outside the database.
- **ASP.NET Core Identity's `PasswordHasher<TUser>` uses PBKDF2 with HMAC-SHA512, a 128-bit salt, a 256-bit subkey and a default of 100,000 iterations** (`PasswordHasherOptions.IterationCount`), in the V3 format `{ 0x01, prf, iterations, salt length, salt, subkey }`. OWASP's current floor for PBKDF2-HMAC-SHA512 is 220,000, so **the default is below the recommendation** — raise it, and migrate via `PasswordVerificationResult.SuccessRehashNeeded`.
- **Argon2 is not in the BCL** ([dotnet/runtime#19933](https://github.com/dotnet/runtime/issues/19933)). Your in-box option is PBKDF2; anything else is a third-party dependency in the auth path.
- **HMAC turns integrity into authenticity** because it is keyed. It cannot give non-repudiation — both parties hold the key. Only a signature can.
- **Compare secrets with `CryptographicOperations.FixedTimeEquals`.** It is documented as taking time proportional to *length* but not *values* — so it does not hide length. `VerifyHmac` packages compute-and-compare, but it is **.NET 11**, not .NET 10.
- **Default to AES-GCM.** 12-byte nonce, 16-byte tag, associated data to bind context. The tag-size-less `AesGcm` constructors are obsolete (**SYSLIB0053**) precisely because inferring the tag size weakened authentication.
- **Never reuse a (key, nonce) pair in GCM** — it breaks confidentiality *and* lets an attacker forge tags.
- **Raw AES-CBC has no integrity**, which makes it malleable and padding-oracle-prone. Encrypt-then-MAC, or just use GCM. Data Protection's own default is AES-256-CBC + HMACSHA256 — encrypt-then-MAC, assembled correctly by the framework.
- **RSA verification is cheap and signing is expensive; ECDSA is the reverse.** Prefer `RSASignaturePadding.Pss` for new work. For ECDSA interop, know that `DSASignatureFormat` distinguishes DER from the fixed-length r‖s that JOSE uses.
- **`RandomNumberGenerator` for anything secret; `Random` for anything else.** The `Random` docs say so explicitly.
- **`Guid.NewGuid()` is not a secret**: at most 122 bits, a partially predictable v4 bit pattern, and the docs recommend against cryptographic use and point you at `RandomNumberGenerator`. RFC 9562 adds that UUIDs "MUST NOT be used as security capabilities". `Guid.CreateVersion7()` is worse — it embeds a timestamp.
- **Hash high-entropy secrets with SHA-256, not a KDF.** There is no wordlist for a 256-bit random value, so slowing the hash costs you throughput and buys nothing.
- **Data Protection defaults**: AES-256-CBC + HMACSHA256, 512-bit master key, 90-day key lifetime, 2-day activation delay, ~24-hour key ring refresh, purposes derive isolated subkeys. Created/active/expired keys all decrypt; revoked ones do not; deleting a key is irreversible data loss.
- **Multi-instance without a shared key ring means random logouts and antiforgery failures.** You need `PersistKeysTo*` *and* `SetApplicationName` *and* `ProtectKeysWith*` — because naming an explicit store deregisters at-rest key encryption. Sticky sessions masking the symptom is a diagnostic, not a fix.
- **TLS protects one hop, in transit.** It terminates at the load balancer, it does not touch backups, logs or the database, and "we use HTTPS" answers a different question from "how do you store this at rest".

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~20-25 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once does not make you interview-ready, and in security material a half-remembered answer is worse than none — it produces confident wrong recommendations. Cover the answers, write them cold, then check. Where a drill quotes a number, learn the source alongside the number.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — Encoding vs hashing vs encryption

> **Q**: What's the difference between encoding, hashing and encryption?
>
> **A**: **Encoding** is reversible with no key — Base64, hex, URL-encoding. It exists to make bytes survive a transport that can't carry them, and it is not a security control, because anyone who can see the encoded value can decode it. **Hashing** is one-way with no key: fixed-size output, no "unhash", you verify by re-computing and comparing. **Encryption** is reversible *with* a key: the security lives entirely in the key, and everything else is assumed public. One-line test: if the operation has no key and someone claims it provides confidentiality, they are wrong.
>
> **Cross-Q**: Where does an HMAC fit in that taxonomy?
>
> **A**: It is a **keyed hash** — one-way like a hash, but with a key like encryption, and it provides *authenticity* rather than confidentiality. The distinction that matters: a plain hash tells you "this hasn't changed since somebody hashed it", which is worthless if the attacker can rewrite the stored digest as well as the data. An HMAC tells you "this hasn't changed since someone holding the key hashed it". So it belongs in the hashing column structurally, but in the security model it does a job neither plain hashing nor encryption does.
>
> **Cross-Q²**: A colleague says "we base64-encode the token before putting it in the URL, so it's protected." Correct them precisely.
>
> **A**: Two separate things are being conflated. Base64url in a URL is **correct and necessary** — the standard Base64 alphabet contains `+`, `/` and `=`, all of which are meaningful in a URL, so encoding is a genuine transport fix. But it contributes nothing to protection: no key is involved and any observer decodes it in one command. If the token in that URL is a bearer capability, the controls that matter are entropy (256 bits from `RandomNumberGenerator`), short expiry, single use, storing only the hash server-side, and keeping URLs with query strings out of logs and `Referer` headers. The encoding is orthogonal to every one of those.

### Drill 2 — Why not SHA-256 for passwords

> **Q**: Why can't you store passwords as SHA-256?
>
> **A**: Because SHA-256 is designed to be fast, and the threat model is an offline attacker who has the whole table and wants to test candidate passwords. Human-chosen passwords come from a small, predictable distribution — a wordlist plus mutations, not 2²⁵⁶ — so the attacker's success is bounded by their *guess rate*, and a fast hash maximises it. A password KDF deliberately spends CPU (and, for Argon2/scrypt, memory) per guess, so the attacker's rate collapses while the honest server pays the cost once per login.
>
> **Cross-Q**: We salt our SHA-256. Does that fix it?
>
> **A**: No. A salt fixes a *different* problem. It kills precomputation — rainbow tables are built for unsalted hashes — and it removes cross-account correlation, so identical passwords no longer produce identical stored values. Both are real wins and you should salt regardless. But the salt does nothing to the attacker's per-guess *cost*: they still compute SHA-256 as fast as their hardware allows, just once per (user, candidate) pair instead of once per candidate. Against a targeted attack on one high-value account, salting changes almost nothing. The missing property is the work factor.
>
> **Cross-Q²**: What exactly does memory-hardness buy that iteration count doesn't?
>
> **A**: It attacks the attacker's *hardware advantage* rather than just their time. Iteration count scales linearly in CPU time for everyone, including someone with a rack of GPUs — you slow them down by the same factor you slow yourself down. GPUs and ASICs are extraordinarily good at massively parallel SHA-256 because arithmetic units are cheap to replicate. Memory is not: giving ten thousand parallel cores 19 MiB each is expensive in a way that giving them another arithmetic unit is not. So a memory-hard KDF narrows the gap between the defender's commodity server and the attacker's specialised hardware, which iteration count alone cannot do. That is why OWASP states the Argon2id recommendation memory-first — `m=19456` (19 MiB), `t=2`, `p=1` as the minimum.

### Drill 3 — What ASP.NET Core Identity actually does

> **Q**: What algorithm does ASP.NET Core Identity use to hash passwords, out of the box?
>
> **A**: PBKDF2 — not bcrypt, not Argon2. Specifically the V3 format in `PasswordHasher<TUser>`: **PBKDF2 with HMAC-SHA512, a 128-bit salt, a 256-bit subkey, and a default of 100,000 iterations**. The stored value is `{ 0x01, prf, iteration count, salt length, salt, subkey }` with the integers big-endian; the leading `0x01` is the format marker that distinguishes V3 from the older V2 (`0x00`, PBKDF2 with HMAC-SHA1, 1,000 iterations). Verification on .NET Core uses `CryptographicOperations.FixedTimeEquals`.
>
> **Cross-Q**: Is 100,000 iterations enough?
>
> **A**: It is below the current OWASP recommendation, and being able to say that with both numbers attributed is the point. OWASP's Password Storage Cheat Sheet lists **220,000 iterations for PBKDF2-HMAC-SHA512**; Identity's `PasswordHasherOptions.IterationCount` documents a **default of 100,000**. So raising it is a one-line configuration change and a reasonable thing to do on any system you own. The caveat is that iteration count is meant to be tuned against your own hardware and your own latency budget — the OWASP figure is a floor, not a target, and you should measure rather than quote.
>
> **Cross-Q²**: You raise `IterationCount` in config. What happens to the 400,000 existing hashes?
>
> **A**: Nothing, and that is by design. Every stored V3 hash carries its own iteration count inside the payload, so existing hashes continue to verify at whatever count produced them. Only new hashes use the new value. The migration path is `PasswordVerificationResult.SuccessRehashNeeded` — documented as "password verification was successful however the password was encoded using a deprecated algorithm and should be rehashed and updated". A successful login is the only moment you hold the plaintext, so that is where you re-hash and update the row. `UserManager.CheckPasswordAsync` does this for you; a custom store has to do it explicitly. Practical addition: track the percentage still on old parameters and force a reset for the tail, or dormant accounts keep the weak parameters indefinitely.

### Drill 4 — Salt placement and secrecy

> **Q**: Why is the salt stored in the same row as the hash? Doesn't that hand it to the attacker?
>
> **A**: Yes, and it does not matter, because the salt is a **uniqueness** device rather than a **secrecy** device. Its job is to guarantee that two users with the same password produce different stored values. That kills precomputed tables (they are built per-salt, so one table per user is no saving over just attacking each user) and it kills cross-account and cross-site correlation of identical passwords. None of those benefits depend on the attacker not knowing the salt, and verification needs the salt, so the only place it can live is beside the hash.
>
> **Cross-Q**: Then what is a pepper, and why would you add one?
>
> **A**: A pepper is a **site-wide secret** mixed in *in addition to* the per-user salt, and OWASP's phrasing is the useful one: it is "shared between stored passwords" and "should not be stored along with the generated hash". It lives in a KMS, HSM or environment secret. The value is scenario-specific: it defends against an attacker who obtains only the database — SQL injection, a leaked backup — because without the pepper they cannot even begin offline cracking. It does nothing against an attacker who has full application compromise, since the app must be able to read it. Treat it as defence in depth with a real cost: peppers are hard to rotate, because rotating one invalidates every stored hash unless you version them.
>
> **Cross-Q²**: How would you rotate a pepper without a mass password reset?
>
> **A**: Version it and re-wrap opportunistically. Store a pepper id alongside each hash; verify with the pepper that id names; on a successful login, re-hash with the current pepper and update the id. That is the same `SuccessRehashNeeded` shape as an iteration-count change. If you need the whole table moved without waiting for logins, the offline option is to store `KDF_new(pepper_new, KDF_old_output)` — a nested construction you apply in one pass — at the cost of a composite format you carry until each user next signs in. Both are workable; both need the version marker, which is why "make the stored format self-describing" is the rule that keeps paying.

### Drill 5 — Timing-safe comparison

> **Q**: Why can't you compare an HMAC with `==`?
>
> **A**: Because `==` on strings and `SequenceEqual` on arrays return as soon as they find a mismatch, so the time taken is proportional to how many leading bytes matched. An attacker who can submit many candidate signatures and measure response time learns the prefix length, and can then discover the tag one byte at a time — turning a 2²⁵⁶ search into roughly 32 × 256 attempts. `CryptographicOperations.FixedTimeEquals` XORs every byte into an accumulator and checks it once at the end, so the loop always runs to completion regardless of the values.
>
> **Cross-Q**: What exactly does `FixedTimeEquals` guarantee, and what does it not?
>
> **A**: The documented guarantee is that it determines equality "in an amount of time that depends on the length of the sequences, but not their values". So it hides the *values* and not the *length* — if the two spans differ in length it can return early, and that leak is real. For a fixed-size tag (HMAC-SHA256 is always 32 bytes) that is a non-issue. For a variable-length secret it is not, and the fix is to hash both sides to a fixed size and compare the digests. It also protects only the comparison: if you decoded the attacker's hex with something that early-exits on invalid input, or did a database lookup keyed on the secret before comparing, the leak has just moved.
>
> **Cross-Q²**: Is there a single call that does compute-and-compare for an HMAC?
>
> **A**: Yes, but check your target framework. `CryptographicOperations.VerifyHmac(HashAlgorithmName, ReadOnlySpan<byte> key, ReadOnlySpan<byte> source, ReadOnlySpan<byte> hash)` returning `bool` is on Microsoft Learn with a moniker list of **net-11.0 only**. On .NET 10 — which is what this guide targets — you write the two steps yourself: `HMACSHA256.HashData(key, source)` then `FixedTimeEquals`. Naming the version gate rather than just naming the API is the part that shows you read the docs rather than an autocomplete list.

### Drill 6 — AEAD and nonces

> **Q**: You need to encrypt a field in your database. What do you reach for and why?
>
> **A**: `AesGcm` — AES in Galois/Counter Mode, an AEAD. It gives confidentiality and integrity from one primitive and one key, so there is no second step to forget. Construct it with an explicit tag size (`new AesGcm(key, 16)`), use a **12-byte random nonce per message** (`AesGcm.NonceByteSizes` is documented as 12 bytes / 96 bits), and pass associated data that binds the ciphertext to its context — tenant id, column name, format version. Store nonce ‖ tag ‖ ciphertext, plus a key id so you can rotate.
>
> **Cross-Q**: Why does the constructor take a tag size at all? The old one didn't.
>
> **A**: The tag-size-less constructors were **obsoleted as SYSLIB0053 in .NET 8**, and the reason is a genuine weakness. AES-GCM natively produces a 16-byte tag, and shorter tags are truncations of it. The old `AesGcm` inferred the expected tag length from whatever tag you handed to `Decrypt` — so if you took the tag from attacker-supplied input and passed it through, an attacker could supply a 12-byte tag and you would validate against 12 bytes, reducing the forgery difficulty. Declaring the size up front means `Encrypt` and `Decrypt` enforce it and a short tag is rejected rather than accepted.
>
> **Cross-Q²**: What actually happens if you reuse a nonce with the same key?
>
> **A**: It is a full break, not a degradation, and it is worth being emphatic. GCM is a counter mode: the nonce plus key produce a keystream that is XORed with the plaintext. Encrypt two messages under the same (key, nonce) and XORing the two ciphertexts cancels the keystream entirely, yielding the XOR of the two plaintexts — recoverable with any structure or known-plaintext. Worse, nonce reuse in GCM enables recovery of the authentication subkey, after which the attacker can **forge valid tags** for that key. So you lose confidentiality *and* integrity. That is why the advice is a random 12-byte nonce per message rather than a counter: counters look tidy and then get reset by a pod restart, a database restore, or a second replica starting at zero.

### Drill 7 — CBC without a MAC

> **Q**: What's wrong with `Aes.Create()` in CBC mode, encrypting and storing the result?
>
> **A**: It provides confidentiality and nothing else, and "nothing else" has two sharp edges. **Malleability**: in CBC each ciphertext block is XORed into the next block's decryption, so flipping a bit in ciphertext block *n* flips the corresponding plaintext bit in block *n+1* — an attacker who knows the plaintext structure can make targeted, predictable edits without the key. **Padding oracles**: CBC needs padding, and if your decrypt path distinguishes "bad padding" from "bad content" by exception, message, status code or *timing*, an attacker can decrypt arbitrary ciphertext a byte at a time without ever learning the key.
>
> **Cross-Q**: Can you fix it by catching all exceptions and returning a single generic error?
>
> **A**: Not reliably, and this is the important part. You can close the *explicit* signals — exception types, messages, status codes — but a padding failure and a content failure typically take different amounts of work, so timing remains a channel, and it is very hard to equalise by hand. The structural fix is **encrypt-then-MAC**: MAC the ciphertext (plus the IV and any context) with a separate key, and on the way back **verify the MAC before you decrypt at all**. If verification fails you never enter the decryption code, so there is no oracle to probe. Order matters — MAC-then-encrypt forces you to decrypt before you can check, which is precisely the shape you were trying to avoid.
>
> **Cross-Q²**: ASP.NET Core Data Protection defaults to AES-256-CBC. Isn't that the thing you just told me not to do?
>
> **A**: No — the default is **AES-256-CBC for confidentiality *and* HMACSHA256 for authenticity**, derived from a 512-bit master key per payload. That is encrypt-then-MAC, assembled correctly, with two derived subkeys and a comparison the framework gets right. The thing to avoid is CBC *alone*. This is actually the best argument for using Data Protection: it is exactly the construction you would otherwise hand-roll, with the parts you would be most likely to get wrong already done. If you are writing your own, `AesGcm` is simpler than reproducing it.

### Drill 8 — Randomness and Guid

> **Q**: How do you generate a secure token?
>
> **A**: `RandomNumberGenerator.GetBytes(32)` for 256 bits of entropy, then encode for transport — `Base64Url.EncodeToString` on .NET 9+, or `Convert.ToHexString`. 128 bits is the floor for anything long-lived; 256 costs sixteen extra bytes and removes the argument. Store only a SHA-256 of the token server-side, scope it to a subject, expire it, and invalidate it on use.
>
> **Cross-Q**: What's wrong with `Guid.NewGuid().ToString()`? It's random and it's unique.
>
> **A**: The .NET documentation answers this directly, which is the best possible citation. Three points. **One**: it is at most **122 bits of entropy regardless of platform**, because a v4 UUID spends six bits on version and variant markers — and the docs note that some cryptographic policies set a 128-bit minimum, which a GUID structurally cannot meet. **Two**: the docs say a v4 UUID "has a partially predictable bit pattern" and therefore "cannot serve as a proper cryptographic pseudo-random function". **Three**: on non-Windows platforms the CSPRNG guarantee only holds **from .NET 6 onward** — before that "the entropy is not guaranteed to be generated by a CSPRNG". The docs close with the recommendation to use `RandomNumberGenerator` instead. At the spec level, RFC 9562's Security Considerations say implementations "SHOULD NOT assume that UUIDs are hard to guess" and "MUST NOT be used as security capabilities (identifiers whose mere possession grants access)" — which is exactly what a reset link is.
>
> **Cross-Q²**: What about `Guid.CreateVersion7()` in .NET 9+ — that's newer, is it better?
>
> **A**: Better for databases, **worse for secrets**. A v7 UUID embeds a Unix-epoch millisecond timestamp in its high bits so that IDs sort by creation time, which is excellent for B-tree index locality and terrible for unpredictability — a large, structured portion of the value is derived from the clock and is therefore guessable by anyone who knows roughly when it was created. RFC 9562 says as much: if a UUID is needed for any security operation, v4 "SHOULD be utilized", and even then not as a capability. So `CreateVersion7()` is a good default for primary keys and a bad one for tokens. Using it as a database id *and* `RandomNumberGenerator` for the secret, as two separate columns, is the right shape.

### Drill 9 — Hashing an API key

> **Q**: You issue API keys to customers. How do you store them?
>
> **A**: Generate 256 bits with `RandomNumberGenerator.GetBytes(32)`, show the encoded key to the customer exactly once, and store only `SHA256.HashData(raw)` — indexed. Verification hashes the presented key and does an indexed lookup by hash. Also store a short display prefix so the UI can show "sk_live_a7Fq…", plus tenant, created, expires and revoked columns.
>
> **Cross-Q**: Why SHA-256 and not bcrypt? You just spent five minutes telling me fast hashes are bad.
>
> **A**: Because the reason fast hashes are bad for passwords does not apply. A KDF's whole purpose is to make each guess expensive, and guessing is only a threat when the search space is small — human-chosen passwords come from a wordlist. A 256-bit value generated by a CSPRNG has no wordlist and no structure; there is nothing to guess. Slowing the hash therefore buys zero security and costs you a KDF on **every single API request**, which is a self-inflicted latency and capacity problem. The rule is entropy-driven: **low-entropy secret → slow KDF; high-entropy secret → fast hash.**
>
> **Cross-Q²**: Why hash at all rather than encrypt, given support would like to read a key back to a customer?
>
> **A**: Because encryption means you retain the ability to recover every customer's live credential, so a database export plus a leaked key is a total compromise — and application compromise is enough on its own, since the app must be able to decrypt. Hashing removes the capability entirely: there is no key in your system that turns the stored value back into a credential. The support workflow that wants read-back is the thing to change, not the storage. "You can't have it back, generate a new one" is what every provider you have ever integrated with does, and it is why. The operational tell that you got it right: a hash also gives you an indexed equality lookup, so verification is a single index seek with no secret comparison in application code at all.

### Drill 10 — Data Protection in a multi-instance deployment

> **Q**: You move an ASP.NET Core app from one VM to three replicas and users start getting randomly logged out. What happened?
>
> **A**: No shared Data Protection key ring. Authentication cookies are protected with `IDataProtector`, and by default the system *guesses* where to store keys: Azure App Service uses a network-backed `%HOME%\ASP.NET\DataProtection-Keys`; a machine with a user profile uses `%LOCALAPPDATA%`, DPAPI-encrypted on Windows; IIS uses an ACLed HKLM registry key. If none of those apply — the plain container case — the documented behaviour is that "keys aren't persisted outside of the current process. When the process shuts down, all generated keys are lost." So each replica has its own in-memory key ring and cannot decrypt its peers' cookies. Random logouts is exactly the expected symptom.
>
> **Cross-Q**: The team turned on sticky sessions and the problem went away. Is that a fix?
>
> **A**: No — it is a diagnostic. If session affinity fixes a logout bug, you have proved the instances disagree about keys. Affinity papers over steady-state traffic and fails the moment the pod a user is pinned to is replaced: every rolling deploy, every autoscale-down, every crash. It also blocks you from ever load-balancing properly. The real fix is three calls: `PersistKeysTo*` for a shared durable store, `SetApplicationName` so every instance uses the same application discriminator, and `ProtectKeysWith*` for at-rest key encryption.
>
> **Cross-Q²**: Why is `ProtectKeysWith*` in that list — the default was encrypting keys at rest already, wasn't it?
>
> **A**: It was, and specifying an explicit store turns it off. The documentation warns about this twice: "If you specify an explicit key persistence location, the data protection system deregisters the default key encryption at rest mechanism, so keys are no longer encrypted at rest." So the moment you add `PersistKeysToFileSystem` or `PersistKeysToAzureBlobStorage` to fix the sharing problem, you have silently created a plaintext key ring — and that key ring protects every auth cookie in the system. Pair it with `ProtectKeysWithAzureKeyVault`, `ProtectKeysWithCertificate` or `ProtectKeysWithDpapi`. A related trap in the same family: if you pick Redis as the shared store, the docs note Redis "doesn't persist data by default when restarting", so a cache restart discards the key ring and invalidates everything — enable persistence or choose a durable store.

### Drill 11 — Purpose strings

> **Q**: What is the `purpose` parameter on `CreateProtector` for?
>
> **A**: Isolation, not naming. The documentation calls it "inherent to the security of the data protection system" because the purpose is fed into subkey derivation: two protectors with different purposes derive different subkeys from the same key ring and therefore cannot read each other's payloads. So a share-link token can never be replayed as a bearer token, even though both were minted by the same application with the same master key. The convention is namespace-plus-type-plus-version — `Contoso.Security.BearerToken.v1` — so that a format change is automatically isolated from the old format.
>
> **Cross-Q**: Does the purpose string need to be secret?
>
> **A**: No — only unique. The docs are explicit: "The purpose string doesn't have to be secret. It should simply be unique in the sense that no other well-behaved component will ever provide the same purpose string." That is why using the consuming type's namespace works so well: it is already guaranteed unique within your application and it documents itself in the code.
>
> **Cross-Q²**: Can I put the username in the purposes chain for per-user isolation?
>
> **A**: Yes, and it is the recommended multi-tenant pattern — but **never as the sole element**, and the docs give the attack. If a secure-messaging component calls `CreateProtector([username])`, a user who registers the name `Contoso.Security.BearerToken` causes that component to mint payloads under the bearer-token purpose, which another component will then happily accept as authentication tokens. The correct form anchors the chain with a component-owned constant and appends the untrusted part: `CreateProtector(["Contoso.Messaging.SecureMessage", $"User: {username}"])`. Purposes are an ordered array and are compared ordinally element by element, so the hierarchy is real isolation, not string concatenation.

### Drill 12 — TLS boundaries

> **Q**: An auditor says customer data must be encrypted. Someone answers "the site is HTTPS-only". Is that an answer?
>
> **A**: It answers a different question. TLS gives confidentiality and integrity **in transit between two endpoints**, plus server authentication via the certificate chain. It says nothing about the database file, the nightly backup, the log pipeline, the cache, or the message bus — and in most deployments it does not even cover the whole path, because TLS terminates at a load balancer, CDN or ingress and the hop from there to the application is a separate concern. The question "can someone with a backup read this?" is answered by encryption at rest, hashing, or tokenisation — never by TLS.
>
> **Cross-Q**: Where is the most common place plaintext actually leaks in a TLS-everywhere system?
>
> **A**: The logging boundary. TLS ends where your code begins, so the request body arrives decrypted; structured logging that serialises the bound model will happily write a `password`, a card number or a bearer token into the log aggregator, where it is retained for months and searchable by anyone with a read seat. The second most common is exception detail — a stack trace or an EF Core parameter dump that includes the values. The control is redaction at the point of logging, plus a deny-list test in CI that fails the build if a known sensitive property name appears in a log template.
>
> **Cross-Q²**: If TLS terminates at the load balancer, what would you actually do about the hop behind it?
>
> **A**: First, find out — most teams cannot answer this, and the answer is usually "plaintext HTTP inside the VPC". Then choose based on threat model and cost: re-encrypt to the backend (the load balancer opens a second TLS connection to the pod), or adopt mTLS between services so both ends authenticate and the traffic is encrypted regardless of network position, typically via a service mesh so certificate rotation is not your problem. The reason to care is not only eavesdropping: an unauthenticated internal hop means anything that can reach the pod's port can impersonate the load balancer, so header-based trust — `X-Forwarded-For`, `X-Authenticated-User` — is forgeable. That is usually a bigger hole than the encryption.

### Drill 13 — HMAC vs signature

> **Q**: A partner needs to verify that a message came from us. HMAC or digital signature?
>
> **A**: It depends on how many parties there are and whether anyone needs to prove it to a third party. **HMAC** if it is a two-party relationship and you already have a way to share a secret — it is fast, small, and simple, which is why almost every webhook provider uses it. **A digital signature** if there are many verifiers (you do not want to distribute a shared secret to twelve consumers), if you cannot securely establish a shared secret, or if you need non-repudiation.
>
> **Cross-Q**: Say more about non-repudiation — why can't an HMAC give it?
>
> **A**: Because both parties hold the same key, so either could have produced the tag. If the partner claims you sent a message and you deny it, the tag proves nothing: the partner could have generated it themselves. With a signature, only the holder of the private key can produce a valid signature, so the verifier can demonstrate to a third party that the message came from the key holder. That is why code signing, certificate issuance and legally-significant documents use signatures and never MACs. The trade is cost and key management: signatures are slower and you now have a private key with a lifecycle.
>
> **Cross-Q²**: Your JWTs use HS256 and eleven services validate them. What is wrong with that?
>
> **A**: Every one of those eleven services can **mint** tokens, not just validate them, because with a symmetric key signing and verification are the same capability. So a single compromised downstream service — the least-maintained one, typically — is a full authentication bypass for the entire estate: it can issue a token for any user with any claims. Rotation is also an eleven-way coordinated change, which means it never happens. Moving to `RS256` or `ES256` fixes both: the issuer holds the private key, everyone else fetches the public key from a JWKS endpoint and can only verify. Blast radius drops from eleven services to one, and rotation becomes "publish a new JWKS entry and retire the old one" with an overlap window.

### Drill 14 — Choosing and rotating a key

> **Q**: You are encrypting a database column with AES-GCM. Where does the key come from and how do you rotate it?
>
> **A**: The key comes from a KMS or secret store — Key Vault, Secrets Manager, Vault — read at startup via a managed identity, never from source, config in the repo, or an image layer. Rotation requires one design decision made **before** the first row is written: store a **key id alongside every ciphertext**. New writes use the current key; reads look up the key the id names; old keys stay available for decryption. Without the id, rotation means re-encrypting the entire corpus atomically, which is why "we'll rotate later" reliably becomes "we never rotated".
>
> **Cross-Q**: What does associated data give you here that the key doesn't?
>
> **A**: It binds the ciphertext to its context, defeating a relocation attack that encryption alone does not touch. Suppose every row's NINO is encrypted with the same key. Without AAD, an attacker with write access to the database can copy tenant A's ciphertext into tenant B's row — they never decrypt anything, but tenant B now sees tenant A's data, and every authentication check passes because the ciphertext is genuinely valid. Passing `$"{tenantId}|nino|v1"` as associated data makes the tag depend on the tenant and the column, so the relocated ciphertext fails to authenticate. AAD is authenticated but not encrypted, which is exactly right for context that is not itself a secret.
>
> **Cross-Q²**: Your key was in a container image layer that got pushed to a public registry. What is the incident response?
>
> **A**: Treat every payload that key ever protected as compromised, and work in that order. **Contain**: revoke the key in the KMS so nothing can use it, and rotate to a new key immediately so new writes are safe. **Assess**: enumerate what that key protected and for how long — this is where a key id column earns its keep, because it tells you exactly which rows are affected instead of "all of them, probably". **Remediate**: re-encrypt affected data under the new key; for anything that was a *credential* rather than data, rotation is not enough and you must invalidate — force password resets, revoke API keys, invalidate sessions. **Prevent**: the key was in an image layer, so the gap is build-time secret scanning and a policy that images never contain secrets; move to runtime injection via managed identity. The thing not to do is rotate quietly and skip the assessment, because the exposure window is what determines the notification obligation.

---

</details>

---

## Cheat Sheet

- **The three-way distinction**: encoding = reversible, no key, **not a security control** · hashing = one-way, no key · encryption = reversible, keyed. Base64 is encoding.
- **JWT** = base64url segments + a signature. **Signed, not encrypted** — anyone reads the claims.
- **Base64 vs Base64Url**: `+ / =` vs `- _` and no padding. `System.Buffers.Text.Base64Url` is **.NET 9+**; `Convert.ToHexString` is **.NET 5+**.
- **Hash one-shots**: `SHA256.HashData` (.NET 5+) · `HMACSHA256.HashData(key, source)` (.NET 6+) · `CryptographicOperations.HashData(HashAlgorithmName, …)` (**.NET 9+**).
- **Passwords**: slow KDF + per-user salt stored beside the hash + self-describing format. Salt is unique, not secret. Pepper is site-wide and lives outside the DB.
- **OWASP floors** (re-check them): Argon2id `m=19456, t=2, p=1` · bcrypt cost ≥ 10 · PBKDF2-HMAC-SHA256 600,000 · **PBKDF2-HMAC-SHA512 220,000** · scrypt `N=2^17, r=8, p=1`. bcrypt truncates at **72 bytes**.
- **Identity's `PasswordHasher<TUser>`**: V3 = PBKDF2 / **HMAC-SHA512** / 128-bit salt / 256-bit subkey / **100,000 iterations default** / format `{0x01, prf, iters, saltLen, salt, subkey}`. V2 = PBKDF2 / HMAC-SHA1 / 1,000 iters / `{0x00, salt, subkey}`. Migrate on `PasswordVerificationResult.SuccessRehashNeeded`.
- **Argon2 is not in the BCL** — [dotnet/runtime#19933](https://github.com/dotnet/runtime/issues/19933).
- **Integrity vs passwords**: SHA-256 is right for one and wrong for the other, and the reason is the same — it is fast.
- **HMAC** = keyed hash → authenticity. **No non-repudiation** (both sides hold the key). Never `H(key ‖ msg)` — length extension.
- **Compare with `CryptographicOperations.FixedTimeEquals`.** Time depends on **length**, not values — so it does not hide length. `VerifyHmac` is **.NET 11**.
- **AES-GCM**: `new AesGcm(key, 16)` (tag-size-less ctors obsolete, **SYSLIB0053**) · nonce **12 bytes**, random per message · tag 16 bytes · AAD binds context. **Nonce reuse = confidentiality *and* integrity break.**
- **CBC alone** = malleable + padding oracles. Encrypt-**then**-MAC, verify before decrypting, or just use GCM.
- **RSA vs ECDSA**: RSA verification cheap / signing expensive; ECDSA the reverse. Prefer `RSASignaturePadding.Pss` for new work. `DSASignatureFormat` distinguishes DER from JOSE's fixed-length r‖s. Never bulk-encrypt with RSA — hybrid.
- **Randomness**: `RandomNumberGenerator.GetBytes/Fill/GetInt32`, plus `GetHexString`/`GetItems<T>` (**.NET 8+**). `GetHexString(n)` counts **characters**, not bytes.
- **`Guid.NewGuid()` is not a secret**: ≤122 bits, partially predictable v4 pattern, CSPRNG guaranteed on non-Windows only from .NET 6; docs say use `RandomNumberGenerator`. RFC 9562: UUIDs "MUST NOT be used as security capabilities". `CreateVersion7()` is worse — timestamped.
- **Token at rest**: 256-bit random → store `SHA256` of it, index the hash, show the plaintext once.
- **Data Protection defaults**: AES-256-CBC + HMACSHA256 · 512-bit master key · **90-day** key lifetime (min 7) · 2-day activation delay · ~24h key ring refresh · created/active/expired all decrypt, revoked does not, **deleting is permanent**.
- **Multi-instance**: `PersistKeysTo*` **and** `SetApplicationName` **and** `ProtectKeysWith*` — explicit persistence **deregisters** at-rest key encryption. Redis needs persistence enabled. App Service slots do not share a key ring.
- **Purposes** derive isolated subkeys. Not secret, must be unique, versioned, hierarchical arrays. Never untrusted input alone.
- **TLS** = one hop, in transit, terminates at the LB. Not backups, not logs, not the database. "We use HTTPS" answers a different question from "how is this stored at rest".

---

## Walkthrough

<details>
<summary>📖 Click to expand — tracing an intermittent-logout incident to its root</summary>

A composite scenario assembled from the way this failure usually presents. The shape is what to rehearse, not the specific details.

**Symptom**: after migrating an ASP.NET Core storefront from a single VM to a three-replica container deployment, support tickets appear saying "I keep getting logged out". Not everyone, not consistently. The rate correlates loosely with traffic. Nothing in the application logs looks like an error — no exceptions, no failed authentications, just requests arriving with no authenticated principal.

**Diagnosis chain**:

1. **Reproduce with intent.** Log in, then hammer refresh. Roughly one request in three loses the session. One in three, with three replicas, is not a coincidence — it is a per-instance problem, and the ratio names the cause before anything else does.

2. **Check the warning-level logs, not just errors.** The `Microsoft.AspNetCore.DataProtection` category is emitting warnings about being unable to unprotect a payload, and about the key ring not containing a valid default key. Nobody had looked, because the dashboards filtered to Error and above.

3. **Ask where the keys live.** The image is a plain `mcr.microsoft.com/dotnet/aspnet` base with no writable user profile, no IIS, not App Service. That is case 4 of the documented storage heuristic: *"If none of these conditions match, keys aren't persisted outside of the current process. When the process shuts down, all generated keys are lost."* Each replica generated its own key ring at startup.

4. **Confirm the mechanism.** The authentication cookie is a Data Protection payload. Replica A protects it with A's key; the next request load-balances to B; B has never seen that key and `Unprotect` throws; the cookie middleware treats an unreadable cookie as "no cookie" and the user is anonymous. There is no error because *this is the designed behaviour* for a cookie that cannot be validated — a tampered cookie should also produce exactly this outcome.

5. **Note what the previous architecture was hiding.** On the single VM, the app ran under a Windows service account with a user profile, so keys landed in `%LOCALAPPDATA%\ASP.NET\DataProtection-Keys`, DPAPI-encrypted, and survived restarts. The bug was latent for years; containerisation removed the accident that had been protecting them.

**The wrong turn taken first**: session affinity was enabled at the ingress, and the tickets stopped. This was recorded as the fix. Six weeks later a rolling deploy signed out the entire user base at once, because affinity cannot pin a user to a pod that no longer exists. **Sticky sessions making a logout bug disappear is a diagnostic result, not a remedy** — it proves the instances disagree about keys.

**Root cause**: no shared, durable Data Protection key ring across replicas.

**Fix**:

```csharp
// Before — nothing. AddDataProtection() was never called; the framework's
// implicit registration used the storage heuristic, which had no answer.

// After
builder.Services.AddDataProtection()
    .PersistKeysToAzureBlobStorage(new Uri(cfg["DataProtection:BlobUri"]!), credential)
    .SetApplicationName("contoso-storefront")
    .ProtectKeysWithAzureKeyVault(new Uri(cfg["DataProtection:KeyId"]!), credential);
```

Three lines, three distinct jobs:

- `PersistKeysToAzureBlobStorage` — a durable store every replica reads and writes, so there is one key ring.
- `SetApplicationName` — sets `DataProtectionOptions.ApplicationDiscriminator`. Without it, the discriminator derives from the content root path, which differed between the old VM and the container. Two deployments of the same application would otherwise refuse to read each other's payloads even sharing a store.
- `ProtectKeysWithAzureKeyVault` — because naming an explicit store **deregisters the default at-rest key encryption**. Skipping this would have swapped a sharing bug for a plaintext-key-ring bug, and the second is worse: the key ring protects every authentication cookie in the system.

**Deployment note that mattered**: the fix could not be shipped as a straight cutover. The new configuration starts a fresh key ring in blob storage, so every existing cookie — protected by a per-pod in-memory key that is about to disappear — becomes unreadable. Everyone gets logged out once. That was scheduled for a low-traffic window and announced, rather than discovered.

**Post-mortem actions**: a startup health check that resolves `IKeyManager`, calls `GetAllKeys()` and fails readiness if the ring is empty or unshared, so the misconfiguration cannot reach production silently; Data Protection warnings promoted into the alerting pipeline; and an added line in the containerisation runbook — *"if the app uses cookie auth, antiforgery or TempData, it needs an explicit key ring before it is scaled past one instance."*

**What to say in an interview**: "The tell was the ratio — one failure in three with three replicas points at per-instance state, not at the load balancer. Data Protection's key storage is a heuristic, and the container case falls through to 'keys live in memory and die with the process'. The fix is three calls, and the third one — `ProtectKeysWith*` — exists because specifying an explicit store turns off at-rest key encryption. Most write-ups of this bug stop after the first two."

</details>

---

## Self-Test

<details>
<summary>1. A code review shows <code>var encrypted = Convert.ToBase64String(apiKeyBytes);</code> written to a config file. What is wrong, and what do you say in the review?</summary>

Nothing is encrypted. Base64 is an encoding — reversible by anyone, no key involved — so the API key is stored in plaintext with an extra step. The variable name is the actual defect, because it will convince the next reader that the value is protected.

The review comment should separate two things. **Naming**: rename to `encodedApiKey` at minimum, so nobody inherits the misconception. **Storage**: the key should not be in a config file at all. Move it to a secret store read at startup via a managed identity, or — if this is a key your system *issues* rather than *consumes* — store only `SHA256.HashData(raw)` and never keep the plaintext.

The generalisation worth stating: encoding never appears in a threat model as a mitigation. If the answer to "how is this protected" is "we base64 it", the answer is "it isn't". Base64 is entirely correct as transport packaging for something already protected — a ciphertext, a signature — and never as the protection itself.
</details>

<details>
<summary>2. Trade-off: <code>PasswordHasher&lt;TUser&gt;</code> with a raised iteration count, versus adding an Argon2id package. Argue both sides.</summary>

**In-box PBKDF2.** Identity's V3 format is PBKDF2 with HMAC-SHA512, a 128-bit salt, a 256-bit subkey and a default of 100,000 iterations, and `PasswordHasherOptions.IterationCount` raises it in one line. PBKDF2 is on OWASP's list, is FIPS-friendly, adds no third-party dependency to the authentication path, and the migration story (`SuccessRehashNeeded`) is already built. The weakness is real though: PBKDF2 is CPU-hard only, so it does not blunt the GPU/ASIC advantage the way a memory-hard KDF does. Note also that the 100,000 default sits below OWASP's current 220,000 floor for the SHA-512 variant, so shipping the default unchanged is itself a finding.

**Third-party Argon2id.** Memory-hardness attacks the attacker's hardware advantage rather than only their time, which is why OWASP lists Argon2id first. It is the better primitive. The cost is that Argon2 is not in the BCL ([dotnet/runtime#19933](https://github.com/dotnet/runtime/issues/19933)), so you are adding an unaudited-by-Microsoft dependency to the most security-sensitive path in the application, and you own its patching, its pinning and its supply-chain risk. You also need to tune `m`, `t` and `p` against your own hardware, and getting memory parameters wrong can make login a memory-pressure problem under concurrency.

**Where it actually lands.** For most business applications, raised-iteration PBKDF2 behind `IPasswordHasher<TUser>` is the right call — defensible, boring, no new dependency. Argon2id earns its dependency when the password store is a genuinely high-value target and someone owns the library's lifecycle. The third option beats both when it is available: federate to an identity provider and never store a password. What is *not* defensible either way is shipping the 100,000 default with no measurement and no rehash path.
</details>

<details>
<summary>3. You find <code>if (signature == expectedSignature)</code> in a webhook handler. Explain the attack concretely enough that a sceptical colleague acts on it.</summary>

String equality returns as soon as it finds a differing character, so the time taken is proportional to the length of the matching prefix. That difference is small but measurable, and it is *systematic* — averaging over many requests pulls it out of the noise.

Concretely: the attacker sends a request with signature `00000…`, then `01000…`, then `02000…`, through all 256 values of the first byte, timing each. The value whose response is consistently slowest is the correct first byte, because it is the only one where the comparison proceeded to the second byte. Fix the first byte, repeat for the second. A 32-byte HMAC falls in roughly 32 × 256 measured requests rather than 2²⁵⁶ guesses.

The fix is one line: `CryptographicOperations.FixedTimeEquals(computed, provided)`, which XORs every byte into an accumulator and checks it once, so the loop always runs to completion.

Two things to add for the sceptic. First, "we're behind a VPN so there's too much jitter" gets it backwards — a low-latency internal network *removes* noise and makes the attack easier, not harder. Second, know the limit of what you are buying: `FixedTimeEquals` is documented as taking time proportional to *length* but not to *values*, so it does not hide a length mismatch. For a fixed-size tag that is fine; for variable-length secrets, hash both sides first.
</details>

<details>
<summary>4. Analyse this: a password reset emails a link containing <code>Guid.NewGuid()</code>, valid 24 hours, stored in the database as-is. List every defect and fix each.</summary>

**Defect 1 — the token is a GUID.** At most 122 bits of entropy, with a partially predictable v4 bit pattern that the .NET docs say "cannot serve as a proper cryptographic pseudo-random function"; the docs recommend `RandomNumberGenerator` instead, and RFC 9562 says UUIDs "MUST NOT be used as security capabilities (identifiers whose mere possession grants access)" — which is exactly what this link is. *Fix*: `RandomNumberGenerator.GetBytes(32)`, encoded with `Base64Url`.

**Defect 2 — the token is stored in plaintext.** Anyone with read access to the database, a backup, or a log of that table can reset any pending account. *Fix*: store `SHA256.HashData(raw)` and look up by hash. Fast hashing is correct here because a 256-bit random value has no wordlist to guess.

**Defect 3 — 24-hour validity.** A long window on a full account-takeover capability. *Fix*: 15 minutes, and invalidate on use.

**Defect 4 — no evident single-use or invalidation.** Nothing described marks the token consumed, so it works repeatedly until it expires, and issuing a new one does not kill the old. *Fix*: mark consumed inside the same transaction as the password change, and invalidate all outstanding tokens for that user on issue and on success.

**Defect 5 — the token is the whole authorisation.** Nothing binds it to the user, so a lookup that matches only on token value is one bug away from resetting the wrong account. *Fix*: store the subject with the hash and verify both.

**Defect 6 — it is in a URL.** URLs land in server access logs, proxy logs, browser history, and the `Referer` header if the reset page loads any third-party resource. *Fix*: strip query strings from access logs, set a `Referrer-Policy`, and prefer a POST-with-token form over a bare GET link where the UX allows.

**Defect 7 — no rate limiting mentioned.** Even a strong token wants a ceiling on consume attempts, and the *request* endpoint needs one too or it becomes an email-bombing and enumeration vector. *Fix*: rate-limit both, and return an identical response whether or not the address exists.
</details>

<details>
<summary>5. Explain what breaks, and in what order, if a team encrypts with AES-CBC and no MAC — and why "we catch all exceptions and return 400" does not save them.</summary>

**Integrity breaks first, silently.** CBC gives confidentiality only. Because each ciphertext block is XORed into the next block's decryption, flipping a bit in ciphertext block *n* flips the corresponding plaintext bit in block *n+1* (block *n* itself becomes garbage). An attacker who knows the plaintext layout can make targeted edits without the key: flip a flag, change a sign, corrupt a field they want to fail open. Nothing detects this, because there is nothing in the scheme whose job is to detect it.

**Confidentiality breaks second, through the oracle.** CBC requires padding, and the decrypt path must handle invalid padding somehow. If an attacker can distinguish "padding invalid" from "padding valid but content wrong", they can decrypt arbitrary ciphertext a byte at a time — the classic padding-oracle attack — without ever recovering the key.

**Why uniform error handling is not enough.** You can equalise the *explicit* signals: same exception swallowed, same status code, same body. But the two paths do different amounts of work — one aborts during unpadding, the other proceeds through content processing — so they take different amounts of time, and timing is a signal. Equalising that by hand is genuinely hard and fragile under refactoring; it is not a thing to defend in a review.

**The structural fix is ordering, not error handling.** Encrypt-then-MAC: compute a MAC over IV ‖ ciphertext with a *separate* key, and on the way back verify the MAC with `FixedTimeEquals` **before** attempting decryption. If it fails you never enter the decryption code, so there is no oracle to probe and no timing difference to measure. MAC-then-encrypt does not work, because you must decrypt in order to check.

**And the practical answer**: do not build this. Use `AesGcm`, which is encrypt-then-MAC done correctly in one API with one key. If you cannot — an external format mandates CBC — then two keys, MAC over IV ‖ ciphertext, verify first. Worth noting that ASP.NET Core Data Protection's own default is AES-256-CBC **plus HMACSHA256**, which is this construction assembled correctly by the framework; the thing that is broken is CBC *alone*.
</details>

---

## Cross-References

- **[Security & Authentication](09-security.md)** — JWT validation, OWASP mapping, the auth pipeline that consumes everything on this page.
- **[API Security](../../02-api-development/04-api-security.md)** — input validation, rate limiting, supply-chain and audit-logging controls that sit around cryptography rather than inside it.
- **[Authentication & Authorization](../../02-api-development/02-authentication-and-authorization.md)** — token issuance and validation, JWKS, refresh-token handling.
- **[Advanced Auth](../../02-api-development/17-advanced-auth.md)** — OAuth 2.1 / OIDC flows, PKCE, mTLS, sender-constrained tokens.
- **[Configuration](15-configuration.md)** — where keys and connection strings come from: user secrets, environment variables, Key Vault providers.
- **[Dependency Injection](02-dependency-injection.md)** — registering `IDataProtectionProvider`, keyed services for per-provider verifiers, and the lifetime rules for anything holding key material.
- **[Data Access](05-data-access.md)** — EF Core value converters, the natural seam for field-level encryption and blind indexes.
- **[Webhooks](../../02-api-development/09-webhooks.md)** — signature schemes, replay windows, and delivery semantics.
- **[Modern C#](12-modern-csharp.md)** — `Span<T>`, `stackalloc` and the span-based crypto overloads.
- **[.NET Version History](18-version-history.md)** — per-release BCL deltas when you need to check a moniker.

---

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

**Primary sources used for every factual claim on this page**

*Hashing, HMAC and comparison*

- [API: `CryptographicOperations`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.cryptographicoperations) — `FixedTimeEquals`, `ZeroMemory`, `HashData`, `HmacData`, `VerifyHmac`, `TryHashData`.
- [API: `CryptographicOperations.VerifyHmac`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.cryptographicoperations.verifyhmac) — moniker list is **net-11.0 only**, which is why this page does not recommend it for .NET 10.
- [API: `SHA256.HashData`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.sha256.hashdata) — .NET 5+ for the byte/span overloads, .NET 7+ for the `Stream` overloads.
- [API: `HMACSHA256.HashData`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.hmacsha256.hashdata) — .NET 6+ for byte/span, .NET 7+ for `Stream`.

*Passwords*

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) — Argon2id `m=19456, t=2, p=1` minimum; scrypt `N=2^17, r=8, p=1`; bcrypt work factor ≥ 10 and the 72-byte input limit with the `bcrypt(base64(hmac-sha384(...)))` pre-hash construction; PBKDF2 iteration counts (SHA-256 600,000 / SHA-512 220,000 / SHA-1 1,400,000); salt and pepper guidance.
- [API: `Rfc2898DeriveBytes.Pbkdf2`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.rfc2898derivebytes.pbkdf2) — .NET 6+ static one-shots; supported algorithms SHA1/SHA256/SHA384/SHA512; UTF-8 conversion of `string` and `ReadOnlySpan<char>` passwords.
- [API: `PasswordHasherOptions`](https://learn.microsoft.com/dotnet/api/microsoft.aspnetcore.identity.passwordhasheroptions) — "`IterationCount` … Default is 100,000"; "`CompatibilityMode` … Defaults to 'ASP.NET Identity version 3'".
- [`PasswordHasher.cs` — dotnet/aspnetcore](https://github.com/dotnet/aspnetcore/blob/main/src/Identity/Extensions.Core/src/PasswordHasher.cs) — the HASHED PASSWORD FORMATS comment block (V2 and V3 layouts), salt generation via `RandomNumberGenerator`, and the use of `CryptographicOperations.FixedTimeEquals` on .NET Core.
- [API: `PasswordVerificationResult`](https://learn.microsoft.com/dotnet/api/microsoft.aspnetcore.identity.passwordverificationresult) — `Failed` (0), `Success` (1), `SuccessRehashNeeded` (2) and its documented meaning.
- [dotnet/runtime#19933 — Add Argon2 support to System.Security.Cryptography](https://github.com/dotnet/runtime/issues/19933) — still an open API idea; Argon2 is not in the BCL.

*Symmetric and asymmetric*

- [API: `AesGcm`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.aesgcm) — constructors (tag-size-less ones marked Obsolete for net-8.0 through net-11.0), `Encrypt`/`Decrypt` signatures, `IsSupported`, `TagSizeInBytes`.
- [API: `AesGcm.NonceByteSizes`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.aesgcm.noncebytesizes) — "The nonce sizes supported by this instance: 12 bytes (96 bits)."
- [SYSLIB0053 — AesGcm should indicate the required tag size](https://learn.microsoft.com/dotnet/fundamentals/syslib-diagnostics/syslib0053) — the obsoletion rationale: tags are 12–16 bytes by truncation of a native 16-byte tag, and inferring the size from input let callers validate against the shortest tag.
- [API: `RSASignaturePadding`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.rsasignaturepadding) — `Pkcs1` and `Pss` are the only two modes.
- [API: `ECDsa`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.ecdsa) — `SignData`/`VerifyData`/`SignHash`/`VerifyHash` overloads taking `DSASignatureFormat`, and `GetMaxSignatureSize(DSASignatureFormat)`.

*Randomness*

- [API: `RandomNumberGenerator`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.randomnumbergenerator) — "Using the static members of this class is the preferred way to generate random values"; full static member list.
- [API: `RandomNumberGenerator.GetHexString`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.randomnumbergenerator.gethexstring) — net-8.0+; `stringLength` is a character count.
- [API: `RandomNumberGenerator.GetItems`](https://learn.microsoft.com/dotnet/api/system.security.cryptography.randomnumbergenerator.getitems) — net-8.0+.
- [API: `System.Random`](https://learn.microsoft.com/dotnet/api/system.random) — "To generate a cryptographically secure random number, such as one that's suitable for creating a random password, use one of the static methods in the `RandomNumberGenerator` class."
- [API: `Guid.NewGuid`](https://learn.microsoft.com/dotnet/api/system.guid.newguid) — the remarks quoted in full on this page: 122 bits of entropy, `CoCreateGuid` on Windows, CSPRNG on non-Windows only from .NET 6, "partially predictable bit pattern", "cannot serve as a proper cryptographic pseudo-random function", and the recommendation to use `RandomNumberGenerator`.
- [API: `Guid.CreateVersion7`](https://learn.microsoft.com/dotnet/api/system.guid.createversion7) — .NET 9+; uses `DateTimeOffset.UtcNow` as the Unix-epoch timestamp source and seeds `rand_a`/`rand_b` with random data.
- [RFC 9562 — Universally Unique IDentifiers (UUIDs)](https://www.rfc-editor.org/rfc/rfc9562.html) — Security Considerations: "Implementations SHOULD NOT assume that UUIDs are hard to guess… they MUST NOT be used as security capabilities"; UUIDv4 should use a CSPRNG; "If UUIDs are required for use with any security operation… then UUIDv4 SHOULD be utilized."

*Encoding*

- [API: `System.Buffers.Text.Base64Url`](https://learn.microsoft.com/dotnet/api/system.buffers.text.base64url) — net-9.0+ (also `Microsoft.Bcl.Memory` for downlevel); `'+'`→`'-'`, `'/'`→`'_'`.
- [API: `Convert.ToHexString`](https://learn.microsoft.com/dotnet/api/system.convert.tohexstring) — net-5.0+.

*Data Protection*

- [Data Protection key management and lifetime](https://learn.microsoft.com/aspnet/core/security/data-protection/configuration/default-settings) — the four-step storage heuristic (App Service `%HOME%`, user profile `%LOCALAPPDATA%` with DPAPI, IIS HKLM registry, then "keys aren't persisted outside of the current process"); deployment slots do not share a key ring; 90-day lifetime; **default algorithms AES-256-CBC + HMACSHA256** with a 512-bit master key; Docker volume / external provider guidance; the delete-keys warning and `IDeletableKeyManager`.
- [Key management in ASP.NET Core](https://learn.microsoft.com/aspnet/core/security/data-protection/implementation/key-management) — the created/active/expired/revoked lifecycle; created/active/expired all unprotect; activation `now + 2 days`, expiry `now + 90 days`; automatic rolling; key ring cache re-read approximately every 24 hours or on default-key expiry; minimum lifetime 7 days; "Deleting a key is truly destructive behavior."
- [Configure ASP.NET Core Data Protection](https://learn.microsoft.com/aspnet/core/security/data-protection/configuration/overview) — `SetDefaultKeyLifetime`, `SetApplicationName` → `ApplicationDiscriminator`, `PersistKeysToFileSystem` / `PersistKeysToAzureBlobStorage` / `PersistKeysToDbContext`, `ProtectKeysWithAzureKeyVault` / `ProtectKeysWithCertificate`, `UnprotectKeysWithAnyCertificate`, and the default-algorithm statement.
- [Key storage providers in ASP.NET Core](https://learn.microsoft.com/aspnet/core/security/data-protection/implementation/key-storage-providers) — the warning that an explicit persistence location "deregisters the default key encryption at rest mechanism"; the Redis-does-not-persist-by-default warning; registry and EF Core providers; custom `IXmlRepository`.
- [Purpose strings in ASP.NET Core](https://learn.microsoft.com/aspnet/core/security/data-protection/consumer-apis/purpose-strings) — purposes are "inherent to the security of the data protection system"; subkey derivation; not secret but unique; namespace-and-type convention with a version suffix; hierarchical arrays; the untrusted-input warning with the `Contoso.Security.BearerToken` example.
- [API: `ITimeLimitedDataProtector`](https://learn.microsoft.com/dotnet/api/microsoft.aspnetcore.dataprotection.itimelimiteddataprotector) — `Protect(byte[], DateTimeOffset)`, `Unprotect(byte[], out DateTimeOffset)`, the `ToTimeLimitedDataProtector()` and `Protect(…, TimeSpan)` extensions, and the "payload lifetimes be somewhat short" remark.

**Further reading**

- [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [OWASP Transport Layer Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html)
- [.NET cryptography model](https://learn.microsoft.com/dotnet/standard/security/cryptography-model)
- [Cryptographic obsoletions (`SYSLIB` diagnostics index)](https://learn.microsoft.com/dotnet/fundamentals/syslib-diagnostics/obsoletions-overview)
- [`System.Security.Cryptography` source tree — dotnet/runtime](https://github.com/dotnet/runtime/tree/main/src/libraries/System.Security.Cryptography)

_Last reviewed: 2026-08-18. The OWASP work factors move; re-verify them, and re-check any moniker list, before quoting a number from this page._

---

</details>
<!-- nav-footer-start -->

---

[← Previous: .NET Version History (.NET 7 → .NET 10)](18-version-history.md) · [↑ Back to top](#cryptography-hashing-and-encoding-in-net-10) · [Next: Concurrency & Parallelism →](20-concurrency-and-parallelism.md)

<!-- nav-footer-end -->
