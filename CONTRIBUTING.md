# Contributing to EV Charge Planner

Thanks for your interest! This is a custom [Home Assistant](https://www.home-assistant.io/) integration, released under the [MIT License](LICENSE). By contributing, you agree that your contributions are licensed under the same terms.

## Reporting bugs and ideas

Open an [issue](https://github.com/mholka/ev-charge-planner/issues) first for anything beyond a small fix, so we can agree on the approach before you write code. For bugs, please include:

- Home Assistant and integration versions
- Your configuration (options screen), with entity names anonymised if you prefer
- The diagnostics file: Settings → Devices & services → EV Charge Planner → ⋮ → *Download diagnostics*
- Debug logs, if relevant:

  ```yaml
  logger:
    logs:
      custom_components.ev_charge_planner: debug
  ```

## Workflow

External contributors can't push to this repository, so contributions go through a fork:

1. Fork the repository and clone your fork.
2. Create a branch from `main` (see [branch names](#branch-naming-convention)).
3. Make your change, with tests (see [development setup](#development-setup)).
4. Push to your fork and open a pull request against `main`.

Maintainers use the same branch names, but directly in this repository.

### Branch naming convention

Use clear, descriptive branch names with a prefix:

- `feat/` — new features (e.g. `feat/tariff-planning`)
- `fix/` — bug fixes (e.g. `fix/pv-eta-horizon`)
- `chore/` — maintenance, dependencies, refactoring, CI (e.g. `chore/update-dependencies`)
- `docs/` — documentation updates (e.g. `docs/configuration`)

### Commits and pull requests

- Keep each pull request focused on one change. Separate refactoring from behaviour changes.
- Write commit messages in the imperative mood ("Add quick trip input", not "Added…"). Explain *why* in the body when it isn't obvious.
- Reference the related issue in the PR description (e.g. `Refs #1`, `Fixes #12`).
- Describe how you tested the change, and whether it ran on a real Home Assistant instance.
- CI (hassfest, HACS validation, ruff and pytest) must pass before merging.

## Development setup

Requires Python 3.13, the same version as current Home Assistant.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

To try your changes in Home Assistant, copy or symlink `custom_components/ev_charge_planner` into your test instance's `config/custom_components/`, then restart Home Assistant.

## Code guidelines

- **Planning logic lives in `planner.py`** (plus `forecast.py` and `baseline.py`). Keep these free of Home Assistant imports so they stay unit-testable. Every behaviour change there needs a test in `tests/test_planner.py`, including edge cases.
- **Home Assistant code** follows current HA integration patterns: config entries with `runtime_data`, `DataUpdateCoordinator`, `has_entity_name`, translation keys, and config subentries for trips.
- **Don't break users' setups:**
  - Keep existing entity IDs and unique IDs stable. Display names can change; IDs can't.
  - New options need defaults that keep the current behaviour.
  - If stored config data changes shape, add a config entry migration.
- **User-facing text** goes in `strings.json`. Then run `python scripts/gen_translations.py` to write `translations/en.json`: Home Assistant doesn't resolve `[%key:...%]` references for custom integrations, so the script does, and a test checks the two match. Name entities so a user understands them without the docs.
- **Formatting and linting** are done by `ruff`, configured in `pyproject.toml`.
- **Integration version:** don't bump `version` in `manifest.json` by hand. The release workflow stamps it from the release tag.
- **The integration is read-only by design:** it plans but doesn't switch the wallbox. Proposals to control devices should be discussed in an issue first.

## Releases

Maintainers tag releases as `vX.Y.Z` (or `vX.Y.Z-beta`) on `main` and publish a GitHub release with notes. Publishing runs `.github/workflows/release.yml`, which stamps the tag's version into `manifest.json` and attaches `ev_charge_planner.zip` to the release. HACS installs that zip (`zip_release` in `hacs.json`), so the version Home Assistant shows always matches the release.
