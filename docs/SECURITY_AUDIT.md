# Application security review

Review date: 2026-11-11. Target: the working tree after 0.15.0, including the staged
relationship repair implementation. Related reports:
[relationships](DATABASE_RELATIONSHIP_AUDIT.md) and [concurrency](CONCURRENCY_AUDIT.md).

## Scope and confidence

Repository-wide inventory and searches covered application, companion, deployment
scripts and frontend sources. Manual tracing focused on authentication, resource
authorization, previews/history, billing approvals, uploads/rendering, companion
credentials and journals, update/backup/restore, and logging. Tests provide
regression evidence, not a security certification.

No production host, proxy configuration, actual user data, hardware, or external
penetration test was inspected. No comprehensive dependency-advisory scan was
completed. Findings below distinguish visible code behavior from potential
exploitation. Severity is practical prioritization, not an unsupported CVSS score.

## Findings

### S1 — Availability: blocking authorization and worker starvation

**Priority: high. Evidence: confirmed call paths; isolated deadlock-pattern
reproduction.** See C1–C3 in the concurrency report for affected functions.

Slow database access can stall the event loop. Bursts of mutations can exhaust
workers waiting for a shared lock while the lock holder's endpoint still needs a
worker. Authenticated users can generate mutation traffic; failed-login traffic
can separately contend with the global lock during password verification.
Existing login limits reduce, but do not eliminate, contention risk.

Mitigate the scheduling boundaries, then test concurrent requests and health
latency under forced database delay. Neither the successful access logs nor the
uploaded image dimensions establish that this caused the reported outage.

### S2 — Bootstrap administrator secret is written to logs

**Priority: medium, conditional on initial setup. Evidence: confirmed.**
`app/auth.py:initialize_auth` logs the contents of `auth-setup-token` at WARNING.
The file has restricted access, but journal readers or log aggregation operators
may have broader access. Before setup completes, such a reader could use the
secret to claim the initial administrator account if they can reach the server.

Log the token file's location rather than its contents, and retrieve it through
the privileged deployment channel. This finding concerns code behavior; no live
credential was extracted during this review. If a real setup token has been
shared outside its intended audience while setup remains open, replace it before
proceeding.

### S3 — General JSON requests lack a total body-size budget

**Priority: high on an exposed server without proxy limits; medium otherwise.
Evidence: code-path risk, no destructive resource-exhaustion test.**
FastAPI request parsing and `app/access.py:authorize_request` can load JSON before
the application has rejected unauthenticated or oversized semantic input.
Per-field Pydantic limits apply after parsing; image-upload streaming limits do
not impose a total limit on ordinary JSON endpoints.

An attacker able to reach these endpoints can send very large JSON bodies and
consume memory and parsing time. The practical exposure depends on reverse-proxy
limits, which were not inspected. Add an application streaming byte limit with
endpoint-specific budgets, including chunked requests, and retain a proxy limit
as a second boundary. Avoid trusting `Content-Length` alone.

### S4 — Rendering and native parsers share application resources

**Priority: medium. Evidence: potential denial of service; no demonstrated parser
exploit or remote code execution.** Image, font and template processing uses
native libraries in the server process. The repository already limits upload
bytes, image dimensions/pixels, SVG syntax and font structure. Those are useful
controls; a compressed-byte limit alone does not bound CPU cost, and independent
bounded inputs can still be expensive when submitted concurrently.

An authorized upload/render user can consume application resources within allowed
inputs. Measure worst-case accepted inputs and add bounded concurrency/work
budgets where necessary. Use process isolation only if measurements or decoder
risk justify its operational cost. Keep decoder dependencies updated. The
reported 935×1004 PNG is within current image limits; its metadata alone does not
show malicious or malformed content.

### S5 — Main interface lacks an explicit anti-framing policy

**Priority: low, defense in depth. Evidence: header configuration review.** The
companion sends framing protection; the main application does not consistently
set an equivalent `frame-ancestors`/`X-Frame-Options` policy. Exploitation requires
a browser/session/embedding context that permits authenticated framing; strict
SameSite cookies constrain common cross-site scenarios.

Set an explicit framing policy consistent with supported deployment embedding.
This is not evidence of an existing XSS vulnerability, and adding a broad CSP
without testing asset and service-worker behavior is not a substitute for input
and authorization controls.

### S6 — Polymorphic grants and JSON memberships need lifecycle checks

**Priority: medium for integrity; no demonstrated privilege escalation.**
Role deletion removes `ResourceGrant` rows and role memberships, but does not
equivalently remove role-principal `BillingGrant` rows. Group ownership for image
and font assets is stored in JSON and is outside SQL foreign-key enforcement.
These paths can leave unusable or stale references.

Normal generated identifiers are not reused, so dangling grants do not by
themselves prove an attacker can inherit access. Add explicit lifecycle checks
and, eventually, normalized membership/grant tables. Keep historical attribution
separate from active authorization. See the relationship inventory for scope.

## Controls observed

- Session tokens are opaque and stored hashed; cookies use HttpOnly and strict
  SameSite, with Secure dependent on HTTPS deployment configuration. Mutations
  check CSRF/origin and recheck authorization at sensitive boundaries.
- Passwords use salted scrypt; expensive verification is bounded and login/recovery
  flows have rate and validity checks. Recovery is not a reusable bearer reset.
- Resource access distinguishes grants, denials, ownership and scoped history.
  Group approver preview access is request-scoped. Self-approval restrictions and
  creditor/global-accounting confirmation protect billing decisions.
- The external status API uses a bearer key and a restricted operational response,
  rather than exposing label content or preview URLs.
- Uploaded images are normalized; avatars discard metadata. SVGs use restricted
  syntax. Asset identifiers/path handling and template logic avoid arbitrary
  filesystem names and unrestricted expression evaluation.
- Push delivery restricts endpoints; administrator-configured notification URLs
  intentionally support private infrastructure. That feature alone is not an SSRF
  vulnerability without an unauthorized configuration path.
- Update and restore code validates archive paths/types and relevant integrity
  properties. Privileged updates still deliberately trust the configured release
  repository and its maintainers.
- The repair screen requires an administrator, CSRF for writes, an explicit
  reason, an existing target and an unchanged orphan record token. Invalid
  credentials can only be revoked. Normal operations remain blocked until
  constraints have been installed successfully.

No confirmed SQL injection, arbitrary command execution, upload-based code
execution or universal cross-user preview bypass was established in this review.
That statement is bounded by the reviewed paths and testing scope; it is not a
claim that the application has no such vulnerabilities.

## Suggested order

1. Reproduce and fix S1/C1–C2 in the actual application under controlled load.
2. Remove bootstrap secret logging and establish request-body budgets.
3. Fix the companion session-generation race and audit JSON/grant deletion paths.
4. Measure parser/render resource use; verify deployed proxy, TLS and cookie
   settings; run a dependency advisory scan against exact deployed versions.
5. Exercise backup restore, ownership loss and interrupted print recovery in an
   isolated deployment before a release.

Security findings are recorded for deliberation. Except for the explicitly
requested relationship enforcement and repair boundaries, this report does not
imply that these mitigations have already been implemented.
