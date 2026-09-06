// src/components/OfflineReadiness.jsx
//
// Field-readiness panel: what this device can still do once the signal goes.
//
// Offline support that you cannot see is offline support nobody trusts. A responder heading
// from Guwahati into the Mizoram hills needs to know, *before* they lose coverage, whether
// the corridor network is on the phone and whether anything is still waiting to be sent.
// After the fact is too late — that is the whole problem this panel exists to solve.

import { useState } from "react";
import { Badge, Card, SectionHeading, Spinner } from "./ui";
import { incidentLabel } from "../lib/accessibility";
import { timeAgo } from "../lib/format";
import { useSync } from "../context/SyncContext";

const OfflineReadiness = () => {
  const { online, pending, pendingCount, syncing, sync, cacheStatus, prepareOffline, offlineReady } =
    useSync();
  const [preparing, setPreparing] = useState(false);
  const [note, setNote] = useState(null);

  const download = async () => {
    setPreparing(true);
    setNote(null);
    try {
      const result = await prepareOffline();
      setNote(
        result.cached === result.total
          ? "This device now holds the full corridor network, cargo profiles and transport rate cards. Route planning and reporting will work with no signal."
          : `Stored ${result.cached} of ${result.total} datasets. Try again in better coverage for the rest.`
      );
    } catch {
      setNote("Could not reach the server. Try again once you have a connection.");
    } finally {
      setPreparing(false);
    }
  };

  return (
    <Card>
      <SectionHeading hint="What this device can do without a connection">
        Offline readiness
      </SectionHeading>

      <div className="flex items-center gap-2 flex-wrap mb-3">
        <Badge tone={online ? "success" : "warning"}>{online ? "Online" : "No connection"}</Badge>
        <Badge tone={offlineReady ? "success" : "danger"}>
          {offlineReady ? `Network data ${cacheStatus.age}` : "No offline data stored"}
        </Badge>
        {pendingCount > 0 && <Badge tone="warning">{pendingCount} report(s) waiting to send</Badge>}
      </div>

      {!offlineReady && (
        <p className="text-sm text-[#fab219]/90 mb-3">
          Nothing is stored on this device yet, so route planning will fail once you lose
          signal. Download the network while you still have coverage.
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={download}
          disabled={preparing || !online}
          className="btn-ghost"
        >
          {preparing ? <Spinner /> : null}
          {offlineReady ? "Refresh offline data" : "Download for offline use"}
        </button>
        {pendingCount > 0 && (
          <button type="button" onClick={sync} disabled={syncing || !online} className="btn-ghost">
            {syncing ? <Spinner /> : null}
            Send {pendingCount} queued report{pendingCount > 1 ? "s" : ""} now
          </button>
        )}
      </div>

      {note && <p className="text-xs text-ink-secondary mt-2">{note}</p>}

      {cacheStatus.storage?.usage != null && (
        <p className="text-xs text-ink-muted mt-2">
          Using {(cacheStatus.storage.usage / 1048576).toFixed(1)} MB of device storage.
        </p>
      )}

      {pendingCount > 0 && (
        <div className="mt-4 border-t border-white/10 pt-3">
          <p className="text-xs text-ink-muted mb-2">Queued on this device</p>
          <ul className="space-y-2">
            {pending.map((item) => (
              <li
                key={item.client_uuid}
                className="text-xs text-ink-secondary flex items-start justify-between gap-3"
              >
                <span className="min-w-0">
                  <span className="text-ink-secondary">{incidentLabel(item.type)}</span> · severity{" "}
                  {item.severity} · queued {timeAgo(item.queued_at)}
                  {item.description ? (
                    <span className="block text-ink-muted truncate">{item.description}</span>
                  ) : null}
                </span>
                {item.attempts > 0 && (
                  <Badge tone={item.attempts > 3 ? "danger" : "warning"}>
                    {item.attempts} failed attempt{item.attempts > 1 ? "s" : ""}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted mt-2">
            Each report carries a device-generated id, so sending it twice cannot create a
            duplicate. They will go automatically the moment you are back in coverage.
          </p>
        </div>
      )}
    </Card>
  );
};

export default OfflineReadiness;
