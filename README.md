# Frigate Identity - Home Assistant Integration

A Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

## Features

- **Real-time person identification** - Uses Frigate's facial recognition as primary source
- **ReID continuity** - Maintains identity when faces are not visible
- **Per-person tracking** - Track location, zones, and confidence for each person
- **Live snapshots** - MQTT camera entities for real-time person snapshots
- **Automated dashboard generation** - One command creates a full Lovelace dashboard with bounded snapshots and location for every tracked person
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

## Dashboard Generation

The `examples/generate_dashboard.py` script creates a **full Lovelace dashboard** for any set of tracked persons with a single command.

For **automatic dashboard regeneration** whenever your `persons.yaml` or camera areas change, see the optional [AppDaemon automation setup](DASHBOARD_SETUP.md#part-7--appdaemon-fully-automatic-updates) in [DASHBOARD_SETUP.md](DASHBOARD_SETUP.md).

### Using `persons.yaml` from the Identity Service

If you already have the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) configured, point the generator directly at its `persons.yaml` — no need to retype names:

```bash
pip install pyyaml
python examples/generate_dashboard.py \
    --persons-file /path/to/frigate_identity_service/persons.yaml \
    --output /config/frigate_identity
```

The generator reads **all useful metadata** from `persons.yaml`:

| Field | Effect on generated config |
|---|---|
| Name (map key) | Person included in dashboard, sensors, cameras |
| `camera` | Default camera mapping for `frigate_integration` mode |
| `role: child` or `requires_supervision: true` | Supervision binary sensor generated; dashboard card gets **Supervised** row |
| `role: trusted_adult` or `can_supervise: true` | Listed as supervisor in all children's supervision sensors |
| `dangerous_zones` | Danger-zone automation generated per child with those zones |

The supervision binary sensors automatically use **HA Area assignments**
(`area_name('camera.<name>')`) to determine cross-camera co-location — no extra
configuration is needed if your cameras are already assigned to Areas in
Home Assistant (Settings → Areas & Zones).

An optional top-level `camera_zones` section provides explicit overrides for
cameras that are not assigned to HA Areas:

```yaml
# Only needed for cameras WITHOUT an HA Area assignment:
camera_zones:
  backyard: back_yard
  patio:    back_yard
```

> **Note:** Frigate zones are pixel-regions scoped to a single camera and
> cannot be used for cross-camera supervision.  HA Areas (or `camera_zones`
> overrides) are the correct mechanism for multi-camera yards.

**Example `persons.yaml`** (from `awayman/frigate_identity_service`):

```yaml
persons:
  Alice:
    role: child
    age: 5
    requires_supervision: true
    dangerous_zones: [street, neighbor_yard]
    camera: backyard
  Bob:
    role: child
    age: 10
    requires_supervision: true
    dangerous_zones: [street]
    camera: front_door
  Dad:
    role: trusted_adult
    can_supervise: true
    camera: driveway
  Mom:
    role: trusted_adult
    can_supervise: true
```

Running the generator against this file produces **four** ready-to-use files:

| File | Contents |
|---|---|
| `mqtt_cameras.yaml` | MQTT camera entities for Alice, Bob, Dad, Mom |
| `template_sensors.yaml` | Location sensors **+** supervision binary sensors for Alice & Bob |
| `dashboard.yaml` | Full dashboard — child cards include a **Supervised** row |
| `danger_zone_automations.yaml` | Danger-zone MQTT automations for Alice & Bob (edit `notify.notify` first) |

You can also add extra persons not in the file by appending them as positional arguments:

```bash
python examples/generate_dashboard.py --persons-file persons.yaml Grandma
```

### Snapshot source options

Use `--snapshot-source` to choose how each person's bounded snapshot is displayed.  Pick the option that best matches your setup:

| `--snapshot-source` | Snapshot entity | Needs official Frigate integration | Needs MQTT camera config |
|---|---|---|---|
| `mqtt` *(default)* | `camera.<person>_snapshot` | No | Yes |
| `frigate_api` | `image.<person>_snapshot` (template) | No | No |
| `frigate_integration` | `image.<camera>_person` | **Yes** | No |

> **Official Frigate HA integration note** – The official
> [Frigate integration](https://github.com/blakeblackshear/frigate-hass-integration)
> creates `image.<camera_name>_person` and `camera.<camera_name>_person` entities
> that show the **latest detection on a specific camera**, regardless of who was
> detected.  These are camera-aware, not identity-aware, so they cannot
> distinguish Alice from Bob.  Use `frigate_integration` mode when you already
> have the official integration installed and want to avoid adding extra config;
> use `mqtt` or `frigate_api` mode when you need per-person identity tracking
> (the snapshot follows the person across cameras).

### Quick start (names on the command line)

```bash
# Requires Python 3 and PyYAML
pip install pyyaml

# mqtt mode (default) – identity-correlated MQTT camera entities
python examples/generate_dashboard.py --output /config/frigate_identity \
    Alice Bob Dad Mom

# frigate_api mode – HA template image entities, no MQTT cameras needed
python examples/generate_dashboard.py --snapshot-source frigate_api \
    --output /config/frigate_identity Alice Bob Dad Mom

# frigate_integration mode – reuse official Frigate integration entities
python examples/generate_dashboard.py --snapshot-source frigate_integration \
    --cameras Alice:backyard Bob:front_door Dad:driveway Mom:backyard \
    --output /config/frigate_identity Alice Bob Dad Mom
```

**mqtt / frigate_api** – reference the generated files in `configuration.yaml`:

```yaml
mqtt:
  camera: !include frigate_identity/mqtt_cameras.yaml  # mqtt mode only

template: !include frigate_identity/template_sensors.yaml

automation: !include frigate_identity/danger_zone_automations.yaml  # when children have dangerous_zones
```

Restart Home Assistant, then go to **Settings → Dashboards → (your dashboard) → Edit → Raw configuration editor** and paste the contents of `dashboard.yaml`.

Each person gets a card that shows:
- 📸 **Bounded snapshot** – the latest cropped image from Frigate
- 📍 **Location** – which Frigate camera last detected them
- 🗺 **Zones** – active Frigate zones
- 🎯 **Confidence** – identification confidence score
- 🕐 **Last Seen** – timestamp of last detection
- 👁 **Supervised** – whether a trusted adult is nearby *(children only, when `persons.yaml` has role data)*

Re-run the script whenever you add or remove tracked persons.  See `examples/dashboard.yaml` for a full example output.

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
