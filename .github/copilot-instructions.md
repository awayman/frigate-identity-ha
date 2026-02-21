# Copilot Instructions for Frigate Identity - Home Assistant Integration

## Project Summary

This repository contains **Frigate Identity**, a Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

The integration:
- Provides real-time person identification using facial recognition and ReID
- Tracks person location, zones, and confidence per person
- Creates per-person camera, sensor, and binary_sensor entities dynamically
- Auto-generates a Lovelace dashboard
- Auto-deploys safety blueprints (child supervision, vehicle detection)
- Configurable via UI config flow (no YAML editing required)

## Technology Stack

- **Language**: Python 3.11+
- **Framework**: Home Assistant Custom Component (config flow + options flow)
- **Integration**: MQTT for real-time messaging (HA MQTT integration dependency)
- **Distribution**: HACS (Home Assistant Community Store)
- **CI**: GitHub Actions (hassfest, HACS validation, ruff linting)
- **Dependencies**: Home Assistant 2024.1.0+, MQTT broker, PyYAML

## Architecture

### Core Pattern: PersonRegistry + Dynamic Entity Creation

The integration uses a **PersonRegistry** (`person_registry.py`) as the central data hub.
Persons are discovered from two sources:
1. `persons.yaml`  loaded on startup for metadata (role, age, dangerous_zones, etc.)
2. MQTT messages — any new person_id triggers dynamic entity creation

Platforms (sensor, camera, binary_sensor, switch) register listeners with the registry.
When a new person appears, the registry fires the listener and the platform creates entities.

### Data Flow

```
MQTT identity/person/{name}  →  sensor.py (LastPersonSensor)  →  PersonRegistry
                                                                      
                                                              fires listeners
                                                                      
                                                    camera.py / binary_sensor.py / sensor.py
                                                    create per-person entities
```

### Entry Point

`__init__.py`  `async_setup_entry()`:
1. Creates PersonRegistry, loads persons.yaml
2. Deploys blueprints (copies .yaml from bundled dir to /config/blueprints/)
3. Forwards platforms: SENSOR, CAMERA, BINARY_SENSOR, SWITCH
4. Sets up dashboard auto-generation (debounced, daily refresh, service)

## Project Structure

```
.
 custom_components/frigate_identity/
    __init__.py              # Entry point, blueprint deploy, dashboard orchestration
    const.py                 # All constants (DOMAIN, CONF_*, DEFAULT_*, TOPIC_*)
    config_flow.py           # UI config flow + options flow
    strings.json             # Config flow UI labels
    translations/en.json     # English translations (same as strings.json)
    person_registry.py       # PersonRegistry + PersonData (central data hub)
    sensor.py                # LastPerson, AllPersons, per-person Location sensors
    camera.py                # Per-person MQTT snapshot cameras
    binary_sensor.py         # Per-child supervision binary sensors
    switch.py                # Manual supervision override switch
    dashboard.py             # Lovelace dashboard generation + push
    manifest.json            # Integration metadata (config_flow: true)
    blueprints/automation/frigate_identity/
        child_danger_zone_alert.yaml
        unknown_person_alert.yaml
        supervision_detection.yaml
        vehicle_children_outside_alert.yaml
        notification_action_handlers.yaml
 examples/                    # Legacy CLI dashboard generator
 appdaemon/                   # Legacy AppDaemon app (no longer needed)
 .github/
    copilot-instructions.md  # This file
    workflows/
        ci.yml               # hassfest + HACS validation + ruff
        release.yml          # Auto-create GitHub Release on v* tags
 release.py                   # Version bump + git tag + push
 CHANGELOG.md
 README.md
 QUICK_START.md
 CONFIGURATION_EXAMPLES.md
 DASHBOARD_SETUP.md
 hacs.json
```

## Code Standards and Best Practices

### Python Code Style
- Follow **PEP 8** style guidelines; enforced by **ruff** in CI
- Use **type hints** for all function parameters and return types
- Use `from __future__ import annotations` for forward compatibility
- Follow Home Assistant's coding standards and patterns
- Use `async`/`await` for all I/O operations (MQTT, HA state, file I/O)

### Logging
- Use the `logging` module with appropriate log levels
- Logger naming: `_LOGGER = logging.getLogger(__name__)`
- Use `_LOGGER.debug()` for verbose diagnostic information
- Use `_LOGGER.error()` for errors that should be visible to users
- Avoid logging sensitive data (person names, camera URLs, etc. in production logs)

### Error Handling
- Use broad exception handling only where necessary
- Always log exceptions with context
- Handle MQTT payload parsing errors gracefully
- Never crash the integration due to malformed MQTT messages

### Home Assistant Patterns
- Use `@callback` decorator for synchronous callback functions
- Subscribe to MQTT topics in `async_added_to_hass()`
- Unsubscribe in `async_will_remove_from_hass()`
- Use `async_write_ha_state()` to update entity state
- Store state in `_attr_native_value` and attributes in `_attr_extra_state_attributes`
- Use `hass.data[DOMAIN][entry.entry_id]` for shared runtime data
- Config flow validates inputs; options flow for post-setup changes

## Key Module Details

### const.py
All shared constants. Topic templates use `{prefix}` placeholder:
- `TOPIC_PERSON = "{prefix}/person/#"`
- `TOPIC_SNAPSHOTS = "{prefix}/snapshots/{person}"`

### config_flow.py
- `async_step_user`: MQTT prefix + persons_file path (validates file exists)
- `async_step_options`: snapshot_source, auto_dashboard, refresh_time
- Options flow mirrors step_options for post-setup changes

### person_registry.py
- `PersonData`: dataclass per person (name, camera, zones, confidence, source, metadata from YAML)
- `PersonRegistry.async_update_person()`: called by LastPersonSensor on MQTT msg
- Listener pattern: `registry.async_add_listener(callback)`  platforms use this
- Helper methods: `adults()`, `children()`, `children_with_danger_zones()`

### sensor.py
- `FrigateIdentityLastPersonSensor`: subscribes to `{prefix}/person/#`, parses JSON, updates registry
- `FrigateIdentityAllPersonsSensor`: state = count, attributes = all person data
- `FrigateIdentityPersonLocationSensor`: per-person, state = camera name

### camera.py
- `FrigateIdentityCamera`: subscribes to `{prefix}/snapshots/{person}`, raw JPEG via MQTT
- Only created when `snapshot_source == "mqtt"`

### binary_sensor.py
- `FrigateIdentitySupervisionSensor`: per-child, ON = adult in same zone
- Zone resolution: camera_zones override → HA Area registry → camera name fallback
- 60-second supervision timeout

### dashboard.py
- `async_generate_dashboard()`: builds Lovelace view, pushes to storage
- Person cards grouped by HA Area when available
- Regeneration debounced (5s) on person/area changes

### __init__.py
- `_deploy_blueprints()`: copies .yaml from bundled dir to `/config/blueprints/automation/frigate_identity/`, mtime-based overwrite
- Registers `frigate_identity.regenerate_dashboard` service
- Dashboard: initial 15s delayed generation, daily at configured time, on-demand via service

## MQTT Integration

### Topic Structure
Topics use configurable prefix (default: `identity`):

- `{prefix}/person/#`  JSON person events
- `{prefix}/snapshots/{person}`  binary JPEG

```json
{
  "person_id": "Alice",
  "camera": "backyard",
  "confidence": 0.94,
  "source": "facial_recognition",
  "frigate_zones": ["safe_play_area"],
  "event_id": "1708286380-abc",
  "timestamp": 1708286400000,
  "snapshot_url": "http://frigate:5000/api/events/1708286380-abc/thumbnail.jpg?crop=1"
}
```

### Message Handling
- Always validate and parse JSON payloads safely
- Handle missing fields gracefully (use `payload.get()` with defaults)
- Support multiple field name variations (e.g., `person_id`, `person`, `name`)
- Update state atomically to prevent race conditions

## Testing and Validation

### CI Pipeline
- **hassfest**: Validates manifest.json and integration structure
- **HACS validation**: Ensures HACS compatibility
- **ruff**: Lints Python code in `custom_components/frigate_identity`

### Manual Testing Checklist
When making changes, verify:
1. **Integration loads**: No errors in HA logs during startup
2. **Config flow**: Can add integration via Settings → Integrations
3. **Entities created**: Sensors, cameras, binary sensors appear for persons in persons.yaml
4. **MQTT subscription**: Topics match configured prefix
5. **Dynamic discovery**: New MQTT person triggers entity creation
6. **Dashboard**: Lovelace view auto-generated in storage mode
7. **Blueprints**: Deployed to /config/blueprints/ and visible in Automations
8. **Options flow**: Can change settings via Configure button
9. **Cleanup**: No resource leaks when integration is unloaded/reloaded

### Debug Logging
```yaml
logger:
  logs:
    custom_components.frigate_identity: debug
    homeassistant.components.mqtt: debug
```

## Documentation Standards

### README Files
- Keep **README.md** up-to-date with feature changes
- Update **QUICK_START.md** if setup process changes
- Update **CHANGELOG.md** for every user-facing change

### Code Comments
- Use docstrings for all classes and functions
- Docstrings should describe **what** the code does, not **how**
- Inline comments only for complex logic or non-obvious behavior

## Common Tasks

### Adding a New Entity Platform
1. Create `<platform>.py` with `async_setup_entry()` that registers a registry listener
2. In the listener callback, create entity instances and call `async_add_entities()`
3. Add the platform to `PLATFORMS` list in `__init__.py`
4. Update `manifest.json` if new dependencies needed
5. Document in README.md

### Adding a New Blueprint
1. Create YAML file in `custom_components/frigate_identity/blueprints/automation/frigate_identity/`
2. Follow Home Assistant blueprint schema
3. Test that `_deploy_blueprints()` copies it on next reload
4. Document in README.md

### Adding a Config Option
1. Add `CONF_*` and `DEFAULT_*` constants to `const.py`
2. Add field to `async_step_options` in `config_flow.py`
3. Add labels in `strings.json` and `translations/en.json`
4. Add to options flow `async_step_init` schema
5. Use `entry.options.get(CONF_*, DEFAULT_*)` in consuming code

### Modifying MQTT Topics
1. Update `TOPIC_*` templates in `const.py`
2. Ensure backward compatibility if possible
3. Document topic changes in README.md
4. Coordinate changes with Frigate Identity Service repository

## Versioning and Releases

- Use semantic versioning (MAJOR.MINOR.PATCH)
- Update version in `manifest.json` via `release.py`
- `release.py` bumps version, updates CHANGELOG, tags, and pushes
- GitHub Actions `release.yml` creates a GitHub Release on `v*` tags
- HACS picks up new releases automatically

## Security and Privacy

- **Never log sensitive data**: Person names, camera URLs, or snapshot data should not appear in logs
- **MQTT credentials**: Never hardcode; use Home Assistant's MQTT integration
- **Snapshot URLs**: Handle carefully; they may contain authentication tokens
- **Person IDs**: Treat as potentially sensitive user data

## Related Projects

- **Frigate Identity Service**: https://github.com/awayman/frigate_identity_service
- **Frigate NVR**: https://frigate.video/
- **Home Assistant**: https://www.home-assistant.io/
