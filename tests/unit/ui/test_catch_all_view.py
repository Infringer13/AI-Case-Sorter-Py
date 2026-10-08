"""The Catch-All dock: live tally, assign bar, and the slot-0 card that opens it."""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence

from sorter.data.repository import HeadstampParentRepo, HeadstampRepo
from sorter.ui.catch_all_view import COL_NAME, COL_REASON, COLUMNS

from .conftest import seed_model


def _post(window, **fields: object) -> None:
    result = {"ok": True, "slot": 0, "label": "BPS", "parent": None, "reason": "unassigned"}
    result.update(fields)
    window.bus.post("run/result", result)
    window.bus.drain()


def _row(view, key: str) -> int:
    for row in range(view.table.rowCount()):
        item = view.table.item(row, COL_NAME)
        if item is not None and item.text() == key:
            return row
    raise AssertionError(f"{key} is not in the table")


def _select(view, key: str) -> None:
    view.table.setCurrentCell(_row(view, key), COL_NAME)


def _names(view) -> list[str]:
    names = []
    for row in range(view.table.rowCount()):
        item = view.table.item(row, COL_NAME)
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable:
            names.append(item.text())
    return names


def test_a_fresh_panel_is_empty_and_closed(window) -> None:
    view = window.catch_all_view
    assert window.catch_all_dock.isClosed()
    assert window.catch_all_dock.windowTitle() == "Catch-All"
    assert view.summary_label.text() == "0 in catch-all of 0 sorted (0%)"
    assert [view.table.horizontalHeaderItem(i).text() for i in range(len(COLUMNS))] == list(COLUMNS)
    assert not view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign to empty slot"
    assert view.assign_button.toolTip() == "Select a headstamp."
    assert view.assigned_label.isHidden()


def test_the_header_matches_the_slot_card_and_ignores_failures(window) -> None:
    _post(window, label="BPS")
    _post(window, label="BPS")
    _post(window, slot=2, label="WIN", reason="routed")
    window.bus.post("run/result", {"ok": False, "slot": 0, "label": "X"})
    window.bus.drain()

    view = window.catch_all_view
    assert window.slot_grid.cards[0].count_label.text() == "2"
    assert window.master_count_label.text() == "3"
    assert view.tally.catch_all_total == 2
    assert view.tally.total == 3
    assert view.summary_label.text() == "2 in catch-all of 3 sorted (67%)"
    assert view.table.item(_row(view, "BPS"), 2).text() == "2"
    assert view.table.item(_row(view, "BPS"), 3).text() == "100%"


def test_top_ten_and_a_greyed_unselectable_other_row(window) -> None:
    for _ in range(6):
        _post(window, label="L00")
    for index in range(1, 11):
        _post(window, label=f"L{index:02d}")

    view = window.catch_all_view
    assert view.table.rowCount() == 11
    assert view.table.item(0, COL_NAME).text() == "L00"
    assert view.table.item(9, COL_NAME).text() == "L09"
    other = view.table.item(10, COL_NAME)
    assert other.text() == "Other: 1 headstamps, 1 cases"
    assert other.flags() == Qt.ItemFlag.NoItemFlags
    assert other.foreground().color().name() == QColor(window.palette_colors["text_muted"]).name()
    for row in range(view.table.rowCount()):
        for column in range(view.table.columnCount()):
            assert view.table.cellWidget(row, column) is None
    view.table.setCurrentCell(10, COL_NAME)
    assert view._selected_key is None
    assert not view.assign_button.isEnabled()


def test_a_parent_rows_tooltip_lists_child_labels(window) -> None:
    _post(window, label="WIN", parent="Brass", reason="unassigned")
    _post(window, label="FC", parent="Brass", reason="below_floor")

    view = window.catch_all_view
    item = view.table.item(_row(view, "Brass"), COL_REASON)
    assert "Labels:" in item.toolTip()
    assert "WIN: 1" in item.toolTip()
    assert "FC: 1" in item.toolTip()
    # Mixed reasons are not painted as a below-floor warning.
    assert item.foreground().style() == Qt.BrushStyle.NoBrush


def test_only_a_below_floor_reason_uses_the_warning_color_and_follows_the_theme(window) -> None:
    _post(window, label="BPS", reason="below_floor")
    _post(window, label="IK", reason="unassigned")
    view = window.catch_all_view

    def reason_brush(key: str):
        return view.table.item(_row(view, key), COL_REASON).foreground()

    assert reason_brush("BPS").color().name() == QColor(window.palette_colors["warning"]).name()
    assert reason_brush("IK").style() == Qt.BrushStyle.NoBrush

    window.set_theme("Light")
    assert reason_brush("BPS").color().name() == "#b45309"
    assert reason_brush("BPS").color().name() == QColor(window.palette_colors["warning"]).name()
    assert reason_brush("IK").style() == Qt.BrushStyle.NoBrush

    window.set_theme("Dark")
    assert reason_brush("BPS").color().name() == "#f59e0b"


def test_counts_survive_stop_and_start_and_reset_clears_them(window) -> None:
    _post(window, label="BPS")
    window.bus.post("run/stopped", None)
    window.bus.post("run/started", None)
    window.bus.drain()
    assert window.catch_all_view.tally.catch_all_total == 1
    assert window.slot_grid.cards[0].count_label.text() == "1"

    window.reset_counts()
    assert window.catch_all_view.tally.total == 0
    assert window.catch_all_view.tally.catch_all_total == 0
    assert window.catch_all_view.summary_label.text() == "0 in catch-all of 0 sorted (0%)"
    assert window.slot_grid.cards[0].count_label.text() == "0"


def test_selection_follows_the_headstamp_when_the_order_changes(window) -> None:
    _post(window, label="BPS")
    _post(window, label="IK")
    view = window.catch_all_view
    _select(view, "BPS")
    assert view._selected_key == "BPS"

    _post(window, label="IK")
    _post(window, label="IK")
    assert view.table.item(0, COL_NAME).text() == "IK"
    assert view.table.item(view.table.currentRow(), COL_NAME).text() == "BPS"
    assert view._selected_key == "BPS"


def test_an_ampersand_in_the_name_is_escaped_on_the_button_only(window, config) -> None:
    seed_model(config, {"S&B": 0})
    _post(window, label="S&B")
    view = window.catch_all_view
    assert view.table.item(_row(view, "S&B"), COL_NAME).text() == "S&B"
    _select(view, "S&B")
    assert view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign S&&B to empty slot #1"
    assert QKeySequence.mnemonic(view.assign_button.text()).isEmpty()


def test_assign_button_states(window, config) -> None:
    seed_model(config, {"WIN": 4, "BPS": 0, "UPSIDE DOWN": 0})
    _post(window, label="GHOST", reason="unknown")
    _post(window, label="WIN", reason="below_floor")
    _post(window, label="BPS", reason="below_floor")
    _post(window, label="UPSIDE DOWN", reason="special")
    view = window.catch_all_view

    _select(view, "GHOST")
    assert not view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign GHOST to empty slot"
    assert "isn't in the model" in view.assign_button.toolTip()

    _select(view, "WIN")
    assert not view.assign_button.isEnabled()
    assert view.assign_button.text() == "→ #4"
    assert "confidence floor" in view.assign_button.toolTip()
    assert "slot #4" in view.assign_button.toolTip()

    # Below the floor, but not yet routed: still assignable.
    _select(view, "BPS")
    assert view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign BPS to empty slot #1"

    _select(view, "UPSIDE DOWN")
    assert view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign UPSIDE DOWN to empty slot #1"

    _post(window, label="")
    _select(view, "(empty)")
    assert not view.assign_button.isEnabled()
    assert "isn't in the model" in view.assign_button.toolTip()


def test_assign_is_disabled_when_every_slot_is_taken(window, config) -> None:
    assignments = {f"H{slot}": slot for slot in range(1, 8)}
    assignments["BPS"] = 0
    seed_model(config, assignments)
    _post(window, label="BPS")
    view = window.catch_all_view
    _select(view, "BPS")
    assert not view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign BPS to empty slot"
    assert view.assign_button.toolTip() == "No empty slot left."


def test_an_external_assignment_drops_the_row_and_keeps_the_bin_total(window, config) -> None:
    seed_model(config, {"BPS": 0, "IK": 0})
    for _ in range(4):
        _post(window, label="BPS")
    _post(window, label="IK")
    view = window.catch_all_view
    _select(view, "BPS")

    config.set_headstamp_slot("BPS", 6)
    window.bus.post("run/assignment_changed", {"label": "BPS", "slot": 6, "source": "editor"})
    window.bus.drain()

    assert view.summary_label.text() == "5 in catch-all of 5 sorted (100%)"
    assert window.slot_grid.cards[0].count_label.text() == "5"
    assert _names(view) == ["IK"]
    assert view._selected_key is None
    assert view.assign_button.text() == "Assign to empty slot"
    assert view.assigned_label.text() == "Assigned this session: BPS → #6 (4 already in bin 0)"
    assert not view.assigned_label.isHidden()

    config.set_headstamp_slot("BPS", 0)
    window.bus.post("run/assignment_changed", {"label": "BPS", "slot": 0, "source": "editor"})
    window.bus.drain()

    assert _names(view) == ["BPS", "IK"]
    assert view.table.item(_row(view, "BPS"), 2).text() == "4"
    assert view.assigned_label.isHidden()


def test_assigning_mid_run_fills_an_empty_slot_and_says_so(window, config, caplog) -> None:
    seed_model(config, {"BPS": 0, "WIN": 3})
    _post(window, label="BPS", reason="unassigned")
    view = window.catch_all_view
    _select(view, "BPS")
    window._is_running = True
    events: list[dict] = []
    window.bus.subscribe("run/assignment_changed", events.append)

    with caplog.at_level(logging.INFO, logger="sorter.ui.app"):
        view.assign_button.click()
    window.bus.drain()

    assert config.slot_for_headstamp("BPS") == 1
    assert "slot assignment: 'BPS' -> slot 1 (source=catch_all, running=True)" in caplog.text
    assert window.statusBar().currentMessage() == (
        "BPS → Slot 1. Put an empty bin there; cases already in the wheel still drop in the catch-all."
    )
    assert events and events[-1] == {"label": "BPS", "slot": 1, "source": "catch_all"}
    assert _names(view) == []
    assert view.summary_label.text() == "1 in catch-all of 1 sorted (100%)"
    assert window.slot_grid.cards[0].count_label.text() == "1"
    assert view.assigned_label.text() == "Assigned this session: BPS → #1 (1 already in bin 0)"
    assert view._selected_key is None
    assert view.assign_button.text() == "Assign to empty slot"
    assert "BPS" in window.slot_grid.cards[1].names_label.text()


def test_assigning_a_parent_row_writes_the_parent_slot(window, config) -> None:
    mid = seed_model(config, {"WIN": 3, "FC": 0})
    brass = HeadstampParentRepo(config.db).add(mid, "Brass")
    win = next(h for h in HeadstampRepo(config.db).list_for_model(mid) if h.name == "WIN")
    HeadstampRepo(config.db).set_parent(win.id, brass.id)
    config.set_use_parent_classifications(True)
    _post(window, label="WIN", parent="Brass", reason="unassigned")
    view = window.catch_all_view
    _select(view, "Brass")
    assert view.assign_button.text() == "Assign Brass to empty slot #1"

    view.assign_button.click()

    assert config.slot_for_headstamp("WIN") == 1
    parent = HeadstampParentRepo(config.db).get(brass.id)
    assert parent is not None and parent.slot == 1
    child = next(h for h in HeadstampRepo(config.db).list_for_model(mid) if h.name == "WIN")
    assert child.slot == 3
    assert _names(view) == []
    assert view.assigned_label.text() == "Assigned this session: Brass → #1 (1 already in bin 0)"
    assert view.assign_button.text() == "Assign to empty slot"


def test_a_mixed_row_keeps_only_what_a_slot_does_not_fix(window, config) -> None:
    seed_model(config, {"BPS": 0, "IK": 0})
    for _ in range(3):
        _post(window, label="BPS", reason="unassigned")
    for _ in range(2):
        _post(window, label="BPS", reason="below_floor")
    _post(window, label="IK", reason="unassigned")
    view = window.catch_all_view
    _select(view, "BPS")

    view.assign_button.click()

    assert view.summary_label.text() == "6 in catch-all of 6 sorted (100%)"
    assert window.slot_grid.cards[0].count_label.text() == "6"
    assert _names(view) == ["BPS", "IK"]
    assert view.table.item(_row(view, "BPS"), 2).text() == "2"
    assert view.table.item(_row(view, "BPS"), COL_REASON).text() == "Below floor"
    assert view.assigned_label.text() == "Assigned this session: BPS → #1 (3 already in bin 0)"
    # The leftover row cannot be assigned again, so the click moves on.
    assert view._selected_key == "IK"
    assert view.assign_button.text() == "Assign IK to empty slot #2"

    config.set_headstamp_slot("BPS", 0)
    window.bus.post("run/assignment_changed", {"label": "BPS", "slot": 0, "source": "editor"})
    window.bus.drain()

    assert view.table.item(_row(view, "BPS"), 2).text() == "5"
    assert view.assigned_label.isHidden()


def test_assigning_from_the_panel_selects_the_new_top_row(window, config) -> None:
    seed_model(config, {"BPS": 0, "IK": 0, "SIG": 0})
    for _ in range(3):
        _post(window, label="BPS")
    for _ in range(2):
        _post(window, label="IK")
    _post(window, label="SIG")
    view = window.catch_all_view
    _select(view, "BPS")

    view.assign_button.click()

    assert _names(view) == ["IK", "SIG"]
    assert view._selected_key == "IK"
    assert view.assign_button.isEnabled()
    assert view.assign_button.text() == "Assign IK to empty slot #2"

    view.assign_button.click()

    assert _names(view) == ["SIG"]
    assert view._selected_key == "SIG"
    assert view.assigned_label.text() == ("Assigned this session: BPS → #1 (3 already in bin 0), IK → #2 (2)")


def test_reset_clears_the_assigned_line(window, config) -> None:
    seed_model(config, {"BPS": 0})
    _post(window, label="BPS")
    view = window.catch_all_view
    _select(view, "BPS")
    view.assign_button.click()
    assert not view.assigned_label.isHidden()

    window.reset_counts()

    assert view.tally.catch_all_total == 0
    assert view.assigned_label.isHidden()
    assert _names(view) == []
