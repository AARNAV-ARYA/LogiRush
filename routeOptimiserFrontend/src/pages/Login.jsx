import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Card, Spinner } from "../components/ui";

/*
  Demonstration accounts mirror the backend roster exactly (src/db/roster.py).
  Credentials are published on purpose — they are seeded demo accounts, and hiding them
  would only make the access model harder to examine.

  Two verifiers share the same password so a countersign demonstration works:
  sign in as one, verify; sign out, sign in as another, countersign — the road closes.
  One controller account can delete or override anything, from any state.
*/

const DEMO_ACCOUNTS = [
  // ── Reporters ──────────────────────────────────────────────────────────────
  {
    group: "Reporter",
    username: "reporter",
    password: "reporter123",
    label: "Field Reporter",
    name: "Bhaskar Das",
    org: "Volunteer, Kamrup district",
    detail: "Submits reports only. Cannot verify or close roads.",
    region: null,
  },

  // ── North-East verifiers ────────────────────────────────────────────────────
  {
    group: "Verifier — North East",
    username: "verifier.as",
    password: "verify123",
    label: "District Verifier — Assam & Meghalaya",
    name: "Anjali Baruah",
    org: "DDMA Assam",
    detail: "Jurisdiction: Assam, Meghalaya",
    region: "North East",
  },
  {
    group: "Verifier — North East",
    username: "verifier.mn",
    password: "verify123",
    label: "District Verifier — Manipur, Nagaland & Mizoram",
    name: "Thangboi Kipgen",
    org: "DDMA Manipur",
    detail: "Jurisdiction: Manipur, Nagaland, Mizoram",
    region: "North East",
  },

  // ── Pan-India regional desks ────────────────────────────────────────────────
  {
    group: "Verifier — North",
    username: "verifier.north",
    password: "verify123",
    label: "Regional Verifier — North",
    name: "Neha Sharma",
    org: "Regional Desk — North",
    detail: "Jurisdiction: Delhi, Haryana, Punjab, Chandigarh, Rajasthan, Uttar Pradesh",
    region: "North",
  },
  {
    group: "Verifier — Himalaya",
    username: "verifier.himalaya",
    password: "verify123",
    label: "Regional Verifier — Himalaya",
    name: "Tsering Dorje",
    org: "Regional Desk — Himalaya",
    detail: "Jurisdiction: J&K, Ladakh, Himachal Pradesh, Uttarakhand",
    region: "Himalaya",
  },
  {
    group: "Verifier — East",
    username: "verifier.east",
    password: "verify123",
    label: "Regional Verifier — East",
    name: "Pritam Mahato",
    org: "Regional Desk — East",
    detail: "Jurisdiction: Bihar, West Bengal, Jharkhand, Odisha",
    region: "East",
  },
  {
    group: "Verifier — West & Central",
    username: "verifier.west",
    password: "verify123",
    label: "Regional Verifier — West & Central",
    name: "Snehal Patil",
    org: "Regional Desk — West & Central",
    detail: "Jurisdiction: Gujarat, Maharashtra, Goa, Madhya Pradesh, Chhattisgarh",
    region: "West & Central",
  },
  {
    group: "Verifier — South",
    username: "verifier.south",
    password: "verify123",
    label: "Regional Verifier — South",
    name: "Karthik Iyer",
    org: "Regional Desk — South",
    detail: "Jurisdiction: Karnataka, Kerala, Tamil Nadu, Puducherry, Andhra Pradesh, Telangana",
    region: "South",
  },

  // ── Controller ──────────────────────────────────────────────────────────────
  {
    group: "Controller",
    username: "controller",
    password: "control123",
    label: "State Controller",
    name: "R. Lalthanmawia",
    org: "State EOC / ASDMA",
    detail: "Acts in all states. The only role that can delete reports.",
    region: null,
  },
];

// Role badge colours (CSS-var based so they follow the theme)
const GROUP_TONE = {
  "Reporter":               { bg: "rgba(99,102,241,0.12)",  border: "rgba(99,102,241,0.3)",  text: "#a5b4fc" },
  "Controller":             { bg: "rgba(239,68,68,0.10)",   border: "rgba(239,68,68,0.3)",   text: "#fca5a5" },
};
function groupTone(group) {
  if (GROUP_TONE[group]) return GROUP_TONE[group];
  // All verifier groups get the same green tone
  return { bg: "rgba(34,197,94,0.08)", border: "rgba(34,197,94,0.25)", text: "#86efac" };
}

const Login = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [activeGroup, setActiveGroup] = useState("all");

  const groups = useMemo(() => {
    const seen = new Set();
    const out = ["all"];
    DEMO_ACCOUNTS.forEach((a) => {
      // Collapse all verifier groups into one tab label
      const tab = a.group.startsWith("Verifier") ? "Verifiers" : a.group;
      if (!seen.has(tab)) { seen.add(tab); out.push(tab); }
    });
    return out;
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return DEMO_ACCOUNTS.filter((a) => {
      const matchesGroup =
        activeGroup === "all" ||
        (activeGroup === "Verifiers" && a.group.startsWith("Verifier")) ||
        a.group === activeGroup;
      const matchesSearch =
        !q ||
        a.label.toLowerCase().includes(q) ||
        a.username.toLowerCase().includes(q) ||
        a.detail.toLowerCase().includes(q) ||
        (a.name && a.name.toLowerCase().includes(q)) ||
        (a.org && a.org.toLowerCase().includes(q));
      return matchesGroup && matchesSearch;
    });
  }, [search, activeGroup]);

  const fill = (account) => {
    setForm({ username: account.username, password: account.password });
    setError("");
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(form.username.trim().toLowerCase(), form.password);
      navigate(location.state?.from || "/dashboard", { replace: true });
    } catch (e) {
      setError(e.message || "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 grid gap-6 lg:grid-cols-[22rem_1fr] items-start">

      {/* ── Sign-in form ── */}
      <Card as="form" onSubmit={submit}>
        <h1 className="text-lg mb-1">Sign in</h1>
        <p className="text-xs text-ink-muted mb-5">
          Reporting an incident does not need an account. Reviewing one does.
        </p>

        <label className="block">
          <span className="field-label">Username</span>
          <input
            id="username"
            className="field"
            autoComplete="username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            required
          />
        </label>

        <label className="block mt-4">
          <span className="field-label">Password</span>
          <input
            id="password"
            type="password"
            className="field"
            autoComplete="current-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
        </label>

        {error && (
          <p role="alert" className="text-sm tone-bad mt-4">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary w-full mt-5" disabled={busy}>
          {busy ? <Spinner /> : null}
          Sign in
        </button>

        {/* Quick hint if a demo account is loaded */}
        {form.username && (
          <p className="text-[11px] text-ink-muted text-center mt-3">
            Signing in as <span className="text-ink-secondary font-medium">{form.username}</span>
          </p>
        )}
      </Card>

      {/* ── Demo account picker ── */}
      <Card>
        <div className="flex items-start justify-between gap-2 flex-wrap mb-3">
          <div>
            <h2 className="text-sm font-semibold">Demonstration accounts</h2>
            <p className="text-[11px] text-ink-muted mt-0.5">
              Click any account to fill the form. All verifiers share password{" "}
              <code className="mono text-ink-secondary">verify123</code>.
            </p>
          </div>
          <span className="text-[11px] text-ink-muted">{DEMO_ACCOUNTS.length} accounts</span>
        </div>

        {/* Search */}
        <div className="relative mb-3">
          <svg
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none"
            width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
            strokeWidth="2" aria-hidden="true"
          >
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="M15 15l3 3" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            className="field !mt-0 !pl-8 !py-1.5 !text-xs"
            placeholder="Search by name, state or role…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search demo accounts"
          />
        </div>

        {/* Role tabs */}
        <div className="flex flex-wrap gap-1.5 mb-4" role="tablist" aria-label="Filter by role">
          {groups.map((g) => (
            <button
              key={g}
              role="tab"
              aria-selected={activeGroup === g}
              onClick={() => setActiveGroup(g)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors border ${
                activeGroup === g
                  ? "border-accent/60 bg-accent/10 text-accent"
                  : "border-white/10 text-ink-muted hover:text-ink hover:border-white/20"
              }`}
            >
              {g === "all" ? `All (${DEMO_ACCOUNTS.length})` : g}
            </button>
          ))}
        </div>

        {/* Account cards */}
        {filtered.length === 0 ? (
          <p className="text-xs text-ink-muted text-center py-6">No accounts match your search.</p>
        ) : (
          <ul className="space-y-2" role="list">
            {filtered.map((account) => {
              const tone = groupTone(account.group);
              const isSelected = form.username === account.username;
              return (
                <li key={account.username}>
                  <button
                    type="button"
                    onClick={() => fill(account)}
                    aria-pressed={isSelected}
                    className={`w-full text-left rounded-xl border px-3 py-2.5 transition-all focus:outline-none focus:ring-2 focus:ring-accent ${
                      isSelected
                        ? "border-accent/50 bg-accent/10"
                        : "border-white/8 hover:border-white/20 hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        {/* Role badge */}
                        <span
                          className="shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-md border"
                          style={{ background: tone.bg, borderColor: tone.border, color: tone.text }}
                        >
                          {account.group.replace("Verifier — ", "")}
                        </span>
                        <span className="text-sm text-ink font-medium truncate">{account.name}</span>
                      </div>
                      {isSelected && (
                        <svg width="14" height="14" viewBox="0 0 20 20" fill="none"
                          stroke="var(--accent)" strokeWidth="2.5" className="shrink-0" aria-hidden="true">
                          <path d="M4 10l4 4 8-8" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>

                    <p className="text-[11px] text-ink-muted mt-1 leading-relaxed">{account.detail}</p>

                    <div className="flex items-center gap-3 mt-1.5">
                      <code className="mono text-[11px] text-ink-secondary">{account.username}</code>
                      <span className="text-white/20">·</span>
                      <code className="mono text-[11px] text-ink-secondary">{account.password}</code>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <p className="text-[10px] text-ink-muted mt-4 leading-relaxed border-t border-white/[0.06] pt-3">
          These are published demo credentials. In a real deployment accounts come from the
          state&apos;s own directory. Two different verifiers must countersign to close a road —
          try it with any two verifier accounts.
        </p>
      </Card>
    </div>
  );
};

export default Login;
