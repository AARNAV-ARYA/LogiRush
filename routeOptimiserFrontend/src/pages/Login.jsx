import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Card, Spinner } from "../components/ui";

/*
  The old form accepted any two non-empty strings and set a boolean. That is worse than no
  login at all: it teaches everyone looking at the project that there is an access model
  when there is not. This one authenticates against the roster and receives a token whose
  role the API actually enforces.

  The demonstration accounts are printed on the page on purpose. They are seeded, published
  credentials for a demo system, and hiding them would only make the access model harder to
  examine — which is the opposite of what it is for. Two verifiers are listed because a road
  closure needs two different people, and one account cannot demonstrate that.
*/

const DEMO = [
  { username: "reporter", password: "reporter123", label: "Field Reporter",
    detail: "Submits reports. Cannot verify anything." },
  { username: "verifier.as", password: "verify123", label: "District Verifier — Assam",
    detail: "Verifies in Assam and Meghalaya only." },
  { username: "verifier.mn", password: "verify123", label: "District Verifier — Manipur",
    detail: "Manipur, Nagaland, Mizoram. Countersigns closures." },
  { username: "controller", password: "control123", label: "State Controller",
    detail: "Acts anywhere. The only role that can delete." },
];

const Login = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
      </Card>

      <Card>
        <h2 className="text-sm font-semibold mb-1">Demonstration accounts</h2>
        <p className="text-xs text-ink-muted mb-4 leading-relaxed">
          Seeded by <code className="mono text-ink-secondary">seed_users.py</code>. Sign in as
          each to see the API refuse what that role may not do — the rules are enforced
          server-side, not hidden in the interface.
        </p>
        <ul className="divide-y divide-white/[0.06]">
          {DEMO.map((account) => (
            <li key={account.username} className="py-2.5 first:pt-0 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink">{account.label}</p>
                <p className="text-[11px] text-ink-muted mt-0.5">{account.detail}</p>
                <p className="text-[11px] mono text-ink-secondary mt-1">
                  {account.username} · {account.password}
                </p>
              </div>
              <button
                type="button"
                className="chip shrink-0"
                onClick={() =>
                  setForm({ username: account.username, password: account.password })
                }
              >
                Use
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
};

export default Login;
