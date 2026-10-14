"""Refreshing one ATS source: fetch, normalize, store a snapshot, diff via the engine (spec 04).

Failure semantics (spec 03/04): a failed refresh stores a run in the history and *nothing
else* - no snapshot, no removals - so earlier data stays exactly as it was.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import AdapterError, FetchOutcome, InvalidToken, PoliteClient, build_adapter
from ..clock import Clock, format_ts, parse_ts
from ..config import Settings
from ..db.models import RefreshRun, Snapshot, Source
from ..errors import AppError
from .analysis import source_events
from .sources import get_source
from .store import store_snapshot

EventKey = tuple[str, str, str, str, str, tuple[str, ...] | None]


@dataclass(frozen=True, slots=True)
class Counters:
    added: int = 0
    changed: int = 0
    removed: int = 0
    reappeared: int = 0
    unchanged: int = 0
    baseline: bool = False


def _event_key(event: dict[str, Any]) -> EventKey:
    # role_id/company_id are left out on purpose: adding a role can shift the group index of
    # its siblings and with it their role ids, while the event itself did not change.
    fields = event["fields"]
    return (
        event["at"],
        event["type"],
        event["source_kind"],
        event["source_ref"],
        event["title"],
        tuple(fields) if fields is not None else None,
    )


def compute_counters(
    session: Session, snapshot: Snapshot, *, source: tuple[str, str], as_of: str
) -> Counters:
    """Lifecycle counters of ``snapshot`` from the engine's replay against the prior ones."""
    before = source_events(session, source=source, as_of=as_of, exclude_snapshot_id=snapshot.id)
    after = source_events(session, source=source, as_of=as_of)
    if before["stats"]["snapshots"] == 0:
        return Counters(baseline=True)

    new_events = Counter(_event_key(e) for e in after["events"]) - Counter(
        _event_key(e) for e in before["events"]
    )
    by_type: Counter[str] = Counter()
    for key, count in new_events.items():
        by_type[key[1]] += count

    # After a full snapshot the active roles of the source are exactly the listed ones.
    listed = sum(
        1
        for role in after["roles"]
        for observation in role["observations"]
        if observation["status"] == "active"
    )
    added, changed, reappeared = by_type["added"], by_type["changed"], by_type["reappeared"]
    return Counters(
        added=added,
        changed=changed,
        removed=by_type["removed"],
        reappeared=reappeared,
        unchanged=max(0, listed - added - changed - reappeared),
    )


def _describe(outcome: FetchOutcome, counters: Counters) -> str:
    stored = len(outcome.postings)
    if counters.baseline:
        head = f"Baseline snapshot recorded: {stored} postings; nothing earlier to compare with"
    else:
        head = (
            f"{stored} postings stored: {counters.added} added, {counters.changed} changed, "
            f"{counters.removed} removed, {counters.reappeared} reappeared, "
            f"{counters.unchanged} unchanged"
        )
    parts = [f"{outcome.host}: {head}"]
    tally = outcome.tally
    if tally.unlisted:
        parts.append(f"{tally.unlisted} unlisted jobs skipped")
    if tally.dropped_total:
        reasons = ", ".join(f"{n} {reason}" for reason, n in tally.dropped.most_common())
        parts.append(f"{tally.dropped_total} jobs dropped ({reasons})")
    if tally.omitted:
        fields = ", ".join(f"{field} x{n}" for field, n in sorted(tally.omitted.items()))
        parts.append(f"optional fields left empty: {fields}")
    return "; ".join(parts)


def _remaining_wait(settings: Settings, last_finished_at: str, now: str) -> int:
    elapsed = int((parse_ts(now) - parse_ts(last_finished_at)).total_seconds())
    return settings.min_refresh_interval_s - max(0, elapsed)


def refresh_source(
    session: Session,
    source_id: int,
    *,
    settings: Settings,
    clock: Clock,
    transport: httpx.BaseTransport | None,
    lock: threading.Lock,
) -> RefreshRun:
    """Run one refresh of ``source_id``; returns the stored run (``ok`` or ``failed``)."""
    with lock:  # one provider request at a time, and no refresh racing a source delete
        source = get_source(session, source_id)
        started = format_ts(clock())

        last = session.scalars(
            select(RefreshRun)
            .where(RefreshRun.source_id == source.id)
            .order_by(RefreshRun.id.desc())
            .limit(1)
        ).first()
        if last is not None and settings.min_refresh_interval_s > 0:
            remaining = _remaining_wait(settings, last.finished_at, started)
            if remaining > 0:
                raise AppError(
                    429,
                    "too_soon",
                    f"This source was refreshed {settings.min_refresh_interval_s - remaining} s ago; "
                    f"wait {remaining} s (minimum interval {settings.min_refresh_interval_s} s)",
                    details={
                        "retry_after_s": remaining,
                        "min_interval_s": settings.min_refresh_interval_s,
                    },
                    headers={"Retry-After": str(remaining)},
                )

        adapter = build_adapter(source.provider, settings.base_urls[source.provider])
        try:
            with PoliteClient(transport=transport) as client:
                outcome = adapter.fetch(client, source.token, source.company_name)
        except AdapterError as exc:
            return _store_failure(session, source, started, clock, exc)
        except InvalidToken as exc:
            failure = AdapterError("malformed", f"Stored token is not usable: {exc}")
            return _store_failure(session, source, started, clock, failure)

        finished = format_ts(clock())
        snapshot = store_snapshot(
            session,
            source_id=source.id,
            source_kind=source.provider,
            source_ref=source.token,
            observed_at=finished,
            mode="full",
            dataset_label=None,
            created_at=finished,
            postings=outcome.postings,
        )
        counters = compute_counters(
            session, snapshot, source=(source.provider, source.token), as_of=finished
        )
        run = RefreshRun(
            source_id=source.id,
            started_at=started,
            finished_at=finished,
            status="ok",
            error_kind=None,
            http_status=200,
            retry_after_s=None,
            items_seen=outcome.tally.items_seen,
            added=counters.added,
            changed=counters.changed,
            removed=counters.removed,
            reappeared=counters.reappeared,
            unchanged=counters.unchanged,
            message=_describe(outcome, counters),
            snapshot_id=snapshot.id,
        )
        session.add(run)
        session.commit()
        return run


def _store_failure(
    session: Session, source: Source, started: str, clock: Clock, error: AdapterError
) -> RefreshRun:
    run = RefreshRun(
        source_id=source.id,
        started_at=started,
        finished_at=format_ts(clock()),
        status="failed",
        error_kind=error.kind,
        http_status=error.http_status,
        retry_after_s=error.retry_after_s,
        items_seen=error.items_seen,
        added=0,
        changed=0,
        removed=0,
        reappeared=0,
        unchanged=0,
        message=f"{error.message}. No snapshot was stored; existing data is untouched.",
        snapshot_id=None,
    )
    session.add(run)
    session.commit()
    return run
