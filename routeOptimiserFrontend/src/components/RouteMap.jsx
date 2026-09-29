/* eslint-disable react/prop-types */
// src/components/RouteMap.jsx
// The map surface — the primary instrument on this platform.
//
// Used by both the accessibility map (whole network) and the shipment planner (one route
// highlighted against the network). Sharing it keeps the colour language identical between
// the two screens — a corridor that reads as degraded on the map reads the same in the plan.
//
// Two things make it work as an operations instrument rather than a picture:
//
//   * Real satellite imagery underneath. A flat road atlas tells you a corridor exists; a
//     photograph of the terrain tells you what it climbs through and what's around it —
//     the same reason Windy and Zoom Earth reach for a globe of actual imagery instead of
//     a vector map. A thin place-name/border layer floats on top so the photography still
//     reads as terrain rather than an unlabeled satellite dump.
//
//   * Corridors carry their condition in stroke width and dash pattern as well as colour.
//     A degraded road is thin and broken; a closed one is a fine dotted red line. That
//     survives colourblindness, a sunlit phone screen and a washed-out projector, none of
//     which are edge cases for this audience.

import { Fragment, memo, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";

import { LABELS, TILES, TILE_THEME } from "../lib/mapTiles";
export { TILES, TILE_THEME };
import {
  ACCESSIBILITY_BANDS,
  HAZARD_LABELS,
  IMPASSABLE_STYLE,
  RISK_BANDS,
  STATUS_COLORS,
  accessibilityColor,
  closureLabel,
  corridorRiskStyle,
  corridorStyle,
  incidentLabel,
  riskColor,
  segmentRisk,
  terrainLabel,
} from "../lib/accessibility";
import { formatKm, formatPercent, timeAgo } from "../lib/format";

// Pan-India: centred on the subcontinent. The North East is still one zoom-in away.
const INDIA_CENTER = [22.8, 81.0];
const ACCENT = "#38bdf8";

// Graticule spanning mainland India. Drawn under everything at very low contrast.
//
// This exists for the case the basemap does not load — which for this audience is not an
// edge case but the normal field condition. Without any ground reference the corridor
// network is a web of lines floating in black, and a responder cannot tell north from
// south or judge a distance. Two degrees of latitude and longitude is enough to anchor it.
const GRATICULE = { latFrom: 8, latTo: 36, lonFrom: 68, lonTo: 98, step: 4 };

// Regional hubs, labelled at every zoom. The rest of the towns get labels only once the
// view is close enough for them not to collide.
//
// At the default zoom all 27 names overlap into an unreadable smear around Guwahati, which
// is worse than no labels at all. Cartography solves this by ranking places and revealing
// the minor ones as you zoom — the same trick every road atlas uses. These eleven are the
// state capitals and the major railheads, which is what someone orienting themselves on
// this network actually looks for first.
// Pan-India: the metros and the regional gateways are labelled at national zoom; the North
// Eastern capitals appear once the view closes in on the region.
const MAJOR_HUBS = new Set([
  "Delhi", "Mumbai", "Kolkata", "Chennai", "Bengaluru", "Hyderabad", "Ahmedabad",
  "Jaipur", "Lucknow", "Patna", "Bhubaneswar", "Nagpur", "Bhopal", "Kochi",
  "Srinagar", "Leh", "Guwahati", "Siliguri", "Visakhapatnam", "Pune",
]);
const REGIONAL_HUBS = new Set([
  "Shillong", "Imphal", "Aizawl", "Agartala", "Kohima", "Itanagar", "Gangtok",
  "Dibrugarh", "Silchar", "Jammu", "Chandigarh", "Shimla", "Dehradun", "Manali", "Kargil",
  "Jodhpur", "Jaisalmer", "Raipur", "Ranchi", "Panaji", "Mangaluru", "Thiruvananthapuram",
  "Madurai", "Coimbatore", "Varanasi", "Indore", "Darbhanga", "Puri", "Tawang",
]);
const REGIONAL_LABEL_ZOOM = 6;
const MINOR_LABEL_ZOOM = 8;

/** Track zoom so labels can be revealed progressively. */
function useZoomLevel() {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  useEffect(() => {
    const update = () => setZoom(map.getZoom());
    map.on("zoomend", update);
    return () => map.off("zoomend", update);
  }, [map]);
  return zoom;
}

/* Fixed geometry — computed once at module load rather than on every render. */
const GRATICULE_LINES = (() => {
  const lines = [];
  for (let lat = GRATICULE.latFrom; lat <= GRATICULE.latTo; lat += GRATICULE.step) {
    lines.push({ key: `lat-${lat}`, positions: [[lat, GRATICULE.lonFrom], [lat, GRATICULE.lonTo]] });
  }
  for (let lon = GRATICULE.lonFrom; lon <= GRATICULE.lonTo; lon += GRATICULE.step) {
    lines.push({ key: `lon-${lon}`, positions: [[GRATICULE.latFrom, lon], [GRATICULE.latTo, lon]] });
  }
  return lines;
})();

const Graticule = memo(function Graticule() {
  const lines = GRATICULE_LINES;
  return (
    <>
      {lines.map((l) => (
        <Polyline
          key={l.key}
          positions={l.positions}
          interactive={false}
          pathOptions={{ color: "#7f97ad", weight: 1, opacity: 0.13, dashArray: "2 6" }}
        />
      ))}
    </>
  );
});

/** Fit the viewport to whatever is being shown, so a route is never half off-screen. */
function FitBounds({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds?.length >= 2) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 9 });
    }
  }, [bounds, map]);
  return null;
}

/** Legend for hazard / multi-hazard colouring: higher is worse, one ramp. */
const RiskLegend = ({ compact, title }) => (
  <div className={`panel-glass px-3 py-2.5 ${compact ? "text-[10px]" : "text-[11px]"}`}>
    <p className="label-micro mb-1.5">{title}</p>
    <ul className="space-y-1">
      {RISK_BANDS.map((band) => (
        <li key={band.label} className="flex items-center gap-2 whitespace-nowrap">
          <svg width="26" height="8" aria-hidden="true" className="shrink-0">
            <line x1="0" y1="4" x2="26" y2="4" stroke={band.color} strokeWidth={band.weight}
              strokeDasharray={band.dash || undefined} strokeLinecap="round" />
          </svg>
          <span className="text-ink-secondary">{band.label}</span>
          <span className="text-ink-muted ml-auto pl-2 tabular-nums">{band.range}</span>
        </li>
      ))}
      <li className="flex items-center gap-2 whitespace-nowrap">
        <svg width="26" height="8" aria-hidden="true" className="shrink-0">
          <line x1="0" y1="4" x2="26" y2="4" stroke="#4b5b6b" strokeWidth="2" strokeDasharray="2 4" />
        </svg>
        <span className="text-ink-muted">Not applicable here</span>
      </li>
      <li className="flex items-center gap-2 whitespace-nowrap pt-1 border-t border-white/10 mt-1">
        <svg width="26" height="8" aria-hidden="true" className="shrink-0">
          <line x1="0" y1="4" x2="26" y2="4" stroke={IMPASSABLE_STYLE.color} strokeWidth={IMPASSABLE_STYLE.weight}
            strokeDasharray={IMPASSABLE_STYLE.dash} strokeLinecap="round" />
        </svg>
        <span className="text-[#e97676]">Closed</span>
      </li>
    </ul>
  </div>
);

/**
 * Legend.
 *
 * Sits on the map rather than beside it because the question it answers ("what does this
 * line mean?") is asked while looking at a line. It shows the stroke as it is actually
 * drawn — width and dash included — so it explains the whole encoding, not just the colour.
 */
const MapLegend = ({ compact }) => (
  <div className={`panel-glass px-3 py-2.5 ${compact ? "text-[10px]" : "text-[11px]"}`}>
    <p className="label-micro mb-1.5">Corridor accessibility</p>
    <ul className="space-y-1">
      {ACCESSIBILITY_BANDS.map((band) => (
        <li key={band.label} className="flex items-center gap-2 whitespace-nowrap">
          <svg width="26" height="8" aria-hidden="true" className="shrink-0">
            <line
              x1="0" y1="4" x2="26" y2="4"
              stroke={band.color}
              strokeWidth={band.weight}
              strokeDasharray={band.dash || undefined}
              strokeLinecap="round"
            />
          </svg>
          <span className="text-ink-secondary">{band.label}</span>
          <span className="text-ink-muted ml-auto pl-2 tabular-nums">
            {band.min}–{band.max}
          </span>
        </li>
      ))}
      <li className="flex items-center gap-2 whitespace-nowrap pt-1 border-t border-white/10 mt-1">
        <svg width="26" height="8" aria-hidden="true" className="shrink-0">
          <line
            x1="0" y1="4" x2="26" y2="4"
            stroke={IMPASSABLE_STYLE.color}
            strokeWidth={IMPASSABLE_STYLE.weight}
            strokeDasharray={IMPASSABLE_STYLE.dash}
            strokeLinecap="round"
          />
        </svg>
        <span className="text-[#e97676]">Closed</span>
      </li>
    </ul>
  </div>
);

const LocationMarkers = memo(function LocationMarkers({ locations }) {
  const zoom = useZoomLevel();
  return (
    <>
      {locations.map((location) => {
        const major = MAJOR_HUBS.has(location.name);
        const regional = REGIONAL_HUBS.has(location.name);
        const labelled = major || (regional && zoom >= REGIONAL_LABEL_ZOOM) || zoom >= MINOR_LABEL_ZOOM;
        return (
          <CircleMarker
            key={location.id}
            center={[location.latitude, location.longitude]}
            radius={major ? 4.5 : 3.5}
            pathOptions={{
              color: "#0a0e13",
              fillColor: major ? "#e6edf5" : "#93a9be",
              fillOpacity: 0.95,
              weight: 1.5,
            }}
          >
            {labelled && (
              /* Permanent, not hover-only. With the basemap missing these names are the
                 only thing telling a reader which line is which, and even with it they
                 save a click on a screen people scan rather than explore. */
              <Tooltip
                direction="right"
                offset={[6, 0]}
                permanent
                className={`ner-town-label${major ? " ner-town-major" : ""}`}
                opacity={1}
              >
                {location.name}
              </Tooltip>
            )}
            <Popup>
              <strong>{location.name}</strong>
              <div style={{ color: "#9fb2c6", fontSize: 12 }}>
                {location.district}, {location.state}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </>
  );
});

export default function RouteMap({
  segments = [],
  locations = [],
  incidents = [],
  highlightSegmentIds = null,
  onSelectSegment,
  selectedSegmentId,
  height = 560,
  fitToHighlight = true,
  showLegend = true,
  overlay = null,
  // Full-bleed: the map is the page canvas rather than a figure sitting in a card, so it
  // drops its frame, fills whatever box it is given, and takes the wheel — on a screen
  // where the map IS the interface, trapping scroll would be the surprising behaviour.
  bleed = false,
  // What the corridor colour encodes: "accessibility" (default), "multi_hazard" (the
  // terrain-weighted disruption index) or one hazard key ("heat", "snow", "fog", ...).
  colorBy = "accessibility",
}) {
  // Track whether the basemap actually arrived. If it did not, the map says so plainly
  // rather than presenting an empty black rectangle as though that were the terrain.
  const [tilesFailed, setTilesFailed] = useState(false);

  const highlightSet = useMemo(
    () => (highlightSegmentIds ? new Set(highlightSegmentIds) : null),
    [highlightSegmentIds]
  );

  // Memoised: this feeds the bounds calculation below, which would otherwise see a new
  // array identity on every render and refit the viewport under the user's hands.
  const drawable = useMemo(
    () => segments.filter((s) => s.source_coords && s.destination_coords),
    [segments]
  );

  const bounds = useMemo(() => {
    const source = fitToHighlight && highlightSet
      ? drawable.filter((s) => highlightSet.has(s.id))
      : drawable;
    const points = source.flatMap((s) => [s.source_coords, s.destination_coords]);
    return points.length >= 2 ? points : null;
  }, [drawable, highlightSet, fitToHighlight]);

  return (
    <div
      className={`relative overflow-hidden ner-map ner-map-tiles-${TILE_THEME} ${
        bleed ? "h-full w-full" : "rounded-xl border border-white/10"
      }`}
      style={bleed ? undefined : { height }}
      data-testid="route-map"
    >
      <MapContainer
        center={INDIA_CENTER}
        zoom={5}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={bleed}
        zoomControl={false}
      >
        {/* Basemap: real satellite/aerial photography (Esri World Imagery), free and
            keyless. maxNativeZoom is set below the imagery's actual resolution ceiling for
            this terrain, so Leaflet upscales the last real tile at deep zoom instead of
            requesting — and 404ing on — levels Esri has no photography for.

            VITE_MAP_TILE_URL overrides it for a different provider; set VITE_MAP_TILE_THEME
            to "light" or "dark" if that override is a conventional street map rather than
            photography, so the CSS in index.css applies the right tonal treatment instead
            of the photographic one. */}
        <TileLayer
          attribution={TILES.attribution}
          url={TILES.url}
          subdomains={TILES.subdomains}
          maxZoom={19}
          maxNativeZoom={TILES.maxNativeZoom}
          eventHandlers={{
            tileerror: () => setTilesFailed(true),
            tileload: () => setTilesFailed(false),
          }}
        />
        {/* Place names and borders over the imagery. Rendered on Leaflet's built-in
            overlayPane — it already exists at map init, so there's no pane-creation race
            with react-leaflet's eager layer mounting — which sits above the base tile pane
            but below the vector layers that follow (graticule, corridors, markers), so
            labels read as part of the ground rather than competing with the data. */}
        <TileLayer
          url={LABELS.url}
          subdomains={LABELS.subdomains}
          maxZoom={19}
          maxNativeZoom={LABELS.maxNativeZoom}
          pane="overlayPane"
          zIndex={350}
        />
        <Graticule />
        {bounds && <FitBounds bounds={bounds} />}

        {drawable.map((segment) => {
          const highlighted = highlightSet ? highlightSet.has(segment.id) : false;
          const dimmed = highlightSet && !highlighted;
          const selected = segment.id === selectedSegmentId;
          const style = colorBy === "accessibility"
            ? corridorStyle(segment.accessibility_score, segment.impassable)
            : corridorRiskStyle(segmentRisk(segment, colorBy), segment.impassable);

          return (
            <Fragment key={segment.id}>
              {/* A dark casing under every corridor. Without it a thin bright line over a
                  dark basemap shimmers and is hard to follow at distance. */}
              <Polyline
                positions={[segment.source_coords, segment.destination_coords]}
                interactive={false}
                pathOptions={{
                  color: "#05080c",
                  weight: (highlighted ? 8 : style.weight) + 3,
                  opacity: dimmed ? 0.25 : 0.75,
                }}
              />
              <Polyline
                positions={[segment.source_coords, segment.destination_coords]}
                eventHandlers={onSelectSegment ? { click: () => onSelectSegment(segment) } : undefined}
                pathOptions={{
                  // The planned route wins the accent colour; everything else keeps its
                  // condition encoding so the route is read against real context.
                  color: highlighted ? ACCENT : style.color,
                  weight: highlighted ? 6 : selected ? style.weight + 2 : style.weight,
                  opacity: dimmed ? 0.3 : 0.95,
                  dashArray: highlighted ? undefined : style.dashArray,
                  lineCap: "round",
                }}
              >
                <Popup>
                  <div style={{ minWidth: 235 }}>
                    <strong>
                      {segment.source_name} → {segment.destination_name}
                    </strong>
                    <div style={{ color: "#9fb2c6", fontSize: 12, marginTop: 2 }}>
                      {segment.highway_corridor} · {formatKm(segment.distance_km)}
                    </div>
                    {segment.terrain && (
                      <div style={{ color: "#9fb2c6", fontSize: 12 }}>
                        {terrainLabel(segment.terrain.class)}
                        {segment.terrain.secondary ? ` + ${terrainLabel(segment.terrain.secondary).toLowerCase()}` : ""}
                        {" · "}{segment.terrain.road_class_label}
                      </div>
                    )}
                    {segment.simulated && (
                      <div style={{ color: STATUS_COLORS.warning, fontSize: 11, fontWeight: 700, marginTop: 2 }}>
                        SIMULATED CONDITIONS
                      </div>
                    )}
                    <hr style={{ borderColor: "rgba(255,255,255,0.12)", margin: "8px 0" }} />
                    <div>
                      Status: <strong>{segment.road_status}</strong>
                      {segment.impassable && (
                        <span style={{ color: STATUS_COLORS.critical, fontWeight: 700 }}>
                          {" "}· CLOSED
                        </span>
                      )}
                    </div>
                    {segment.closure && (
                      <div style={{ fontSize: 11, color: "#e97676" }}>
                        {closureLabel(segment.closure.type)}: {segment.closure.reason}
                      </div>
                    )}
                    <div>
                      Accessibility:{" "}
                      <strong style={{ color: accessibilityColor(segment.accessibility_score) }}>
                        {segment.accessibility_score}/100
                      </strong>{" "}
                      ({segment.accessibility_category})
                    </div>
                    {segment.prediction && (
                      <div style={{ marginTop: 4 }}>
                        Predicted disruption:{" "}
                        <strong>
                          {formatPercent(segment.prediction.combined_disruption_probability * 100)}
                        </strong>
                        <div style={{ fontSize: 11, color: "#9fb2c6" }}>
                          flood {formatPercent(segment.prediction.flood_probability * 100, 0)} ·
                          landslide{" "}
                          {formatPercent(segment.prediction.landslide_probability * 100, 0)}
                        </div>
                      </div>
                    )}
                    {segment.hazards && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ fontSize: 11, color: "#9fb2c6" }}>
                          Multi-hazard index{" "}
                          <strong style={{ color: riskColor(segment.multi_hazard_index) }}>
                            {Math.round(segment.multi_hazard_index)}/100
                          </strong>
                          {segment.dominant_hazard ? ` · mainly ${HAZARD_LABELS[segment.dominant_hazard]?.toLowerCase()}` : ""}
                        </div>
                        <div style={{ fontSize: 11, color: "#9fb2c6", marginTop: 2 }}>
                          {Object.values(segment.hazards)
                            .filter((h) => h.applicable && h.risk !== null)
                            .sort((a, b) => b.risk - a.risk)
                            .slice(0, 4)
                            .map((h) => `${HAZARD_LABELS[h.hazard]} ${Math.round(h.risk)}`)
                            .join(" · ")}
                        </div>
                      </div>
                    )}
                    {segment.active_incident_count > 0 && (
                      <div style={{ marginTop: 4, color: STATUS_COLORS.warning }}>
                        {segment.active_incident_count} active incident(s)
                      </div>
                    )}
                  </div>
                </Popup>
              </Polyline>
            </Fragment>
          );
        })}

        <LocationMarkers locations={locations} />

        {incidents.map((incident) => {
          // Verified incidents can close a road, so they are drawn as a hard critical marker.
          // Unverified ones are a hollow ring: present, visibly provisional, not yet acted on.
          const verified = incident.verification_status === "verified";
          return (
            <CircleMarker
              key={`incident-${incident.id}`}
              center={[incident.latitude, incident.longitude]}
              radius={verified ? 8 : 6}
              pathOptions={{
                color: verified ? STATUS_COLORS.critical : STATUS_COLORS.warning,
                fillColor: verified ? STATUS_COLORS.critical : "transparent",
                fillOpacity: verified ? 0.45 : 0,
                weight: 2,
                dashArray: verified ? undefined : "3 3",
              }}
            >
              <Popup>
                <strong>{incidentLabel(incident.type)}</strong>
                <div style={{ color: "#9fb2c6", fontSize: 12 }}>
                  Severity {incident.severity}/5 · {incident.verification_status}
                </div>
                {incident.description && (
                  <div style={{ marginTop: 4 }}>{incident.description}</div>
                )}
                <div style={{ color: "#6d8299", fontSize: 11, marginTop: 4 }}>
                  {timeAgo(incident.reported_at)}
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Overlays sit above the Leaflet pane. z-[400] clears Leaflet's own tile and marker
          panes without reaching the popup layer, which must stay on top. */}
      {showLegend && (
        <div className="absolute left-3 bottom-6 z-[400] pointer-events-none">
          {colorBy === "accessibility" ? (
            <MapLegend compact={!bleed && height < 400} />
          ) : (
            <RiskLegend
              compact={!bleed && height < 400}
              title={colorBy === "multi_hazard" ? "Multi-hazard index" : `${HAZARD_LABELS[colorBy] || colorBy} risk`}
            />
          )}
        </div>
      )}
      {overlay ? <div className="absolute inset-x-3 top-3 z-[400]">{overlay}</div> : null}

      {tilesFailed && (
        <div className="absolute right-3 bottom-24 md:bottom-6 z-[400] panel-glass px-3 py-2 max-w-[240px]">
          <p className="text-xs font-medium" style={{ color: "var(--status-warning)" }}>Basemap unavailable</p>
          <p className="text-[11px] text-ink-secondary mt-0.5 leading-snug">
            Showing the corridor network on a coordinate grid. Positions are accurate;
            terrain and place context are not loaded.
          </p>
        </div>
      )}
    </div>
  );
}
