# EV Charge Planner

Home Assistant custom integration that estimates **when your EV reaches a target** — full / charge limit, or the SoC needed for configured trips — when charging from **PV surplus** or from the **grid**. It also answers **"I need X by a deadline"** with the grid top-up and the latest time grid charging must start.

The planner is read-only by design: it does not control the wallbox. Use its sensors in your own automations (or next to evcc) to decide when to charge.

**You need:**
- a state-of-charge sensor for the car (%)
- PV power and house consumption sensors in **W**
- the [Solcast PV Forecast](https://github.com/BJReplay/ha-solcast-solar) integration (forecast today / tomorrow sensors)

## Installation

**HACS** (recommended):
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/mholka/ev-charge-planner`, type *Integration*.
2. Search for **EV Charge Planner**, download it and restart Home Assistant.

**Manual:** download `ev_charge_planner.zip` from the [latest release](https://github.com/mholka/ev-charge-planner/releases/latest), unpack it into `config/custom_components/ev_charge_planner/` and restart Home Assistant.

Requires Home Assistant 2025.3 or newer. The integration icon shows in Home Assistant from 2026.3.

## Configuration

Settings → Devices & services → Add integration → **EV Charge Planner**. Everything can be changed later under **Configure**.

| Setting | Notes |
|---|---|
| Battery level | SoC sensor (%), e.g. Tesla battery level |
| Charge limit | optional; target of the *full* scenario (defaults to 100 %) |
| PV power | actual PV production (W); used instead of the forecast for the next 30 minutes |
| House consumption | household load **excluding** the wallbox (W). If it includes the wallbox, charging counts as house load and hides the surplus |
| Wallbox power | optional (W); shown as an attribute of *House consumption estimate* |
| Solcast forecast today / tomorrow | Solcast sensors with the `detailedForecast` attribute (e.g. `sensor.solcast_pv_forecast_forecast_today`) |
| Solcast forecast day 3+ | optional, several allowed (Solcast day 3–7 sensors); extends the PV horizon |
| Usable battery capacity (when new), consumption (km/kWh), efficiency | vehicle model; energy needed = ΔSoC × usable capacity / efficiency |
| Outdoor temperature, winter consumption | optional sensor or weather entity. With it, consumption moves linearly from the normal figure at 20 °C and above to the winter figure at 0 °C and below (10 °C with 6 and 4 km/kWh → 5 km/kWh). Without it, the normal figure always applies |
| Battery health (SoH) | share of the original capacity still usable (default 100 %). 60 kWh at 95 % = 57 kWh usable, so a full charge from 0 % is 57 / 0.9 = 63.3 kWh from the wallbox |
| Charger min / max power | surplus below *min* is not used; charging never exceeds *max* |
| Minimum solar share | 100 % (default) = solar charging only from pure surplus. Lower values let the grid top up weak surplus to the charger minimum (like evcc's solar share); the grid part is reported as `grid_topup_kwh` |
| Automatic 1/3-phase switching | if the wallbox drops to one phase on low surplus: PV counts from the single-phase minimum (≈1.4 kW) up to the single-phase maximum (≈3.7 kW); between that and the 3-phase minimum it stays at the single-phase maximum |
| Minimum battery level | battery level to arrive with on trips; on a round trip, the level you get home with. Also adjustable on the dashboard via `number.ev_minimum_soc` |
| House baseline mode | **Rolling average** of house consumption over a window, or a **fixed** value in W |

### Quick trip

On the **EV** device set **Quick trip: distance (one way)** and **Quick trip: round trip**. The quick-trip sensors (`sensor.ev_quick_trip_*`) update immediately, so you can ask "how long to charge for 120 km?" without saving a trip.

### Trips

Each trip is a sub-entry: on the integration page choose **Add trip** (name, one-way distance, round trip). Trips can be edited or deleted at any time; their entities update without a restart.

Target SoC for a trip = `minimum battery level + distance × (2 if round trip) / km_per_kWh / (capacity × health) × 100`.

## Entities

Each scenario has the same set of entities. *Full* and *Quick trip* live on the **EV** device, with the scenario as a name prefix (e.g. *Full: charging time on solar*). Each saved trip gets its own device, **EV &lt;trip&gt;**.

| Entity | Name | Meaning |
|---|---|---|
| `sensor.ev_<scenario>_energy_needed` | Energy to charge | kWh still to charge from the current SoC to the target; changes as the car drives and charges (attributes `target_soc`, `reachable`) |
| `sensor.ev_<trip>_trip_energy` | Energy the trip uses | kWh the trip itself uses, charging losses included, whatever the SoC (quick trip and trips only) |
| `sensor.ev_<scenario>_charge_time_grid` | Charging time on grid | charging time at max charger power |
| `sensor.ev_<scenario>_charge_time_pv` | Charging time on solar | time the charger has to run on solar, nights excluded (attributes `done_at`, `extrapolated`, `grid_topup_kwh`); `unknown` if the forecast has no usable surplus |
| `sensor.ev_<scenario>_eta_grid` | Ready at (grid) | done when charging at max charger power from now |
| `sensor.ev_<scenario>_eta_pv` | Ready at (solar) | done on PV surplus only; `unknown` if not reached within the forecast |
| `binary_sensor.ev_<scenario>_ready` | Charged (*Yes*/*No*) | SoC ≥ target |

Deadline planning:

| Entity | Meaning |
|---|---|
| `datetime.ev_deadline` (*Departure time*) | when the energy is needed |
| `select.ev_deadline_scenario` (*Charge for*) | Full, Quick trip or a saved trip |
| `sensor.ev_deadline_grid_topup` (*Grid energy needed before departure*) | kWh that must come from the grid |
| `sensor.ev_latest_grid_start` (*Start grid charging by*) | latest time to switch to full-power charging; `unknown` if solar suffices |
| `binary_sensor.ev_ready_on_time` (*Will be ready on time*, *Yes*/*No*) | *Yes* while the departure target can still be met, at the latest by grid charging from now |
| `sensor.ev_deadline_pv_energy` (*Solar energy by departure*) | kWh the charger can take from PV surplus between now and departure, capped at what the *Charge for* target needs (attributes `uncapped_kwh`, `target_soc`, `grid_topup_kwh`, `until`, `projection`) |
| `sensor.ev_deadline_soc_at_departure` (*Battery level at departure (solar only)*) | SoC % at departure when charging from PV surplus only |
| `sensor.ev_deadline_pv_share` (*Solar share of the charge*) | % of *Energy to charge* that PV covers by departure |

These three are `unknown` without a future departure time. The `projection` attribute is always there: one point per forecast slot (`time`, `pv_w`, `surplus_w`, `charge_w`, cumulative `energy_kwh`, projected `soc`) until departure, or over the whole forecast without one. It isn't recorded in the database.

#### Graph: solar charging until departure

With [apexcharts-card](https://github.com/RomRider/apexcharts-card) (HACS):

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Solar charging until departure
graph_span: 24h
span:
  start: minute
yaxis:
  - id: kwh
    min: 0
  - id: soc
    opposite: true
    min: 0
    max: 100
series:
  - entity: sensor.ev_deadline_pv_energy
    name: Charged from solar
    type: area
    curve: stepline
    yaxis_id: kwh
    unit: kWh
    data_generator: |
      return entity.attributes.projection.map(p => [new Date(p.time).getTime(), p.energy_kwh]);
  - entity: sensor.ev_deadline_pv_energy
    name: Battery level
    type: line
    curve: smooth
    yaxis_id: soc
    unit: "%"
    data_generator: |
      return entity.attributes.projection.map(p => [new Date(p.time).getTime(), p.soc]);
  - entity: sensor.ev_deadline_pv_energy
    name: Target
    type: line
    yaxis_id: soc
    unit: "%"
    data_generator: |
      const t = entity.attributes.target_soc;
      return entity.attributes.projection.map(p => [new Date(p.time).getTime(), t]);
```

Solar:

| Entity | Name | Meaning |
|---|---|---|
| `sensor.ev_pv_phase` | Solar production phase | `before_production`, `producing`, `paused` (forecast says sun, but PV below 50 W) or `after_production` |

Diagnostics:

| Entity | Name | Meaning |
|---|---|---|
| `sensor.ev_pv_surplus_forecast` | Solar energy available for the car today | kWh the charger could take from PV surplus between now and midnight (attributes `tomorrow_kwh`, `horizon_kwh` for the whole forecast, `forecast_slots`, `horizon_end`, `peak_forecast_w`, `live_pv_w`, `no_forecast_data`, `entities_without_data`) |
| `sensor.ev_consumption` | Consumption used for planning | km/kWh after the temperature correction (attribute `temperature_c`) |
| `sensor.ev_house_baseline` | House consumption estimate | W used as house load (attributes `nowcast_factor`, `charging_power_w`) |

### Example automation

Notify when the car won't make it to departure on time:

```yaml
automation:
  - alias: "EV won't be ready on time"
    triggers:
      - trigger: state
        entity_id: binary_sensor.ev_ready_on_time
        to: "off"
    actions:
      - action: notify.notify
        data:
          message: >
            The car won't be ready by departure. Start grid charging now
            ({{ states('sensor.ev_deadline_grid_topup') }} kWh from the grid).
```

## How it works

- **PV ETA**: walks forecast slots from now; surplus = PV − house baseline. For the next 30 minutes the measured PV power replaces the forecast. The charger runs at `min(surplus, max)` when surplus ≥ min; with phase switching it runs on one phase for smaller surplus; otherwise not at all. Forecast gaps count as no PV.
- **Deadline**: charge on PV surplus, then switch to full power at the latest moment *s* where `PV(now → s) + P_max × (deadline − s) ≥ energy needed`.
- **PV charge time**: the charging hours from the same walk. If the target is beyond the forecast horizon, the remainder is extrapolated at the average PV charging power (`extrapolated: true`).
- Updates every 5 minutes and immediately when SoC, charge limit, forecast, deadline or deadline scenario change.

The calculation lives in `planner.py` without Home Assistant imports.

## Troubleshooting

- **Solar values stay `unknown` or 0.0 kWh**: check the attributes of *Solar energy available for the car today*. `no_forecast_data: true` or a non-empty `entities_without_data` means the Solcast sensors aren't configured or lack `detailedForecast`. `live_pv_w` should match your PV power in W. A surplus below the charger minimum counts as 0 (enable phase switching or lower the solar share if your wallbox charges on less).

- **Diagnostics**: Settings → Devices & services → EV Charge Planner → ⋮ → **Download diagnostics**. The file has your settings, the source entity states and the latest planner result; attach it to bug reports.
- **Debug logs**: they show the inputs (SoC, PV, house baseline, consumption, forecast slots) and each scenario's result on every update.

  ```yaml
  logger:
    logs:
      custom_components.ev_charge_planner: debug
  ```

Report problems in [issues](https://github.com/mholka/ev-charge-planner/issues).

## Development

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the fork workflow, branch names and guidelines.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

## Limitations

- Solcast is the only supported forecast (no Forecast.Solar yet), and only its `pv_estimate` (no p10/p90).
- Power sensors must report W, not kW.
- Charge taper above ~80 % and dynamic tariffs are not modelled.
- The temperature correction uses the current outdoor temperature, not the forecast for the trip.
- Wallbox control is out of scope by design.

## License

[MIT](LICENSE)
