/* eslint-disable react/prop-types */
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useSync } from "../context/SyncContext";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "./ui";
import {
  IconAlert, IconClose, IconDashboard, IconMap, IconMenu, IconReport, IconRoute, IconTruck,
} from "./icons";
import logoUrl from "../assets/logo-small.png";

/*
  The application chrome.

  The previous header was a horizontal marketing nav: logo left, seven text links, sign-in
  right. It framed the product as a website you visit. This is a console someone sits in
  front of for a shift, and the reference points for that — Windy, Zoom Earth, any incident
  wall — all share one move: pin navigation to a narrow vertical rail and give the whole
  remaining viewport to the data. A rail costs 76 px of width; a top bar costs 64 px of
  height off every screen, and height is what a map wants.

  Each destination keeps a text label under its glyph. Icon-only rails are a designer's
  luxury: they assume an unhurried user who will learn the set. This one is read by someone
  triaging a landslide report at 2 a.m.
*/

const NAV = [
  { to: "/dashboard", label: "Overview", Icon: IconDashboard },
  { to: "/accessibility-map", label: "Network", Icon: IconMap },
  { to: "/shipment-planner", label: "Plan", Icon: IconRoute },
  { to: "/shipments", label: "Convoys", Icon: IconTruck },
  { to: "/incidents", label: "Review", Icon: IconAlert },
  { to: "/report-incident", label: "Report", Icon: IconReport },
];

const SECONDARY = [
  { to: "/data-sources", label: "Where this data comes from" },
  { to: "/", label: "Cross-border optimiser" },
  { to: "/about", label: "About" },
  { to: "/contact", label: "Contact" },
];

/* Who is signed in, and what that lets them do. An operations console should never leave
   this ambiguous: the same screen shows different controls to different people, so the
   identity behind those controls has to be visible at all times, not buried in a menu. */
const Identity = () => {
  const { user, logout } = useAuth();
  if (!user) {
    return (
      <Link to="/login" className="block px-3 py-2.5 rounded-lg text-sm text-accent hover:bg-white/[0.06]">
        Sign in
      </Link>
    );
  }
  return (
    <div className="px-3 py-2.5">
      <p className="text-sm text-ink truncate">{user.full_name}</p>
      <p className="text-[11px] text-ink-muted capitalize">
        {user.role}
        {user.jurisdiction?.length ? ` · ${user.jurisdiction.join(", ")}` : ""}
      </p>
      {user.organisation && (
        <p className="text-[11px] text-ink-muted truncate">{user.organisation}</p>
      )}
      <button onClick={logout} className="text-[11px] text-accent mt-1.5">
        Sign out
      </button>
    </div>
  );
};

const TITLES = Object.fromEntries(NAV.map((n) => [n.to, n.label]));

/** Connectivity and queue depth. Visible on every screen — a queue you can only see on the
 *  page that fills it is a queue people forget. */
export const SyncStatus = ({ stacked = false }) => {
  const { online, pendingCount, syncing, sync } = useSync();

  const shell = stacked
    ? "flex flex-col items-center gap-1 text-[9px] leading-none"
    : "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border";

  if (syncing) {
    return (
      <span
        className={shell}
        style={stacked ? { color: "var(--accent)" } : {
          color: "var(--accent)",
          backgroundColor: "rgb(var(--accent-rgb) / 0.12)",
          borderColor: "rgb(var(--accent-rgb) / 0.35)",
        }}
      >
        <Spinner className="w-3 h-3" />
        {stacked ? "Sync" : "Syncing"}
      </span>
    );
  }

  if (pendingCount > 0) {
    return (
      <button
        onClick={sync}
        disabled={!online}
        title={online ? "Sync queued reports now" : "Will sync automatically when back online"}
        className={`${shell} disabled:opacity-60`}
        style={stacked ? { color: "var(--status-warning)" } : {
          color: "var(--status-warning)",
          backgroundColor: "rgb(var(--status-warning-rgb) / 0.12)",
          borderColor: "rgb(var(--status-warning-rgb) / 0.4)",
        }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full animate-live"
          style={{ backgroundColor: "var(--status-warning)" }}
        />
        {pendingCount}{stacked ? "" : " pending"}
      </button>
    );
  }

  const tone = online ? "var(--status-good)" : "var(--status-warning)";
  return (
    <span
      className={shell}
      title={online ? "Connected" : "Offline — reports queue on this device"}
      style={stacked ? { color: "var(--ink-muted)" } : {
        color: online ? "var(--text-success)" : "var(--status-warning)",
        backgroundColor: `rgb(${online ? "var(--status-good-rgb)" : "var(--status-warning-rgb)"} / 0.1)`,
        borderColor: `rgb(${online ? "var(--status-good-rgb)" : "var(--status-warning-rgb)"} / 0.3)`,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full animate-live" style={{ backgroundColor: tone }} />
      {online ? "Online" : "Offline"}
    </span>
  );
};

const railLink = ({ isActive }) =>
  `relative flex flex-col items-center justify-center gap-1 w-full py-2.5 rounded-lg transition-colors ${
    isActive ? "text-accent bg-accent/10" : "text-ink-muted hover:text-ink hover:bg-white/[0.05]"
  }`;

const tabLink = ({ isActive }) =>
  `flex flex-col items-center justify-center gap-1 flex-1 min-h-[3.25rem] transition-colors ${
    isActive ? "text-accent" : "text-ink-muted"
  }`;

const AppShell = ({ children }) => {
  const [moreOpen, setMoreOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMoreOpen(false), [location.pathname]);

  return (
    <div className="h-[100dvh] flex overflow-hidden">
      {/* ---------- desktop rail ---------- */}
      <aside
        className="hidden md:flex flex-col items-center shrink-0 w-[76px] border-r"
        style={{ borderColor: "var(--hairline)", backgroundColor: "var(--surface-sunken)" }}
      >
        <Link to="/dashboard" className="mt-3 mb-4 shrink-0" aria-label="NER Smart Logistics home">
          <img src={logoUrl} alt="" className="w-8 h-8 rounded-md" />
        </Link>

        <nav className="flex flex-col gap-1 w-full px-2" aria-label="Main">
          {NAV.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={railLink}>
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 rounded-r"
                      style={{ backgroundColor: "var(--accent)" }}
                    />
                  )}
                  <Icon width="20" height="20" />
                  <span className="text-[10px] font-medium leading-none">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto mb-3 flex flex-col items-center gap-3 w-full px-2">
          <SyncStatus stacked />
          <button
            onClick={() => setMoreOpen((v) => !v)}
            className="w-full py-2 rounded-lg text-ink-muted hover:text-ink hover:bg-white/[0.05] flex justify-center"
            aria-label="More links"
            aria-expanded={moreOpen}
          >
            {moreOpen ? <IconClose width="18" height="18" /> : <IconMenu width="18" height="18" />}
          </button>
        </div>
      </aside>

      {/* ---------- content column ---------- */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* mobile top bar */}
        <header
          className="md:hidden flex items-center gap-3 px-4 h-12 shrink-0 border-b"
          style={{ borderColor: "var(--hairline)", backgroundColor: "var(--surface-sunken)" }}
        >
          <img src={logoUrl} alt="" className="w-6 h-6 rounded" />
          <span className="text-sm font-semibold truncate">
            {TITLES[location.pathname] || "NER Logistics"}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <SyncStatus />
            {/* The secondary sheet holds sign-in, and it used to exist only in the desktop
                rail — which is hidden on a phone. A District Verifier standing at a landslide
                with a phone could not sign in at all, and the review queue they are there to
                clear was therefore unreachable from the device they actually carry. */}
            <button
              onClick={() => setMoreOpen((v) => !v)}
              className="p-2 -mr-2 rounded-lg text-ink-muted hover:text-ink hover:bg-white/[0.06]"
              aria-label="More links"
              aria-expanded={moreOpen}
            >
              {moreOpen ? <IconClose width="18" height="18" /> : <IconMenu width="18" height="18" />}
            </button>
          </div>
        </header>

        <main id="main" className="flex-1 min-h-0 overflow-y-auto">
          {children}
        </main>

        {/* mobile tab bar */}
        <nav
          className="md:hidden flex shrink-0 border-t"
          style={{ borderColor: "var(--hairline)", backgroundColor: "var(--surface-sunken)" }}
          aria-label="Main"
        >
          {NAV.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={tabLink}>
              <Icon width="19" height="19" />
              <span className="text-[9px] font-medium leading-none">{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* ---------- secondary links sheet ---------- */}
      {moreOpen && (
        <div
          className="fixed inset-0 z-[1200] flex"
          onClick={() => setMoreOpen(false)}
          role="presentation"
        >
          <div className="absolute inset-0" style={{ backgroundColor: "rgba(4,7,11,0.6)" }} />
          <div
            className="relative m-auto md:m-0 md:ml-[76px] md:mt-auto md:mb-3 panel-glass p-2 w-[min(20rem,90vw)]"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="More links"
          >
            <Identity />
            <div className="h-px my-1" style={{ backgroundColor: "var(--hairline)" }} />
            {SECONDARY.map(({ to, label }) => (
              <Link
                key={to}
                to={to}
                className="block px-3 py-2.5 rounded-lg text-sm text-ink-secondary hover:text-ink hover:bg-white/[0.06]"
              >
                {label}
              </Link>
            ))}
            <p className="px-3 pt-2 pb-1 text-[11px] leading-snug text-ink-muted border-t border-white/10 mt-1">
              Demonstration system. Road risk data is synthetic; predictions are model
              estimates, not official forecasts.{" "}
              <Link to="/data-sources" className="text-accent">Input by input</Link>.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default AppShell;
