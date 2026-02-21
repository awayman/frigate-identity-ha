# Frigate Identity - Quick Start Guide

This guide will help you get Frigate Identity Service running and integrated with Home Assistant in under 15 minutes.

## Prerequisites Checklist

- [ ] Frigate installed and running
- [ ] Frigate facial recognition configured and trained
- [ ] MQTT broker (Mosquitto) running
- [ ] Home Assistant with MQTT integration configured
- [ ] Frigate Identity Service running and publishing to MQTT

---

## Step 1: Configure Frigate MQTT Snapshots

Edit your Frigate `config.yml` to enable cropped MQTT snapshots:

```yaml
mqtt:
  enabled: true

cameras:
  backyard:
    mqtt:
      enabled: true
      timestamp: true
      bounding_box: true
      crop: true              # Enable cropping!
      height: 400
      quality: 80
  
  driveway:
    mqtt:
      enabled: true
      crop: true
      height: 400
      quality: 80
```

**Restart Frigate** after making changes.

---

## Step 2: Install & Run Frigate Identity Service

```bash
git clone https://github.com/awayman/frigate_identity_service.git
cd frigate_identity_service
pip install -r requirements.txt
```

Edit `.env` with your MQTT broker and Frigate details, then edit `persons.yaml`:

```yaml
persons:
  Alice:
    role: child
    age: 5
    requires_supervision: true
    dangerous_zones: [street, neighbor_yard]
  
  Dad:
    role: trusted_adult
    can_supervise: true
```

Start the service:

```bash
python identity_service.py
```

---

## Step 3: Install Home Assistant Integration via HACS

1. Open HACS → Integrations
2. Click ⋮ menu → **Custom repositories**
3. Add: `https://github.com/awayman/frigate-identity-ha`
4. Category: **Integration**
5. Click **Install**
6. **Restart Home Assistant**

---

## Step 4: Add the Integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **"Frigate Identity"**
3. Configure:
   - **MQTT topic prefix**: `identity` (default)
   - **Path to persons.yaml**: `/config/persons.yaml` (or wherever your file is)
4. Choose options:
   - **Snapshot source**: `mqtt` (default, recommended)
   - **Auto-generate dashboard**: Yes
5. **Done!**

---

## What Happens Automatically

After adding the integration, everything is set up for you:

### Entities Created
- `sensor.frigate_identity_last_person` — most recently detected person
- `sensor.frigate_identity_all_persons` — count + data for all tracked persons
- `sensor.frigate_identity_<name>_location` — per-person location sensor (camera, zones, confidence)
- `camera.frigate_identity_<name>_snapshot` — per-person MQTT camera with latest snapshot
- `binary_sensor.frigate_identity_<name>_supervised` — per-child supervision tracking
- `switch.frigate_identity_manual_supervision` — manual override for supervision

### Blueprints Deployed
All safety automation blueprints are copied to `/config/blueprints/automation/frigate_identity/`:
- Child Danger Zone Alert
- Unknown Person Alert
- Supervision Detection
- Vehicle with Children Outside Alert
- Notification Action Handlers

### Dashboard Generated
A **Frigate Identity** view is automatically added to your Lovelace dashboard with:
- Person snapshot cards grouped by area
- Location, zones, confidence, and supervision status
- System status summary

---

## Step 5: Create Your First Automation

1. **Settings → Automations & Scenes → Create Automation**
2. **Start with a blueprint**
3. Select **"Frigate Identity - Child Danger Zone Alert"**
4. Fill in:
   - **Child Name**: `Alice`
   - **Dangerous Zones**: `["street", "neighbor_yard"]`
   - **Supervision Sensor**: `binary_sensor.frigate_identity_alice_supervised`
   - **Notification Service**: `mobile_app_your_phone`
5. **Save**

---

## Step 6: Test

1. Walk in front of a camera with face visible
2. Check **Developer Tools → States**:
   - `sensor.frigate_identity_last_person` should update
   - `sensor.frigate_identity_all_persons` should show your data
3. Check the auto-generated **Frigate Identity** dashboard view
4. Walk into a zone marked as dangerous to test safety alerts

---

## Changing Settings

Go to **Settings → Devices & Services → Frigate Identity → Configure** to change:
- MQTT topic prefix
- persons.yaml path
- Snapshot source
- Dashboard auto-generation

To manually refresh the dashboard, call the `frigate_identity.regenerate_dashboard` service.

---

## Troubleshooting

### Integration not showing sensors

1. Verify MQTT is configured and the identity service is publishing
2. Check that the MQTT topic prefix matches (default: `identity`)
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

---

## Success Checklist

- [ ] Identity service running and connected to MQTT
- [ ] Integration added via Settings → Integrations
- [ ] Seeing person detections in HA sensors
- [ ] Per-person snapshot cameras showing images
- [ ] Frigate Identity dashboard view visible
- [ ] First safety automation created from blueprint
- [ ] Received test notification on phone
