"""Catch-All breakdown — the right-hand panel (CLAUDE.md §5).

Slot 0 is where a case goes when the run cannot put it in a bin. This panel
says which headstamps those were and why, counted from the same successful
``run/result`` events the slot card uses, so the header matches the card.
Counts survive Stop/Start; ``QtMainWindow._clear_counts`` is what zeroes them.

The table is items only — no cell widgets (CLAUDE.md §5). It ranks only
headstamps that would still land in slot 0 if seen now: giving one a slot
drops its unassigned and unknown cases so the next one moves up. Below
floor, upside down and batch full stay, and a mixed row shows only that
remainder. The header stays the physical bin total. A line under the table
names what left the ranking and how many of those cases are already in bin 0.

The one action sits on the selection bar under the table, keyed on the
headstamp name so a re-sort does not lose the selection. Assigning from the
panel then selects the next headstamp that can still be assigned. ``&`` in a
name goes through ``formatting.escape_mnemonic``. Only a below-floor reason
takes the palette's warning colour ("Hue is meaning"); ``apply_palette``
re-bakes that brush because an item foreground is outside the stylesheet.

Subscribes ``run/result`` and ``run/assignment_changed`` on ``win.bus``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..control.catch_all import (
    BELOW_FLOOR,
    EMPTY_KEY,
    CatchAllBucket,
    CatchAllTally,
    assigned_session_line,
    fixed_by_assignment,
    percent,
    reason_summary,
    reason_tooltip,
)
from .formatting import escape_mnemonic

COLUMNS = ("#", "Headstamp", "Count", "Share", "Reason")
COL_RANK, COL_NAME, COL_COUNT, COL_SHARE, COL_REASON = range(5)

_FALLBACK_WARNING = "#f59e0b"
_FALLBACK_MUTED = "#9a9a9a"


def _summary(tally: CatchAllTally) -> str:
    caught = tally.catch_all_total
    total = tally.total
    return f"{caught} in catch-all of {total} sorted ({percent(caught, total)}%)"


class CatchAllView(QWidget):
    """The breakdown table and its one-click assign button."""

    def __init__(self, win: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._win = win
        self.tally = CatchAllTally()
        # The selected headstamp's key, not its row: a new case re-sorts the
        # table and the row number moves.
        self._selected_key: str | None = None
        # Keys assigned away from the ranking, in the order it happened.
        self._session_order: list[str] = []
        self._open_top: list[CatchAllBucket] = []
        # Set for the refresh that follows the panel's own Assign click.
        self._prefer_next_assignable = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.summary_label = QLabel(_summary(self.tally), self)
        self.summary_label.setObjectName("catchAllSummary")
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setObjectName("catchAllTable")
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(1)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        outer.addWidget(self.table, 1)

        self.assigned_label = QLabel("", self)
        self.assigned_label.setObjectName("catchAllAssigned")
        self.assigned_label.setWordWrap(True)
        self.assigned_label.hide()
        outer.addWidget(self.assigned_label)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.assign_button = QPushButton("Assign to empty slot", self)
        self.assign_button.setObjectName("action")
        self.assign_button.clicked.connect(self._assign_selected)
        bar.addWidget(self.assign_button)
        outer.addLayout(bar)

        self._update_button()
        win.bus.subscribe("run/result", self._on_result)
        win.bus.subscribe("run/assignment_changed", self._on_assignment_changed)

    # ----- bus -----------------------------------------------------------------

    def _on_result(self, result: Any) -> None:
        # Same gate as the slot card: a failed cycle carries a slot but did
        # not land, and counting it would drift from the card.
        if not isinstance(result, dict) or not result.get("ok"):
            return
        self.tally.add(result)
        self.refresh()

    def _on_assignment_changed(self, _payload: Any) -> None:
        # The tally is historical. The ranking and the button ask the live config.
        self.refresh()

    def reset(self) -> None:
        """Zero the breakdown. The dashboard's Reset counts is the caller."""
        self.tally.reset()
        self._selected_key = None
        self._session_order.clear()
        self.refresh()

    def apply_palette(self) -> None:
        """Re-bake the below-floor brush from the live palette."""
        self.refresh()

    # ----- table ---------------------------------------------------------------

    def refresh(self) -> None:
        self.summary_label.setText(_summary(self.tally))
        self._sync_session_order()
        self._paint_session_line()
        self._open_top, other = self.tally.open_ranking(self._has_slot)
        selected = self._first_assignable_key() if self._prefer_next_assignable else self._selected_key
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        caught = self.tally.catch_all_total
        warning = self._color("warning", _FALLBACK_WARNING)
        muted = self._color("text_muted", _FALLBACK_MUTED)
        for rank, bucket in enumerate(self._open_top, start=1):
            self._add_bucket_row(rank, bucket, caught, warning)
        other_keys, other_cases = other
        if other_keys:
            self._add_other_row(other_keys, other_cases, caught, muted)
        self._restore_selection(selected)
        self.table.blockSignals(False)
        self._update_button()

    def _sync_session_order(self) -> None:
        """Remember who left the ranking, and forget them once the slot is gone."""
        active = [
            bucket.key
            for bucket in self.tally.buckets()
            if self._has_slot(bucket.key) and fixed_by_assignment(bucket) > 0
        ]
        active_set = set(active)
        self._session_order = [key for key in self._session_order if key in active_set]
        for key in active:
            if key not in self._session_order:
                self._session_order.append(key)

    def _paint_session_line(self) -> None:
        by_key = {bucket.key: bucket for bucket in self.tally.buckets()}
        entries: list[tuple[str, list[int], int]] = []
        for key in self._session_order:
            bucket = by_key.get(key)
            slots = self._assigned_slots(key)
            if bucket is None or not slots:
                continue
            entries.append((key, slots, fixed_by_assignment(bucket)))
        text = assigned_session_line(entries)
        self.assigned_label.setText(text)
        self.assigned_label.setVisible(bool(text))

    def _first_assignable_key(self) -> str | None:
        """The first ranked headstamp the Assign button can still act on."""
        if self._win.config.first_empty_slot() is None:
            return None
        for bucket in self._open_top:
            if self._has_slot(bucket.key) or not self._known(bucket.key):
                continue
            return bucket.key
        return None

    def _add_bucket_row(self, rank: int, bucket: CatchAllBucket, caught: int, warning: QColor) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (
            str(rank),
            bucket.key,
            str(bucket.count),
            f"{percent(bucket.count, caught)}%",
            reason_summary(bucket),
        )
        below_only = set(bucket.reasons) == {BELOW_FLOOR}
        tip = reason_tooltip(bucket)
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, bucket.key)
            item.setToolTip(tip)
            if column == COL_REASON and below_only:
                item.setForeground(QBrush(warning))
            self.table.setItem(row, column, item)

    def _add_other_row(self, n_keys: int, n_cases: int, caught: int, muted: QColor) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        phrase = f"Other: {n_keys} headstamps, {n_cases} cases"
        values = ("", phrase, str(n_cases), f"{percent(n_cases, caught)}%", "")
        brush = QBrush(muted)
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(brush)
            item.setToolTip(phrase)
            self.table.setItem(row, column, item)

    def _restore_selection(self, key: str | None) -> None:
        self._selected_key = None
        if not key:
            self.table.clearSelection()
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_NAME)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                self.table.setCurrentCell(row, COL_NAME)
                self._selected_key = key
                return
        self.table.clearSelection()

    def _on_selection_changed(self) -> None:
        item = self.table.item(self.table.currentRow(), COL_NAME)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            self._selected_key = None
        else:
            stored = item.data(Qt.ItemDataRole.UserRole)
            self._selected_key = stored if isinstance(stored, str) else None
        self._update_button()

    def _color(self, role: str, fallback: str) -> QColor:
        colors = getattr(self._win, "palette_colors", None) or {}
        return QColor(str(colors.get(role) or fallback))

    # ----- assign --------------------------------------------------------------

    def _assigned_slots(self, key: str) -> list[int]:
        config = self._win.config
        if config.run_package_mode:
            return list(config.slots_for_headstamp_package(key))
        slot = config.slot_for_headstamp(key)
        if slot:
            return [int(slot)]
        return []

    def _has_slot(self, key: str) -> bool:
        return bool(self._assigned_slots(key))

    def _known(self, key: str) -> bool:
        if not key or key == EMPTY_KEY:
            return False
        return self._win.config.slot_for_headstamp(key) is not None

    def _bucket(self, key: str) -> CatchAllBucket | None:
        for bucket in self._open_top:
            if bucket.key == key:
                return bucket
        return None

    def _update_button(self) -> None:
        button = self.assign_button
        key = self._selected_key
        bucket = self._bucket(key) if key else None
        if key is None or bucket is None:
            button.setEnabled(False)
            button.setText("Assign to empty slot")
            button.setToolTip("Select a headstamp.")
            return
        if not self._known(key):
            button.setEnabled(False)
            button.setText(escape_mnemonic(f"Assign {key} to empty slot"))
            button.setToolTip("This label isn't in the model, so it can't be assigned to a slot.")
            return
        assigned = self._assigned_slots(key)
        if assigned:
            shown = assigned[0]
            button.setEnabled(False)
            button.setText(f"→ #{shown}")
            where = ", ".join(f"#{slot}" for slot in assigned)
            noun = "slot" if len(assigned) == 1 else "slots"
            if set(bucket.reasons) == {BELOW_FLOOR}:
                button.setToolTip(
                    f"{key} is already routed to {noun} {where}. These cases were below the "
                    "confidence floor, so they stayed in the catch-all."
                )
            else:
                button.setToolTip(f"{key} is already routed to {noun} {where}.")
            return
        empty = self._win.config.first_empty_slot()
        if empty is None:
            button.setEnabled(False)
            button.setText(escape_mnemonic(f"Assign {key} to empty slot"))
            button.setToolTip("No empty slot left.")
            return
        button.setEnabled(True)
        button.setText(escape_mnemonic(f"Assign {key} to empty slot #{empty}"))
        button.setToolTip(f"Put an empty bin in slot {empty}. Cases already in the wheel still drop in the catch-all.")

    def _assign_selected(self) -> None:
        key = self._selected_key
        if not key or not self.assign_button.isEnabled():
            return
        assign = getattr(self._win, "assign_from_catch_all", None)
        if assign is None:
            return
        assign(key)
        # A failed assign leaves the row where it was. A successful one moves
        # the selection to the next headstamp that can still take a bin, so
        # Assign can be clicked straight down the list.
        self._prefer_next_assignable = self._has_slot(key)
        self.refresh()
        self._prefer_next_assignable = False


def build_catch_all_view(win: Any) -> CatchAllView:
    return CatchAllView(win)
