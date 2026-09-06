/* eslint-disable react/prop-types */
import { AccessibilityBadge } from "./ui";
import { accessibilityColor, riskTextClass } from "../lib/accessibility";
import { formatKm, formatPercent } from "../lib/format";

/*
  A route drawn as a journey rather than tabulated as rows.

  The corridor table it replaces was correct and unreadable: five columns of numbers with no
  sense of sequence, so working out where the bad stretch fell meant reading down a column
  and counting. Every shipment-tracking interface worth copying draws the legs as a spine
  with the stops as nodes, because that is the shape of the thing — and it lets the connector
  itself carry the leg's condition, so the weak link is visible before you read a single
  figure.

  The connector is coloured on the impediment ramp and, for a closed corridor, dotted as
  well: colour alone never carries this, since it is the one thing on the screen that decides
  whether a convoy moves.
*/
const RouteTimeline = ({ route, dense = false }) => {
  const stops = route.path_names || [];
  const hasLegDetail = (route.segments || []).some((x) => x && typeof x === "object");

  return (
    <>
    <ol className="relative" data-testid="route-timeline">
      {stops.map((stop, i) => {
        // Two callers, two shapes: a freshly planned route carries full leg objects, while a
        // stored shipment snapshot keeps only segment IDs. Anything that is not an object is
        // a leg we have no detail for — and "no detail" must never render as "closed". A
        // dotted red spine is this screen's strongest claim; making it the fallback for
        // missing data would tell an operator a corridor is shut when nobody said so.
        const raw = route.segments?.[i];
        const leg = raw && typeof raw === "object" ? raw : null;
        const last = i === stops.length - 1;
        const closed = !!leg && (leg.impassable === true || (leg.road_status && leg.road_status !== "Open"));
        const legColor = leg ? accessibilityColor(leg.accessibility_score) : "var(--hairline-strong)";

        return (
          <li key={`${stop}-${i}`} className="relative flex gap-3">
            {/* spine */}
            <div className="flex flex-col items-center shrink-0 w-4">
              <span
                className="rounded-full shrink-0 mt-1"
                style={{
                  width: i === 0 || last ? 10 : 7,
                  height: i === 0 || last ? 10 : 7,
                  backgroundColor: i === 0 || last ? "var(--accent)" : "var(--surface)",
                  border: i === 0 || last ? "none" : "2px solid var(--ink-muted)",
                }}
              />
              {!last && (
                <span
                  className="flex-1 my-1 rounded-full"
                  style={{
                    width: 3,
                    minHeight: dense ? 26 : 34,
                    backgroundColor: closed ? "transparent" : legColor,
                    backgroundImage: closed
                      ? "repeating-linear-gradient(to bottom, var(--status-critical) 0 3px, transparent 3px 7px)"
                      : undefined,
                  }}
                />
              )}
            </div>

            {/* stop + the leg that leaves it */}
            <div className={`min-w-0 flex-1 ${last ? "pb-0" : dense ? "pb-3" : "pb-4"}`}>
              <p className="text-sm text-ink font-medium leading-none pt-0.5">{stop}</p>

              {leg && (
                <div className="mt-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[11px] text-ink-secondary">{leg.highway_corridor}</span>
                    <span className="text-[11px] text-ink-muted tabular-nums">
                      {formatKm(leg.distance_km)}
                    </span>
                    {closed && (
                      <span
                        className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                        style={{
                          color: "var(--status-critical)",
                          backgroundColor: "rgb(var(--status-critical-rgb) / 0.14)",
                        }}
                      >
                        {leg.road_status}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1.5">
                    <AccessibilityBadge score={leg.accessibility_score} showLabel={!dense} />
                    <span
                      className={`text-[11px] tabular-nums ${riskTextClass(leg.disruption_risk_percent)}`}
                    >
                      {formatPercent(leg.disruption_risk_percent, 0)} risk
                    </span>
                  </div>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
    {!hasLegDetail && stops.length > 1 && (
      <p className="text-[11px] text-ink-muted mt-2 pl-7">
        Stops only — this snapshot stored corridor IDs, not per-leg condition. Re-check the
        route for current figures.
      </p>
    )}
    </>
  );
};

export default RouteTimeline;
