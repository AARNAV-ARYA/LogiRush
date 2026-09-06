/* eslint-disable react/prop-types */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import {
  Badge, Card, DemoDataNotice, EmptyState, ErrorState, SectionHeading, Spinner, Toggle,
} from "../components/ui";
import { useApi } from "../hooks/useApi";
import { incidentLabel } from "../lib/accessibility";
import { formatDistance, timeAgo } from "../lib/format";

const SEVERITY_TONES = ["neutral", "neutral", "warning", "warning", "danger", "danger"];

const STATUS_TONES = {
  unverified: "neutral",
  awaiting_countersign: "warning",
  verified: "success",
  rejected: "danger",
  resolved: "info",
  withdrawn: "neutral",
};

/* Which client filed it. Worth a line in the row: a report from the field app was filed by
   someone standing at the obstruction with a GPS fix taken on the spot, and one from the
   console was typed by someone who was told about it. Both are welcome; they are not equally
   direct evidence, and a verifier deciding whether to close a highway should be able to see
   which one they are looking at. */
const SOURCE_LABELS = {
  app: "via field app",
  web: "via web console",
  api: "via API",
};

const STATUS_LABELS = {
  unverified: "pending review",
  awaiting_countersign: "awaiting countersign",
  verified: "verified",
  rejected: "rejected",
  resolved: "resolved",
  withdrawn: "withdrawn",
};

/** A short prompt for a reason, inline rather than a browser dialog (which blocks and looks
 *  like a bug on a kiosk screen). */
const ReasonPrompt = ({ title, placeholder, confirmLabel, tone, onConfirm, onCancel }) => {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="mt-3 rounded-lg border border-white/10 p-3" style={{ backgroundColor: "var(--surface-sunken)" }}>
      <p className="text-xs text-ink mb-2">{title}</p>
      <textarea
        rows="2"
        className="field !mt-0 !text-xs"
        placeholder={placeholder}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        autoFocus
      />
      <div className="flex items-center gap-2 mt-2">
        <button
          className={tone === "danger" ? "btn-danger !py-1.5 !min-h-[2rem]" : "btn-primary !py-1.5 !min-h-[2rem]"}
          disabled={busy || reason.trim().length < 3}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm(reason.trim());
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Spinner /> : null}
          {confirmLabel}
        </button>
        <button className="btn-ghost !py-1.5 !min-h-[2rem]" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        {reason.trim().length < 3 && (
          <span className="text-[11px] text-ink-muted">A reason is required — it is logged.</span>
        )}
      </div>
    </div>
  );
};

const IncidentRow = ({ incident, onChanged }) => {
  const { can, refusalFor, isSignedIn } = useAuth();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [prompt, setPrompt] = useState(null);   // "reject" | "resolve" | "delete"
  const [audit, setAudit] = useState(null);

  const status = incident.verification_status;
  const refusal = refusalFor(incident, "verify");
  const deleteRefusal = refusalFor(incident, "delete");

  const run = async (fn, key) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      setPrompt(null);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const isClosure =
    incident.severity >= 5 &&
    ["landslide", "flood", "road_block", "bridge_damage"].includes(incident.type);
  const closesCorridor = status === "verified" && isClosure && incident.segment_id;
  const terminal = ["resolved", "rejected", "withdrawn"].includes(status);
  // "Verify" is only meaningful where there is something left to sign. On an already-verified
  // report it is a button that does nothing, which teaches people to distrust the controls.
  const canSign = status === "unverified" || status === "awaiting_countersign";

  return (
    <div className="py-3.5 first:pt-0 last:pb-0" data-testid="incident-row">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-ink font-medium">{incidentLabel(incident.type)}</span>
            <Badge tone={SEVERITY_TONES[incident.severity] || "neutral"}>
              Severity {incident.severity}/5
            </Badge>
            <Badge tone={STATUS_TONES[status] || "neutral"}>
              {STATUS_LABELS[status] || status}
            </Badge>
            {incident.segment_id && <Badge tone="info">{incident.segment_id}</Badge>}
            {/* A report nobody can tie to a road cannot close one, and a verifier should see
                that before they reach for the Verify button rather than after. */}
            {!incident.segment_id && <Badge tone="neutral">Off network</Badge>}
            {closesCorridor && <Badge tone="danger">Closing this corridor</Badge>}
          </div>

          <p className="text-sm text-ink-secondary mt-1.5">
            {incident.description || "No description provided."}
          </p>
          <p className="text-xs text-ink-muted mt-1">
            {incident.reporter_name || "Anonymous"}
            {SOURCE_LABELS[incident.source] ? <> · {SOURCE_LABELS[incident.source]}</> : null} ·{" "}
            {timeAgo(incident.reported_at)} ·{" "}
            {incident.latitude.toFixed(3)}, {incident.longitude.toFixed(3)}
            {/* How well the coordinate actually matches the corridor it is filed against.
                "Attributed to RS004" reads as certainty; "0.4 km from it" is evidence, and a
                report 28 km off the line is a prompt to look again before signing. */}
            {incident.segment_distance_km !== null &&
              incident.segment_distance_km !== undefined && (
                <> · {formatDistance(incident.segment_distance_km)} from{" "}
                  {incident.segment_id ? "the corridor" : "the nearest corridor"}</>
              )}
          </p>

          {!incident.segment_id && (
            <p className="text-[11px] text-ink-muted mt-1.5">
              No modelled corridor is close enough to attribute this to, so it cannot affect
              routing. It is kept and mapped at the coordinates reported — most often that
              means a mistyped coordinate worth checking with the reporter.
            </p>
          )}

          {/* Decision provenance, in the row. "Verified" without a name is not an audit
              trail — the question anyone asks about a closed highway is who closed it. */}
          {(incident.verified_by || incident.countersigned_by || incident.resolution_note) && (
            <p className="text-[11px] text-ink-muted mt-1.5">
              {incident.verified_by && <>Signed by {incident.verified_by}</>}
              {incident.countersigned_by && <> · countersigned by {incident.countersigned_by}</>}
              {incident.resolution_note && <> · “{incident.resolution_note}”</>}
            </p>
          )}

          {status === "awaiting_countersign" && (
            <p
              className="text-[11px] mt-2 px-2.5 py-1.5 rounded-md inline-block"
              style={{
                color: "var(--status-warning)",
                backgroundColor: "rgb(var(--status-warning-rgb) / 0.1)",
              }}
            >
              One signature so far. This would close a corridor, so a second verifier must
              countersign — the road stays open until then.
            </p>
          )}
        </div>

        {/* Actions. A control the signed-in user may not use is disabled with the reason
            attached, rather than hidden: someone who cannot act still needs to know who can. */}
        <div className="flex items-center gap-2 flex-wrap">
          {canSign && can.verify && (
            <button
              onClick={() => run(() => api.verifyIncident(incident.id), "verify")}
              disabled={Boolean(busy) || Boolean(refusal)}
              title={refusal || undefined}
              className="btn-primary !py-1.5 !min-h-[2.25rem]"
            >
              {busy === "verify" ? <Spinner /> : null}
              {status === "awaiting_countersign" ? "Countersign" : "Verify"}
            </button>
          )}

          {!terminal && can.verify && status !== "rejected" && (
            <button
              onClick={() => setPrompt("reject")}
              disabled={Boolean(busy) || Boolean(refusal)}
              title={refusal || undefined}
              className="btn-danger !py-1.5 !min-h-[2.25rem]"
            >
              Reject
            </button>
          )}

          {/* The answer to "the incident isn't permanent". Resolving reopens the corridor
              immediately and keeps the record; deleting would throw away a real event. */}
          {can.resolve && ["verified", "awaiting_countersign", "unverified"].includes(status) && (
            <button
              onClick={() => setPrompt("resolve")}
              disabled={Boolean(busy)}
              className="btn-ghost !py-1.5 !min-h-[2.25rem]"
              title="The obstruction is gone — reopen the corridor, keep the record"
            >
              Mark cleared
            </button>
          )}

          {can.delete && (
            <button
              onClick={() => setPrompt("delete")}
              disabled={Boolean(busy) || Boolean(deleteRefusal)}
              title={deleteRefusal || "Spam or duplicate only — a real event should be cleared"}
              className="btn-ghost !py-1.5 !min-h-[2.25rem] tone-bad"
            >
              Delete
            </button>
          )}

          <button
            className="chip"
            onClick={async () => {
              if (audit) return setAudit(null);
              const r = await api.getIncidentAudit(incident.id);
              setAudit(r.audit || []);
            }}
          >
            History
          </button>
        </div>
      </div>

      {!isSignedIn && !terminal && (
        <p className="text-[11px] text-ink-muted mt-2">
          <Link to="/login" className="text-accent">Sign in</Link> as a District Verifier to
          review this report.
        </p>
      )}

      {refusal && isSignedIn && !terminal && (
        <p className="text-[11px] text-ink-muted mt-2">{refusal}</p>
      )}

      {prompt === "reject" && (
        <ReasonPrompt
          title="Why is this report not valid? The reason is kept in the audit log."
          placeholder="Duplicate of #12 / could not be confirmed on the ground"
          confirmLabel="Reject report"
          tone="danger"
          onCancel={() => setPrompt(null)}
          onConfirm={(reason) => run(() => api.rejectIncident(incident.id, reason), "reject")}
        />
      )}

      {prompt === "resolve" && (
        <ReasonPrompt
          title="What cleared it? The corridor reopens as soon as this is saved."
          placeholder="Slip cleared by BRO, single lane open"
          confirmLabel="Mark cleared"
          onCancel={() => setPrompt(null)}
          onConfirm={(reason) => run(() => api.resolveIncident(incident.id, reason), "resolve")}
        />
      )}

      {prompt === "delete" && (
        <ReasonPrompt
          title="Delete removes the report entirely. Use it for spam or duplicates — a real event that is over should be marked cleared instead."
          placeholder="Spam submission / exact duplicate of #12"
          confirmLabel="Delete permanently"
          tone="danger"
          onCancel={() => setPrompt(null)}
          onConfirm={(reason) => run(() => api.deleteIncident(incident.id, reason), "delete")}
        />
      )}

      {audit && (
        <div className="mt-3 rounded-lg border border-white/10 p-3" style={{ backgroundColor: "var(--surface-sunken)" }}>
          <p className="label-micro mb-2">Decision history</p>
          {audit.length === 0 ? (
            <p className="text-[11px] text-ink-muted">No decisions recorded yet.</p>
          ) : (
            <ol className="space-y-1.5">
              {audit.map((row) => (
                <li key={row.id} className="text-[11px] text-ink-secondary">
                  <span className="text-ink">{row.action}</span>
                  {row.from_status && <> · {row.from_status} → {row.to_status}</>}
                  {row.actor && <> · {row.actor} ({row.actor_role})</>}
                  {row.reason && <> · “{row.reason}”</>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {error && <p className="text-sm tone-bad mt-2">{error}</p>}
    </div>
  );
};

const Incidents = () => {
  const query = useApi(() => api.getIncidents(200), { pollMs: 60000 });
  const { user, can } = useAuth();
  const [filter, setFilter] = useState("all");

  const incidents = useMemo(() => query.data?.incidents || [], [query.data]);
  const visible = useMemo(
    () => (filter === "all" ? incidents : incidents.filter((i) => i.verification_status === filter)),
    [incidents, filter]
  );

  const counts = useMemo(() => {
    const by = (s) => incidents.filter((i) => i.verification_status === s).length;
    return {
      unverified: by("unverified"),
      awaiting: by("awaiting_countersign"),
      verified: by("verified"),
      resolved: by("resolved"),
      rejected: by("rejected"),
      // This queue and the field app are one database, and the count of reports that came in
      // from a phone is the plainest evidence of it — for an operator wondering whether the
      // field team's reports are actually landing, and for anyone being shown the platform.
      fromApp: incidents.filter((i) => i.source === "app").length,
    };
  }, [incidents]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-5 sm:py-6">
      <header className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1>Incident Review</h1>
          <p className="text-ink-secondary mt-1 text-sm">
            {counts.unverified} pending
            {counts.awaiting > 0 && (
              <>
                {" · "}
                <span style={{ color: "var(--status-warning)" }}>
                  {counts.awaiting} awaiting countersign
                </span>
              </>
            )}
            {counts.fromApp > 0 && <> · {counts.fromApp} filed from the field app</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {user ? (
            <span className="text-xs text-ink-muted">
              {user.full_name} · {user.role}
              {user.jurisdiction?.length ? ` · ${user.jurisdiction.join(", ")}` : ""}
            </span>
          ) : (
            <Link to="/login" className="btn-ghost">Sign in to review</Link>
          )}
          <Link to="/report-incident" className="btn-primary">Report incident</Link>
        </div>
      </header>

      <div className="mb-4">
        <DemoDataNotice compact />
      </div>

      <Card className="mb-4 !p-3">
        <p className="text-xs text-ink-muted leading-relaxed">
          Verification is a human decision, never automated. A report raises a corridor&apos;s
          risk on its own but can never close it;{" "}
          <strong className="text-ink-secondary">closing a road needs two different verifiers</strong>,
          and a verifier can only act inside their assigned states. When an obstruction is
          cleared, mark it <strong className="text-ink-secondary">cleared</strong> — that
          reopens the corridor at once and keeps the record. Deletion is for spam only.
        </p>
      </Card>

      <div className="mb-4">
        <Toggle
          ariaLabel="Filter incidents by status"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `All (${incidents.length})` },
            { value: "unverified", label: `Pending (${counts.unverified})` },
            { value: "awaiting_countersign", label: `Countersign (${counts.awaiting})` },
            { value: "verified", label: `Verified (${counts.verified})` },
            { value: "resolved", label: `Cleared (${counts.resolved})` },
            { value: "rejected", label: `Rejected (${counts.rejected})` },
          ]}
        />
      </div>

      {query.error && <ErrorState message={query.error} onRetry={query.refetch} />}

      {query.loading ? (
        <Card>
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => <div key={i} className="h-16 skeleton rounded-lg" />)}
          </div>
        </Card>
      ) : visible.length ? (
        <Card>
          <SectionHeading hint={can.verify ? undefined : "Sign in as a verifier to act on these"}>
            {visible.length} report{visible.length === 1 ? "" : "s"}
          </SectionHeading>
          <div className="divide-y divide-white/[0.07]">
            {visible.map((incident) => (
              <IncidentRow key={incident.id} incident={incident} onChanged={query.refetch} />
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <EmptyState
            title="Nothing here"
            description={filter === "all" ? "No incidents reported yet." : `No ${filter.replace(/_/g, " ")} reports.`}
          />
        </Card>
      )}
    </div>
  );
};

export default Incidents;
