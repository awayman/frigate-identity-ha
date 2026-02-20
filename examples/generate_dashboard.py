#!/usr/bin/env python3
"""Generate Home Assistant configuration for the Frigate Identity dashboard.

This script produces ready-to-use YAML files from a list of person names.
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
import os
import sys
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Return a lowercase, underscore-separated entity-id-friendly slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


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
    persons: list[str], snapshot_source: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [
        {"sensor": [_person_template_sensor(p) for p in persons]}
    ]
    if snapshot_source == "frigate_api":
        result.append({"image": [_person_template_image(p) for p in persons]})
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
    person: str, snapshot_source: str, camera_map: dict[str, str]
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

    status_card: dict[str, Any] = {
        "type": "entities",
        "title": f"{person} Status",
        "entities": [
            {"entity": location_entity, "name": "Location"},
            {
                "type": "attribute",
                "entity": location_entity,
                "attribute": "zones",
                "name": "Zones",
            },
            {
                "type": "attribute",
                "entity": location_entity,
                "attribute": "confidence",
                "name": "Confidence",
            },
            {
                "type": "attribute",
                "entity": location_entity,
                "attribute": "source",
                "name": "Source",
            },
            {
                "type": "attribute",
                "entity": location_entity,
                "attribute": "last_seen",
                "name": "Last Seen",
            },
        ],
    }

    return {
        "type": "vertical-stack",
        "cards": [snapshot_card, status_card],
    }


def _build_dashboard(
    persons: list[str], snapshot_source: str, camera_map: dict[str, str]
) -> dict[str, Any]:
    header_card: dict[str, Any] = {
        "type": "markdown",
        "content": (
            "# 📍 Frigate Identity – Person Tracker\n"
            "Real-time location and bounded snapshot for each tracked person."
        ),
    }

    person_cards = [_person_card(p, snapshot_source, camera_map) for p in persons]

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
        "icon": "mdi:account-search",
        "cards": [header_card, *person_cards, summary_card],
    }


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
# Main
# ---------------------------------------------------------------------------

def generate(
    persons: list[str],
    output_dir: str,
    snapshot_source: str,
    camera_map: dict[str, str],
) -> None:
    if not persons:
        print("ERROR: supply at least one person name.", file=sys.stderr)
        sys.exit(1)

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
            _dump(_build_template_sensors(persons, snapshot_source)),
        )

    _write(
        os.path.join(output_dir, "dashboard.yaml"),
        _dump(_build_dashboard(persons, snapshot_source, camera_map)),
    )

    print(f"\n✅ Done!  Next steps:")
    print()
    if snapshot_source == "mqtt":
        print("1. Add to configuration.yaml:")
        print(f"     mqtt:")
        print(f"       camera: !include {os.path.join(output_dir, 'mqtt_cameras.yaml')}")
        print()
        print(f"     template: !include {os.path.join(output_dir, 'template_sensors.yaml')}")
        print()
        print("2. Restart Home Assistant.")
        print()
        print("3. In Lovelace → Edit dashboard → Raw configuration editor,")
        print("   paste the contents of dashboard.yaml.")
    elif snapshot_source == "frigate_api":
        print("1. Add to configuration.yaml:")
        print(f"     template: !include {os.path.join(output_dir, 'template_sensors.yaml')}")
        print()
        print("2. Restart Home Assistant.")
        print()
        print("3. In Lovelace → Edit dashboard → Raw configuration editor,")
        print("   paste the contents of dashboard.yaml.")
    else:  # frigate_integration
        print("1. Ensure the official Frigate HA integration is installed and")
        print("   the image.<camera>_person entities are available.")
        print()
        print("2. In Lovelace → Edit dashboard → Raw configuration editor,")
        print("   paste the contents of dashboard.yaml.")
        print()
        print("   NOTE: Each snapshot card shows the latest person detected on the")
        print("   mapped camera, not necessarily the specific identified person.")


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
        nargs="+",
        metavar="PERSON",
        help="One or more person names (must match Frigate face recognition names)",
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
            "The camera name must match a Frigate camera name."
        ),
    )
    args = parser.parse_args()
    camera_map = _parse_camera_map(args.cameras)
    generate(args.persons, args.output, args.snapshot_source, camera_map)


if __name__ == "__main__":
    main()

