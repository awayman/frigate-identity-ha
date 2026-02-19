# Frigate Identity - Home Assistant Configuration Examples

This guide shows how to configure Home Assistant to use Frigate Identity for child safety monitoring and location tracking.

## Prerequisites

1. **Frigate** configured with facial recognition
2. **Frigate Identity Service** running and connected to MQTT
3. **Home Assistant** with MQTT integration configured

---

## Basic Setup

### 1. MQTT Camera Entities for Live Snapshots

Add MQTT camera entities to display live person snapshots:

```yaml
# configuration.yaml
mqtt:
  camera:
    # Per-person snapshot cameras (update in real-time)
    - name: "Alice Snapshot"
      unique_id: "frigate_identity_alice_snapshot"
      topic: "identity/snapshots/Alice"
      
    - name: "Bob Snapshot"
      unique_id: "frigate_identity_bob_snapshot"
      topic: "identity/snapshots/Bob"
      
    - name: "Dad Snapshot"
      unique_id: "frigate_identity_dad_snapshot"
      topic: "identity/snapshots/Dad"
    
    # Vehicle detection snapshot
    - name: "Driveway Vehicle"
      unique_id: "frigate_identity_vehicle_driveway"
      topic: "identity/snapshots/vehicle_driveway"
```

---

## Per-Person Template Sensors

Create template sensors to extract individual person data from the "All Persons" sensor:

```yaml
# configuration.yaml
template:
  - sensor:
      # Alice location tracking
      - name: "Alice Location"
        unique_id: "alice_location"
        state: >
          {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
          {% if persons and 'Alice' in persons %}
            {{ persons['Alice'].camera }}
          {% else %}
            unknown
          {% endif %}
        attributes:
          zones: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].frigate_zones }}
            {% else %}
              []
            {% endif %}
          confidence: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].confidence }}
            {% else %}
              0
            {% endif %}
          source: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].source }}
            {% else %}
              unknown
            {% endif %}
          snapshot_url: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].snapshot_url }}
            {% else %}
              null
            {% endif %}
          last_seen: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].last_seen }}
            {% else %}
              unknown
            {% endif %}
      
      # Bob location tracking
      - name: "Bob Location"
        unique_id: "bob_location"
        state: >
          {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
          {% if persons and 'Bob' in persons %}
            {{ persons['Bob'].camera }}
          {% else %}
            unknown
          {% endif %}
        attributes:
          zones: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Bob' in persons %}
              {{ persons['Bob'].frigate_zones }}
            {% else %}
              []
            {% endif %}
          confidence: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Bob' in persons %}
              {{ persons['Bob'].confidence }}
            {% else %}
              0
            {% endif %}
```

---

## Person Roles Configuration

Define person roles and supervision requirements:

```yaml
# configuration.yaml
input_text:
  # Person role definitions (for use in automations)
  alice_role:
    name: "Alice Role"
    initial: "child"
  
  bob_role:
    name: "Bob Role"
    initial: "child"
  
  dad_role:
    name: "Dad Role"
    initial: "trusted_adult"
  
  mom_role:
    name: "Mom Role"
    initial: "trusted_adult"

input_number:
  alice_age:
    name: "Alice Age"
    min: 0
    max: 100
    initial: 5
  
  bob_age:
    name: "Bob Age"
    min: 0
    max: 100
    initial: 10
```

---

## Supervision Detection

Binary sensors to detect if children are supervised:

```yaml
# configuration.yaml
template:
  - binary_sensor:
      # Alice supervision status
      - name: "Alice Supervised"
        unique_id: "alice_supervised"
        state: >
          {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
          {% if not persons or 'Alice' not in persons %}
            {{ false }}
          {% else %}
            {% set alice = persons['Alice'] %}
            {% set alice_camera = alice.camera %}
            {% set alice_zones = alice.frigate_zones %}
            {% set alice_time = as_timestamp(alice.last_seen) %}
            {% set now = as_timestamp(now()) %}
            
            {# Check if any adult is on same camera within 60 seconds #}
            {% set adults = ['Dad', 'Mom'] %}
            {% set supervised = namespace(value=false) %}
            
            {% for adult in adults %}
              {% if adult in persons %}
                {% set adult_data = persons[adult] %}
                {% set adult_camera = adult_data.camera %}
                {% set adult_time = as_timestamp(adult_data.last_seen) %}
                
                {% if alice_camera == adult_camera and (now - adult_time) < 60 %}
                  {% set supervised.value = true %}
                {% endif %}
              {% endif %}
            {% endfor %}
            
            {# Allow manual override #}
            {{ supervised.value or is_state('input_boolean.manual_supervision', 'on') }}
          {% endif %}
      
      # Bob supervision status
      - name: "Bob Supervised"
        unique_id: "bob_supervised"
        state: >
          {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
          {% if not persons or 'Bob' not in persons %}
            {{ false }}
          {% else %}
            {% set bob = persons['Bob'] %}
            {% set bob_camera = bob.camera %}
            {% set bob_time = as_timestamp(bob.last_seen) %}
            {% set now = as_timestamp(now()) %}
            
            {% set adults = ['Dad', 'Mom'] %}
            {% set supervised = namespace(value=false) %}
            
            {% for adult in adults %}
              {% if adult in persons %}
                {% set adult_data = persons[adult] %}
                {% set adult_camera = adult_data.camera %}
                {% set adult_time = as_timestamp(adult_data.last_seen) %}
                
                {% if bob_camera == adult_camera and (now - adult_time) < 60 %}
                  {% set supervised.value = true %}
                {% endif %}
              {% endif %}
            {% endfor %}
            
            {{ supervised.value or is_state('input_boolean.manual_supervision', 'on') }}
          {% endif %}

# Manual supervision override
input_boolean:
  manual_supervision:
    name: "Manual Supervision Active"
    icon: mdi:account-check
```

---

## Safety Automations

### Alert: Child Near Dangerous Zone

```yaml
# automations.yaml
- alias: "Alert - Alice Near Street"
  description: "Alert when Alice is near the street without supervision"
  trigger:
    - platform: state
      entity_id: sensor.alice_location
  condition:
    - condition: template
      value_template: >
        {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
        {% if persons and 'Alice' in persons %}
          {{ 'street' in persons['Alice'].frigate_zones or 'neighbor_yard' in persons['Alice'].frigate_zones }}
        {% else %}
          false
        {% endif %}
    - condition: state
      entity_id: binary_sensor.alice_supervised
      state: "off"
  action:
    - service: notify.mobile_app_your_phone
      data:
        title: "⚠️ Child Safety Alert"
        message: "Alice is near a dangerous area without supervision!"
        data:
          image: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {% if persons and 'Alice' in persons %}
              {{ persons['Alice'].snapshot_url }}
            {% endif %}
          actions:
            - action: "MARK_ADULT_PRESENT"
              title: "Adult is Present"
            - action: "VIEW_CAMERA"
              title: "View Camera"
```

### Alert: Vehicle in Driveway with Children Outside

```yaml
- alias: "Alert - Vehicle with Children Outside"
  description: "Alert when vehicle enters driveway and children are outside"
  trigger:
    - platform: mqtt
      topic: "identity/vehicle/detected"
  condition:
    - condition: or
      conditions:
        - condition: template
          value_template: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {{ persons and 'Alice' in persons }}
        - condition: template
          value_template: >
            {% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}
            {{ persons and 'Bob' in persons }}
  action:
    - service: notify.mobile_app_your_phone
      data:
        title: "🚗 Vehicle Alert"
        message: "Vehicle detected in driveway. Children are outside."
        data:
          priority: high
          actions:
            - action: "CHILDREN_SAFE"
              title: "Children Are Safe"
```

### Action Handler: Manual Supervision Toggle

```yaml
- alias: "Handle - Mark Adult Present"
  description: "Toggle manual supervision when action button pressed"
  trigger:
    - platform: event
      event_type: mobile_app_notification_action
      event_data:
        action: "MARK_ADULT_PRESENT"
  action:
    - service: input_boolean.turn_on
      target:
        entity_id: input_boolean.manual_supervision
    - delay:
        minutes: 10
    - service: input_boolean.turn_off
      target:
        entity_id: input_boolean.manual_supervision
```

---

## Dashboard Example

### Lovelace Card Configuration

```yaml
# dashboard.yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      # 👨‍👩‍👧‍👦 Family Location Tracker
  
  # Alice card
  - type: picture-entity
    entity: camera.alice_snapshot
    name: Alice
    show_state: true
    camera_view: live
    
  - type: entities
    entities:
      - entity: sensor.alice_location
        name: Current Camera
      - entity: binary_sensor.alice_supervised
        name: Supervised
      - type: attribute
        entity: sensor.alice_location
        attribute: zones
        name: Zones
      - type: attribute
        entity: sensor.alice_location
        attribute: confidence
        name: Confidence
      - type: attribute
        entity: sensor.alice_location
        attribute: last_seen
        name: Last Seen
  
  # Bob card
  - type: picture-entity
    entity: camera.bob_snapshot
    name: Bob
    show_state: true
    camera_view: live
  
  - type: entities
    entities:
      - entity: sensor.bob_location
        name: Current Camera
      - entity: binary_sensor.bob_supervised
        name: Supervised
  
  # Summary card
  - type: entity
    entity: sensor.frigate_identity_all_persons
    name: Total Persons Detected
```

---

## Frigate Configuration

Configure Frigate to enable MQTT snapshots with cropping:

```yaml
# frigate/config.yml
cameras:
  backyard:
    mqtt:
      enabled: true
      timestamp: true
      bounding_box: true
      crop: true           # Enable cropping to person
      height: 400
      quality: 80
      required_zones:      # Only publish snapshots when in these zones
        - safe_play_area
        - near_fence
        - street
  
  driveway:
    mqtt:
      enabled: true
      timestamp: true
      bounding_box: true
      crop: true
      height: 400
      quality: 80

  front_door:
    mqtt:
      enabled: true
      crop: true
      height: 400
      quality: 80
```

---

## Testing

### Verify MQTT Messages

Use MQTT Explorer or Home Assistant MQTT integration to verify messages:

```
identity/person/Alice
identity/person/Bob
identity/snapshots/Alice
identity/snapshots/Bob
identity/vehicle/detected
```

### Test Safety Automation

1. Walk to a dangerous zone (e.g., near street)
2. Verify notification is received
3. Test "Adult is Present" action button
4. Confirm notification cooldown works

---

## Advanced: Time-Based Confidence Decay

Add a template sensor that reduces confidence over time:

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
            {% set last_seen = as_timestamp(alice.last_seen) %}
            {% set now = as_timestamp(now()) %}
            {% set minutes_ago = (now - last_seen) / 60 %}
            
            {# Decay 10% per minute after 5 minutes #}
            {% if minutes_ago > 5 %}
              {% set decay = 1 - ((minutes_ago - 5) * 0.1) %}
              {{ [base_conf * decay, 0] | max }}
            {% else %}
              {{ base_conf }}
            {% endif %}
          {% else %}
            0
          {% endif %}
```

---

## Troubleshooting

### No Snapshots Appearing

1. Check Frigate MQTT configuration has `enabled: true` and `crop: true`
2. Verify identity service is subscribed to snapshot topics
3. Check MQTT broker logs for published messages

### Person Not Identified

1. Ensure Frigate facial recognition is configured and trained
2. Check identity service logs for ReID matching attempts
3. Verify `REID_SIMILARITY_THRESHOLD` is not too high (try lowering to 0.5)

### False Supervision Alerts

1. Increase supervision timeout (change 60 seconds to 120 seconds)
2. Add more trusted adults to the list
3. Use manual supervision toggle as backup

---

## Next Steps

- Configure zone-specific safety rules per child age
- Add vehicle detection logic for gate safety
- Implement notification escalation (SMS, phone call)
- Add historical tracking and analytics
- Create custom Lovelace cards for visual zone map
