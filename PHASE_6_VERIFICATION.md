# Phase 6 — Duration-based waste detection and simulated savings

Phase 6 extends the existing automatic shutoff. The ESP32 firmware, MQTT topics, Phase 3 console service, and Phase 5 monitoring layout remain. Current and power stay simulated.

## What was already there

- Empty-room detection with MQTT OFF commands
- Acknowledgement on `/state` plus confirming telemetry
- Demo buttons for light / fan / AC left on
- `control_actions` history on the dashboard

## What Phase 6 adds

1. Configurable hold time before OFF (`WASTE_HOLD_SECONDS`)
2. Waste-event fields and savings on confirmed actions
3. Analytics API endpoints
4. Energy Saving Analytics panel and manual ON/OFF controls

## Hold-time settings

| Use | `WASTE_HOLD_SECONDS` |
| :--- | :--- |
| Wokwi classroom demo | `30` |
| Normal local testing | `60` |
| Real-world report example | `300` (5 minutes) |

Set the value in the project `.env` and restart `py -m phase4`. One backend setting is enough.

## Waste workflow

1. Room is unoccupied and light, fan or AC is still on.
2. Backend creates a `watching` event and stores `waste_started_at`.
3. If occupancy returns, or every load turns off, the event becomes `cancelled`.
4. If the condition lasts for the hold time, the backend sends one OFF command and the event becomes `pending`.
5. A matching ESP32 acknowledgement is required.
6. A newer telemetry sample must show every targeted load off.
7. Only then is the event `confirmed`, and simulated savings are stored.

Missing acknowledgement or confirmation becomes `unconfirmed` / `failed`, never `confirmed`.

## Savings formulas

Only confirmed events count.

```text
power_reduction_w = before_w - after_w
energy_saved_wh   = power_reduction_w × hours(waste_started_at → confirmation)
energy_saved_kwh  = energy_saved_wh / 1000
money_saved_inr   = energy_saved_kwh × 8
```

If power does not fall, savings stay zero. All values are simulated estimates.

## New and extended API routes

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/rooms/{id}/waste-events` | Waste-event list |
| `GET` | `/rooms/{id}/waste-events/{event_id}` | One event |
| `GET` | `/rooms/{id}/savings` | Confirmed totals |
| `GET` | `/rooms/{id}/analytics` | Daily/weekly consumption and savings |
| `GET` | `/savings` | Global confirmed totals |
| `POST` | `/rooms/{id}/commands` | Manual MQTT ON/OFF |
| `GET` | `/rooms/{id}/control-actions` | Existing history, now includes savings fields |

## Demonstrate the 30-second Wokwi case

1. `AUTO_LOAD_OFF=1` and `WASTE_HOLD_SECONDS=30` in `.env`
2. Start PostgreSQL, `py -m phase4`, and the dashboard
3. Start Wokwi. Leave the room unoccupied. Set current mode to zero.
4. Click **Simulate light left on**
5. Watch the yellow LED stay on through the short demo window, then through the 30-second hold
6. The backend sends OFF. The panel moves to **Confirmed** with before/after power and estimated savings

## Limits

- Savings are simulated. There is no physical electricity meter.
- Only samples that reached the backend are counted.
- Five minutes is a report example. The live demo uses 30 seconds.
