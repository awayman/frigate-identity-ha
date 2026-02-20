#!/usr/bin/env python3
"""Generate Home Assistant configuration for the Frigate Identity dashboard.

This script produces three ready-to-use YAML files from a list of person names:

  - mqtt_cameras.yaml        MQTT camera entities (bounded snapshots from Frigate)
  - template_sensors.yaml    Per-person location / confidence / zone template sensors
  - dashboard.yaml           Full Lovelace dashboard (snapshot + location per person)

Usage
-----
    python generate_dashboard.py Alice Bob Dad Mom

    # Write to a custom output directory
    python generate_dashboard.py --output /config/frigate_identity Alice Bob Dad Mom

Then add to ``configuration.yaml``::

    mqtt:
      camera: !include frigate_identity/mqtt_cameras.yaml

    template: !include frigate_identity/template_sensors.yaml

Finally copy ``dashboard.yaml`` to a Lovelace raw-config dashboard or paste its
content into an existing view.
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


def _build_template_sensors(persons: list[str]) -> list[dict[str, Any]]:
    return [{"sensor": [_person_template_sensor(p) for p in persons]}]


# ---------------------------------------------------------------------------
# Dashboard cards
# ---------------------------------------------------------------------------

def _person_card(person: str) -> dict[str, Any]:
    slug = _slug(person)
    camera_entity = f"camera.{slug}_snapshot"
    location_entity = f"sensor.{slug}_location"

    snapshot_card: dict[str, Any] = {
        "type": "picture-entity",
        "entity": camera_entity,
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


def _build_dashboard(persons: list[str]) -> dict[str, Any]:
    header_card: dict[str, Any] = {
        "type": "markdown",
        "content": (
            "# 📍 Frigate Identity – Person Tracker\n"
            "Real-time location and bounded snapshot for each tracked person."
        ),
    }

    person_cards = [_person_card(p) for p in persons]

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_FILE_HEADER + content)
    print(f"  Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(persons: list[str], output_dir: str) -> None:
    if not persons:
        print("ERROR: supply at least one person name.", file=sys.stderr)
        sys.exit(1)

    output_dir = os.path.abspath(output_dir)
    print(f"\nGenerating Frigate Identity dashboard for: {', '.join(persons)}")
    print(f"Output directory: {output_dir}\n")

    _write(
        os.path.join(output_dir, "mqtt_cameras.yaml"),
        _dump(_build_mqtt_cameras(persons)),
    )
    _write(
        os.path.join(output_dir, "template_sensors.yaml"),
        _dump(_build_template_sensors(persons)),
    )
    _write(
        os.path.join(output_dir, "dashboard.yaml"),
        _dump(_build_dashboard(persons)),
    )

    print("\n✅ Done!  Next steps:")
    print()
    print("1. Add to configuration.yaml:")
    print("     mqtt:")
    print("       camera: !include frigate_identity/mqtt_cameras.yaml")
    print()
    print("     template: !include frigate_identity/template_sensors.yaml")
    print()
    print("2. Restart Home Assistant.")
    print()
    print("3. In Lovelace → Edit dashboard → Raw configuration editor,")
    print("   paste the contents of dashboard.yaml.")


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
    args = parser.parse_args()
    generate(args.persons, args.output)


if __name__ == "__main__":
    main()
