# EV Charge Planner

Home Assistant custom integration that estimates **when your EV reaches a target** — full / charge limit, or the SoC needed for configured trips — when charging from **PV surplus** or from the **grid**. It also answers **"I need X by a deadline"** with the grid top-up and the latest time grid charging must start.

The planner is read-only: it does not control the wallbox.

## Installation

HACS → Integrations → ⋮ → Custom repositories → add `https://github.com/mholka/ev-charge-planner` (category *Integration*), install **EV Charge Planner**, restart HA.

Manual: copy `custom_components/ev_charge_planner` into your `config/custom_components/`.

Requires Home Assistant 2025.3 or newer.

## Configuration

Settings → Devices & services → Add integration → **EV Charge Planner**. Everything can be changed later under **Configure**.

| Setting | Notes |
|---|---|
| Battery level | SoC sensor (%), e.g. Tesla battery level |
| Charge limit | optional; target of the *full* scenario (defaults to 100 %) |
| PV power | actual PV production (W); corrects the current forecast slot (now-cast) |
| House consumption | household load **excluding** the wallbox (W) |
| Wallbox power | optional; shown as an attribute |
| Solcast forecast today / tomorrow | Solcast sensors with the `detailedForecast` attribute |
| Solcast forecast day 3+ | optional, several allowed (Solcast day 3–7 sensors); extends the PV horizon |
| Battery capacity, consumption (km/kWh), efficiency | vehicle model; energy needed = ΔSoC × capacity / efficiency |
| Charger min / max power | surplus below *min* is not used; charging never exceeds *max* |
| Automatic 1/3-phase switching | if the wallbox drops to one phase on low surplus: PV counts from the single-phase minimum (≈1.4 kW) up to the single-phase maximum (≈3.7 kW); between that and the 3-phase minimum it stays at the single-phase maximum |
| Arrival reserve | SoC to keep on arrival for trip scenarios |
| House baseline mode | **Rolling average** of house consumption over a window, or a **fixed** value in W |

### Trips

Each trip is a sub-entry: on the integration page choose **Add trip** (name, one-way distance, round trip). Trips can be edited or deleted at any time; their entities update without a restart.

Target SoC for a trip = `reserve + distance × (2 if round trip) / km_per_kWh / capacity × 100`.

## Entities

For the *full* scenario (device **EV**) and each trip (device **EV &lt;trip&gt;**):

| Entity | Meaning |
|---|---|
| `sensor.ev_<scenario>_energy_needed` | kWh the wallbox has to deliver (attributes: `target_soc`, `reachable`) |
| `sensor.ev_<scenario>_charge_time_grid` | charging time at max charger power (duration, like Waze travel time) |
| `sensor.ev_<scenario>_charge_time_pv` | time the charger has to run on PV surplus, nights excluded (attributes: `done_at`, `extrapolated`); `unknown` if the forecast has no usable surplus |
| `sensor.ev_<scenario>_eta_grid` | done at max charger power |
| `sensor.ev_<scenario>_eta_pv` | done on PV surplus only; `unknown` if not reached within the forecast |
| `binary_sensor.ev_<scenario>_ready` | SoC ≥ target |

Deadline planning:

| Entity | Meaning |
|---|---|
| `datetime.ev_deadline` | when the energy is needed |
| `select.ev_deadline_scenario` | which scenario (Full or a trip) |
| `sensor.ev_deadline_grid_topup` | kWh that must come from the grid |
| `sensor.ev_latest_grid_start` | latest time to switch to full-power charging; `unknown` if PV suffices |
| `binary_sensor.ev_deadline_at_risk` | the target cannot be met even with grid charging from now |

Diagnostics:
- `sensor.ev_house_baseline` (W; attributes `nowcast_factor`, `charging_power_w`)
- `sensor.ev_pv_surplus_forecast`: kWh the charger could take from PV surplus within the forecast (attributes `forecast_slots`, `horizon_end`, `peak_forecast_w`, `entities_without_data`). If PV ETAs stay `unknown`, check this first.

## How it works

- **PV ETA**: walks forecast slots from now; surplus = forecast PV − house baseline (current slot scaled by actual/forecast PV, clamped 0.3–2). The charger runs at `min(surplus, max)` when surplus ≥ min; with phase switching it runs on one phase for smaller surplus; otherwise not at all. Forecast gaps count as no PV.
- **Deadline**: charge on PV surplus, then switch to full power at the latest moment *s* where `PV(now → s) + P_max × (deadline − s) ≥ energy needed`.
- **PV charge time**: the charging hours from the same walk. If the target is beyond the forecast horizon, the remainder is extrapolated at the average PV charging power (`extrapolated: true`).
- Updates every 5 minutes and immediately when SoC, charge limit, forecast, deadline or deadline scenario change.

The calculation lives in `planner.py` without Home Assistant imports.

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

## Not yet supported

Charge taper above ~80 %, Forecast.Solar, Solcast p10/p90, wallbox control, dynamic tariffs.
