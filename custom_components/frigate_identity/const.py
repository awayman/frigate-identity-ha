"""Constants for the Frigate Identity integration."""
from __future__ import annotations

DOMAIN = "frigate_identity"

# ── Config keys ─────────────────────────────────────────────────────────────
CONF_MQTT_TOPIC_PREFIX = "mqtt_topic_prefix"
CONF_SNAPSHOT_SOURCE = "snapshot_source"
CONF_AUTO_DASHBOARD = "auto_dashboard"
CONF_DASHBOARD_REFRESH_TIME = "dashboard_refresh_time"
CONF_DASHBOARD_NAME = "dashboard_name"
CONF_DASHBOARD_PERSONS = "dashboard_persons"
CONF_SERVICE_HEALTH_CHECK_INTERVAL = "service_health_check_interval"

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_MQTT_TOPIC_PREFIX = "identity"
DEFAULT_SNAPSHOT_SOURCE = "mqtt"
DEFAULT_AUTO_DASHBOARD = True
DEFAULT_DASHBOARD_REFRESH_TIME = "03:00"
DEFAULT_DASHBOARD_NAME = "Kids"
DEFAULT_DASHBOARD_PERSONS = []
DEFAULT_SERVICE_HEALTH_CHECK_INTERVAL = 15

# ── Person entity custom attributes ──────────────────────────────────────────
ATTR_FRIGATE_IDENTITY_IS_CHILD = "frigate_identity_is_child"
ATTR_FRIGATE_IDENTITY_SAFE_ZONES = "frigate_identity_safe_zones"

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
TOPIC_HEARTBEAT = "{prefix}/health"
TOPIC_FALSE_POSITIVE = "frigate_identity/feedback/false_positive"
TOPIC_FALSE_POSITIVE_ACK = "frigate_identity/feedback/false_positive_ack"

SERVICE_HEARTBEAT_INTERVAL_SECONDS = 30
SERVICE_HEARTBEAT_STALE_THRESHOLD_SECONDS = 90
