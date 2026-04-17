"""Cost tracking dialog.

Queries the Deepgram Management API billing breakdown endpoint to display
approximate usage costs for the current project, optionally scoped to a
specific API key via the accessor filter.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

log = logging.getLogger(__name__)

BILLING_URL = "https://api.deepgram.com/v1/projects/{project_id}/billing/breakdown"


def _round_to_2c(amount: float) -> float:
    """Round to the nearest 2 cents."""
    return round(amount * 50) / 50


def _fmt(amount: float) -> str:
    return f"${_round_to_2c(amount):.2f}"


@dataclass
class CostBuckets:
    today: float
    week: float
    all_time: float


def _week_start(today: date) -> date:
    # Monday-based week
    return today - timedelta(days=today.weekday())


def _fetch_cost(
    project_id: str,
    api_key: str,
    start: date,
    end: date,
    accessor: str = "",
) -> float:
    """Fetch total USD cost for the date range from the billing breakdown endpoint."""
    url = BILLING_URL.format(project_id=project_id)
    params: dict[str, str] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    if accessor:
        params["accessor"] = accessor
    resp = httpx.get(
        url,
        headers={"Authorization": f"Token {api_key}"},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    total = 0.0
    for row in data.get("results", []):
        total += float(row.get("dollars", 0.0) or 0.0)
    return total


class CostDialog(QDialog):
    def __init__(self, project_id: str, api_key: str, accessor: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("VoiceType — Usage & Costs")
        self.setMinimumWidth(380)
        self._project_id = project_id
        self._api_key = api_key
        self._accessor = accessor

        layout = QVBoxLayout(self)

        scope = "this API key" if accessor else "project-wide"
        header = QLabel(f"Deepgram costs ({scope}), rounded to nearest 2¢")
        header.setStyleSheet("color: #6B7280; font-size: 12px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()
        self._today_lbl = QLabel("Loading…")
        self._week_lbl = QLabel("Loading…")
        self._all_lbl = QLabel("Loading…")
        for lbl in (self._today_lbl, self._week_lbl, self._all_lbl):
            lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E2229;")
        form.addRow("Today:", self._today_lbl)
        form.addRow("This week:", self._week_lbl)
        form.addRow("All-time:", self._all_lbl)
        layout.addLayout(form)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #D83636; font-size: 12px;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        btn_row = QVBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._load)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btn_row.addWidget(refresh)
        btn_row.addWidget(close)
        layout.addLayout(btn_row)

        QTimer.singleShot(0, self._load)

    def _load(self) -> None:
        self._today_lbl.setText("Loading…")
        self._week_lbl.setText("Loading…")
        self._all_lbl.setText("Loading…")
        self._status.setText("")

        project_id = self._project_id
        api_key = self._api_key
        accessor = self._accessor

        if not project_id or not api_key:
            self._status.setText("Set API key and Project ID in Settings first.")
            self._today_lbl.setText("—")
            self._week_lbl.setText("—")
            self._all_lbl.setText("—")
            return

        def _worker() -> None:
            try:
                today = date.today()
                tomorrow = today + timedelta(days=1)  # end is exclusive-ish; add 1 day
                week_start = _week_start(today)
                # Deepgram launched in 2018 — safe lower bound for "all time"
                epoch = date(2018, 1, 1)

                today_cost = _fetch_cost(project_id, api_key, today, tomorrow, accessor)
                week_cost = _fetch_cost(project_id, api_key, week_start, tomorrow, accessor)
                all_cost = _fetch_cost(project_id, api_key, epoch, tomorrow, accessor)
                buckets = CostBuckets(today=today_cost, week=week_cost, all_time=all_cost)
                err = ""
            except httpx.HTTPStatusError as e:
                buckets = None
                err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            except Exception as e:
                buckets = None
                err = str(e)

            QTimer.singleShot(0, lambda: self._apply(buckets, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply(self, buckets: CostBuckets | None, err: str) -> None:
        if buckets is None:
            self._today_lbl.setText("—")
            self._week_lbl.setText("—")
            self._all_lbl.setText("—")
            self._status.setText(err or "Unknown error")
            return
        self._today_lbl.setText(_fmt(buckets.today))
        self._week_lbl.setText(_fmt(buckets.week))
        self._all_lbl.setText(_fmt(buckets.all_time))
