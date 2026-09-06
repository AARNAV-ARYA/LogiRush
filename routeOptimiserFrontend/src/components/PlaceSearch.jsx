/* eslint-disable react/prop-types */
import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api/client";
import { IconChevron } from "./icons";

/*
  Type-ahead place search.

  Two kinds of result share this list and the difference matters operationally, so it is
  stated rather than implied:

    · a corridor node   — a place the router can plan from directly
    · an OSM place      — a real address the network does not reach, which is snapped to the
                          nearest node, with the gap shown in kilometres

  Hiding that distinction would be the tempting thing to do (it looks tidier) and the wrong
  thing: a trader who picks "Paltan Bazaar" and is silently planned from Guwahati 4 km away
  has been told something untrue about their own consignment.

  Built as a real combobox rather than a styled div: an operator on a keyboard, and anyone on
  a screen reader, gets arrow-key navigation, an announced option count, and Escape to close.
*/

const DEBOUNCE_MS = 250;

const PlaceSearch = ({ label, value, onChange, placeholder, id }) => {
  const generatedId = useId();
  const inputId = id || generatedId;
  const listId = `${inputId}-listbox`;

  const [text, setText] = useState(value?.label || "");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [degraded, setDegraded] = useState(false);
  const boxRef = useRef(null);
  const skipNextSearch = useRef(false);

  useEffect(() => { setText(value?.label || ""); }, [value?.id]);

  useEffect(() => {
    if (skipNextSearch.current) {
      skipNextSearch.current = false;
      return;
    }
    const query = text.trim();
    if (query.length < 1) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const response = await api.searchPlaces(query);
        if (cancelled) return;
        setResults(response.results || []);
        setDegraded(Boolean(response.degraded));
        setOpen(true);
        setActive(-1);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [text]);

  // Close on an outside click, but not on a click inside the list — otherwise the option
  // unmounts under the pointer before its own handler runs.
  useEffect(() => {
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const choose = async (place) => {
    skipNextSearch.current = true;
    setText(place.label);
    setOpen(false);
    setActive(-1);

    if (place.routable) {
      onChange({ ...place, planFrom: place, offsetKm: 0 });
      return;
    }
    // Off-network: snap to the nearest corridor node and keep both, so the UI can say which
    // is which.
    try {
      const resolved = await api.resolvePlace(place.latitude, place.longitude);
      onChange({
        ...place,
        planFrom: resolved.origin || null,
        offsetKm: resolved.origin?.distance_km ?? null,
      });
    } catch {
      onChange({ ...place, planFrom: null, offsetKm: null });
    }
  };

  const onKeyDown = (e) => {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) { setOpen(true); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(results[active]); }
    else if (e.key === "Escape") { setOpen(false); setActive(-1); }
  };

  return (
    <div ref={boxRef} className="relative">
      <label htmlFor={inputId} className="field-label">{label}</label>
      <div className="relative">
        <input
          id={inputId}
          className="field"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${inputId}-opt-${active}` : undefined}
          autoComplete="off"
          placeholder={placeholder || "Town, station, market…"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {loading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-ink-muted">
            …
          </span>
        )}
      </div>

      {/* What the router will actually use, whenever that is not what was typed. */}
      {value && !value.routable && (
        <p className="text-[11px] mt-1" style={{ color: "var(--status-warning)" }}>
          {value.planFrom
            ? `Not on the corridor network — planning from ${value.planFrom.name}, ${value.offsetKm} km away.`
            : "Not on the corridor network and no nearby node found."}
        </p>
      )}

      <span className="sr-only" role="status" aria-live="polite">
        {open ? `${results.length} suggestions` : ""}
      </span>

      {open && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-[900] left-0 right-0 mt-1 panel-glass max-h-72 overflow-y-auto py-1"
        >
          {results.map((place, index) => (
            <li key={place.id} id={`${inputId}-opt-${index}`} role="option" aria-selected={index === active}>
              <button
                type="button"
                onClick={() => choose(place)}
                onMouseEnter={() => setActive(index)}
                className={`w-full text-left px-3 py-2 flex items-center gap-2.5 ${
                  index === active ? "bg-accent/10" : ""
                }`}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    backgroundColor: place.routable ? "var(--accent)" : "var(--ink-muted)",
                  }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-ink truncate">{place.name}</span>
                  <span className="block text-[11px] text-ink-muted truncate">
                    {place.context || "—"}
                  </span>
                </span>
                <span className="text-[10px] text-ink-muted shrink-0">
                  {place.routable ? "on network" : "nearby"}
                </span>
              </button>
            </li>
          ))}
          {degraded && (
            <li className="px-3 py-2 text-[11px] text-ink-muted border-t border-white/10">
              Showing corridor network only — the place search service is unreachable.
            </li>
          )}
        </ul>
      )}
    </div>
  );
};

export default PlaceSearch;
