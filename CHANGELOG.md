# Changelog

All notable changes to the Frigate Identity HA integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.5] - 2026-02-21

## [0.3.4] - 2026-02-21

## [0.3.3] - 2026-02-21

## [0.3.2] - 2026-02-21

## [0.3.1] - 2026-02-21

## [0.3.0] - 2026-02-21

### Added
- **Config flow** — add the integration via Settings → Integrations → Add (no YAML needed)
- **Options flow** — change settings after setup without removing the integration
- **Per-person camera entities** — MQTT camera per person created automatically
- **Per-person location sensors** — state = current camera, attributes = zones/confidence/source
- **Supervision binary sensors** — per-child, auto-created when persons.yaml has role data
- **Manual supervision switch** — replaces manual `input_boolean` creation
- **Dashboard auto-generation** — Lovelace view created and updated automatically
- **Blueprint auto-deployment** — blueprints copied to HA's blueprints directory on load
- **Person registry** — shared discovery from MQTT + persons.yaml metadata
- **`frigate_identity.regenerate_dashboard` service** — manual dashboard refresh
- **Ruff linting** in CI workflow

### Changed
- Bumped minimum HA version to 2024.1.0
- Added `iot_class: local_push` to manifest
- Added `pyyaml` to requirements
- Sensors now use configurable MQTT topic prefix (default: `identity`)
- `manifest.json` version bumped to 0.2.0

### Removed
- AppDaemon dependency no longer required (functionality absorbed into integration)
- External `generate_dashboard.py` no longer required (kept as optional legacy CLI tool)
- Manual blueprint copy step eliminated
- Manual `input_boolean` helper creation no longer needed

## [0.1.1]

### Fixed
- Minor sensor updates

## [0.1.0]

### Added
- Initial release
- Last person sensor and all persons sensor via MQTT
- AppDaemon dashboard auto-generation
- Blueprint automations for child safety, unknown person alerts, vehicle detection
