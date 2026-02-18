# Frigate Identity - Home Assistant Integration

A Home Assistant custom component that integrates with the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) to consume face identity events and expose them as sensors in Home Assistant.

## Features

- Monitors Frigate identity events via MQTT
- Exposes detected faces and identified persons as Home Assistant sensors
- Supports propagation of identities to weaker cameras using ReID heuristics
- Zero configuration after setup (uses existing MQTT broker)

## Prerequisites

Before using this integration, you must have:

1. **Home Assistant** (latest version)
2. **MQTT Broker** configured in Home Assistant (e.g., Mosquitto)
3. **Frigate Identity Service** running separately
   - Consumes Frigate MQTT events
   - Publishes identity events to your MQTT broker
   - See [Frigate Identity Service](https://github.com/awayman/frigate_identity_service) for deployment instructions

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

Add this to your `configuration.yaml`:

```yaml
mqtt:
  broker: 192.168.1.100  # Your MQTT broker address
  port: 1883
  
frigate_identity:
  mqtt_topic_prefix: frigate/identity  # Topic prefix for identity events
```

### Configuration Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `mqtt_topic_prefix` | string | No | `frigate/identity` | MQTT topic prefix for identity events |

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

The integration publishes to the following topics:

- `frigate/identity/detected_faces` - Detected faces
- `frigate/identity/identified_persons` - Identified persons
- `frigate/identity/propagated_identities` - Propagated identities across cameras

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
