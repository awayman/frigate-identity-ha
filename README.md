# Frigate Identity - Home Assistant Integration

A Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to provide person identification continuity and location tracking.

## Features

- **Real-time person identification** — Uses Frigate's facial recognition as primary source
- **ReID continuity** — Maintains identity when faces are not visible
- **Per-person tracking** — Track location, zones, and confidence for each person
- **Live snapshots** — Per-person MQTT camera entities created automatically
- **Auto-generated dashboard** — Lovelace view created and updated automatically on setup
- **Supervision tracking** — Binary sensors track if children are supervised by adults
- **Blueprint automations** — Safety blueprints auto-deployed to HA on integration load
- **Vehicle detection** — Safety alerts when vehicles detected with children outside
- **Zone-aware** — Uses HA Areas for cross-camera zone grouping
- **Config flow UI** — Full setup via Settings → Integrations (no YAML editing)
- **HACS auto-update** — Install via HACS, get updates automatically

## Quick Setup (5 steps)

📘 **Full walkthrough**: [QUICK_START.md](QUICK_START.md)

1. **Install Frigate Identity Service** and configure `persons.yaml`
2. **Install via HACS**: Add `https://github.com/awayman/frigate-identity-ha` as a custom repository
3. **Restart Home Assistant**
4. **Settings → Integrations → Add → Frigate Identity** — configure MQTT prefix and persons.yaml path
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

Persons are discovered from `persons.yaml` on startup and from MQTT messages at runtime.
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

A **Frigate Identity** Lovelace view is auto-generated and pushed to your dashboard. It includes:

- Header with system status
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
| persons.yaml path | `/config/persons.yaml` | Path to Frigate Identity Service persons file |
| Snapshot source | `mqtt` | `mqtt`, `frigate_api`, or `frigate_integration` |
| Auto-generate dashboard | `true` | Automatically create/update Lovelace view |
| Dashboard refresh time | `03:00` | Daily dashboard refresh time (HH:MM) |

Change settings any time via **Settings → Integrations → Frigate Identity → Configure**.

### persons.yaml Format

The integration reads person metadata from the Frigate Identity Service's `persons.yaml`:

```yaml
persons:
  Alice:
    role: child
    age: 5
    requires_supervision: true
    dangerous_zones: [street, neighbor_yard]
    camera: backyard
  Dad:
    role: trusted_adult
    can_supervise: true
    camera: driveway

# Optional: override camera→zone mapping for supervision
camera_zones:
  backyard: back_yard
  patio: back_yard
```

| Field | Effect |
|---|---|
| `role: child` / `requires_supervision: true` | Supervision binary sensor created; dashboard card shows Supervised row |
| `role: trusted_adult` / `can_supervise: true` | Listed as supervisor in children's supervision sensors |
| `dangerous_zones` | Used by Child Danger Zone Alert blueprint |
| `camera` | Used for `frigate_integration` snapshot mode |

## Snapshot Sources

| Mode | Snapshot entity | Needs Frigate integration | Needs MQTT camera config |
|---|---|---|---|
| `mqtt` *(default)* | `camera.frigate_identity_<name>_snapshot` | No | Automatic |
| `frigate_api` | `image.frigate_identity_<name>_snapshot_image` | No | No |
| `frigate_integration` | `image.<camera>_person` | Yes | No |

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

## Legacy Tools

The following are still available but **no longer required**:

- **`examples/generate_dashboard.py`** — standalone CLI dashboard generator. Useful if you prefer manual control or YAML-mode dashboards.
- **`appdaemon/`** — AppDaemon app for automatic dashboard regeneration. The integration now handles this natively.

See [CONFIGURATION_EXAMPLES.md](CONFIGURATION_EXAMPLES.md) for advanced manual configuration.

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
