# 0.13.0 stable-release acceptance results

Reported by the deployment operator on 2026-11-09. IDs match the A1–J6
checklist supplied in the release-evaluation conversation. These are reported
manual results, not an assertion that the final candidate has passed automated
or independent verification. Exact tested main/companion versions and the
remaining individual permissions under D1 and D2 have not yet been supplied.
A5 still needs role-separation verification; D1/D2 cover many permissions that
have not all been tested.

Summary: **40 passed, 3 partial, 0 failed, 41 not tested** (84 checks).

**G7 passed — operator retest reported on 2026-11-09.** The operator confirmed
automatic companion recovery now passes. The exact tested main/companion versions
were not supplied. All other reported results remain unchanged; testing continues.
The earlier failure was a companion page staying disconnected/loading after an
update and requiring a manual browser refresh.

Local investigation: both existing simulated browser-reconnection tests passed.
Before pre5, the companion refreshed station data without frontend-build update detection;
the main application's service-worker update notice is not used by the companion.
Inspection of pre2 found that its page can stop retrying after the shared request
helper marks the service unavailable: its polling does not recheck health. The
current page already rechecks health, but updating the server cannot replace the
JavaScript in an old open page. This is a possible explanation, not a confirmed
root cause without the tested versions.

The operator approved automatic reload only while safely locked. Local changes
add companion frontend-build reporting and a reload after verifying the new
shell is available, with no open dialog or pending control request and protection
against stale-cache reload loops. An old open page still needs one manual refresh
to adopt this behavior. These changes are included in 0.13.0-pre5.

Local verification passed: 16 companion backend tests, seven browser checks
covering reconnect/update recovery, safe reload deferral, stale-cache protection,
and existing station controls; companion build, Pyright, targeted mypy and Ruff
checks also passed. The subsequent operator retest marks G7 passed.

The operator requested publication as stable **0.13.0** after reporting this
retest. Publication does not mark the partial or untested checks below as passed.

G11 concerns the companion status/version feature added in pre5; it is not
included in pre4. Previously successful 0.12.2 checks and
the reported pre3-to-pre2 automatic rollback remain separate historical evidence.
A6/B2 are now reported passed, but do not establish a specific deployed tag until
that version is confirmed. Partial and untested checks remain open. No failed
subcheck is inferred from a Partial result.

Use the [deployment checklist](DEPLOYMENT_CHECKLIST.md),
[release plan](V0_13_0_PLAN.md), and
[hardware procedures](HARDWARE_VERIFICATION.md) for the detailed checks.

## A — Installation, upgrades and recovery

| ID | Check | Reported result |
| --- | --- | --- |
| A1 | Fresh main installation | Passed |
| A2 | Fresh companion installation | Passed |
| A3 | Configuration preservation | Passed |
| A4 | Deployment detection and overrides | Passed |
| A5 | Role separation, confirmation and read-only checks | Partial — role separation remains unverified |
| A6 | Upgrade paths and data preservation | Passed |
| A7 | Frontend delivery and separate builds | Passed |
| A8 | Backup and rollback | Passed |
| A9 | Companion update recovery | Not tested |

## B — Database and asset storage

| ID | Check | Reported result |
| --- | --- | --- |
| B1 | SQLite fresh installation and upgrade | Not tested |
| B2 | MariaDB fresh installation and upgrade | Passed |
| B3 | SQLite-to-MariaDB migration | Passed |
| B4 | Database ownership and connection loss | Not tested |
| B5 | Legacy asset import | Passed |
| B6 | Asset archival and import recovery | Passed |
| B7 | Idle rendering cache | Passed |
| B8 | Database-only asset recovery | Not tested |
| B9 | Large assets and binary backup safeguards | Not tested |

## C — Inventory, migration and ownership

| ID | Check | Reported result |
| --- | --- | --- |
| C1 | Initial migration printing gate | Passed |
| C2 | Administrator migration workflow | Passed |
| C3 | Migration interruption, replay and retained holds | Passed |
| C4 | Locations, hierarchy, ownership and filters | Passed |
| C5 | Inventory ownership transfers | Not tested |
| C6 | Account deletion and ownerless inventory | Not tested |
| C7 | Cartridge swaps, locations, creation and notes | Passed |
| C8 | Printer retirement and movement | Passed |

## D — Permissions and access boundaries

| ID | Check | Reported result |
| --- | --- | --- |
| D1 | Independent granular printer permissions | Partial — remaining individual permissions not yet tested |
| D2 | Independent cartridge permissions | Partial — remaining individual permissions not yet tested |
| D3 | Inheritance and allow/deny precedence | Passed |
| D4 | Protected ownership and administrator rights | Passed |
| D5 | Separate location grants through locations and roles | Passed |
| D6 | Permission explanations, graph and impact confirmation | Passed |
| D7 | Request versus direct submission | Passed |
| D8 | Scope isolation and immediate revocation | Not tested |

## E — Costs, debts, repayments and retries

| ID | Check | Reported result |
| --- | --- | --- |
| E1 | Ordinary accounting and no self-debt | Passed |
| E2 | Ownerless cartridge debts and later assignment | Not tested |
| E3 | Quotes, price limits and affordability notifications | Not tested |
| E4 | Pricing edge cases and allowance preservation | Not tested |
| E5 | Explicit substitutions and requester price protection | Not tested |
| E6 | Owner approval warnings and discount notifications | Not tested |
| E7 | Repayment permissions, allocation and idempotency | Not tested |
| E8 | Free and requester-funded retries | Not tested |

## F — Physical printing and failure recovery

| ID | Check | Reported result |
| --- | --- | --- |
| F1 | Physical output quality and preview agreement | Passed |
| F2 | Tape estimates and reviewed consumption | Passed |
| F3 | Queue operation, holds and routing | Passed |
| F4 | Idle printer disconnect and reconnect | Passed |
| F5 | Printer errors and investigation blocks | Passed |
| F6 | Graceful and emergency stop behavior | Passed |
| F7 | Process restart and uncertain work | Passed |
| F8 | Independent operation of two physical printers | Not tested |

## G — Companion connectivity, identity and kiosk

| ID | Check | Reported result |
| --- | --- | --- |
| G1 | Enrollment, cross-network access and key revocation | Passed |
| G2 | Persistent web printer management | Passed |
| G3 | Personal PINs and companion access | Passed |
| G4 | Administrator-bound shared-PIN mode | Not tested |
| G5 | Locking, timeout, countdown and keypad | Passed |
| G6 | Locked/offline stop policy | Passed |
| G7 | Automatic recovery without browser refresh | Passed — operator retest on 2026-11-09; exact versions not supplied |
| G8 | No execution before complete transfer and authorization | Not tested |
| G9 | Authorized offline completion and exactly-once reconciliation | Not tested |
| G10 | Operational dashboard and 1024 × 600 layout | Not tested |
| G11 | New companion status/version reporting | Not tested |

## H — Editor and everyday interface

| ID | Check | Reported result |
| --- | --- | --- |
| H1 | Automatic text width and logic dependencies | Passed |
| H2 | Image proportions, box locking, scaling and reset | Not tested |
| H3 | Media compatibility enforcement | Not tested |
| H4 | Large-library template picker | Not tested |
| H5 | Frozen queued artwork and CSV workflows | Passed |
| H6 | Responsive layouts, spacing, motion and form preservation | Passed |
| H7 | Avatar lifecycle and visibility | Not tested |

## I — Activity, review, notifications and audit

| ID | Check | Reported result |
| --- | --- | --- |
| I1 | Combined Print Activity filters and access | Not tested |
| I2 | Completed-batch packing accuracy | Not tested |
| I3 | Misprint corrections and retained original charges | Not tested |
| I4 | Evidence policy for reviews and misprint reports | Not tested |
| I5 | Evidence privacy and backup | Not tested |
| I6 | In-app notifications and authorized actions | Not tested |
| I7 | External notification delivery and retry | Not tested |
| I8 | Comprehensive audit coverage | Not tested |
| I9 | Audit redaction and inference resistance | Not tested |
| I10 | Audit integrity, revocation and secret exclusion | Not tested |

## J — Final engineering and release checks

| ID | Check | Reported result |
| --- | --- | --- |
| J1 | Full regression suite on the final candidate | Not tested |
| J2 | Security and dependency review | Not tested |
| J3 | Coverage of supported deployment and integration combinations | Not tested |
| J4 | Sustained operation and resource usage | Not tested |
| J5 | Agreed scope, documented gaps and release consistency | Not tested |
| J6 | Final deployed release smoke test | Not tested |
