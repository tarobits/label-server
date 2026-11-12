"""Fsynced local attempts: a lost acknowledgement must never repeat hardware writes."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from app.companion.companion_protocol import BatchEnvelope, ExecutionResult, payload_digest


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, digest TEXT NOT NULL, local_id TEXT NOT NULL, payload TEXT NOT NULL, phase TEXT NOT NULL, go_token TEXT, result TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS blocked_printers (local_id TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE IF NOT EXISTS session_revocations (token TEXT PRIMARY KEY)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS clearances (local_id TEXT PRIMARY KEY, generation INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS printers (id TEXT PRIMARY KEY, payload TEXT NOT NULL, enabled INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS station (id TEXT PRIMARY KEY CHECK (id='binding'), companion_id TEXT NOT NULL)"
            )
        path.chmod(0o600)

    def revoke_session(self, token: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO session_revocations VALUES (?)", (token,))

    def pending_revocations(self) -> list[str]:
        with self.transaction(readonly=True) as db:
            return [row[0] for row in db.execute("SELECT token FROM session_revocations LIMIT 100")]

    def acknowledge_revocation(self, token: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM session_revocations WHERE token=?", (token,))

    @contextmanager
    def transaction(self, *, readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA query_only=ON" if readonly else "PRAGMA query_only=OFF")
            connection.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def receive(self, payload: dict[str, Any], digest: str) -> BatchEnvelope:
        envelope = BatchEnvelope.model_validate(payload)
        if payload_digest(envelope.model_dump()) != digest:
            raise ValueError("Incomplete or altered batch")
        with self.transaction() as db:
            existing = db.execute(
                "SELECT digest FROM attempts WHERE id = ?", (envelope.batch_id,)
            ).fetchone()
            if existing and existing["digest"] != digest:
                raise ValueError("Batch identity already has different content")
            if not existing:
                db.execute(
                    "INSERT INTO attempts (id,digest,local_id,payload,phase) VALUES (?,?,?,?, 'prepared')",
                    (
                        envelope.batch_id,
                        digest,
                        envelope.local_id,
                        json.dumps(envelope.model_dump()),
                    ),
                )
        return envelope

    def authorize(self, identifier: str, digest: str, go_token: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM attempts WHERE id = ?", (identifier,)).fetchone()
            if (
                not row
                or row["digest"] != digest
                or not go_token
                or row["go_token"]
                and row["go_token"] != go_token
            ):
                raise ValueError("Batch authorization does not match")
            if row["phase"] == "prepared":
                db.execute(
                    "UPDATE attempts SET phase='authorized', go_token=? WHERE id=?",
                    (go_token, identifier),
                )

    def start(self, identifier: str) -> bool:
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE attempts SET phase='running' WHERE id=? AND phase='authorized'",
                (identifier,),
            )
            return changed.rowcount == 1

    def finish(self, identifier: str, result: ExecutionResult) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM attempts WHERE id=?", (identifier,)).fetchone()
            if not row or row["go_token"] != result.go_token or row["digest"] != result.digest:
                raise ValueError("Result does not match durable authorization")
            encoded = json.dumps(result.model_dump(), sort_keys=True)
            if row["result"] and row["result"] != encoded:
                raise ValueError("Attempt already has another result")
            if row["phase"] not in ("running", "finished"):
                raise ValueError("Attempt is not running")
            db.execute(
                "UPDATE attempts SET phase='finished', result=? WHERE id=?", (encoded, identifier)
            )
            if result.outcome != "printed":
                db.execute(
                    "INSERT OR IGNORE INTO blocked_printers (local_id) VALUES (?)",
                    (row["local_id"],),
                )

    def recover(self) -> None:
        # Called once before starting workers, while holding the process lock.
        with self.transaction() as db:
            for row in db.execute("SELECT * FROM attempts WHERE phase='running'").fetchall():
                result = ExecutionResult(
                    digest=row["digest"], go_token=row["go_token"], outcome="interrupted"
                )
                db.execute(
                    "UPDATE attempts SET phase='finished', result=? WHERE id=?",
                    (json.dumps(result.model_dump(), sort_keys=True), row["id"]),
                )
                db.execute(
                    "INSERT OR IGNORE INTO blocked_printers (local_id) VALUES (?)",
                    (row["local_id"],),
                )

    def row(self, identifier: str) -> dict[str, Any]:
        with self.transaction(readonly=True) as db:
            row = db.execute("SELECT * FROM attempts WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("Unknown attempt")
            return dict(row)

    def pending_results(self) -> list[tuple[str, ExecutionResult]]:
        with self.transaction(readonly=True) as db:
            return [
                (row["id"], ExecutionResult.model_validate_json(row["result"]))
                for row in db.execute("SELECT * FROM attempts WHERE phase='finished'")
            ]

    def acknowledge(self, identifier: str) -> None:
        with self.transaction() as db:
            # Keep the execution tombstone, but release the rendered artwork.
            db.execute(
                "UPDATE attempts SET phase='acknowledged', payload='{}' WHERE id=? AND phase='finished'",
                (identifier,),
            )

    def cancel(self, identifier: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE attempts SET phase='cancelled', payload='{}' WHERE id=? AND phase IN ('prepared','authorized')",
                (identifier,),
            )

    def blocked(self, local_id: str) -> bool:
        with self.transaction(readonly=True) as db:
            return (
                db.execute(
                    "SELECT 1 FROM blocked_printers WHERE local_id=?", (local_id,)
                ).fetchone()
                is not None
            )

    def clearance(self, local_id: str) -> int:
        with self.transaction(readonly=True) as db:
            row = db.execute(
                "SELECT generation FROM clearances WHERE local_id=?", (local_id,)
            ).fetchone()
            return int(row["generation"]) if row else 0

    def clear(self, local_id: str, generation: int) -> None:
        with self.transaction() as db:
            previous = db.execute(
                "SELECT generation FROM clearances WHERE local_id=?", (local_id,)
            ).fetchone()
            if generation <= (previous["generation"] if previous else 0):
                return
            if db.execute(
                "SELECT 1 FROM attempts WHERE local_id=? AND phase IN ('running','authorized','finished')",
                (local_id,),
            ).fetchone():
                raise ValueError("Synchronize and resolve the active attempt first")
            db.execute("DELETE FROM blocked_printers WHERE local_id=?", (local_id,))
            db.execute(
                "INSERT OR REPLACE INTO clearances (local_id,generation) VALUES (?,?)",
                (local_id, generation),
            )

    def record_stop(
        self, printer_id: str, mode: str, user_id: str | None, *, offline: bool, locked: bool
    ) -> None:
        identifier = str(uuid.uuid4())
        payload = {
            "id": identifier,
            "occurred_at": time.time(),
            "printer_id": printer_id,
            "mode": mode,
            "user_id": user_id,
            "offline": offline,
            "locked": locked,
        }
        with self.transaction() as db:
            db.execute("INSERT INTO events VALUES (?, ?)", (identifier, json.dumps(payload)))

    def pending_events(self) -> list[dict[str, Any]]:
        with self.transaction(readonly=True) as db:
            return [
                json.loads(row["payload"])
                for row in db.execute("SELECT payload FROM events ORDER BY rowid LIMIT 100")
            ]

    def acknowledge_event(self, identifier: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM events WHERE id=?", (identifier,))

    def seed_printer(self, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO printers VALUES (?, ?, 1)",
                (payload["local_id"], json.dumps(payload)),
            )

    def printers(self, *, enabled: bool = True) -> list[dict[str, Any]]:
        with self.transaction(readonly=True) as db:
            return [
                json.loads(row["payload"])
                for row in db.execute(
                    "SELECT payload FROM printers WHERE enabled=? ORDER BY rowid", (int(enabled),)
                )
            ]

    def set_printer_enabled(self, local_id: str, enabled: bool) -> None:
        with self.transaction() as db:
            db.execute("UPDATE printers SET enabled=? WHERE id=?", (int(enabled), local_id))

    def update_printer(self, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE printers SET payload=? WHERE id=?",
                (json.dumps(payload), payload["local_id"]),
            )

    def bind_station(self, identifier: str) -> None:
        with self.transaction() as db:
            previous = db.execute("SELECT companion_id FROM station WHERE id='binding'").fetchone()
            if previous and previous["companion_id"] != identifier:
                raise ValueError(
                    "Use a separate data directory for a different companion registration"
                )
            db.execute("INSERT OR IGNORE INTO station VALUES ('binding', ?)", (identifier,))
