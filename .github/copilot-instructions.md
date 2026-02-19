# Copilot Instructions for Frigate Identity - Home Assistant Integration

## Project Summary

This repository contains **Frigate Identity**, a Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

The integration:
- Provides real-time person identification using facial recognition and ReID
- Tracks person location, zones, and confidence
- Exposes MQTT-based sensors for Home Assistant automation
- Offers blueprints for safety automations (child supervision, vehicle detection)

## Technology Stack

- **Language**: Python 3.11+
- **Framework**: Home Assistant Custom Component
- **Integration**: MQTT for real-time messaging
- **Distribution**: HACS (Home Assistant Community Store)
- **Dependencies**: Home Assistant 2023.12.0+, MQTT broker

## Project Structure

```
.
├── custom_components/frigate_identity/  # Main integration code
│   ├── __init__.py                      # Integration setup and lifecycle
│   ├── sensor.py                        # Sensor entities (Last Person, All Persons)
│   └── manifest.json                    # Integration metadata
├── blueprints/automation/frigate_identity/  # Home Assistant Blueprints
│   ├── child_danger_zone.yaml          # Child safety alerts
│   ├── vehicle_with_children.yaml      # Vehicle detection alerts
│   ├── supervision_detection.yaml      # Supervision tracking
│   └── notification_actions.yaml       # Action handlers for notifications
├── examples/                            # Example configurations and setups
├── README.md                            # Main documentation
├── QUICK_START.md                       # Quick start guide for beginners
├── CONFIGURATION_EXAMPLES.md            # Detailed configuration examples
└── hacs.json                            # HACS repository metadata
```

## Code Standards and Best Practices

### Python Code Style
- Follow **PEP 8** style guidelines
- Use **type hints** for all function parameters and return types
- Use `from __future__ import annotations` for forward compatibility
- Follow Home Assistant's coding standards and patterns
- Use `async`/`await` for all I/O operations (MQTT, Home Assistant state updates)

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

## MQTT Integration

### Topic Structure
The integration subscribes to `identity/person/#` topics with this data format:

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

### No Automated Tests
- This repository does **not** have automated tests
- All changes should be manually validated in a Home Assistant environment
- Test with actual MQTT messages from Frigate Identity Service

### Manual Testing Checklist
When making changes, verify:
1. **Integration loads**: No errors in Home Assistant logs during startup
2. **Sensors created**: Both sensors appear in Home Assistant
3. **MQTT subscription**: Integration subscribes to `identity/person/#` correctly
4. **State updates**: Sensors update when MQTT messages are received
5. **Attributes**: Extra state attributes are populated correctly
6. **Cleanup**: No resource leaks when integration is unloaded/reloaded

### Debug Logging
Enable debug logging to test integration behavior:
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
- Update **CONFIGURATION_EXAMPLES.md** if new configuration options are added

### Code Comments
- Use docstrings for all classes and functions
- Docstrings should describe **what** the code does, not **how**
- Inline comments only for complex logic or non-obvious behavior

### Blueprints
- All blueprints should include:
  - Clear description and purpose
  - Input parameters with descriptions
  - Example configurations
  - Selector types appropriate for Home Assistant UI

## Integration Requirements

### Dependencies
- **Required**: Home Assistant 2023.12.0+
- **Required**: MQTT integration configured in Home Assistant
- **External**: Frigate Identity Service running and publishing to MQTT

### Manifest File
The `manifest.json` must include:
- `domain`: `frigate_identity`
- `dependencies`: `["mqtt"]` (critical for MQTT functionality)
- `config_flow`: `false` (no config flow UI, auto-discovered via MQTT)
- `codeowners`: Maintain attribution

### Version Numbering
- Use semantic versioning (MAJOR.MINOR.PATCH)
- Update version in `manifest.json` for releases
- Update version in `hacs.json` if structure changes

## Common Tasks

### Adding a New Sensor
1. Create sensor class extending `SensorEntity` in `sensor.py`
2. Implement required properties: `name`, `unique_id`, `native_value`
3. Subscribe to appropriate MQTT topics in `async_added_to_hass()`
4. Update state using `async_write_ha_state()`
5. Add sensor to `async_setup_entry()` list
6. Document the sensor in README.md

### Adding a New Blueprint
1. Create YAML file in `blueprints/automation/frigate_identity/`
2. Follow Home Assistant blueprint schema
3. Use appropriate input selectors (`entity`, `zone`, `time`, etc.)
4. Test blueprint can be imported and used in Home Assistant
5. Document in README.md with usage instructions

### Modifying MQTT Topics
1. Ensure backward compatibility if possible
2. Document topic changes in README.md MQTT Topics section
3. Test with both old and new message formats if backward compatible
4. Coordinate changes with Frigate Identity Service repository

## Security and Privacy

- **Never log sensitive data**: Person names, camera URLs, or snapshot data should not appear in logs
- **MQTT credentials**: Never hardcode MQTT credentials; use Home Assistant's MQTT integration
- **Snapshot URLs**: Handle snapshot URLs carefully; they may contain authentication tokens
- **Person IDs**: Treat person IDs as potentially sensitive user data

## Contribution Guidelines

### Making Changes
1. Keep changes minimal and focused
2. Test manually in a Home Assistant environment
3. Update documentation to match code changes
4. Ensure backward compatibility with existing configurations
5. Follow existing code patterns and structure

### Pull Requests
- Provide clear description of what changed and why
- Reference related issues if applicable
- Include testing notes and validation steps
- Update version number if applicable

## Related Projects

- **Frigate Identity Service**: https://github.com/awayman/frigate_identity_service
- **Frigate NVR**: https://frigate.video/
- **Home Assistant**: https://www.home-assistant.io/

## Special Notes

- This is a **custom component**, not part of core Home Assistant
- Users install via HACS or manual installation
- Integration auto-discovers and requires no config flow
- Heavily dependent on MQTT message format from Frigate Identity Service
- Changes should consider both Home Assistant and Frigate Identity Service compatibility
