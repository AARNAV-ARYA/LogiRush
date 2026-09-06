/* eslint-disable react/prop-types */
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Spinner } from "./ui";

/*
  Where the goods actually change hands.

  A route between two towns is not a plan a trader can act on — somebody has to physically
  hand a crate to somebody else, at a counter, during opening hours. In much of this region
  that counter is a bus station parcel office or a highway fuel stop, not a freight terminal,
  which is why the facility list is deliberately broad.

  Contact details are shown exactly as OpenStreetMap records them. Where OSM has no number
  the row says so rather than leaving a suggestive blank, and nothing here is ever
  synthesised: a plausible-looking number attached to a real cargo operator would be dialled
  by somebody, and would be worse than no number at all.
*/

const KIND_ORDER = ["Post office", "Courier", "Logistics office", "Parcel point", "Depot",
                    "Warehouse", "Bus station", "Railway station", "Airport", "Fuel station"];

const NearbyFacilities = ({ point, title = "Handover points nearby", radiusKm = 6 }) => {
  const [state, setState] = useState({ loading: false, facilities: [], degraded: false });

  useEffect(() => {
    if (!point?.latitude) {
      setState({ loading: false, facilities: [], degraded: false });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    api
      .nearbyPlaces(point.latitude, point.longitude, radiusKm)
      .then((r) => {
        if (cancelled) return;
        const facilities = [...(r.facilities || [])].sort((a, b) => {
          const rank = (f) => {
            const i = KIND_ORDER.indexOf(f.kind);
            return i === -1 ? KIND_ORDER.length : i;
          };
          return rank(a) - rank(b) || a.distance_km - b.distance_km;
        });
        setState({ loading: false, facilities, degraded: Boolean(r.degraded) });
      })
      .catch(() => !cancelled && setState({ loading: false, facilities: [], degraded: true }));
    return () => { cancelled = true; };
  }, [point?.latitude, point?.longitude, radiusKm]);

  if (!point?.latitude) return null;

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <p className="label-micro">{title}</p>
        {state.loading && <Spinner className="w-3 h-3" />}
      </div>

      {state.degraded && !state.loading && (
        <p className="text-[11px] text-ink-muted">
          Facility lookup is unavailable offline. The route below is unaffected.
        </p>
      )}

      {!state.degraded && !state.loading && state.facilities.length === 0 && (
        <p className="text-[11px] text-ink-muted">
          No handover points mapped within {radiusKm} km.
        </p>
      )}

      {state.facilities.length > 0 && (
        <ul className="divide-y divide-white/[0.06]">
          {state.facilities.slice(0, 8).map((facility) => (
            <li key={facility.id} className="py-2">
              <div className="flex items-baseline gap-2">
                <span className="text-xs text-ink truncate flex-1">{facility.name}</span>
                <span className="text-[10px] text-ink-muted tabular-nums shrink-0">
                  {facility.distance_km} km
                </span>
              </div>
              <p className="text-[10px] text-ink-muted mt-0.5">
                {facility.kind}
                {facility.operator ? ` · ${facility.operator}` : ""}
                {facility.address ? ` · ${facility.address}` : ""}
              </p>
              <div className="flex items-center gap-3 mt-1">
                {facility.phone ? (
                  <a
                    href={`tel:${facility.phone.replace(/\s+/g, "")}`}
                    className="text-[11px] text-accent link-inline"
                  >
                    {facility.phone}
                  </a>
                ) : (
                  <span className="text-[11px] text-ink-muted">No number listed</span>
                )}
                {facility.opening_hours && (
                  <span className="text-[10px] text-ink-muted truncate">
                    {facility.opening_hours}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {state.facilities.length > 0 && (
        <p className="text-[10px] text-ink-muted mt-2 pt-2 border-t border-white/10">
          Places and contact details from OpenStreetMap (ODbL), shown as recorded there.
        </p>
      )}
    </div>
  );
};

export default NearbyFacilities;
