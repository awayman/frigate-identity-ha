# Frigate Identity - Home Assistant Blueprints

This folder contains automation blueprints that make it easy to set up safety monitoring and person tracking without writing YAML.

## Available Blueprints

### 1. Child Danger Zone Alert
**File:** `child_danger_zone_alert.yaml`

Automatically alerts you when a child enters a dangerous zone (street, neighbor's yard, etc.) without adult supervision.

**Inputs:**
- Child name (must match Frigate face recognition)
- List of dangerous zones
- Optional supervision sensor
- Notification service
- Alert cooldown time

**Features:**
- Includes cropped snapshot in notification
- Action buttons: "Adult Present", "View Camera"
- Configurable cooldown to prevent spam
- Works with or without supervision detection

---

### 2. Vehicle with Children Outside
**File:** `vehicle_children_outside_alert.yaml`

Alerts when a vehicle is detected in the driveway while children are currently outside.

**Inputs:**
- List of children names to monitor
- Driveway camera name
- Optional gate sensor
- Notification service
- Priority escalation setting

**Features:**
- CRITICAL priority if gate is open
- HIGH priority if gate closed or not configured
- Action buttons for acknowledgment
- Checks all configured children

---

### 3. Supervision Detection
**File:** `supervision_detection.yaml`

Creates a binary sensor that indicates if a child is currently supervised by checking if any trusted adult is on the same camera.

**Inputs:**
- Child name
- List of trusted adults
- Supervision timeout (seconds)
- Optional manual override entity

**Features:**
- Automatically detects adult proximity
- Configurable timeout (default 60 seconds)
- Manual override option
- Shows supervising adult in attributes

---

### 4. Notification Action Handlers
**File:** `notification_action_handlers.yaml`

Handles action button presses from safety alert notifications.

**Inputs:**
- Manual supervision input_boolean entity
- Supervision duration (minutes)

**Features:**
- "Adult Present" button activates manual supervision
- Auto-disables after configured duration
- "View Camera" opens Home Assistant app
- Confirmation notifications

---

## Installation

### Method 1: Via HACS Integration Install (Recommended)

When you install the Frigate Identity integration via HACS, the blueprints are automatically included!

1. The blueprints are located in:
   ```
   <config>/custom_components/frigate_identity/blueprints/automation/frigate_identity/
   ```

2. Copy the blueprint files to:
   ```
   /config/blueprints/automation/frigate_identity/
   ```

3. Restart Home Assistant

4. Go to **Settings → Automations & Scenes → Blueprints**

### Method 2: Import from GitHub

You can import blueprints directly from GitHub:

1. Copy the raw blueprint URL from GitHub
2. Go to **Settings → Automations & Scenes → Blueprints**
3. Click **"Import Blueprint"**
4. Paste the URL
5. Click **"Preview"** then **"Import"**

Example URL format:
```
https://raw.githubusercontent.com/awayman/frigate-identity-ha/main/custom_components/frigate_identity/blueprints/automation/frigate_identity/child_danger_zone_alert.yaml
```

---

## Usage Example

### Creating a Danger Zone Alert

1. **Settings → Automations & Scenes**
2. **Create Automation → Start with a blueprint**
3. Select **"Frigate Identity - Child Danger Zone Alert"**
4. Fill in:
   ```
   Child Name: Alice
   Dangerous Zones: ["street", "neighbor_yard", "near_fence"]
   Supervision Sensor: binary_sensor.alice_supervised
   Notification Service: mobile_app_pixel_8
   Alert Cooldown: 60
   ```
5. **Save** as "Alice Safety Alert"

### Creating Supervision Detection

1. **Settings → Automations & Scenes**
2. **Create Automation → Start with a blueprint**
3. Select **"Frigate Identity - Supervision Detection"**
4. Fill in:
   ```
   Child Name: Alice
   Trusted Adults: ["Dad", "Mom"]
   Supervision Timeout: 60
   Manual Override: input_boolean.manual_supervision
   ```
5. **Save** as "Alice Supervision Sensor"

This creates `binary_sensor.alice_supervised` that you can use in other automations!

---

## Required Helper Entities

Some blueprints require helper entities. Create these in **Settings → Devices & Services → Helpers**:

### Input Booleans
- `input_boolean.manual_supervision` - Manual supervision override
- `input_boolean.front_gate_open` - Gate status (if no sensor)

### Creating Helpers

1. **Settings → Devices & Services → Helpers**
2. **Create Helper → Toggle**
3. Name: "Manual Supervision"
4. Entity ID: `input_boolean.manual_supervision`
5. Icon: `mdi:account-check`

---

## Customization Tips

### Multiple Children

Create separate automations for each child using the same blueprint:
- "Alice Safety Alert"
- "Bob Safety Alert"
- "Toddler Safety Alert"

Each can have different:
- Dangerous zones (younger = more zones)
- Supervision requirements
- Alert priorities

### Zone-Specific Alerts

Create multiple automations for the same child with different zones:
- "Alice - Street Alert" (CRITICAL)
- "Alice - Near Fence" (WARNING)
- "Alice - Neighbor Yard" (INFO)

Use different notification priorities for each.

### Time-Based Rules

Add conditions to blueprints:
- Only alert during specific hours
- Only alert on certain days
- Disable during "outside play time"

Edit the automation after creation to add conditions.

---

## Troubleshooting

### Blueprint Not Appearing

1. Check file is in correct folder: `/config/blueprints/automation/frigate_identity/`
2. Restart Home Assistant
3. Check for YAML syntax errors in files

### Automation Not Triggering

1. Check identity service is running and publishing MQTT messages
2. Verify topic names match (case-sensitive)
3. Test with Developer Tools → MQTT → Listen to `identity/person/#`
4. Check automation trace in HA for condition failures

### Notifications Not Received

1. Verify notification service name (without `notify.` prefix)
2. Test notification service independently
3. Check phone notification settings
4. Ensure mobile app is configured

---

## Advanced: Modifying Blueprints

Blueprints are regular YAML automations with input variables. To customize:

1. Create automation from blueprint
2. Edit the created automation
3. Modify triggers, conditions, or actions as needed
4. Save changes

Changes to the automation are independent of the blueprint.

---

## Contributing

Have ideas for new blueprints? Open an issue or pull request on GitHub!

**Ideas for Future Blueprints:**
- Time-based confidence decay alerts
- Daily outdoor time reports
- Zone dwell time analytics
- Multi-home synchronization
- Pet tracking integration
