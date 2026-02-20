#!/usr/bin/env python3
"""Generate Home Assistant configuration for the Frigate Identity dashboard.

This script produces ready-to-use YAML files from a list of person names.
Person names can be supplied as positional arguments **or** read directly
from the ``persons.yaml`` used by the Frigate Identity Service:

    python generate_dashboard.py --persons-file /path/to/persons.yaml

The ``persons.yaml`` format (from ``awayman/frigate_identity_service``):

.. code-block:: yaml

    persons:
      Alice:
        role: child
        age: 5
        requires_supervision: true
        dangerous_zones: [street, neighbor_yard]
        camera: backyard          # optional – used for frigate_integration mode
      Dad:
        role: trusted_adult
        can_supervise: true
        camera: driveway

When ``--persons-file`` is given, person names are taken from the ``persons``
mapping keys.  Any ``camera`` field inside a person's entry is used as the
default camera mapping for ``--snapshot-source frigate_integration``.
Explicit ``--cameras`` arguments always take precedence over the YAML values.

You can combine both sources; positional ``PERSON`` args are merged after the
file so they can extend or override the list:

    python generate_dashboard.py --persons-file persons.yaml Grandma

Use ``--snapshot-source`` to choose how the bounded snapshot is displayed:

``mqtt`` (default)
    MQTT camera entities subscribing to ``identity/snapshots/{person_id}``.
    The Frigate Identity Service publishes a cropped JPEG there for each
    identified person, so the snapshot follows the person across cameras.
    Generates ``mqtt_cameras.yaml``, ``template_sensors.yaml``,
    ``dashboard.yaml``.

``frigate_api``
    HA template ``image`` entities built from the ``snapshot_url`` attribute
    already stored in each person's location sensor.  Uses the same Frigate
    HTTP API that the official Frigate HA integration uses — no extra MQTT
    camera subscription required.  Generates ``template_sensors.yaml`` and
    ``dashboard.yaml`` only (``mqtt_cameras.yaml`` is not needed).

``frigate_integration``
    Reuses the ``image.<camera>_person`` entities created by the official
    Frigate HA integration (blakeblackshear/frigate-hass-integration).
    These entities are **per camera**, not per identified person: they show
    the latest detected person on a specific camera regardless of who it is.
    Pass ``--cameras`` to map each person to their primary camera name so the
    generator can construct the right entity ID.  When a person is not mapped
    their card will reference the person-slug camera entity as a best-effort
    fallback.  No extra YAML configuration is generated beyond
    ``dashboard.yaml``.

Usage
-----
    # From persons.yaml (recommended when you already have the service configured)
    python generate_dashboard.py --persons-file /config/persons.yaml

    # MQTT cameras (default)
    python generate_dashboard.py Alice Bob Dad Mom

    # Frigate API template images (no MQTT cameras needed)
    python generate_dashboard.py --snapshot-source frigate_api Alice Bob Dad Mom

    # Official Frigate integration (per-camera entities)
    python generate_dashboard.py --snapshot-source frigate_integration \\
        --cameras Alice:backyard Bob:front_door Dad:driveway Mom:backyard \\
        Alice Bob Dad Mom

    # Write to a custom output directory
    python generate_dashboard.py --output /config/frigate_identity Alice Bob Dad Mom

MQTT / frigate_api — add to ``configuration.yaml``::

    mqtt:
      camera: !include frigate_identity/mqtt_cameras.yaml   # mqtt mode only

    template: !include frigate_identity/template_sensors.yaml

Then paste ``dashboard.yaml`` into a Lovelace Raw-configuration editor.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from typing import Any

import yaml

# Resolve blueprint source directory relative to this script so --copy-blueprints
# works regardless of the working directory.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BLUEPRINTS_SRC = os.path.normpath(
    os.path.join(
        _SCRIPT_DIR, "..", "custom_components",
        "frigate_identity", "blueprints", "automation", "frigate_identity",
    )
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Return a lowercase, underscore-separated entity-id-friendly slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# persons.yaml loader
# ---------------------------------------------------------------------------

def load_persons_yaml(
    path: str,
) -> tuple[list[str], dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
    """Load person names and metadata from a Frigate Identity Service
    ``persons.yaml`` file.

    Expected format::

        persons:
          Alice:
            role: child
            age: 5
            requires_supervision: true
            dangerous_zones: [near_fence, street_view]
            camera: backyard   # optional – used for frigate_integration mode
          Dad:
            role: trusted_adult
            can_supervise: true
            camera: driveway   # optional

        # Optional: map each Frigate camera to a logical supervision zone.
        # Cameras assigned the same zone name are treated as co-located so an
        # adult on camera A is considered supervising a child on camera B when
        # both cameras map to the same zone.  Frigate zones are per-camera and
        # cannot be used for this cross-camera check.
        camera_zones:
          backyard: back_yard
          patio: back_yard
          front_door: front_entry
          driveway: front_entry

    Returns
    -------
    persons : list[str]
        Person names in file order.
    camera_map : dict[str, str]
        Mapping of person name → camera name (for ``frigate_integration`` mode).
    persons_meta : dict[str, dict[str, Any]]
        Full attribute dict per person (role, age, requires_supervision, …).
    camera_zones : dict[str, str]
        Mapping of Frigate camera name → logical supervision zone name.
        Empty dict when the section is absent (supervision falls back to
        same-camera matching).
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        print(f"ERROR: persons file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"ERROR: failed to parse {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict) or "persons" not in data:
        print(
            f"ERROR: {path} must contain a top-level 'persons' mapping.",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = data["persons"]
    if not isinstance(raw, dict):
        print(
            f"ERROR: 'persons' in {path} must be a mapping of name → attributes.",
            file=sys.stderr,
        )
        sys.exit(1)

    persons: list[str] = list(raw.keys())
    camera_map: dict[str, str] = {}
    persons_meta: dict[str, dict[str, Any]] = {}
    for name, attrs in raw.items():
        attrs_dict: dict[str, Any] = attrs if isinstance(attrs, dict) else {}
        persons_meta[name] = attrs_dict
        if attrs_dict.get("camera"):
            camera_map[name] = str(attrs_dict["camera"])

    raw_cz = data.get("camera_zones")
    camera_zones: dict[str, str] = (
        {str(k): str(v) for k, v in raw_cz.items()}
        if isinstance(raw_cz, dict)
        else {}
    )

    return persons, camera_map, persons_meta, camera_zones



# ---------------------------------------------------------------------------
# Role helpers  (derived from persons.yaml metadata)
# ---------------------------------------------------------------------------

def _is_child(meta: dict[str, Any]) -> bool:
    """Return True if the person's metadata marks them as a child."""
    return meta.get("role") == "child" or bool(meta.get("requires_supervision"))


def _is_adult(meta: dict[str, Any]) -> bool:
    """Return True if the person's metadata marks them as a trusted adult."""
    return meta.get("role") == "trusted_adult" or bool(meta.get("can_supervise"))


# ---------------------------------------------------------------------------
# Supervision binary sensors  (one per child, using trusted adults from meta)
# ---------------------------------------------------------------------------

def _build_supervision_binary_sensor(
    child: str, adults: list[str], camera_zones: dict[str, str]
) -> dict[str, Any]:
    """Build a HA template binary sensor tracking whether *child* is supervised.

    Each camera is mapped to a logical supervision zone via *camera_zones*
    (e.g. ``{'backyard': 'back_yard', 'patio': 'back_yard'}``).  An adult
    is considered to be supervising the child when both were seen within the
    last 60 seconds **and** their cameras resolve to the **same zone**.

    When *camera_zones* is empty the zone of a camera is its own name, which
    means supervision falls back to requiring the same camera — exactly the
    original behaviour.

    Note: Frigate zones are pixel-regions scoped to a single camera and cannot
    be used for cross-camera supervision checks.  Use *camera_zones* instead.
    """
    slug = _slug(child)
    adults_repr = repr(adults)
    camera_zones_repr = repr(camera_zones)
    state = _LiteralStr(
        "{% set persons = state_attr('sensor.frigate_identity_all_persons', 'persons') %}\n"
        f"{{% if not persons or '{child}' not in persons %}}\n"
        "  {{ false }}\n"
        "{% else %}\n"
        f"  {{% set child_camera = persons['{child}'].camera %}}\n"
        f"  {{% set camera_zones = {camera_zones_repr} %}}\n"
        "  {% set child_zone = camera_zones.get(child_camera, child_camera) %}\n"
        "  {% set now = as_timestamp(now()) %}\n"
        "  {% set supervised = namespace(value=false) %}\n"
        f"  {{% for adult in {adults_repr} %}}\n"
        "    {% if adult in persons %}\n"
        "      {% if (now - as_timestamp(persons[adult].last_seen)) < 60 %}\n"
        "        {% set adult_zone = camera_zones.get(persons[adult].camera, persons[adult].camera) %}\n"
        "        {% if adult_zone == child_zone %}\n"
        "          {% set supervised.value = true %}\n"
        "        {% endif %}\n"
        "      {% endif %}\n"
        "    {% endif %}\n"
        "  {% endfor %}\n"
        "  {{ supervised.value }}\n"
        "{% endif %}\n"
    )
    return {
        "name": f"{child} Supervised",
        "unique_id": f"frigate_identity_{slug}_supervised",
        "state": state,
        "device_class": "presence",
    }


# ---------------------------------------------------------------------------
# Danger-zone automations  (one per child that has dangerous_zones)
# ---------------------------------------------------------------------------

def _build_danger_zone_automation(
    child: str, dangerous_zones: list[str], has_supervision_sensor: bool
) -> dict[str, Any]:
    """Build a HA automation that alerts when *child* enters a dangerous zone."""
    slug = _slug(child)
    zones_repr = repr(dangerous_zones)
    condition: list[dict[str, Any]] = [
        {
            "condition": "template",
            "value_template": (
                "{% set zones = trigger.payload_json.get('frigate_zones', []) %}"
                f" {{{{ zones | select('in', {zones_repr}) | list | length > 0 }}}}"
            ),
        }
    ]
    if has_supervision_sensor:
        condition.append(
            {
                "condition": "state",
                "entity_id": f"binary_sensor.{slug}_supervised",
                "state": "off",
            }
        )
    return {
        "alias": f"Frigate Identity - {child} Danger Zone Alert",
        "description": (
            f"Alert when {child} enters a dangerous zone"
            + (" without supervision" if has_supervision_sensor else "")
        ),
        "mode": "single",
        "max_exceeded": "silent",
        "trigger": [{"platform": "mqtt", "topic": f"identity/person/{child}"}],
        "condition": condition,
        "action": [
            {
                "service": "notify.notify",
                "data": {
                    "title": "⚠️ Child Safety Alert",
                    "message": (
                        f"{child} detected in dangerous zone: "
                        "{{ trigger.payload_json.get('frigate_zones', []) | join(', ') }}"
                    ),
                    "data": {
                        "image": "{{ trigger.payload_json.snapshot_url }}",
                        "tag": f"child_safety_{slug}",
                        "actions": [
                            {"action": "MARK_SUPERVISED", "title": "Adult Present"},
                            {"action": "VIEW_CAMERA", "title": "View Camera"},
                        ],
                    },
                },
            },
            {"delay": "00:01:00"},
        ],
    }


# ---------------------------------------------------------------------------
# MQTT cameras  (identity/snapshots/{person_id})
# ---------------------------------------------------------------------------

def _build_mqtt_cameras(persons: list[str]) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    for person in persons:
        cameras.append(
            {
                "name": f"{person} Snapshot",
                "unique_id": f"frigate_identity_{_slug(person)}_snapshot",
                "topic": f"identity/snapshots/{person}",
            }
        )
    return cameras


# ---------------------------------------------------------------------------
# Template sensors  (per-person location, confidence, zones, snapshot_url)
# ---------------------------------------------------------------------------

def _person_template_sensor(person: str) -> dict[str, Any]:
    slug = _slug(person)
    all_persons_entity = "sensor.frigate_identity_all_persons"

    def _attr_template(field: str, default: str) -> _LiteralStr:
        return _LiteralStr(
            f"{{% set persons = state_attr('{all_persons_entity}', 'persons') %}}\n"
            f"{{% if persons and '{person}' in persons %}}\n"
            f"  {{{{ persons['{person}'].{field} }}}}\n"
            f"{{% else %}}\n"
            f"  {default}\n"
            f"{{% endif %}}\n"
        )

    return {
        "name": f"{person} Location",
        "unique_id": f"frigate_identity_{slug}_location",
        "state": _attr_template("camera", "unknown"),
        "attributes": {
            "zones": _attr_template("frigate_zones", "[]"),
            "confidence": _attr_template("confidence", "0"),
            "source": _attr_template("source", "unknown"),
            "snapshot_url": _attr_template("snapshot_url", "unavailable"),
            "last_seen": _attr_template("last_seen", "unknown"),
        },
    }


def _person_template_image(person: str) -> dict[str, Any]:
    """Template image entity that fetches the event thumbnail from Frigate API."""
    slug = _slug(person)
    location_entity = f"sensor.{slug}_location"
    return {
        "name": f"{person} Snapshot",
        "unique_id": f"frigate_identity_{slug}_snapshot_image",
        "url": _LiteralStr(
            f"{{{{ state_attr('{location_entity}', 'snapshot_url') }}}}\n"
        ),
        "verify_ssl": False,
    }


def _build_template_sensors(
    persons: list[str],
    snapshot_source: str,
    persons_meta: dict[str, dict[str, Any]],
    camera_zones: dict[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [
        {"sensor": [_person_template_sensor(p) for p in persons]}
    ]
    if snapshot_source == "frigate_api":
        result.append({"image": [_person_template_image(p) for p in persons]})

    # Supervision binary sensors — only when persons.yaml provides role data
    adults = [p for p in persons if _is_adult(persons_meta.get(p, {}))]
    children_needing_supervision = [
        p for p in persons if _is_child(persons_meta.get(p, {}))
    ]
    if adults and children_needing_supervision:
        result.append(
            {
                "binary_sensor": [
                    _build_supervision_binary_sensor(child, adults, camera_zones)
                    for child in children_needing_supervision
                ]
            }
        )

    return result


# ---------------------------------------------------------------------------
# Dashboard cards
# ---------------------------------------------------------------------------

def _snapshot_entity(person: str, snapshot_source: str, camera_map: dict[str, str]) -> str:
    """Return the HA entity ID used for the snapshot card."""
    slug = _slug(person)
    if snapshot_source == "mqtt":
        return f"camera.{slug}_snapshot"
    if snapshot_source == "frigate_api":
        return f"image.{slug}_snapshot"
    # frigate_integration: official Frigate HA integration provides image.<camera>_person
    camera = camera_map.get(person, slug)
    return f"image.{_slug(camera)}_person"


def _person_card(
    person: str,
    snapshot_source: str,
    camera_map: dict[str, str],
    persons_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    slug = _slug(person)
    location_entity = f"sensor.{slug}_location"
    snap_entity = _snapshot_entity(person, snapshot_source, camera_map)

    snapshot_card: dict[str, Any] = {
        "type": "picture-entity",
        "entity": snap_entity,
        "name": f"{person} – Latest Snapshot",
        "show_state": False,
        "show_name": True,
    }

    status_entities: list[dict[str, Any]] = [
        {"entity": location_entity, "name": "Location"},
        {"type": "attribute", "entity": location_entity, "attribute": "zones", "name": "Zones"},
        {"type": "attribute", "entity": location_entity, "attribute": "confidence", "name": "Confidence"},
        {"type": "attribute", "entity": location_entity, "attribute": "source", "name": "Source"},
        {"type": "attribute", "entity": location_entity, "attribute": "last_seen", "name": "Last Seen"},
    ]

    # Add supervision row for children when a supervision sensor exists
    if _is_child(persons_meta.get(person, {})):
        status_entities.insert(
            1,
            {"entity": f"binary_sensor.{slug}_supervised", "name": "Supervised"},
        )

    status_card: dict[str, Any] = {
        "type": "entities",
        "title": f"{person} Status",
        "entities": status_entities,
    }

    return {
        "type": "vertical-stack",
        "cards": [snapshot_card, status_card],
    }


def _build_view(
    persons: list[str],
    snapshot_source: str,
    camera_map: dict[str, str],
    persons_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a single Lovelace view dict (title, path, icon, cards)."""
    header_card: dict[str, Any] = {
        "type": "markdown",
        "content": (
            "# 📍 Frigate Identity – Person Tracker\n"
            "Real-time location and bounded snapshot for each tracked person."
        ),
    }
    person_cards = [
        _person_card(p, snapshot_source, camera_map, persons_meta) for p in persons
    ]
    summary_card: dict[str, Any] = {
        "type": "entities",
        "title": "System Status",
        "entities": [
            {
                "entity": "sensor.frigate_identity_all_persons",
                "name": "Persons Currently Tracked",
            },
            {
                "entity": "sensor.frigate_identity_last_person",
                "name": "Last Detection",
            },
        ],
    }
    return {
        "title": "Frigate Identity",
        "path": "frigate-identity",
        "icon": "mdi:account-search",
        "cards": [header_card, *person_cards, summary_card],
    }


def _build_dashboard(
    persons: list[str],
    snapshot_source: str,
    camera_map: dict[str, str],
    persons_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a complete HA Lovelace dashboard dict (views wrapper)."""
    return {"views": [_build_view(persons, snapshot_source, camera_map, persons_meta)]}


# ---------------------------------------------------------------------------
# YAML serialisation helpers
# ---------------------------------------------------------------------------

class _LiteralStr(str):
    """Scalar that serialises as a YAML literal block (|)."""


def _literal_representer(dumper: yaml.Dumper, data: _LiteralStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


def _build_dumper() -> type[yaml.Dumper]:
    dumper = yaml.Dumper
    dumper.add_representer(_LiteralStr, _literal_representer)
    return dumper


def _dump(obj: Any) -> str:
    return yaml.dump(
        obj,
        Dumper=_build_dumper(),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

_FILE_HEADER = (
    "# Generated by examples/generate_dashboard.py\n"
    "# Re-run the script to update this file after adding or removing persons.\n\n"
)


def _write(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_FILE_HEADER + content)
    print(f"  Wrote {path}")


# ---------------------------------------------------------------------------
# HA packages file  (one file that loads all generated includes into HA)
# ---------------------------------------------------------------------------

def _build_package_content(
    output_dir: str, snapshot_source: str, has_automations: bool
) -> str:
    """Return the text of the HA package YAML that wires all generated files."""
    lines = [
        "# Frigate Identity – Home Assistant package",
        "# Generated by examples/generate_dashboard.py",
        "# Auto-loaded when HA packages are configured (see DASHBOARD_SETUP.md).",
        "",
    ]
    if snapshot_source == "mqtt":
        lines += [
            "mqtt:",
            f"  camera: !include {os.path.join(output_dir, 'mqtt_cameras.yaml')}",
            "",
        ]
    if snapshot_source != "frigate_integration":
        lines += [
            f"template: !include {os.path.join(output_dir, 'template_sensors.yaml')}",
            "",
        ]
    if has_automations:
        lines += [
            f"automation: !include {os.path.join(output_dir, 'danger_zone_automations.yaml')}",
            "",
        ]
    return "\n".join(lines)


def _write_ha_package(
    ha_config_dir: str,
    output_dir: str,
    snapshot_source: str,
    has_automations: bool,
) -> None:
    """Write ``packages/frigate_identity.yaml`` and ensure packages are enabled."""
    packages_dir = os.path.join(ha_config_dir, "packages")
    os.makedirs(packages_dir, exist_ok=True)
    pkg_path = os.path.join(packages_dir, "frigate_identity.yaml")
    content = _build_package_content(output_dir, snapshot_source, has_automations)
    with open(pkg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  Wrote {pkg_path}")
    _ensure_packages_enabled(ha_config_dir)


def _ensure_packages_enabled(ha_config_dir: str) -> None:
    """Enable HA packages in ``configuration.yaml`` if not already configured."""
    config_path = os.path.join(ha_config_dir, "configuration.yaml")
    if not os.path.exists(config_path):
        print(f"  ⚠️  {config_path} not found — enable packages manually:")
        print("      homeassistant:")
        print("        packages: !include_dir_named packages")
        return

    with open(config_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    if "packages" in content:
        print(f"  ✅ HA packages already configured in {config_path}")
        return

    if "homeassistant:" in content:
        # Can't safely insert into an existing block via text editing.
        print(f"  ℹ️  Add one line to your homeassistant: section in {config_path}:")
        print("      homeassistant:")
        print("        packages: !include_dir_named packages")
        return

    # No homeassistant: section yet — safe to append a new one.
    with open(config_path, "a", encoding="utf-8") as fh:
        fh.write(
            "\n# Added by examples/generate_dashboard.py\n"
            "homeassistant:\n"
            "  packages: !include_dir_named packages\n"
        )
    print(f"  ✅ Enabled HA packages in {config_path}")


# ---------------------------------------------------------------------------
# Blueprint installer
# ---------------------------------------------------------------------------

def _copy_blueprints(ha_config_dir: str) -> None:
    """Copy blueprint YAML files to ``/config/blueprints/automation/frigate_identity/``."""
    dest = os.path.join(
        ha_config_dir, "blueprints", "automation", "frigate_identity"
    )
    os.makedirs(dest, exist_ok=True)

    if not os.path.isdir(_BLUEPRINTS_SRC):
        print(f"  ⚠️  Blueprint source not found: {_BLUEPRINTS_SRC}", file=sys.stderr)
        return

    count = 0
    for filename in sorted(os.listdir(_BLUEPRINTS_SRC)):
        if filename.endswith(".yaml"):
            shutil.copy2(os.path.join(_BLUEPRINTS_SRC, filename),
                         os.path.join(dest, filename))
            count += 1
    print(f"  ✅ Copied {count} blueprint(s) to {dest}")


# ---------------------------------------------------------------------------
# HA REST API helpers
# ---------------------------------------------------------------------------

def _ha_request(
    method: str,
    ha_url: str,
    ha_token: str,
    path: str,
    body: Any = None,
) -> Any:
    """Make a request to the HA REST API; return parsed JSON or None on error."""
    url = ha_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {ha_token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        print(f"  ⚠️  HA API {method} {path} → HTTP {exc.code}: {detail}",
              file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌  HA API error: {exc}", file=sys.stderr)
        return None


def _ha_push_dashboard(
    ha_url: str, ha_token: str, view: dict[str, Any]
) -> None:
    """Merge the Frigate Identity view into the default HA Lovelace dashboard."""
    print("  Pushing dashboard to Home Assistant...")
    current = _ha_request("GET", ha_url, ha_token, "/api/lovelace/config") or {}
    views: list[dict[str, Any]] = list(current.get("views", []))
    # Replace any existing frigate-identity view.
    views = [v for v in views if v.get("path") != "frigate-identity"]
    views.append(view)
    current["views"] = views
    result = _ha_request(
        "POST", ha_url, ha_token, "/api/lovelace/config?force=true", current
    )
    if result is not None:
        print("  ✅ Dashboard pushed — 'Frigate Identity' view added to HA.")
    else:
        print("  ⚠️  Dashboard push failed (HA may be in YAML Lovelace mode).")
        print("      Paste dashboard.yaml manually via Settings → Dashboards → Raw config.")


def _ha_restart(ha_url: str, ha_token: str) -> None:
    """Trigger a Home Assistant restart via the service API."""
    print("  Restarting Home Assistant...")
    _ha_request("POST", ha_url, ha_token, "/api/services/homeassistant/restart", {})
    print("  ✅ Restart triggered — HA will be back online in ~30 seconds.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(
    persons: list[str],
    output_dir: str,
    snapshot_source: str,
    camera_map: dict[str, str],
    persons_meta: dict[str, dict[str, Any]] | None = None,
    camera_zones: dict[str, str] | None = None,
    ha_config_dir: str | None = None,
    ha_url: str | None = None,
    ha_token: str | None = None,
    copy_blueprints: bool = False,
    restart: bool = False,
) -> None:
    if not persons:
        print("ERROR: supply at least one person name.", file=sys.stderr)
        sys.exit(1)

    if persons_meta is None:
        persons_meta = {}
    if camera_zones is None:
        camera_zones = {}

    output_dir = os.path.abspath(output_dir)
    print(f"\nGenerating Frigate Identity dashboard for: {', '.join(persons)}")
    print(f"Snapshot source: {snapshot_source}")
    print(f"Output directory: {output_dir}\n")

    if snapshot_source == "mqtt":
        _write(
            os.path.join(output_dir, "mqtt_cameras.yaml"),
            _dump(_build_mqtt_cameras(persons)),
        )

    if snapshot_source != "frigate_integration":
        _write(
            os.path.join(output_dir, "template_sensors.yaml"),
            _dump(_build_template_sensors(persons, snapshot_source, persons_meta, camera_zones)),
        )

    _write(
        os.path.join(output_dir, "dashboard.yaml"),
        _dump(_build_dashboard(persons, snapshot_source, camera_map, persons_meta)),
    )

    # Danger-zone automations — only when children have dangerous_zones in their meta
    adults = [p for p in persons if _is_adult(persons_meta.get(p, {}))]
    automations = []
    for person in persons:
        meta = persons_meta.get(person, {})
        if not _is_child(meta):
            continue
        zones = meta.get("dangerous_zones") or []
        if not zones:
            continue
        automations.append(
            _build_danger_zone_automation(person, list(zones), bool(adults))
        )
    danger_path = os.path.join(output_dir, "danger_zone_automations.yaml")
    if automations:
        danger_header = (
            "# Generated by examples/generate_dashboard.py\n"
            "# Re-run the script to update this file after adding or removing persons.\n"
            "#\n"
            "# IMPORTANT: Replace 'notify.notify' in each action with your actual\n"
            "# notification service (e.g. notify.mobile_app_your_phone).\n\n"
        )
        parent = os.path.dirname(danger_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(danger_path, "w", encoding="utf-8") as fh:
            fh.write(danger_header + _dump(automations))
        print(f"  Wrote {danger_path}")

    # -----------------------------------------------------------------------
    # Automated HA setup (enabled by flags)
    # -----------------------------------------------------------------------

    if ha_config_dir:
        print()
        _write_ha_package(
            ha_config_dir, output_dir, snapshot_source, bool(automations)
        )
        if copy_blueprints:
            _copy_blueprints(ha_config_dir)

    if ha_url and ha_token:
        print()
        view = _build_view(persons, snapshot_source, camera_map, persons_meta)
        _ha_push_dashboard(ha_url, ha_token, view)
        if restart:
            _ha_restart(ha_url, ha_token)

    # -----------------------------------------------------------------------
    # Next-steps hint (skipped when fully automated)
    # -----------------------------------------------------------------------

    fully_automated = bool(ha_config_dir and ha_url and ha_token)
    if fully_automated:
        print(f"\n✅ All done! Frigate Identity is configured in Home Assistant.")
        if not restart:
            print("   Restart Home Assistant to load the new sensors and cameras.")
        if automations:
            print()
            print("   ⚠️  Edit danger_zone_automations.yaml and replace 'notify.notify'")
            print("      with your actual notification service, then restart HA.")
        return

    print(f"\n✅ Done!  Next steps:")
    print()
    if ha_config_dir:
        print("1. Restart Home Assistant to load the new package file.")
    else:
        if snapshot_source == "mqtt":
            print("1. Add to configuration.yaml (or use --ha-config-dir to automate):")
            print(f"     mqtt:")
            print(f"       camera: !include {os.path.join(output_dir, 'mqtt_cameras.yaml')}")
            print()
            print(f"     template: !include {os.path.join(output_dir, 'template_sensors.yaml')}")
            if automations:
                print()
                print(f"     automation: !include {os.path.join(output_dir, 'danger_zone_automations.yaml')}")
        elif snapshot_source == "frigate_api":
            print("1. Add to configuration.yaml (or use --ha-config-dir to automate):")
            print(f"     template: !include {os.path.join(output_dir, 'template_sensors.yaml')}")
            if automations:
                print()
                print(f"     automation: !include {os.path.join(output_dir, 'danger_zone_automations.yaml')}")
        else:
            print("1. Ensure the official Frigate HA integration is installed.")
            if automations:
                print(f"   Add to configuration.yaml:")
                print(f"     automation: !include {os.path.join(output_dir, 'danger_zone_automations.yaml')}")
        print()
        print("   Restart Home Assistant.")

    if not (ha_url and ha_token):
        print()
        print("2. In Home Assistant: Settings → Dashboards → Add dashboard")
        print("   Open it → Edit ✏️ → ⋮ menu → Raw configuration editor")
        print("   Paste the contents of dashboard.yaml and Save.")
        print()
        print("   Or skip this step next time with: --ha-url URL --ha-token TOKEN")

    if automations:
        print()
        print("   ⚠️  Edit danger_zone_automations.yaml and replace 'notify.notify'")
        print("      with your actual notification service before restarting HA.")


def _parse_camera_map(pairs: list[str]) -> dict[str, str]:
    """Parse 'Person:camera_name' pairs into a dict."""
    result: dict[str, str] = {}
    for pair in pairs:
        if ":" not in pair:
            print(f"ERROR: --cameras entry '{pair}' must be in Person:camera format.",
                  file=sys.stderr)
            sys.exit(1)
        person, camera = pair.split(":", 1)
        result[person.strip()] = camera.strip()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "persons",
        nargs="*",
        metavar="PERSON",
        help=(
            "One or more person names (must match Frigate face recognition names). "
            "Optional when --persons-file is provided; any names given here are "
            "appended to the list from the file."
        ),
    )
    parser.add_argument(
        "--persons-file",
        metavar="FILE",
        help=(
            "Path to the Frigate Identity Service persons.yaml file. "
            "Person names are read from the 'persons' mapping keys. "
            "Any 'camera' field inside a person's entry is used as the default "
            "camera mapping for --snapshot-source frigate_integration. "
            "Explicit --cameras args take precedence over values in the file."
        ),
    )
    parser.add_argument(
        "--output",
        default=".",
        metavar="DIR",
        help="Directory where the generated YAML files are written (default: current dir)",
    )
    parser.add_argument(
        "--snapshot-source",
        choices=["mqtt", "frigate_api", "frigate_integration"],
        default="mqtt",
        metavar="SOURCE",
        help=(
            "How to source the bounded snapshot image. "
            "'mqtt' (default): MQTT camera entities from identity/snapshots/{person}. "
            "'frigate_api': HA template image entities using the snapshot_url attribute "
            "(no MQTT camera config needed). "
            "'frigate_integration': reuse image.<camera>_person entities from the "
            "official Frigate HA integration (requires --cameras mapping)."
        ),
    )
    parser.add_argument(
        "--cameras",
        nargs="*",
        default=[],
        metavar="PERSON:CAMERA",
        help=(
            "Person-to-camera mappings for --snapshot-source frigate_integration, "
            "e.g. Alice:backyard Bob:front_door.  "
            "The camera name must match a Frigate camera name. "
            "These override any 'camera' values found in --persons-file."
        ),
    )
    parser.add_argument(
        "--ha-config-dir",
        metavar="DIR",
        help=(
            "Path to your Home Assistant config directory (usually /config). "
            "When set, the script writes packages/frigate_identity.yaml so HA "
            "loads all generated files automatically, and patches configuration.yaml "
            "to enable packages if needed. Use with --copy-blueprints to also install "
            "the blueprint files."
        ),
    )
    parser.add_argument(
        "--ha-url",
        metavar="URL",
        help=(
            "Home Assistant base URL (e.g. http://homeassistant.local:8123). "
            "When set together with --ha-token, the Lovelace dashboard is pushed "
            "directly to HA via the REST API — no manual pasting required."
        ),
    )
    parser.add_argument(
        "--ha-token",
        metavar="TOKEN",
        help=(
            "Home Assistant long-lived access token. "
            "Create one in HA under Profile → Security → Long-Lived Access Tokens."
        ),
    )
    parser.add_argument(
        "--copy-blueprints",
        action="store_true",
        help=(
            "Copy blueprint YAML files to <ha-config-dir>/blueprints/automation/"
            "frigate_identity/. Requires --ha-config-dir."
        ),
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help=(
            "Trigger a Home Assistant restart after pushing the dashboard. "
            "Requires --ha-url and --ha-token."
        ),
    )
    args = parser.parse_args()

    if args.copy_blueprints and not args.ha_config_dir:
        parser.error("--copy-blueprints requires --ha-config-dir.")
    if args.restart and not (args.ha_url and args.ha_token):
        parser.error("--restart requires --ha-url and --ha-token.")

    # Build persons list and camera map from --persons-file (if given)
    yaml_persons: list[str] = []
    yaml_camera_map: dict[str, str] = {}
    yaml_persons_meta: dict[str, dict[str, Any]] = {}
    yaml_camera_zones: dict[str, str] = {}
    if args.persons_file:
        yaml_persons, yaml_camera_map, yaml_persons_meta, yaml_camera_zones = (
            load_persons_yaml(args.persons_file)
        )

    # Merge: file names first, then any extra CLI names (deduplicating, preserving order)
    seen: set[str] = set()
    merged_persons: list[str] = []
    for name in yaml_persons + list(args.persons):
        if name not in seen:
            seen.add(name)
            merged_persons.append(name)

    if not merged_persons:
        parser.error("Supply at least one person name, or use --persons-file.")

    # CLI --cameras override YAML camera hints
    cli_camera_map = _parse_camera_map(args.cameras)
    camera_map = {**yaml_camera_map, **cli_camera_map}

    generate(
        merged_persons,
        args.output,
        args.snapshot_source,
        camera_map,
        yaml_persons_meta,
        yaml_camera_zones,
        ha_config_dir=args.ha_config_dir,
        ha_url=args.ha_url,
        ha_token=args.ha_token,
        copy_blueprints=args.copy_blueprints,
        restart=args.restart,
    )


if __name__ == "__main__":
    main()

