import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, DemoDataNotice, SectionHeading, Spinner } from "../components/ui";
import { useSync } from "../context/SyncContext";
import { incidentLabel } from "../lib/accessibility";
import { formatDistance, timeAgo } from "../lib/format";
import { newClientUuid, queueIncident } from "../utils/offlineQueue";
import { compressImage } from "../utils/offlineStore";
import OfflineReadiness from "../components/OfflineReadiness";
import IncidentLocationPreview from "../components/IncidentLocationPreview";

const INCIDENT_TYPES = ["landslide", "flood", "road_block", "bridge_damage", "accident", "other"];

const SEVERITY_HINTS = {
  1: "Minor — traffic largely unaffected",
  2: "Slight — some slowing",
  3: "Moderate — one lane or partial obstruction",
  4: "Serious — heavy delays, difficult passage",
  5: "Severe — road impassable",
};

const EMPTY_FORM = {
  type: "landslide",
  severity: 3,
  description: "",
  latitude: "",
  longitude: "",
  image_url: "",
  reporter_name: "",
  reporter_contact: "",
};

const ReportIncident = () => {
  const { online, pending, pendingCount, syncing, sync, refreshQueue } = useSync();
  const [form, setForm] = useState(EMPTY_FORM);
  const [status, setStatus] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [photoError, setPhotoError] = useState(null);
  // What the server says this coordinate resolves to, refreshed as the coordinate changes.
  const [attribution, setAttribution] = useState(null);
  const [attributionError, setAttributionError] = useState(null);

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  const setCoordinates = (lat, lon) =>
    setForm((f) => ({ ...f, latitude: lat.toFixed(5), longitude: lon.toFixed(5) }));

  const coords = useMemo(() => {
    const lat = Number(form.latitude);
    const lon = Number(form.longitude);
    if (form.latitude === "" || form.longitude === "") return null;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { lat, lon };
  }, [form.latitude, form.longitude]);

  /*
    Resolve the coordinate against the corridor network while it is still editable.

    The old form found out where a report had landed only after it was a record, in a
    sentence naming a segment id. Nobody can check "RS002" — so a mistyped digit produced a
    report filed against a corridor hundreds of kilometres away and nothing on either side
    said anything was wrong. Asking the server the same question up front, and drawing the
    answer, makes that mistake visible while it still costs nothing to fix.

    Debounced, because this fires on every keystroke in a coordinate field.
  */
  const attributionRequest = useRef(0);
  useEffect(() => {
    if (!coords) {
      setAttribution(null);
      setAttributionError(null);
      return undefined;
    }
    const ticket = ++attributionRequest.current;
    const timer = setTimeout(async () => {
      try {
        const result = await api.previewIncidentAttribution(coords.lat, coords.lon);
        if (ticket !== attributionRequest.current) return;   // a newer coordinate won
        setAttribution(result);
        setAttributionError(null);
      } catch {
        if (ticket !== attributionRequest.current) return;
        // Offline is the normal case for this form; the report still submits and the server
        // does the attribution when it arrives. Say that rather than showing an error.
        setAttribution(null);
        setAttributionError("offline");
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [coords?.lat, coords?.lon]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * Attach a photograph of the obstruction.
   *
   * A verifier deciding whether to close a corridor to convoy traffic is making a serious
   * call on the strength of a text description; a picture of the actual slip changes that.
   * The image is downscaled on the device before it is stored or sent, because a raw phone
   * JPEG will not survive a 2G uplink from a valley, and it is held in IndexedDB with the
   * queued report so it still arrives when the report syncs days later.
   */
  const attachPhoto = async (event) => {
    const file = event.target.files?.[0];
    setPhotoError(null);
    if (!file) {
      setPhoto(null);
      setForm((f) => ({ ...f, image_url: "" }));
      return;
    }
    try {
      const { dataUrl, width, height } = await compressImage(file);
      setPhoto({ dataUrl, width, height, bytes: Math.round((dataUrl.length * 3) / 4) });
      setForm((f) => ({ ...f, image_url: dataUrl }));
    } catch (error) {
      setPhotoError(error.message);
    }
  };

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setStatus({ kind: "error", message: "Geolocation is not available in this browser." });
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoordinates(position.coords.latitude, position.coords.longitude);
        setLocating(false);
      },
      () => {
        setStatus({ kind: "error", message: "Could not read your location. Enter it manually." });
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setStatus(null);

    const payload = {
      ...form,
      client_uuid: newClientUuid(),
      severity: Number(form.severity),
      latitude: Number(form.latitude),
      longitude: Number(form.longitude),
      reported_at: new Date().toISOString(),
      // Which client filed it. The review queue shows this, because a report typed here and
      // one filed from a phone at the obstruction are not equally direct evidence.
      source: "web",
    };

    try {
      const response = await api.reportIncident(payload);
      const match = response.attribution || {};
      setStatus(
        match.on_network
          ? {
              kind: "success",
              message: `Report submitted, ${formatDistance(match.distance_km)} from the ${
                match.segment_label
              } corridor. It will be reviewed before it can close a road.`,
            }
          : {
              // Filed, kept, visible on the map at its own coordinates — but honest that it
              // will not touch routing, because nothing it could touch is anywhere near it.
              kind: "queued",
              message: `Report submitted and recorded at ${payload.latitude}, ${payload.longitude}. No corridor in this network is within ${match.snap_radius_km || 30} km, so it will not affect any route. If that is a surprise, check the coordinates.`,
            }
      );
      setForm(EMPTY_FORM);
      setPhoto(null);
      setAttribution(null);
    } catch (error) {
      // A 4xx means the server rejected the content — queueing it would just retry a
      // permanent failure, so surface it instead. Anything else (offline, 5xx, timeout)
      // is worth queueing: the client UUID makes a later retry safe.
      if (error.status && error.status >= 400 && error.status < 500) {
        setStatus({ kind: "error", message: `Report rejected: ${error.message}` });
      } else {
        await queueIncident(payload);
        await refreshQueue();
        setStatus({
          kind: "queued",
          message:
            "No connection to the server. Your report is saved on this device and will sync automatically when you're back online.",
        });
        setForm(EMPTY_FORM);
        setPhoto(null);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const statusStyles = {
    success: "state-success",
    queued: "state-warning",
    error: "state-error-light",
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 sm:py-8">
      <header className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1>Report an Incident</h1>
          <p className="text-ink-secondary mt-1 text-sm">
            Works offline — reports are queued on your device and sync automatically
          </p>
        </div>
        <Badge tone={online ? "success" : "warning"}>{online ? "Online" : "Offline"}</Badge>
      </header>

      <div className="mb-4">
        <DemoDataNotice compact />
      </div>

      <div className="mb-4">
        <OfflineReadiness />
      </div>

      {status && (
        <div
          role="status"
          className={`rounded-lg border px-4 py-3 mb-4 text-sm ${statusStyles[status.kind]}`}
        >
          {status.message}
        </div>
      )}

      <Card as="form" onSubmit={submit}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label>
            <span className="field-label">Incident type</span>
            <select className="field" value={form.type} onChange={update("type")}>
              {INCIDENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {incidentLabel(type)}
                </option>
              ))}
            </select>
          </label>

          <div>
            <span className="field-label" id="severity-label">
              Severity: {form.severity}/5
            </span>
            <input
              type="range"
              min="1"
              max="5"
              step="1"
              value={form.severity}
              onChange={update("severity")}
              className="w-full mt-3"
              style={{ accentColor: 'var(--accent)' }}
              aria-labelledby="severity-label"
              aria-describedby="severity-hint"
              aria-valuetext={`${form.severity} of 5: ${SEVERITY_HINTS[form.severity]}`}
            />
            <p id="severity-hint" className="text-xs text-ink-muted mt-1">
              {SEVERITY_HINTS[form.severity]}
            </p>
          </div>
        </div>

        <fieldset className="mt-4">
          <legend className="field-label mb-1.5">Location</legend>
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
            <label>
              <span className="sr-only">Latitude</span>
              <input
                type="number"
                step="any"
                className="field !mt-0"
                placeholder="Latitude"
                value={form.latitude}
                onChange={update("latitude")}
                required
              />
            </label>
            <label>
              <span className="sr-only">Longitude</span>
              <input
                type="number"
                step="any"
                className="field !mt-0"
                placeholder="Longitude"
                value={form.longitude}
                onChange={update("longitude")}
                required
              />
            </label>
            <button type="button" onClick={useMyLocation} disabled={locating} className="btn-ghost">
              {locating ? <Spinner /> : null}
              Use my location
            </button>
          </div>

          {/* Two numbers in two boxes cannot be checked by the person typing them. The map
              can: the pin is where the report will be recorded, the blue line is the
              corridor it will be filed against, and tapping moves the pin. */}
          <div className="mt-3">
            <IncidentLocationPreview
              latitude={form.latitude}
              longitude={form.longitude}
              corridor={
                attribution?.on_network
                  ? {
                      source_coords: attribution.source_coords,
                      destination_coords: attribution.destination_coords,
                    }
                  : null
              }
              onPick={setCoordinates}
            />
          </div>

          <div aria-live="polite" className="mt-2">
            {attribution?.on_network && (
              <p className="text-xs text-ink-secondary">
                Nearest corridor:{" "}
                <span className="text-ink">{attribution.segment_label}</span>{" "}
                <span className="text-ink-muted">
                  ({formatDistance(attribution.distance_km)} away)
                </span>
              </p>
            )}

            {attribution && !attribution.on_network && (
              <p
                className="text-xs px-2.5 py-2 rounded-md"
                style={{
                  color: "var(--status-warning)",
                  backgroundColor: "rgb(var(--status-warning-rgb) / 0.1)",
                }}
              >
                No corridor within {attribution.snap_radius_km} km — the nearest is{" "}
                {formatDistance(attribution.distance_km)} away. The report will still be
                recorded at these coordinates, but it will not affect any route. Check the
                numbers if you expected it to.
              </p>
            )}

            {attributionError && (
              <p className="text-xs text-ink-muted">
                Can&apos;t reach the server to check this coordinate — the report will still
                be queued, and the corridor is worked out when it syncs.
              </p>
            )}
          </div>
        </fieldset>

        <label className="block mt-4">
          <span className="field-label">Description</span>
          <textarea
            rows="3"
            className="field"
            value={form.description}
            onChange={update("description")}
            placeholder="What happened, and how badly is the road affected?"
          />
        </label>

        <label className="block mt-4">
          <span className="field-label">Photo URL (optional)</span>
          <input
            type="url"
            className="field"
            value={form.image_url}
            onChange={update("image_url")}
            placeholder="https://…"
          />
          <span className="text-xs text-ink-muted mt-1 block">
            Direct file upload is not wired up yet — paste a link if you have one.
          </span>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
          <label>
            <span className="field-label">Your name (optional)</span>
            <input className="field" value={form.reporter_name} onChange={update("reporter_name")} />
          </label>
          <label>
            <span className="field-label">Contact (optional)</span>
            <input
              className="field"
              value={form.reporter_contact}
              onChange={update("reporter_contact")}
            />
          </label>
        </div>

        <button type="submit" disabled={submitting} className="btn-primary w-full mt-5">
          {submitting ? <Spinner /> : null}
          {submitting ? "Submitting…" : "Submit report"}
        </button>
      </Card>

      {pendingCount > 0 && (
        <Card className="mt-5 !border-amber-800/40">
          <SectionHeading
            hint="Queued on this device. Safe to retry — duplicates are impossible."
            action={
              <button onClick={sync} disabled={syncing || !online} className="btn-ghost">
                {syncing ? <Spinner /> : null}
                Sync now
              </button>
            }
          >
            <span style={{ color: 'var(--status-warning)' }}>
              {pendingCount} report{pendingCount === 1 ? "" : "s"} waiting to sync
            </span>
          </SectionHeading>
          <ul className="divide-y divide-white/[0.07]">
            {pending.map((item) => (
              <li key={item.client_uuid} className="flex justify-between gap-3 py-2 text-sm">
                <span className="text-ink-secondary">
                  {incidentLabel(item.type)} · severity {item.severity}
                </span>
                <span className="text-ink-muted text-xs">
                  {item.attempts > 0 ? `${item.attempts} attempt(s)` : "queued"}{" "}
                  {item.queued_at ? `· ${timeAgo(item.queued_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
};

export default ReportIncident;
