# Security model and operational limits

This guide describes the current source tree. Deployed releases may differ;
review the [changelog](../CHANGELOG.md) before upgrading. Automated checks provide
regression evidence, not a security certification. Production proxy configuration,
load, hardware recovery and external penetration testing require separate validation.

## Authentication and authorization

Sessions use opaque tokens stored hashed, with HttpOnly cookies. Main-server
cookies use strict SameSite; Secure depends on HTTPS configuration. Mutations
check CSRF/origin and recheck authorization at sensitive transaction boundaries.
Password verification uses salted scrypt, bounded concurrency and throttling.
Verification runs outside the fleet lock, followed by fresh credential, account
and session checks before writes. Initial administrator setup logs the token
file's location, not its contents; retrieve the token through privileged host access.

Resource access combines ownership, grants and explicit denials. History and
previews remain scoped to the viewer's access. Group-account approver previews
are limited to the relevant pending request; financial access alone does not
grant general access to labels. Requesters cannot approve their own funding
requests. Payment receipt requires creditor or global accounting authorization.
See [access control](ACCESS_CONTROL.md) and [group accounts](GROUP_ACCOUNTS.md).

Role deletion removes associated billing grants. Permission groups cannot be
deleted while templates or image/font assets still refer to them. These lifecycle
checks complement SQL constraints; JSON and polymorphic references are not all
database-enforced. See [relationship repair](RELATIONSHIP_MIGRATION.md).

## Request and processing limits

Application middleware counts actual request bytes before parsing, including
chunked bodies, rather than relying solely on Content-Length. Default budgets
are 16 MiB for ordinary requests and 64 MiB for CSV, run and migration requests.
Authentication requests other than avatars also have a 16 KiB cap. Oversized
requests return 413. Image/font uploads retain their separate 5 MB limit.

Expensive HTTP render/upload routes admit two simultaneous requests by default.
When full, they return 503 with Retry-After; clients should retry with the same
idempotency key where supported. Admission occurs after receiving the bounded
body so slow uploads do not hold processing slots. These limits are configurable
in [deployment](DEPLOYMENT.md); retain proxy size/time limits and resource monitoring.

Images are normalized, avatars discard metadata, SVG syntax is restricted and
font structure is validated. Asset access includes authorization and deletion
checks. Template logic is a bounded expression language, not arbitrary Python
or JavaScript execution.

Native image/font parsers still share the server process. HTTP admission is not
decoder isolation, a per-call CPU deadline, or a global memory budget; physical
printer workers are outside that limit. Concurrent accepted large images can
consume hundreds of MiB. Lower concurrency on constrained hosts and measure
representative workloads. Process isolation remains an option if workloads or
decoder risks justify it.

## Deployment trust boundaries

The main interface permits same-origin framing only. The companion defaults to
the same policy; external embedding requires an exact-origin allowlist in its
deployment configuration, `LABEL_COMPANION_FRAME_ANCESTORS`. Unset, blank or empty
lists retain same-origin framing. With external embedding enabled, HTTPS companion
cookies use SameSite=None; browser third-party-cookie restrictions can still
prevent embedded sessions. Parent origins do not gain permission to make API
writes. See [companion deployment](COMPANION.md) for configuration.

The external status API uses a separate bearer key and exposes restricted
operational information. Administrator-configured notification destinations can
intentionally reach private infrastructure; protect configuration access.
See [integrations](INTEGRATIONS.md).

Updates and restores validate archive paths, file types and relevant integrity
properties. Privileged updates still trust the configured release repository and
its maintainers. Keep coordinated, tested backups and follow the
[deployment checklist](DEPLOYMENT_CHECKLIST.md). Database ownership cannot make
physical printing atomic; uncertain output requires review, as described in
[printer architecture](PRINTER_ARCHITECTURE.md#concurrency-and-ownership).

## Cancellation and session expiry

Companion idle auto-lock durably queues remote-session revocation before clearing
local access. If the main server is unreachable, revocation is retried after
reconnection or restart. The remote credential can remain usable until that
revocation succeeds or the server expires it; using it also requires a valid
companion installation API key.

Cancelling an admitted expensive HTTP request does not release its processing
slot until the application work and transaction cleanup finish. Cancellation
cannot stop a running native or synchronous worker, and it does not guarantee
that a submitted mutation was rolled back. Reuse supported idempotency keys
when retrying after a lost response.

Regression tests in `tests/test_adversarial_release.py` and
`tests/test_security_remediation.py` exercise these boundaries, including offline
revocation recovery and late failures after cancellation. Earlier-feature probes
in `tests/test_adversarial_legacy_features.py` cover selected retry, authorization,
recovery, accounting and migration boundaries.

## Dependency maintenance

Scan the Python lockfile/environment with `pip-audit` and the frontend lockfile
with `npm audit --package-lock-only` before releases. Maintain packaging tools
and system libraries separately from application dependencies. A scan with no
known advisories does not prove the absence of vulnerabilities.

The 2026-11-12 scan retained one accepted build-only issue:
[deepmerge GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4),
through @rollup/plugin-node-resolve, workbox-build and vite-plugin-pwa. The scan
reported four low-severity entries for this dependency chain and no patched
release. It merges build configuration, not runtime label uploads; exploitation
requires influence over objects passed into that build-time merge. Monitor the
upstream fix and recheck before releases. Do not automatically apply npm's
suggested major downgrade of the PWA tooling. The production-only frontend scan
reported no known advisories on that date.
