"""Simulated energy and money savings after a confirmed automatic shutoff."""

from __future__ import annotations

from datetime import datetime


ENERGY_TARIFF_INR_PER_KWH = 8.0
SIMULATED_SAVINGS_NOTE = (
    "All energy consumption, power and savings values are simulated estimates "
    "for academic demonstration purposes. They are not actual electricity-meter measurements."
)


def compute_savings(
    before_w: float,
    after_w: float,
    waste_started_at: datetime | None,
    confirmed_at: datetime,
) -> tuple[float, float, float, float]:
    """Return power reduction W, energy Wh, energy kWh, and money INR.

    Duration is waste_started_at until confirmation. Positive savings require a
    real power drop and a positive elapsed time.
    """

    reduction = float(before_w) - float(after_w)
    if reduction <= 0 or waste_started_at is None:
        return max(reduction, 0.0), 0.0, 0.0, 0.0
    seconds = (confirmed_at - waste_started_at).total_seconds()
    if seconds <= 0:
        return reduction, 0.0, 0.0, 0.0
    hours = seconds / 3600.0
    energy_wh = reduction * hours
    energy_kwh = energy_wh / 1000.0
    money = energy_kwh * ENERGY_TARIFF_INR_PER_KWH
    return reduction, energy_wh, energy_kwh, money
