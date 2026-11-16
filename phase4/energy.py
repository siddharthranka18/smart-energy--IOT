"""Server-side energy interval for one accepted telemetry sample.

The ESP32 publishes a running energy and cost counter. That counter returns
to zero when the board restarts. These helpers turn two successive counters
into the amount that should be added to the database total.
"""

from __future__ import annotations

from dataclasses import dataclass


# A tiny drop is float noise. A reboot sends the device counter back toward zero.
ENERGY_RESET_MARGIN_WH = 0.0001


@dataclass(frozen=True)
class EnergyInterval:
    energy_delta_wh: float
    cost_delta_inr: float
    device_counter_reset: bool


def energy_interval(
    previous_energy_wh: float | None,
    previous_cost_inr: float | None,
    _previous_sequence: int | None,
    _previous_uptime_ms: int | None,
    energy_wh: float,
    cost_inr: float,
    _sequence: int,
    _uptime_ms: int,
) -> EnergyInterval:
    """Return the energy and cost added by this sample.

    A restart is recognized only when the device energy counter falls.
    """

    if previous_energy_wh is None or previous_cost_inr is None:
        return EnergyInterval(energy_wh, cost_inr, False)

    if energy_wh + ENERGY_RESET_MARGIN_WH < previous_energy_wh:
        return EnergyInterval(max(energy_wh, 0.0), max(cost_inr, 0.0), True)

    return EnergyInterval(
        max(energy_wh - previous_energy_wh, 0.0),
        max(cost_inr - previous_cost_inr, 0.0),
        False,
    )
