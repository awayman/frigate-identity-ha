# Frigate Identity - Home Assistant Integration

A Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

## Features

- **Real-time person identification** - Uses Frigate's facial recognition as primary source
- **ReID continuity** - Maintains identity when faces are not visible
- **Per-person tracking** - Track location, zones, and confidence for each person
- **Live snapshots** - MQTT camera entities for real-time person snapshots
- **Vehicle detection** - Safety alerts when vehicles detected with children outside
- **Supervision tracking** - Monitor if children are supervised by adults
- **Zone-aware** - Integrates with Frigate zones for safety monitoring
- **Two-tier architecture** - Fast MQTT snapshots + accurate API embeddings

## Prerequisites

Before using this integration, you must have:

1. **Home Assistant** (2023.x or later)
2. **MQTT Broker** configured in Home Assistant (e.g., Mosquitto)
3. **Frigate** with facial recognition configured
4. **Frigate Identity Service** running and connected to MQTT
   - See [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) for deployment

## Quick Start

📘 **New to Home Assistant configuration?** Start here: [QUICK_START.md](QUICK_START.md)

For complete setup, see [CONFIGURATION_EXAMPLES.md](CONFIGURATION_EXAMPLES.md) which includes:
- MQTT camera entities for live person snapshots
- Template sensors for per-person tracking
- Supervision detection sensors
- Safety automation examples
- Dashboard configuration
- Frigate MQTT snapshot configuration

## Blueprints

This integration includes **Home Assistant Blueprints** for easy automation setup:

📋 **Available Blueprints** (in `custom_components/frigate_identity/blueprints/automation/frigate_identity/`):

1. **Child Danger Zone Alert** - Alert when child enters dangerous zone without supervision
2. **Vehicle with Children Outside** - Alert when vehicle detected and children are outside
3. **Supervision Detection** - Binary sensor to track if child is supervised
4. **Notification Action Handlers** - Handle "Adult Present" and "View Camera" buttons

### Using Blueprints

When you install this integration via HACS, the blueprints are automatically included in your installation. To use them:

1. Go to **Settings → Automations & Scenes → Blueprints**
2. Click **"Import Blueprint"**
3. Use the blueprint URL from the repository, or copy the blueprint files from:
   `<config>/custom_components/frigate_identity/blueprints/automation/frigate_identity/`
   to:
   `/config/blueprints/automation/frigate_identity/`
4. Click **"Create Automation"** → **"Start with a blueprint"**
5. Select a Frigate Identity blueprint and configure

No YAML editing required!

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click "Integrations"
3. Click the three dots menu → "Custom repositories"
4. Add `https://github.com/awayman/frigate-identity-ha`
5. Select "Integration" as the category
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Clone this repository into your `custom_components` directory:
   ```bash
   git clone https://github.com/awayman/frigate-identity-ha.git \
     ~/.homeassistant/custom_components/frigate_identity
   ```

2. Restart Home Assistant

## Configuration

This integration requires minimal configuration. After installation, it will automatically:

1. Subscribe to `identity/person/#` MQTT topics
2. Create two sensors:
   - `sensor.frigate_identity_last_person` - Most recently detected person
   - `sensor.frigate_identity_all_persons` - All currently tracked persons

**No YAML configuration required!** Simply install the integration and it will start working.

For advanced configuration (per-person sensors, supervision tracking, safety automations), see [CONFIGURATION_EXAMPLES.md](CONFIGURATION_EXAMPLES.md).

## Setup Instructions

### 1. Deploy Frigate Identity Service

Follow the [Frigate Identity Service documentation](https://github.com/awayman/frigate_identity_service) to deploy the core service:

**Docker (Recommended):**
```bash
docker run -d \
  --name frigate-identity \
  -e MQTT_BROKER=192.168.1.100 \
  -e MQTT_PORT=1883 \
  awayman/frigate-identity:latest
```

**Standalone (Python):**
```bash
git clone https://github.com/awayman/frigate_identity_service.git
cd frigate_identity_service
pip install -r requirements.txt
MQTT_BROKER=192.168.1.100 python identity_service.py
```

### 2. Install Home Assistant Integration

Use HACS or manual installation (see Installation section above).

### 3. Configure MQTT

Ensure your MQTT broker is accessible and properly configured in Home Assistant.

## MQTT Topics

The integration subscribes to and publishes to the following topics:

**Identity Service → Home Assistant:**
- `identity/person/{person_id}` - Person identification events with location, zones, confidence
- `identity/snapshots/{person_id}` - Real-time person snapshots (JPEG)
- `identity/snapshots/{person_id}/metadata` - Snapshot correlation metadata
- `identity/vehicle/detected` - Vehicle detection events

**Data Format:**
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

## Troubleshooting

### Integration not showing sensors

1. **MQTT Connection**: Verify MQTT is properly configured and running
2. **Frigate Identity Service**: Ensure the core service is running and publishing to MQTT
3. **Topics**: Check that the service is publishing to the configured `mqtt_topic_prefix`
4. **Home Assistant Logs**: Enable debug logging in `configuration.yaml`:
   ```yaml
   logger:
     logs:
       custom_components.frigate_identity: debug
   ```

### Debug Logging

Enable MQTT debug logging to troubleshoot:

```yaml
logger:
  logs:
    homeassistant.components.mqtt: debug
    custom_components.frigate_identity: debug
```

## Support

For issues with this integration, please open an issue on [GitHub](https://github.com/awayman/frigate-identity-ha/issues).

For issues with the Frigate Identity Service itself, see [frigate_identity_service](https://github.com/awayman/frigate_identity_service/issues).

## License

See [LICENSE](LICENSE) file for details.
