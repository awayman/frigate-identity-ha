"""Constants for the Frigate Identity integration."""
from __future__ import annotations

DOMAIN = "frigate_identity"

# ── Config keys ─────────────────────────────────────────────────────────────
CONF_MQTT_TOPIC_PREFIX = "mqtt_topic_prefix"
CONF_PERSONS_FILE = "persons_file"
CONF_SNAPSHOT_SOURCE = "snapshot_source"
CONF_AUTO_DASHBOARD = "auto_dashboard"
CONF_DASHBOARD_REFRESH_TIME = "dashboard_refresh_time"

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_MQTT_TOPIC_PREFIX = "identity"
DEFAULT_PERSONS_FILE = "/config/persons.yaml"
DEFAULT_SNAPSHOT_SOURCE = "mqtt"
DEFAULT_AUTO_DASHBOARD = True
DEFAULT_DASHBOARD_REFRESH_TIME = "03:00"

# ── Snapshot source options ─────────────────────────────────────────────────
SNAPSHOT_SOURCE_MQTT = "mqtt"
SNAPSHOT_SOURCE_FRIGATE_API = "frigate_api"
SNAPSHOT_SOURCE_FRIGATE_INTEGRATION = "frigate_integration"

SNAPSHOT_SOURCES = [
    SNAPSHOT_SOURCE_MQTT,
    SNAPSHOT_SOURCE_FRIGATE_API,
    SNAPSHOT_SOURCE_FRIGATE_INTEGRATION,
]

# ── Internal data keys ─────────────────────────────────────────────────────
DATA_PERSONS = "persons"
DATA_PERSONS_META = "persons_meta"
DATA_CAMERA_ZONES = "camera_zones"
DATA_UNSUBSCRIBE = "unsub"

# ── Events ──────────────────────────────────────────────────────────────────
EVENT_PERSONS_UPDATED = f"{DOMAIN}_persons_updated"

# ── MQTT topic templates ───────────────────────────────────────────────────
TOPIC_PERSON = "{prefix}/person/{name}"
TOPIC_PERSON_WILDCARD = "{prefix}/person/#"
TOPIC_SNAPSHOTS = "{prefix}/snapshots/{name}"
TOPIC_SNAPSHOTS_WILDCARD = "{prefix}/snapshots/#"
