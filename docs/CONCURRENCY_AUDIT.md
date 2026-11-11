# Concurrency and deadlock review

Review date: 2026-11-11. Scope: the working tree after 0.15.0, including the
relationship migration. This is a repository review, not a production incident
postmortem. The earlier avatar outage has no captured thread dump; its cause
cannot be established from successful access logs followed by a timeout.

The review inventoried `app/`, `companion/`, `scripts/`, and `frontend/src/`
(300 files), searched asynchronous boundaries, locks, transactions, threads,
subprocesses, network calls and browser request lifecycles, and traced the critical
paths below. It is not a claim that every interleaving or line has been verified.

## Findings to discuss

| ID | Priority | Evidence / realistic trigger | Consequence | Recommendation |
| --- | --- | --- | --- | --- |
| C1 | High; investigate first | `app/access.py:authorize_request` is async but calls synchronous `authorize_current_request` / `access_context`, including database checkout and queries. Slow database or pool exhaustion can occur during ordinary load. Confirmed call path; outage not reproduced end to end. | The event loop waits for synchronous I/O, delaying unrelated requests, including health checks. | Move database authorization into an appropriate worker boundary, retaining the second authorization check under the mutation lock. Test health latency with deliberately delayed database calls. |
| C2 | High; investigate first | `app/http.py:db` and `app/companion_auth.py:device_db` hold the fleet lock across a synchronous dependency `yield`. Enough waiting dependency calls can occupy every worker while the lock holder's endpoint awaits a worker. Pattern reproduced in an isolated FastAPI harness. | Requests stop progressing without an exception; service can remain running. | Admit mutations before consuming a worker, or execute acquisition, endpoint work and release within one worker. Preserve transaction and authorization ordering. Increasing the pool merely raises the threshold. |
| C3 | Medium; realistic contention | `app/auth_api.py:login` takes the fleet lock and starts a write transaction before password verification. Password changes have a similar boundary. | Expensive password hashing delays printing reservations and other writes. Failed-login traffic can amplify this. | Perform bounded verification outside the global lock, then recheck the account, password fingerprint and disabled state before issuing a session. Keep rate limits ahead of expensive work. |
| C4 | Medium; realistic during outages | `companion/web.py:dashboard` fetches an operator outside the station lock, then writes `station.operator` or clears the station without checking that the token is still current. Unlock also writes a remote result after an unlocked network interval. | An old failed poll can lock a newly unlocked station; a delayed unlock can take effect after a lock action. Stale operator display is also possible. | Add a station generation counter; apply remote results only to the generation/token that requested them. Explicitly revoke superseded remote sessions. Test delayed success and failure after lock/unlock. |
| C5 | Medium / low; retention edge case | `app/template_previews.py` uses an instance lock, but `invalidate_deleted_previews` constructs another instance. A rendering instance can finish writing after another instance purges its files. Static ordering analysis, not a reproduced data exposure. | A derived preview can remain on disk after retention cleanup. Database permission/tombstone checks still protect normal access. | Share cache coordination and recheck deletion before publishing generated files; test render overlapping purge. |
| C6 | Low; shutdown edge case | `companion/agent.py:stop` and `companion/web.py` shutdown use unbounded thread joins. Normal HTTP operations have timeouts, but a stuck native driver or unexpected blocking path can exceed those assumptions. | Maintenance shutdown may hang until service-manager termination. | Exercise stuck-driver shutdown. Add a bounded shutdown policy that preserves uncertain-print review instead of silently retrying physical output. |
| C7 | Low; distributed ownership edge case | `app/database_lock.py` checks MariaDB advisory ownership and uses heartbeat/fencing checks. Losing the ownership connection between a check and a later statement is a small remaining interval. | A former owner may have in-flight work while another process starts. Hardware effects cannot be rolled back with SQL. | Failure-injection tests for network partitions and lock loss; preserve reservation and uncertain-result semantics. Do not claim exactly-once physical printing. |
| C8 | Low; performance investigation only | `companion/journal.py` serializes journal work with SQLite write transactions and durable commits. Contending polling and journal operations can wait. | Slow station responses under unusually heavy I/O; no demonstrated deadlock. | Profile before changing durability. Consider read-only transactions where safe. |

C1 and C2 should be addressed before treating the upload hang as resolved by image
validation alone. C4 is a normal kiosk interaction race, not an extreme scenario.
C5–C8 warrant targeted tests, but do not justify a broad concurrency rewrite.

## C2 reproduction and limits

An isolated subprocess used the application's installed FastAPI/AnyIO stack:

1. Set the AnyIO worker limiter to two tokens.
2. Define a synchronous generator dependency that acquires a `threading.Lock`,
   then yields to a synchronous endpoint.
3. Pause the first dependency immediately before its yield; start two further
   requests so one worker waits for the lock and another dependency is queued.
4. Release the pause. The queued dependency can consume the freed worker and
   block on the lock before the first endpoint gets its worker.

The observed result was three dependency attempts, zero executed endpoints and
zero completed requests. The subprocess was terminated by its three-second test
deadline. This demonstrates the scheduling mechanism, not its frequency in this
application. Production defaults permit more concurrent workers, so a larger
burst is needed. Cleanup's separate worker limiter does not help an endpoint that
has not started. [Starlette documents the shared thread pool](https://www.starlette.io/threadpool/).

For C1, synchronous helpers called directly from an async function are not
automatically offloaded. [FastAPI's concurrency documentation](https://fastapi.tiangolo.com/async/)
describes this distinction.

## Protections observed

- Printer workers take printer locks before the fleet lock; API paths that need
  the reverse order use nonblocking printer acquisition rather than waiting in a
  circular lock order.
- Expensive preparation paths release shared locks and recheck current access,
  revisions and assets before committing work.
- Reservations are committed before physical printing. Interrupted/uncertain
  batches require review rather than automatic duplicate printing.
- Companion journals retain durable progress and acknowledgement state.
- SQLite process locking and MariaDB ownership checks prevent ordinary duplicate
  server workers.
- Browser resource-cache generations prevent late responses from a previous
  account from repopulating the active account's cache.

The new relationship repair endpoint acquires its mutation lock inside the
endpoint worker, rather than carrying a lock across a dependency yield. Existing
application concurrency findings above remain discussion items; they were not
silently refactored as part of the foreign-key change.
