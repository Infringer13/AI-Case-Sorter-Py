"""Reason codes and the catch-all tally. Qt-free: the panel only paints this."""

from __future__ import annotations

from sorter.control.catch_all import (
    BATCH_FULL,
    BELOW_FLOOR,
    EMPTY_KEY,
    ROUTED,
    SPECIAL,
    UNASSIGNED,
    UNKNOWN,
    CatchAllTally,
    classify_reason,
    is_special_label,
    percent,
    reason_summary,
    reason_tooltip,
)


def _ok(**overrides: object) -> dict:
    result: dict = {
        "ok": True,
        "slot": 0,
        "label": "BPS",
        "parent": None,
        "reason": UNASSIGNED,
    }
    result.update(overrides)
    return result


def test_special_labels_match_any_case() -> None:
    assert is_special_label("UPSIDE DOWN")
    assert is_special_label("  upside down ")
    assert not is_special_label("WIN")
    assert not is_special_label("")


def test_classify_reason_precedence() -> None:
    # The floor wins over a real bin, a halt, and a special label.
    assert classify_reason(label="WIN", slot=3, above_floor=False, halt=True, known=True) == BELOW_FLOOR
    assert classify_reason(label="UPSIDE DOWN", slot=0, above_floor=False, halt=False, known=True) == BELOW_FLOOR
    assert classify_reason(label="WIN", slot=4, above_floor=True, halt=True, known=True) == BATCH_FULL
    assert classify_reason(label="WIN", slot=3, above_floor=True, halt=False, known=True) == ROUTED
    # Special is checked before "unknown", so a trained class the model list
    # does not contain is still special rather than unknown.
    assert classify_reason(label="upside down", slot=0, above_floor=True, halt=False, known=False) == SPECIAL
    assert classify_reason(label="", slot=0, above_floor=True, halt=False, known=False) == UNKNOWN
    assert classify_reason(label="NOPE", slot=0, above_floor=True, halt=False, known=False) == UNKNOWN
    assert classify_reason(label="BPS", slot=0, above_floor=True, halt=False, known=True) == UNASSIGNED
    # A special label that already has a bin is just routed.
    assert classify_reason(label="UPSIDE DOWN", slot=2, above_floor=True, halt=False, known=True) == ROUTED


def test_add_counts_every_success_and_only_slot_zero_as_catch_all() -> None:
    tally = CatchAllTally()
    tally.add({"ok": False, "slot": 0, "label": "BPS"})
    tally.add(_ok(slot=3, label="WIN", reason=ROUTED))
    tally.add(_ok())
    assert tally.total == 2
    assert tally.catch_all_total == 1
    assert tally.top()[0].key == "BPS"
    assert tally.top()[0].count == 1


def test_key_is_parent_then_label_then_empty() -> None:
    tally = CatchAllTally()
    tally.add(_ok(label="WIN", parent="Brass"))
    tally.add(_ok(label="  ", parent="  "))
    tally.add(_ok(label="", parent=None))
    keys = {bucket.key for bucket in tally.top()}
    assert keys == {"Brass", EMPTY_KEY}
    assert tally.catch_all_total == 3


def test_children_are_counted_only_when_the_label_is_not_the_parent() -> None:
    tally = CatchAllTally()
    tally.add(_ok(label="WIN", parent="Brass", reason=UNASSIGNED))
    tally.add(_ok(label="FC", parent="Brass", reason=BELOW_FLOOR))
    tally.add(_ok(label="brass", parent="Brass", reason=UNASSIGNED))
    bucket = tally.top()[0]
    assert bucket.count == 3
    assert bucket.children == {"WIN": 1, "FC": 1}
    assert bucket.reasons == {UNASSIGNED: 2, BELOW_FLOOR: 1}


def test_top_orders_by_count_then_name_and_other_is_the_rest() -> None:
    tally = CatchAllTally()
    # Equal counts: name is the tie-break, case-insensitive.
    tally.add(_ok(label="IK"))
    tally.add(_ok(label="bps"))
    assert [bucket.key for bucket in tally.top()] == ["bps", "IK"]

    tally.reset()
    for index in range(12):
        name = f"H{index:02d}"
        for _ in range(12 - index):
            tally.add(_ok(label=name))
    top = tally.top()
    assert [bucket.key for bucket in top] == [f"H{index:02d}" for index in range(10)]
    assert top[0].count == 12
    assert tally.top(0) == []
    # H10 has 2 cases, H11 has 1.
    assert tally.other() == (2, 3)
    assert tally.catch_all_total == sum(range(1, 13))


def test_percent_rounds_and_is_zero_for_an_empty_whole() -> None:
    assert percent(319, 615) == 52
    assert percent(2, 3) == 67
    assert percent(0, 0) == 0
    assert percent(1, 0) == 0


def test_reason_summary_and_tooltip() -> None:
    tally = CatchAllTally()
    tally.add(_ok(label="WIN", parent="Brass", reason=UNASSIGNED))
    tally.add(_ok(label="FC", parent="Brass", reason=BELOW_FLOOR))
    bucket = tally.top()[0]
    # Equal counts break the tie on the reason code, so below_floor leads.
    assert reason_summary(bucket) == "Below floor 1, Unassigned 1"
    assert reason_tooltip(bucket) == "Below floor: 1\nUnassigned: 1\n\nLabels:\nFC: 1\nWIN: 1"

    alone = CatchAllTally()
    alone.add(_ok(reason=SPECIAL, label="UPSIDE DOWN"))
    assert reason_summary(alone.top()[0]) == "Upside down"
    assert reason_tooltip(alone.top()[0]) == "Upside down: 1"


def test_reset_clears_totals_and_buckets() -> None:
    tally = CatchAllTally()
    tally.add(_ok())
    tally.reset()
    assert tally.total == 0
    assert tally.catch_all_total == 0
    assert tally.top() == []
    assert tally.other() == (0, 0)
