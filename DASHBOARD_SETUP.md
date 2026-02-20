# Frigate Identity – Dashboard Setup & Further Automations

This guide covers the complete end-to-end flow: running the generator, wiring
the output files into Home Assistant, creating the Lovelace dashboard through
the HA UI, and setting up further automations to get the most out of the system.

---

## Part 1 – Generate the Configuration Files

If you have a `persons.yaml` from the [Frigate Identity Service](https://github.com/awayman/frigate_identity_service), run:

```bash
pip install pyyaml
python examples/generate_dashboard.py \
    --persons-file /path/to/frigate_identity_service/persons.yaml \
    --output /config/frigate_identity
```

Or supply person names directly:

```bash
python examples/generate_dashboard.py \
    --output /config/frigate_identity \
    Alice Bob Dad Mom
```

The generator writes these files to `/config/frigate_identity/`:

| File | What it contains |
|---|---|
| `mqtt_cameras.yaml` | MQTT `camera` entities — one per person (bounded snapshot) |
| `template_sensors.yaml` | Per-person location sensors + supervision binary sensors (when role data present) |
| `dashboard.yaml` | Full Lovelace dashboard YAML |
| `danger_zone_automations.yaml` | Danger-zone MQTT automations *(only when children have `dangerous_zones`)* |

---

## Part 2 – Wire the Files into Home Assistant

Open `/config/configuration.yaml` and add the following includes:

```yaml
# MQTT camera entities for bounded person snapshots
mqtt:
  camera: !include frigate_identity/mqtt_cameras.yaml

# Per-person location/confidence/zone sensors (+ supervision binary sensors)
template: !include frigate_identity/template_sensors.yaml

# Danger-zone automations — only needed if the file was generated
automation: !include frigate_identity/danger_zone_automations.yaml
```

> **Tip — existing `automation:` block**: If you already have automations in
> `configuration.yaml`, change the existing key to a list or use
> `automation: !include_dir_merge_list automations/` and place the generated
> file inside that folder.

**Restart Home Assistant** after saving (`Settings → System → Restart`).

### Verify the entities appeared

1. Go to **Settings → Devices & Services → Entities**
2. Search for `alice_location` (or whichever name you used) — you should see:
   - `sensor.alice_location`
   - `binary_sensor.alice_supervised` *(only if role data was present)*
   - `camera.alice_snapshot`

---

## Part 3 – Create the Lovelace Dashboard

### 3a. Create a new dashboard

1. Go to **Settings → Dashboards**
2. Click **+ Add dashboard** (bottom-right)
3. Fill in:
   - **Title**: `Frigate Identity` (or any name you like)
   - **Icon**: `mdi:account-search`
   - **URL path**: `frigate-identity`
4. Uncheck **"Show in sidebar"** if you want it hidden until ready
5. Click **Create**

### 3b. Open the Raw Configuration Editor

1. Click on your new dashboard to open it
2. Click the **pencil ✏️ (Edit)** button in the top-right
3. Click the **three-dot ⋮ menu** → **"Raw configuration editor"**

   > The Raw Configuration Editor lets you paste YAML directly.
   > If you don't see it, ensure you are in **Edit mode** first.

### 3c. Paste the generated dashboard YAML

1. Open `/config/frigate_identity/dashboard.yaml` in a text editor
2. Select **all** content (`Ctrl+A` / `Cmd+A`)
3. Copy it
4. In the HA Raw Configuration Editor, **select all** existing content and **replace** it with what you copied
5. Click **Save**
6. Click the **X** to close the editor

Your dashboard is now live. 🎉

### 3d. Verify it looks correct

- Each tracked person should have a **snapshot card** (shows latest bounded image) and a **status card** (location, zones, confidence, etc.)
- Children will also show a **Supervised** row
- The bottom **System Status** card shows total tracked persons and last detection

> **No image showing?** The MQTT camera entity updates only when the Identity
> Service publishes to `identity/snapshots/{person}`.  Walk in front of a
> camera and check if `camera.alice_snapshot` updates.

### 3e. Keeping the dashboard up to date

When you add or remove people from `persons.yaml`, re-run the generator and
repeat steps 3b–3c:

```bash
python examples/generate_dashboard.py \
    --persons-file persons.yaml \
    --output /config/frigate_identity
```

Then restart HA to pick up any new sensors.

---

## Part 4 – Further Automation Steps

Beyond the danger-zone alerts the generator creates automatically, the
following automations cover the most common real-world scenarios.

### 4.1 – Use the built-in Blueprints (no YAML needed)

This integration ships with **seven blueprints**.  Install them by copying the
blueprint files from the integration directory to your HA blueprints folder:

```bash
cp /config/custom_components/frigate_identity/blueprints/automation/frigate_identity/*.yaml \
   /config/blueprints/automation/frigate_identity/
```

Then in HA: **Settings → Automations & Scenes → Blueprints** — they appear
immediately (no restart needed).

#### Available Blueprints

| Blueprint | What it does |
|---|---|
| **Child Danger Zone Alert** | Alert when child enters a dangerous zone without supervision |
| **Vehicle with Children Outside** | Alert when a vehicle is in the driveway and children are outside |
| **Supervision Detection** | Template binary sensor — is this child supervised right now? |
| **Notification Action Handlers** | Handle "Adult Present" / "View Camera" notification buttons |
| **Curfew Alert** *(new)* | Alert when a child is still outside after curfew time |
| **All Children Home** *(new)* | Notify when every child is detected on a home camera |
| **Unknown Person Alert** *(new)* | Alert when a low-confidence / unrecognised person is detected |

### 4.2 – Curfew Alert

**Scenario**: You want a notification at 20:00 if any child is still outside.

1. **Settings → Automations & Scenes → Create Automation**
2. **Start with a blueprint → "Frigate Identity - Curfew Alert"**
3. Fill in:
   - **Child Name**: `Alice`
   - **Curfew Time**: `20:00`
   - **Stop Checking At**: `23:00`
   - **Notification Service**: `mobile_app_your_phone`
4. **Save** as "Alice Curfew Alert"

Repeat for each child with their own curfew time.

### 4.3 – All Children Home

**Scenario**: Send one calm confirmation when everyone is inside for the night.

1. **Create Automation → Start with a blueprint → "Frigate Identity - All Children Home"**
2. Fill in:
   - **Children Names**: `["Alice", "Bob"]`
   - **Home Cameras**: `["front_door", "hallway"]`
   - **Start Checking After**: `14:00` (school dismissal)
   - **Notification Service**: `mobile_app_your_phone`
3. **Save**

### 4.4 – Unknown Person Alert

**Scenario**: Alert when someone is detected with low confidence (a stranger or
someone the system couldn't identify clearly).

1. **Create Automation → Start with a blueprint → "Frigate Identity - Unknown Person Alert"**
2. Fill in:
   - **Confidence Threshold**: `0.5`
   - **Known Persons**: `["Alice", "Bob", "Dad", "Mom"]`
   - **Cameras to Monitor**: `["front_door", "driveway"]`
   - **Notification Service**: `mobile_app_your_phone`
3. **Save**

### 4.5 – Time-based confidence decay sensor

Adds a sensor that reduces confidence over time so stale detections don't
appear as current.  Add to `configuration.yaml` (or include via a template
file):

```yaml
template:
  - sensor:
      - name: "Alice Effective Confidence"
        unique_id: "alice_effective_confidence"
        state: >
          {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
          {% if persons and 'Alice' in persons %}
            {% set alice = persons['Alice'] %}
            {% set base_conf = alice.confidence | float(0) %}
            {% set minutes_ago = (as_timestamp(now()) - as_timestamp(alice.last_seen)) / 60 %}
            {% if minutes_ago > 5 %}
              {{ [base_conf * (1 - ((minutes_ago - 5) * 0.1)), 0] | max | round(2) }}
            {% else %}
              {{ base_conf | round(2) }}
            {% endif %}
          {% else %}
            0
          {% endif %}
        unit_of_measurement: "%"
```

### 4.6 – Daily outdoor time report

**Scenario**: At 21:00 every day, count how many times each child was detected
and send a summary.

```yaml
# automations.yaml
- alias: "Daily Report - Outdoor Time"
  trigger:
    - platform: time
      at: "21:00:00"
  action:
    - service: notify.mobile_app_your_phone
      data:
        title: "📊 Daily Activity Report"
        message: >
          Today's outdoor detections:
          Alice: {{ states('counter.alice_detections') }} times
          Bob: {{ states('counter.bob_detections') }} times
```

Pair with `counter` helpers and an automation that increments the counter on
each `identity/person/{name}` MQTT message.

### 4.7 – Notification action handler

Make the "Adult Present" and "View Camera" buttons on notifications functional:

1. **Create Automation → Start with a blueprint → "Frigate Identity - Notification Action Handlers"**
2. Fill in:
   - **Manual Supervision Entity**: `input_boolean.manual_supervision`
   - **Supervision Duration**: `10` minutes
3. **Save**

Create the helper entity first if needed:
**Settings → Devices & Services → Helpers → Create Helper → Toggle**
Name: "Manual Supervision" / Entity ID: `input_boolean.manual_supervision`

---

## Part 5 – Recommended Automation Sequence

Here's the order to set things up for a full family-safety setup:

```
Step 1  ✅  Install integration (HACS or manual)
Step 2  ✅  Run generate_dashboard.py → wire into configuration.yaml → restart HA
Step 3  ✅  Create Lovelace dashboard (Part 3 above)
Step 4  ✅  Copy blueprints to /config/blueprints/automation/frigate_identity/
Step 5  ✅  Create "Manual Supervision" helper
Step 6  🔲  Create Supervision Detection automation for each child
Step 7  🔲  Create Child Danger Zone Alert for each child
Step 8  🔲  Create Curfew Alert for each child
Step 9  🔲  Create All Children Home notification
Step 10 🔲  Create Vehicle with Children Outside alert
Step 11 🔲  Create Unknown Person Alert for outdoor cameras
Step 12 🔲  Create Notification Action Handlers automation
```

---

## Troubleshooting

### Dashboard shows "Entity not found" / grey cards

The entities were not created.  Check:
1. `configuration.yaml` includes `template_sensors.yaml` and `mqtt_cameras.yaml`
2. HA was restarted after adding the includes
3. **Developer Tools → States** — search for `alice_location`

### Snapshot card is blank / no image

1. The Identity Service must be running and publishing to `identity/snapshots/{person}`
2. Check in **Developer Tools → MQTT → Listen** → subscribe to `identity/snapshots/#`
3. Verify Frigate has `mqtt.crop: true` for each camera

### Automation condition failing

1. Open the automation in HA → click **Traces** tab
2. The trace shows exactly which condition failed and what values were evaluated
3. Common fix: ensure `sensor.frigate_identity_all_persons` is updating (`Developer Tools → States`)

### Blueprint not appearing in HA

1. File must be in `/config/blueprints/automation/frigate_identity/` (not the custom_components subfolder)
2. No HA restart needed — blueprints are hot-loaded
3. Check for YAML syntax errors in the blueprint file
