"""Why a case landed in the catch-all, and a running tally of those cases.

Qt-free on purpose: the sort loop decides the reason, the Catch-All panel
only paints this tally, and the tests import neither widgets nor the
controller. A case is one result dict of the shape ``RunController`` posts
on ``run/result``.
"""

from __future__ import annotations

from typing import Any

# Destination.reason. ``routed`` is a real bin; everything else is slot 0.
ROUTED = "routed"
BELOW_FLOOR = "below_floor"
UNASSIGNED = "unassigned"  # known headstamp whose slot is 0
UNKNOWN = "unknown"  # empty label, or not one of the model's headstamps
SPECIAL = "special"  # unassigned label in CATCH_ALL_LABELS
BATCH_FULL = "batch_full"  # package mode: every configured slot is full

REASONS = (ROUTED, BELOW_FLOOR, UNASSIGNED, UNKNOWN, SPECIAL, BATCH_FULL)

# Trained classes that are expected to have no bin of their own. Matched
# case-insensitively against the classifier's label. "UPSIDE DOWN" is a
# normal class, not an error.
CATCH_ALL_LABELS = ("upside down",)

# Tally key when a catch-all case has neither a parent nor a label.
EMPTY_KEY = "(empty)"

# Short labels for the panel's Reason column and its tooltip.
REASON_LABELS = {
    ROUTED: "Routed",
    BELOW_FLOOR: "Below floor",
    UNASSIGNED: "Unassigned",
    UNKNOWN: "Unknown",
    SPECIAL: "Upside down",
    BATCH_FULL: "Batch full",
}

_CATCH_ALL_FOLDED = {name.casefold() for name in CATCH_ALL_LABELS}


def is_special_label(label: str) -> bool:
    """True when ``label`` is one of :data:`CATCH_ALL_LABELS` (any case)."""
    return (label or "").strip().casefold() in _CATCH_ALL_FOLDED


def classify_reason(
    *,
    label: str,
    slot: int,
    above_floor: bool,
    halt: bool,
    known: bool,
) -> str:
    """The reason code for one routing decision.

    ``known`` is whether the label is one of the model's headstamps (or, in
    parent mode, a parent name). In standard mode that is
    ``config.slot_for_headstamp(label) is not None``: ``None`` is an unknown
    label, ``0`` is a known headstamp left on the catch-all. The confidence
    floor wins over every assignment reason, and a package-mode halt wins
    over "this would have been a bin".
    """
    if not above_floor:
        return BELOW_FLOOR
    if halt:
        return BATCH_FULL
    if int(slot) > 0:
        return ROUTED
    if is_special_label(label):
        return SPECIAL
    if not (label or "").strip() or not known:
        return UNKNOWN
    return UNASSIGNED


class CatchAllBucket:
    """One catch-all key: a parent name, a label, or :data:`EMPTY_KEY`."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.count = 0
        self.reasons: dict[str, int] = {}
        self.children: dict[str, int] = {}


class CatchAllTally:
    """Counts from successful sort results, catch-all cases broken down by key.

    ``add`` counts every successful result toward :attr:`total` (so the
    header's denominator matches the slot cards' master counter) and, when
    ``slot == 0``, toward :attr:`catch_all_total` under ``parent or label or
    "(empty)"``. Each bucket keeps per-reason counts and, when the key is a
    parent, per-child-label counts.
    """

    def __init__(self) -> None:
        self._total = 0
        self._catch_all = 0
        self._buckets: dict[str, CatchAllBucket] = {}

    def add(self, result: dict[str, Any]) -> None:
        """Count one result. Anything that did not succeed is ignored."""
        if not isinstance(result, dict) or not result.get("ok"):
            return
        self._total += 1
        try:
            slot = int(result.get("slot") or 0)
        except (TypeError, ValueError):
            slot = 0
        if slot != 0:
            return
        self._catch_all += 1
        label = str(result.get("label") or "").strip()
        parent = result.get("parent")
        parent_name = str(parent).strip() if parent else ""
        key = parent_name or label or EMPTY_KEY
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = CatchAllBucket(key)
            self._buckets[key] = bucket
        bucket.count += 1
        reason = str(result.get("reason") or UNKNOWN)
        bucket.reasons[reason] = bucket.reasons.get(reason, 0) + 1
        if parent_name and label and label.casefold() != parent_name.casefold():
            bucket.children[label] = bucket.children.get(label, 0) + 1

    def _ordered(self) -> list[CatchAllBucket]:
        return sorted(self._buckets.values(), key=lambda bucket: (-bucket.count, bucket.key.casefold()))

    def top(self, n: int = 10) -> list[CatchAllBucket]:
        """The ``n`` fullest keys, highest count first, name as the tie-break."""
        return self._ordered()[: max(0, n)]

    def other(self) -> tuple[int, int]:
        """Keys past :meth:`top`'s default 10, as ``(n_keys, n_cases)``."""
        rest = self._ordered()[10:]
        return len(rest), sum(bucket.count for bucket in rest)

    @property
    def total(self) -> int:
        return self._total

    @property
    def catch_all_total(self) -> int:
        return self._catch_all

    def reset(self) -> None:
        self._total = 0
        self._catch_all = 0
        self._buckets.clear()


def percent(part: int, whole: int) -> int:
    """``part / whole`` as a rounded percentage, or 0 when ``whole`` is 0."""
    if whole <= 0:
        return 0
    return int(round(100 * part / whole))


def reason_summary(bucket: CatchAllBucket) -> str:
    """The Reason column: one label, or ``"Unassigned 18, Below floor 4"``."""
    parts = sorted(bucket.reasons.items(), key=lambda item: (-item[1], item[0]))
    if len(parts) == 1:
        reason, _count = parts[0]
        return REASON_LABELS.get(reason, reason)
    return ", ".join(f"{REASON_LABELS.get(reason, reason)} {count}" for reason, count in parts)


def reason_tooltip(bucket: CatchAllBucket) -> str:
    """Full per-reason counts, plus child labels when the key is a parent."""
    parts = sorted(bucket.reasons.items(), key=lambda item: (-item[1], item[0]))
    lines = [f"{REASON_LABELS.get(reason, reason)}: {count}" for reason, count in parts]
    if bucket.children:
        lines.append("")
        lines.append("Labels:")
        children = sorted(bucket.children.items(), key=lambda item: (-item[1], item[0].casefold()))
        lines.extend(f"{name}: {count}" for name, count in children)
    return "\n".join(lines)
