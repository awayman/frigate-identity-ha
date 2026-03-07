# Frigate Identity - Home Assistant Integration

A Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

## Table of Contents

- [Features](#features)
- [Quick Setup (5 steps)](#quick-setup-5-steps)
- [What Gets Created](#what-gets-created)
- [Blueprints](#blueprints)
- [Dashboard](#dashboard)
- [Configuration](#configuration)
  - [Config Flow](#config-flow)
  - [Person Profile Services](#person-profile-services)
- [Services](#services)
- [Snapshot Sources](#snapshot-sources)
- [MQTT Topics](#mqtt-topics)
- [Installation](#installation)
  - [HACS (Recommended)](#hacs-recommended)
  - [Manual Installation](#manual-installation)
- [Troubleshooting](#troubleshooting)
  - [Integration not showing sensors](#integration-not-showing-sensors)
  - [Dashboard not appearing](#dashboard-not-appearing)
  - [Debug Logging](#debug-logging)
- [Support](#support)
- [License](#license)

## Features

- **Real-time person identification** — Uses Frigate's facial recognition as primary source
- **ReID continuity** — Maintains identity when faces are not visible
- **Per-person tracking** — Track location, zones, and confidence for each person
- **Live snapshots** — Per-person MQTT camera entities created automatically
- **Auto-generated dashboard** — Dedicated Lovelace dashboard created and updated automatically
- **Supervision tracking** — Binary sensors track if children are supervised by adults
- **Blueprint automations** — Safety blueprints auto-deployed to HA on integration load
- **Vehicle detection** — Safety alerts when vehicles detected with children outside
- **Zone-aware** — Uses HA Areas for cross-camera zone grouping
- **Config flow UI** — Full setup via Settings → Integrations (no YAML editing)
- **Person profile services** — Mark children/adults and define per-child safe zones from HA services
- **Debug controls** — Toggle Frigate Identity Service debug mode from Home Assistant
- **HACS auto-update** — Install via HACS, get updates automatically

## Quick Setup (5 steps)

📘 **Full walkthrough**: [QUICK_START.md](QUICK_START.md)

1. **Install Frigate Identity Service** and verify it is publishing person events to MQTT
2. **Install via HACS**: Add `https://github.com/awayman/frigate-identity-ha` as a custom repository
3. **Restart Home Assistant**
4. **Settings → Integrations → Add → Frigate Identity** — configure MQTT prefix and snapshot/dashboard options
5. **Done!** — sensors, cameras, dashboard, and blueprints are all created automatically

## What Gets Created

After adding the integration, the following entities are automatically created:

| Entity | Description |
|---|---|
| `sensor.frigate_identity_last_person` | Last detected person name + attributes |
| `sensor.frigate_identity_all_persons` | Count of all tracked persons + data dict |
| `sensor.frigate_identity_<name>_location` | Per-person: state = camera, attrs = zones/confidence/source |
| `camera.frigate_identity_<name>_snapshot` | Per-person MQTT camera with latest cropped snapshot |
| `binary_sensor.frigate_identity_<name>_supervised` | Per-child: is a trusted adult nearby? |
| `switch.frigate_identity_manual_supervision` | Manual supervision override for notification handlers |

Persons are discovered from Home Assistant `person.*` entities on startup and from MQTT messages at runtime.
New persons detected via MQTT get entities created dynamically.

## Blueprints

Blueprints are **automatically deployed** to `/config/blueprints/automation/frigate_identity/` when the integration loads. Go to **Settings → Automations → Blueprints** to use them:

| Blueprint | Purpose |
|---|---|
| Child Danger Zone Alert | Alert when child enters a dangerous zone without supervision |
| Unknown Person Alert | Alert when an unrecognised person is detected |
| Supervision Detection | Template binary sensor for child supervision tracking |
| Vehicle with Children Outside | Alert when vehicle detected and children are outside |
| Notification Action Handlers | Handle "Adult Present" and "View Camera" notification buttons |

## Dashboard

A dedicated Lovelace dashboard (`/lovelace/frigate-identity`) is auto-generated and updated. It includes:

- Header with person tracker status
- Person cards grouped by HA Area (or flat layout if no areas assigned)
- Each person card shows: snapshot, location, zones, confidence, source, last seen
- Children's cards include a supervised status row

The dashboard regenerates automatically when:
- New persons are discovered
- HA Area assignments change
- Daily at a configurable time (default 03:00)

To manually refresh: call the `frigate_identity.regenerate_dashboard` service.

## Configuration

### Config Flow

All settings are configured via the UI:

| Setting | Default | Description |
|---|---|---|
| MQTT topic prefix | `identity` | Prefix for MQTT topics (e.g., `identity/person/#`) |
| Snapshot source | `mqtt` | `mqtt`, `frigate_api`, or `frigate_integration` |
| Auto-generate dashboard | `true` | Automatically create/update the dedicated dashboard |
| Dashboard refresh time | `03:00` | Daily dashboard refresh time (HH:MM) |
| Dashboard name | `Kids` | Sidebar title used for the dedicated Lovelace dashboard |

Change settings any time via **Settings → Integrations → Frigate Identity → Configure**.

### Person Profile Services

Use Home Assistant services to mark children and define safe zones directly from HA.

#### `frigate_identity.update_person_profile`

Fields:
- `person_name` (required): Person display name
- `is_child` (optional): `true` for child, `false` for adult
- `safe_zones` (optional): list of Frigate zone names where the child can be unsupervised

Example service call:

```yaml
service: frigate_identity.update_person_profile
data:
  person_name: Alice
  is_child: true
  safe_zones:
    - safe_play_area
    - patio
```

#### `frigate_identity.update_child_safe_zones`

Backward-compatible alias for updating safe zones only.

```yaml
service: frigate_identity.update_child_safe_zones
data:
  person_name: Alice
  safe_zones:
    - safe_play_area

## Services

The integration registers these Home Assistant services:

| Service | Purpose |
|---|---|
| `frigate_identity.regenerate_dashboard` | Force dashboard regeneration immediately |
| `frigate_identity.get_registry_status` | Log current person registry state for troubleshooting |
| `frigate_identity.set_debug_mode` | Publish debug on/off command to Frigate Identity Service |
| `frigate_identity.update_person_profile` | Set child/adult status and safe zones for a person |
| `frigate_identity.update_child_safe_zones` | Backward-compatible alias for safe-zones-only updates |
```

## Snapshot Sources

| Mode | Snapshot entity | Needs Frigate integration | Needs MQTT camera config |
|---|---|---|---|
| `mqtt` *(default)* | `camera.frigate_identity_<name>_snapshot` | No | Automatic |
| `frigate_api` | `image.frigate_identity_<name>_snapshot_image` | No | No |
| `frigate_integration` | `image.<person>_person` | Yes | No |

## MQTT Topics

The integration subscribes to these topics (prefix is configurable):

| Topic | Purpose |
|---|---|
| `identity/person/#` | Person identification events (JSON) |
| `identity/snapshots/{person}` | Cropped JPEG snapshots per person |

**Message format:**
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

## Installation

### HACS (Recommended)

1. Open HACS → Integrations
2. Click ⋮ menu → **Custom repositories**
3. Add `https://github.com/awayman/frigate-identity-ha`, category **Integration**
4. Click **Install** → **Restart Home Assistant**
5. **Settings → Integrations → Add → Frigate Identity**

### Manual Installation

Copy the `custom_components/frigate_identity` folder to your HA config directory, restart HA, then add via Settings → Integrations.

## Troubleshooting

### Integration not showing sensors

1. Verify MQTT is configured and the identity service is publishing
2. Check the MQTT topic prefix matches (default: `identity`)
3. Enable debug logging:
   ```yaml
   logger:
     logs:
       custom_components.frigate_identity: debug
   ```

### Dashboard not appearing

1. Dashboard auto-generation requires Lovelace in storage mode (the default)
2. Call `frigate_identity.regenerate_dashboard` service to force refresh
3. Check HA logs for dashboard push errors

### Debug Logging

```yaml
logger:
  logs:
    homeassistant.components.mqtt: debug
    custom_components.frigate_identity: debug
```

## Support

- **Integration issues**: [GitHub Issues](https://github.com/awayman/frigate-identity-ha/issues)
- **Service issues**: [frigate_identity_service](https://github.com/awayman/frigate_identity_service/issues)

## License

See [LICENSE](LICENSE) file for details.
