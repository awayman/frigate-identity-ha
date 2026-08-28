(function () {
  const DEFAULTS = {
    title: "Tracker Geofence",
    zoom: 18,
    show_beeper_zones: true,
    show_tracker_position: true,
    show_distance_to_boundary: true,
    show_status_panel: true,
    enable_beeper: true,
    buzzer_gpio: 0,
    warn_dist_approaching: 50,
    warn_dist_near: 20,
    warn_dist_critical: 5,
  };

  class FrigateIdentityPolygonEditorCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = { ...DEFAULTS };
      this._polygon = [];
      this._initialPolygon = [];
      this._editingFinished = false;
    }

    setConfig(config) {
      if (!config?.tracker_id || !config?.person_name) {
        throw new Error("tracker_id and person_name are required");
      }
      this._config = { ...DEFAULTS, ...config };
      this._polygon = [];
      this._initialPolygon = [];
      this._editingFinished = false;
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._syncFromEntities();
      this._render();
    }

    getCardSize() {
      return 8;
    }

    _slug(value) {
      return String(value || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_|_$/g, "");
    }

    _entityId(suffix) {
      return `sensor.frigate_identity_${this._slug(this._config.person_name)}_${suffix}`;
    }

    _entityState(entityId) {
      return this._hass?.states?.[entityId];
    }

    _syncFromEntities() {
      const geofenceState = this._entityState("geofence_status");
      const attrs = geofenceState?.attributes || {};
      if (!this._polygon.length && Array.isArray(attrs.polygon) && attrs.polygon.length >= 3) {
        this._polygon = attrs.polygon.map((point) => [Number(point[0]), Number(point[1])]);
        this._initialPolygon = this._polygon.map((point) => [...point]);
      }
      if (!this._config.center_latitude && Array.isArray(this._polygon[0])) {
        this._config.center_latitude = this._polygon[0][0];
      }
      if (!this._config.center_longitude && Array.isArray(this._polygon[0])) {
        this._config.center_longitude = this._polygon[0][1];
      }
    }

    _trackerStatus() {
      const geofence = this._entityState("geofence_status");
      const distance = this._entityState("distance_to_boundary");
      const beepZone = this._entityState("beep_zone");
      const battery = this._entityState("battery_percent");
      const position = this._entityState("last_position");
      const relay = this._entityState("relay_state");
      const lastUpdate = this._entityState("last_update");
      const coords = position?.state?.split(",") || [];
      return {
        geofence: geofence?.state || "unknown",
        distance: distance?.state || "unknown",
        beepZone: beepZone?.state || "unknown",
        battery: battery?.state || "unknown",
        relay: relay?.state || "unknown",
        gpsFix: geofence?.attributes?.gps_fix,
        updated: lastUpdate?.state || geofence?.attributes?.last_update || "unknown",
        latitude: Number(coords[0]),
        longitude: Number(coords[1]),
      };
    }

    _mapScale() {
      const zoom = Number(this._config.zoom || DEFAULTS.zoom);
      return 360 / (256 * Math.pow(2, zoom));
    }

    _pointToSvg(lat, lon, width = 520, height = 320) {
      const centerLat = Number(this._config.center_latitude || lat || 0);
      const centerLon = Number(this._config.center_longitude || lon || 0);
      const scale = this._mapScale() * 220;
      return {
        x: width / 2 + (lon - centerLon) / scale,
        y: height / 2 - (lat - centerLat) / scale,
      };
    }

    _svgToPoint(offsetX, offsetY, width = 520, height = 320) {
      const centerLat = Number(this._config.center_latitude || 0);
      const centerLon = Number(this._config.center_longitude || 0);
      const scale = this._mapScale() * 220;
      return [
        Number((centerLat - (offsetY - height / 2) * scale).toFixed(6)),
        Number((centerLon + (offsetX - width / 2) * scale).toFixed(6)),
      ];
    }

    _handleCanvasClick(event) {
      if (this._editingFinished) {
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      this._polygon = [
        ...this._polygon,
        this._svgToPoint(event.clientX - rect.left, event.clientY - rect.top),
      ];
      this._render();
    }

    _handleCanvasContext(event) {
      event.preventDefault();
      if (this._polygon.length >= 3) {
        this._editingFinished = true;
        this._render();
      }
    }

    _clearPolygon() {
      this._polygon = [];
      this._editingFinished = false;
      this._render();
    }

    _cancelChanges() {
      this._polygon = this._initialPolygon.map((point) => [...point]);
      this._editingFinished = Boolean(this._polygon.length);
      this._render();
    }

    async _save() {
      if (!this._hass) {
        return;
      }
      if (this._polygon.length < 3) {
        this._toast("Polygon must have at least 3 points");
        return;
      }
      const data = {
        tracker_id: this._config.tracker_id,
        person_name: this._config.person_name,
        geofence_name: this._config.geofence_name || "",
        polygon: this._polygon,
        relay_entity: this._config.relay_entity,
        enable_beeper: Boolean(this._config.enable_beeper),
        buzzer_gpio: Number(this._config.buzzer_gpio || 0),
        warn_dist_approaching: Number(this._config.warn_dist_approaching || 50),
        warn_dist_near: Number(this._config.warn_dist_near || 20),
        warn_dist_critical: Number(this._config.warn_dist_critical || 5),
      };
      try {
        await this._hass.callService("frigate_identity", "configure_tracker_geofence", data);
        this._initialPolygon = this._polygon.map((point) => [...point]);
        this._editingFinished = true;
        this._toast("Tracker geofence saved");
      } catch (error) {
        this._toast(error?.message || "Unable to save tracker geofence");
      }
    }

    _toast(message) {
      this.dispatchEvent(
        new CustomEvent("hass-notification", {
          bubbles: true,
          composed: true,
          detail: { message },
        }),
      );
    }

    _render() {
      if (!this.shadowRoot || !this._config) {
        return;
      }

      const status = this._trackerStatus();
      const polygonPoints = this._polygon
        .map((point) => this._pointToSvg(point[0], point[1]))
        .map((point) => `${point.x},${point.y}`)
        .join(" ");
      const trackerPoint = Number.isFinite(status.latitude) && Number.isFinite(status.longitude)
        ? this._pointToSvg(status.latitude, status.longitude)
        : null;
      const centerPoint = this._pointToSvg(
        Number(this._config.center_latitude || 0),
        Number(this._config.center_longitude || 0),
      );
      const invalid = this._polygon.length > 0 && this._polygon.length < 3;

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }
          ha-card {
            background: var(--ha-card-background, var(--card-background-color, #fff));
            color: var(--primary-text-color);
          }
          .content {
            display: grid;
            gap: 16px;
            padding: 16px;
          }
          .status {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 8px;
          }
          .pill {
            border-radius: 12px;
            background: var(--secondary-background-color);
            padding: 8px 10px;
            font-size: 0.9rem;
          }
          .map {
            border: 1px solid var(--divider-color);
            border-radius: 16px;
            overflow: hidden;
            background:
              linear-gradient(0deg, rgba(255,255,255,0.04) 24%, transparent 25%, transparent 74%, rgba(255,255,255,0.04) 75%, rgba(255,255,255,0.04)),
              linear-gradient(90deg, rgba(255,255,255,0.04) 24%, transparent 25%, transparent 74%, rgba(255,255,255,0.04) 75%, rgba(255,255,255,0.04)),
              var(--secondary-background-color);
            background-size: 32px 32px;
            position: relative;
          }
          svg {
            display: block;
            width: 100%;
            height: auto;
            cursor: crosshair;
          }
          .controls,
          .points {
            display: grid;
            gap: 8px;
          }
          .row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 8px;
          }
          label {
            display: grid;
            gap: 4px;
            font-size: 0.85rem;
          }
          input {
            width: 100%;
            box-sizing: border-box;
            padding: 8px;
            border-radius: 10px;
            border: 1px solid var(--divider-color);
            background: var(--card-background-color);
            color: var(--primary-text-color);
          }
          .buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }
          button {
            border: 0;
            border-radius: 999px;
            padding: 10px 14px;
            cursor: pointer;
            color: #fff;
            background: var(--primary-color);
          }
          button.secondary {
            background: var(--secondary-text-color);
          }
          button.warn {
            background: var(--error-color);
          }
          ol {
            margin: 0;
            padding-left: 18px;
          }
          .hint {
            font-size: 0.85rem;
            color: var(--secondary-text-color);
          }
        </style>
        <ha-card header="${this._config.title}">
          <div class="content">
            ${this._config.show_status_panel ? `
              <div class="status">
                <div class="pill"><strong>Status</strong><br>${status.geofence}</div>
                <div class="pill"><strong>Battery</strong><br>${status.battery}%</div>
                <div class="pill"><strong>Beep Zone</strong><br>${status.beepZone}</div>
                <div class="pill"><strong>GPS Fix</strong><br>${status.gpsFix === false ? "lost" : "ok"}</div>
                <div class="pill"><strong>Relay</strong><br>${status.relay}</div>
                <div class="pill"><strong>Distance</strong><br>${this._config.show_distance_to_boundary ? status.distance : "hidden"}</div>
              </div>` : ""}
            <div class="map">
              <svg viewBox="0 0 520 320" aria-label="Geofence editor canvas">
                ${this._config.show_beeper_zones ? `
                  <circle cx="${centerPoint.x}" cy="${centerPoint.y}" r="90" fill="rgba(76,175,80,0.12)" stroke="#4caf50" stroke-dasharray="4 4"></circle>
                  <circle cx="${centerPoint.x}" cy="${centerPoint.y}" r="60" fill="rgba(255,235,59,0.12)" stroke="#ffeb3b" stroke-dasharray="4 4"></circle>
                  <circle cx="${centerPoint.x}" cy="${centerPoint.y}" r="36" fill="rgba(255,152,0,0.12)" stroke="#ff9800" stroke-dasharray="4 4"></circle>
                  <circle cx="${centerPoint.x}" cy="${centerPoint.y}" r="18" fill="rgba(244,67,54,0.16)" stroke="#f44336" stroke-dasharray="4 4"></circle>
                ` : ""}
                <circle cx="${centerPoint.x}" cy="${centerPoint.y}" r="6" fill="#2196f3"></circle>
                ${polygonPoints ? `<polygon points="${polygonPoints}" fill="rgba(33,150,243,0.18)" stroke="${invalid ? "#f44336" : "#2196f3"}" stroke-width="2"></polygon>` : ""}
                ${this._polygon.map((point, index) => {
                  const svgPoint = this._pointToSvg(point[0], point[1]);
                  return `<g>
                    <circle cx="${svgPoint.x}" cy="${svgPoint.y}" r="5" fill="${invalid ? "#f44336" : "#2196f3"}"></circle>
                    <text x="${svgPoint.x + 8}" y="${svgPoint.y - 8}" fill="currentColor" font-size="12">${index + 1}</text>
                  </g>`;
                }).join("")}
                ${this._config.show_tracker_position && trackerPoint ? `
                  <circle cx="${trackerPoint.x}" cy="${trackerPoint.y}" r="7" fill="#9c27b0"></circle>
                  <text x="${trackerPoint.x + 8}" y="${trackerPoint.y + 4}" fill="currentColor" font-size="12">Tracker</text>
                ` : ""}
              </svg>
            </div>
            <div class="hint">Click to add vertices. Right-click to finish the polygon.</div>
            <div class="controls">
              <div class="row">
                <label>Approaching (m)<input data-field="warn_dist_approaching" type="number" value="${this._config.warn_dist_approaching}"></label>
                <label>Near (m)<input data-field="warn_dist_near" type="number" value="${this._config.warn_dist_near}"></label>
                <label>Critical (m)<input data-field="warn_dist_critical" type="number" value="${this._config.warn_dist_critical}"></label>
              </div>
            </div>
            <div class="buttons">
              <button id="save">Save</button>
              <button id="cancel" class="secondary">Cancel</button>
              <button id="clear" class="warn">Clear</button>
            </div>
            <div class="points">
              <strong>Polygon points (${this._polygon.length})</strong>
              <ol>${this._polygon.map((point) => `<li>${point[0]}, ${point[1]}</li>`).join("")}</ol>
            </div>
          </div>
        </ha-card>
      `;

      const svg = this.shadowRoot.querySelector("svg");
      if (svg) {
        svg.addEventListener("click", this._handleCanvasClick.bind(this));
        svg.addEventListener("contextmenu", this._handleCanvasContext.bind(this));
      }
      this.shadowRoot.querySelectorAll("input[data-field]").forEach((input) => {
        input.addEventListener("change", (event) => {
          const field = event.target.getAttribute("data-field");
          this._config[field] = Number(event.target.value);
        });
      });
      this.shadowRoot.getElementById("save")?.addEventListener("click", () => this._save());
      this.shadowRoot.getElementById("cancel")?.addEventListener("click", () => this._cancelChanges());
      this.shadowRoot.getElementById("clear")?.addEventListener("click", () => this._clearPolygon());
    }
  }

  customElements.define(
    "frigate-identity-polygon-editor",
    FrigateIdentityPolygonEditorCard,
  );

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "frigate-identity-polygon-editor",
    name: "Frigate Identity Polygon Editor",
    description: "Visual editor for Meshtastic tracker geofences",
  });
})();
