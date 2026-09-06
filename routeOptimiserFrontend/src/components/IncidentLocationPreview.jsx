/* eslint-disable react/prop-types */
// src/components/IncidentLocationPreview.jsx
//
// The report form's answer to "is this actually where I mean?"
//
// Two numbers in two text boxes are unfalsifiable. A reporter cannot tell 26.14 from 26.41,
// and neither could the old form — it accepted the coordinate, silently filed the report
// against whichever corridor happened to be nearest on the whole planet, and told them
// afterwards that it had been "attributed to RS002". The failure was invisible on both
// sides.
//
// So: draw the point. A dot on a map is checkable at a glance, the matched corridor is drawn
// with it, and clicking moves the dot — which is usually faster than typing coordinates and
// is the only way to file a report from a place whose coordinates nobody knows.

import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { STATUS_COLORS } from "../lib/accessibility";
import { LABELS, TILES, TILE_THEME } from "../lib/mapTiles";

const NER_CENTER = [25.9, 92.6];

/** Keep the view on the point when it is changed from outside (typing, or "use my location"). */
function Recenter({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.setView(position, Math.max(map.getZoom(), 9), { animate: true });
  }, [position?.[0], position?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function ClickToPlace({ onPick }) {
  useMapEvents({ click: (event) => onPick(event.latlng.lat, event.latlng.lng) });
  return null;
}

export default function IncidentLocationPreview({ latitude, longitude, corridor, onPick }) {
  const position = useMemo(() => {
    const lat = Number(latitude);
    const lon = Number(longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return [lat, lon];
  }, [latitude, longitude]);

  const [tilesFailed, setTilesFailed] = useState(false);

  return (
    <div
      className={`relative overflow-hidden rounded-lg border border-white/10 ner-map ner-map-tiles-${TILE_THEME}`}
      style={{ height: "14rem" }}
      data-testid="incident-location-preview"
    >
      <MapContainer
        center={position || NER_CENTER}
        zoom={position ? 9 : 6}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={false}
        zoomControl={false}
      >
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
        {/* Place-name/border overlay — see RouteMap.jsx for why overlayPane. */}
        <TileLayer
          url={LABELS.url}
          subdomains={LABELS.subdomains}
          maxZoom={19}
          maxNativeZoom={LABELS.maxNativeZoom}
          pane="overlayPane"
          zIndex={350}
        />
        <ClickToPlace onPick={onPick} />
        <Recenter position={position} />

        {/* The corridor the report will be filed against, drawn so the reporter can see the
            relationship rather than take "0.6 km from RS003" on trust. */}
        {corridor?.source_coords && corridor?.destination_coords && (
          <Polyline
            positions={[corridor.source_coords, corridor.destination_coords]}
            interactive={false}
            pathOptions={{ color: "#38bdf8", weight: 4, opacity: 0.85 }}
          />
        )}

        {position && (
          <>
            <CircleMarker
              center={position}
              radius={9}
              interactive={false}
              pathOptions={{
                color: STATUS_COLORS.warning,
                fillColor: STATUS_COLORS.warning,
                fillOpacity: 0.25,
                weight: 2,
              }}
            />
            <CircleMarker
              center={position}
              radius={3}
              interactive={false}
              pathOptions={{
                color: STATUS_COLORS.warning,
                fillColor: STATUS_COLORS.warning,
                fillOpacity: 1,
                weight: 2,
              }}
            />
          </>
        )}
      </MapContainer>

      {!position && (
        <div className="absolute inset-x-0 bottom-0 z-[400] px-3 py-2 panel-glass rounded-none">
          <p className="text-[11px] text-ink-secondary">
            Tap the map to drop a pin, type the coordinates, or use “Use my location”.
          </p>
        </div>
      )}

      {tilesFailed && (
        <div className="absolute inset-x-2 top-2 z-[400] panel-glass px-2.5 py-1.5">
          <p className="text-[11px]" style={{ color: "var(--status-warning)" }}>
            Basemap unavailable — the pin is still at the coordinates shown.
          </p>
        </div>
      )}
    </div>
  );
}
