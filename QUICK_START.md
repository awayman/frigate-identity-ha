# Frigate Identity - Quick Start Guide

This guide will help you get Frigate Identity Service running and integrated with Home Assistant in under 30 minutes.

## Prerequisites Checklist

- [ ] Frigate installed and running
- [ ] Frigate facial recognition configured and trained
- [ ] MQTT broker (Mosquitto) running
- [ ] Home Assistant with MQTT integration configured
- [ ] Python 3.9+ installed (for identity service)

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
      required_zones:         # Optional: only publish in these zones
        - safe_play_area
        - near_fence
        - street
  
  driveway:
    mqtt:
      enabled: true
      crop: true
      height: 400
      quality: 80
```

**Restart Frigate** after making changes.

---

## Step 2: Install Frigate Identity Service

### Windows

```powershell
cd C:\Users\YourName\Documents
git clone https://github.com/yourusername/frigate_identity_service.git
cd frigate_identity_service

# Create virtual environment
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Linux/Docker

```bash
git clone https://github.com/yourusername/frigate_identity_service.git
cd frigate_identity_service
pip install -r requirements.txt

# Or use Docker
docker build -t frigate-identity .
```

---

## Step 3: Configure Identity Service

Edit the `.env` file (already created in your repo):

```env
MQTT_BROKER=192.168.1.100      # Your MQTT broker IP
MQTT_PORT=1883
FRIGATE_HOST=http://192.168.1.100:5000  # Your Frigate IP
REID_SIMILARITY_THRESHOLD=0.6
```

Edit `persons.yaml` to match your family:

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

---

## Step 4: Run Identity Service

```powershell
python identity_service.py
```

You should see:
```
Initializing embedding store...
Initializing ReID model: osnet_x1_0
ReID system ready!
Connected to MQTT Broker at 192.168.1.100:1883
Subscribed to: frigate/+/+/update
Subscribed to: frigate/+/person/snapshot
```

---

## Step 5: Install Home Assistant Integration

### Via HACS (Recommended)

1. Open HACS → Integrations
2. Click ⋮ menu → Custom repositories
3. Add: `https://github.com/yourusername/frigate-identity-ha`
4. Category: Integration
5. Click "Install"
6. **Restart Home Assistant**

### Manual Install

```bash
cd /config
mkdir -p custom_components/frigate_identity
cd custom_components/frigate_identity
# Copy files from frigate-identity-ha/custom_components/frigate_identity/
```

---

## Step 6: Add MQTT Camera Entities

Add to Home Assistant `configuration.yaml`:

```yaml
mqtt:
  camera:
    - name: "Alice Snapshot"
      unique_id: "frigate_identity_alice_snapshot"
      topic: "identity/snapshots/Alice"
    
    - name: "Bob Snapshot"
      unique_id: "frigate_identity_bob_snapshot"
      topic: "identity/snapshots/Bob"
    
    - name: "Driveway Vehicle"
      unique_id: "frigate_identity_vehicle"
      topic: "identity/snapshots/vehicle_driveway"
```

**Restart Home Assistant**

---

## Step 7: Install Blueprints

1. Copy blueprint files to Home Assistant:
   ```
   /config/blueprints/automation/frigate_identity/
   ├── child_danger_zone_alert.yaml
   ├── vehicle_children_outside_alert.yaml
   ├── supervision_detection.yaml
   └── notification_action_handlers.yaml
   ```

2. In HA: **Settings → Automations & Scenes → Blueprints**

3. Blueprints should appear automatically

---

## Step 8: Create Your First Automation

1. **Settings → Automations & Scenes → Create Automation**
2. **Start with a blueprint**
3. Select **"Frigate Identity - Child Danger Zone Alert"**
4. Fill in:
   - **Child Name**: `Alice`
   - **Dangerous Zones**: `["street", "neighbor_yard"]`
   - **Notification Service**: `mobile_app_your_phone` (without "notify.")
5. **Save**

---

## Step 9: Add Helper Entities

**Settings → Devices & Services → Helpers → Create Helper**

Create these input booleans:
- `input_boolean.manual_supervision` - Manual supervision override
- `input_boolean.front_gate_open` - Gate status (until you add sensor)

---

## Step 10: Test the System

### Test Detection

1. Walk in front of a camera with face visible
2. Check **Developer Tools → States**:
   - `sensor.frigate_identity_last_person` should update
   - `sensor.frigate_identity_all_persons` should show your data
3. Check **Developer Tools → MQTT**:
   - Listen to `identity/person/#`
   - Should see JSON messages with your name

### Test Snapshot

1. Check `camera.alice_snapshot` (or your name) entity
2. Should show recently cropped image of detected person
3. Updates every ~2 seconds while person in view

### Test Safety Alert

1. Walk into a zone marked as dangerous (e.g., near street)
2. You should receive notification on your phone
3. Check notification includes:
   - Alert message
   - Cropped snapshot
   - Action buttons

---

## Troubleshooting

### No Detections Appearing

**Check Identity Service Logs:**
```
[FACE] Alice identified via facial recognition at backyard
[EMBEDDING] Stored accurate embedding for Alice
```

If not appearing:
1. Verify Frigate face recognition is working
2. Check MQTT broker connectivity
3. Verify topic subscriptions match

### No Snapshots Appearing

1. Check Frigate MQTT config has `crop: true`
2. Verify snapshot topic in MQTT Explorer: `frigate/backyard/person/snapshot`
3. Check HA camera entity subscribes to correct topic

### False Positive Alerts

1. Increase `REID_SIMILARITY_THRESHOLD` (try 0.7)
2. Add supervision sensor to automation blueprint
3. Increase alert cooldown time

### Person Misidentified

1. Check embedding quality (blur, lighting, angle)
2. Retrain Frigate face recognition with more samples
3. Lower `REID_SIMILARITY_THRESHOLD` for stricter matching

---

## Next Steps

- [ ] Set up supervision detection for each child
- [ ] Configure vehicle detection automation
- [ ] Add dashboard (see `examples/dashboard.yaml`)
- [ ] Configure notification action handlers
- [ ] Set up gate sensor integration
- [ ] Test all dangerous zone alerts

---

## Getting Help

- **GitHub Issues**: Report bugs and request features
- **Documentation**: See `CONFIGURATION_EXAMPLES.md` for advanced setups
- **Logs**: Enable debug logging in HA:
  ```yaml
  logger:
    logs:
      custom_components.frigate_identity: debug
  ```

---

## Success Checklist

- [x] ✅ Identity service running and connected to MQTT
- [x] ✅ Seeing person detections in HA sensors
- [x] ✅ MQTT camera entities showing snapshots
- [x] ✅ First safety alert automation created
- [x] ✅ Received test notification on phone
- [ ] 🎯 Ready to configure full safety monitoring!
