"""AppDaemon app — Frigate Identity Dashboard auto-generator.

Automatically (re-)generates the Frigate Identity HA configuration whenever:

* Home Assistant starts (``initialize`` is called)
* A camera's Area assignment changes (``area_registry_updated`` event)
* A device moves to a different area (``device_registry_updated`` event)
* The Frigate Identity ``persons.yaml`` file is modified on disk
* Daily at the configured time (default 03:00 local time)

All regeneration calls are **debounced** (default 10 s) so rapid successive
events (e.g. bulk area re-assignments) produce only one generation run.

Configuration (in ``apps.yaml``)::

    frigate_identity:
      module: frigate_identity_dashboard
      class: FrigateIdentityDashboard

      # Path to the Frigate Identity Service persons.yaml
      persons_file: /config/persons.yaml

      # Directory to write generated YAML files into
      output_dir: /config/frigate_identity

      # HA config directory — enables automatic package file creation
      ha_config_dir: /config

      # HA base URL (default: http://localhost:8123)
      ha_url: http://localhost:8123

      # Long-lived access token (required for area lookup and Lovelace push)
      # Create at: Profile → Security → Long-Lived Access Tokens
      ha_token: !secret ha_long_lived_token

      # Snapshot source: mqtt (default) | frigate_api | frigate_integration
      snapshot_source: mqtt

      # Copy blueprints to HA on (re-)generation (default: true)
      copy_blueprints: true

      # Auto-restart HA after generation (default: false — restart manually
      # the first time; subsequent runs only update dashboard + automations)
      auto_restart: false

      # Daily regeneration time in HH:MM format (default: "03:00")
      daily_refresh_time: "03:00"

      # Debounce delay in seconds (default: 10)
      debounce_seconds: 10

      # How often to poll persons.yaml for changes, in seconds (default: 30)
      file_poll_interval: 30

      # Path to generate_dashboard.py — only needed if not using the default
      # HACS installation path (/config/custom_components/frigate_identity/
      # examples/generate_dashboard.py)
      # generator_script: /config/examples/generate_dashboard.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from typing import Any

import appdaemon.plugins.hass.hassapi as hass
import yaml

# Default path when installed via HACS
_DEFAULT_GENERATOR_PATH = (
    "/config/custom_components/frigate_identity/examples/generate_dashboard.py"
)


class FrigateIdentityDashboard(hass.Hass):
    """AppDaemon app that keeps the Frigate Identity HA setup up-to-date."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        self.log("Frigate Identity Dashboard app starting…")

        # Load the generator module once
        self._gen: types.ModuleType | None = self._load_generator()
        if self._gen is None:
            self.log(
                "Generator module could not be loaded — app inactive.",
                level="ERROR",
            )
            return

        # Runtime state
        self._debounce_handle: Any = None
        self._persons_mtime: float = 0.0

        # Validate required config
        if not self.args.get("persons_file"):
            self.log("'persons_file' is required in apps.yaml.", level="ERROR")
            return
        if not self.args.get("ha_token"):
            self.log(
                "'ha_token' is required for area lookup and Lovelace push.",
                level="WARNING",
            )

        # ---- Listeners -----------------------------------------------

        # Re-generate when camera area assignments change
        self.listen_event(
            self._on_registry_update, "area_registry_updated"
        )
        self.listen_event(
            self._on_registry_update, "device_registry_updated"
        )

        # Poll persons.yaml for file changes
        poll_interval = int(self.args.get("file_poll_interval", 30))
        self.run_every(self._poll_persons_file, "now+1", poll_interval)

        # Daily full refresh
        daily_time = self.args.get("daily_refresh_time", "03:00")
        self.run_daily(self._daily_refresh, daily_time)

        # ---- Initial generation ----------------------------------------
        self._generate("startup")

    # ------------------------------------------------------------------
    # Trigger handlers
    # ------------------------------------------------------------------

    def _on_registry_update(
        self, event_name: str, data: dict[str, Any], kwargs: dict[str, Any]
    ) -> None:
        self._schedule_regen(f"HA event: {event_name}")

    def _poll_persons_file(self, kwargs: dict[str, Any]) -> None:
        """Check persons.yaml mtime; schedule regeneration if it changed."""
        path = self.args.get("persons_file", "")
        if not path:
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if mtime != self._persons_mtime:
            if self._persons_mtime != 0.0:
                self.log(f"persons.yaml changed — scheduling regeneration.")
                self._schedule_regen("persons.yaml changed")
            self._persons_mtime = mtime

    def _daily_refresh(self, kwargs: dict[str, Any]) -> None:
        self._generate("daily refresh")

    # ------------------------------------------------------------------
    # Debounce
    # ------------------------------------------------------------------

    def _schedule_regen(self, reason: str) -> None:
        """Cancel any pending regen timer and schedule a new debounced one."""
        if self._debounce_handle is not None:
            try:
                self.cancel_timer(self._debounce_handle)
            except (ValueError, TypeError) as exc:
                self.log(f"Could not cancel pending timer: {exc}", level="DEBUG")
        delay = int(self.args.get("debounce_seconds", 10))
        self.log(f"Regeneration queued in {delay}s ({reason}).")
        self._debounce_handle = self.run_in(
            self._debounced_generate, delay, reason=reason
        )

    def _debounced_generate(self, kwargs: dict[str, Any]) -> None:
        self._debounce_handle = None
        self._generate(kwargs.get("reason", "debounced"))

    # ------------------------------------------------------------------
    # Generator
    # ------------------------------------------------------------------

    def _load_generator(self) -> types.ModuleType | None:
        """Import ``generate_dashboard.py`` from the configured path."""
        script_path = self.args.get("generator_script", _DEFAULT_GENERATOR_PATH)
        if not os.path.exists(script_path):
            self.log(
                f"Generator script not found: {script_path}\n"
                "Set 'generator_script' in apps.yaml if installed in a "
                "non-standard location.",
                level="ERROR",
            )
            return None
        spec = importlib.util.spec_from_file_location(
            "generate_dashboard", script_path
        )
        if spec is None or spec.loader is None:
            self.log(f"Could not create module spec for {script_path}", level="ERROR")
            return None
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except (ImportError, SyntaxError, AttributeError) as exc:
            self.log(f"Failed to load generator ({type(exc).__name__}): {exc}",
                     level="ERROR")
            return None
        self.log(f"Loaded generator from {script_path}")
        return mod

    def _generate(self, reason: str = "manual") -> None:
        """Load persons.yaml and call generate() from the imported module."""
        if self._gen is None:
            return

        persons_file: str = self.args.get("persons_file", "")
        output_dir: str = self.args.get("output_dir", "/config/frigate_identity")
        snapshot_source: str = self.args.get("snapshot_source", "mqtt")
        ha_config_dir: str | None = self.args.get("ha_config_dir")
        ha_url: str = self.args.get("ha_url", "http://localhost:8123")
        ha_token: str | None = self.args.get("ha_token")
        copy_blueprints: bool = bool(self.args.get("copy_blueprints", True))

        self.log(f"Generating Frigate Identity config ({reason})…")

        # Redirect generator stdout/stderr to AppDaemon log
        class _LogWriter:
            def __init__(self_, level: str = "INFO") -> None:
                self_._level = level
                self_._buf = ""

            def write(self_, msg: str) -> None:
                self_._buf += msg
                while "\n" in self_._buf:
                    line, self_._buf = self_._buf.split("\n", 1)
                    if line.strip():
                        self.log(line, level=self_._level)

            def flush(self_) -> None:
                if self_._buf.strip():
                    self.log(self_._buf, level=self_._level)
                    self_._buf = ""

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = _LogWriter("INFO")  # type: ignore[assignment]
        sys.stderr = _LogWriter("WARNING")  # type: ignore[assignment]

        try:
            persons, camera_map, persons_meta, camera_zones = (
                self._gen.load_persons_yaml(persons_file)
            )
            self._gen.generate(
                persons=persons,
                output_dir=output_dir,
                snapshot_source=snapshot_source,
                camera_map=camera_map,
                persons_meta=persons_meta,
                camera_zones=camera_zones,
                ha_config_dir=ha_config_dir,
                ha_url=ha_url,
                ha_token=ha_token,
                copy_blueprints=copy_blueprints,
                restart=False,  # AppDaemon handles restart below
            )
            self.log("✅ Generation complete.")

            if self.args.get("auto_restart", False):
                self.log("Restarting Home Assistant to load new configuration…")
                self.call_service("homeassistant/restart")

        except SystemExit as exc:
            # Generator calls sys.exit(1) on fatal errors; log and continue.
            self.log(
                f"Generation failed (exit code {exc.code}). "
                "Check the log lines above for details.",
                level="ERROR",
            )
        except (OSError, yaml.YAMLError) as exc:
            self.log(f"File I/O or YAML error during generation: {exc}", level="ERROR")
        except (TypeError, ValueError, KeyError) as exc:
            self.log(f"Configuration or data error during generation: {exc}",
                     level="ERROR")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
