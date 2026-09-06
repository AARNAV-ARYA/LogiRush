// src/lib/mapTiles.js
//
// One tile source for every map in the application.
//
// This used to be plain OpenStreetMap raster, darkened with a CSS filter to fit the dark
// operations-centre UI. It worked, but it read as a wireframe — a road atlas with the
// colour drained out. What actually sells "we know this terrain" for a disaster-logistics
// platform is the terrain itself: real satellite photography, the same instinct behind
// Windy and Zoom Earth, where you can see the river braids and the cloud cover and the
// literal shape of the hills a corridor climbs through.
//
// So the default is now Esri's World Imagery service — real, current satellite/aerial
// photography, served free and keyless (no account, no token, nothing to leak in this
// repo). A second, keyless Esri layer (Reference/World_Boundaries_and_Places) draws place
// names and borders on top of the photography, because raw imagery alone has no labels —
// without it nobody could tell which river or town they were looking at.
//
// Both layers use Esri's tile addressing, which orders the path as {z}/{y}/{x} — row
// before column — the opposite of the {z}/{x}/{y} convention OSM and most other XYZ
// sources use. Getting that backwards silently 404s every tile.
//
// VITE_MAP_TILE_URL / VITE_MAP_LABELS_URL point this at different providers (MapTiler,
// Stadia, a CARTO plan, or back to plain OSM) without touching any component. Set
// VITE_MAP_TILE_THEME to "light" or "dark" if the override is a conventional street map
// rather than photographic imagery, so the CSS in index.css applies the right treatment —
// see the .ner-map-tiles-* rules there for what each theme does to the tile pane.
//
// This lives in its own module so a map that needs the tile config — the report form's
// small location preview, for instance — does not have to import the whole network map to
// get it.

export const TILES = {
  url:
    import.meta.env.VITE_MAP_TILE_URL ||
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  attribution:
    import.meta.env.VITE_MAP_TILE_ATTRIBUTION ||
    "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  subdomains: import.meta.env.VITE_MAP_TILE_SUBDOMAINS || "",
  // Esri's World Imagery has real photography up to about zoom 17 for terrain like this;
  // past that it has nothing to serve. maxNativeZoom tells Leaflet to keep upscaling the
  // last real tile instead of requesting (and 404ing on) zoom levels that don't exist.
  maxNativeZoom: 17,
};

/** Place names and administrative borders, drawn over the imagery so the photography
 *  underneath still reads as photography rather than a printed map. */
export const LABELS = {
  url:
    import.meta.env.VITE_MAP_LABELS_URL ||
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  subdomains: import.meta.env.VITE_MAP_LABELS_SUBDOMAINS || "",
  maxNativeZoom: 17,
};

/* "satellite" gets a photographic colour treatment (see index.css) that must never invert
   real imagery the way the old light-basemap filter inverted a road atlas. A vendor override
   that serves a conventional light or dark street map should set this back to "light"/"dark". */
export const TILE_THEME = import.meta.env.VITE_MAP_TILE_THEME || "satellite";
