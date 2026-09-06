import { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { getQueue, getSent, sync } from "../src/lib/queue";
import { T, severityColor, typeLabel } from "../src/lib/theme";
import { attributionLine } from "../src/lib/format";
import { s } from "../src/lib/ui";

/*
  What I have filed, and where each one got to.

  A queue you cannot see is a queue people stop trusting — and a reporter who is unsure
  whether their landslide reached anyone will file it again, which is how a control room ends
  up with four reports of one slip. So every item shows its actual state, including the
  awkward ones: still on the phone, sent, already known to the server, or refused.
*/

const STATE = {
  queued:    { label: "On this phone",  color: T.warning,
               hint: "Will send by itself when you have signal" },
  created:   { label: "Sent",           color: T.goodText,
               // Named concretely: "a verifier will review it" leaves a reporter guessing
               // whether it reached anything real. It is in the control room's queue now.
               hint: "In the control room's review queue on the web console" },
  duplicate: { label: "Already sent",   color: T.inkMuted,
               hint: "The server already had this one; nothing was duplicated" },
  rejected:  { label: "Not accepted",   color: T.criticalText,
               hint: null },
};

export default function ReportsScreen() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [queue, sent] = await Promise.all([getQueue(), getSent()]);
    setItems([
      ...queue.map((q) => ({ ...q, _state: "queued" })),
      ...sent.map((x) => ({ ...x, _state: x.server_status || "created" })),
    ]);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const pushNow = async () => {
    setBusy(true);
    try {
      await sync();
      await load();
    } finally {
      setBusy(false);
    }
  };

  const queuedCount = items.filter((i) => i._state === "queued").length;

  return (
    <View style={s.screen}>
      <FlatList
        data={items}
        keyExtractor={(item) => item.client_uuid}
        contentContainerStyle={[s.pad, { gap: 12, paddingBottom: 40 }]}
        refreshControl={
          <RefreshControl refreshing={busy} onRefresh={pushNow} tintColor={T.accent} />
        }
        ListHeaderComponent={
          queuedCount > 0 ? (
            <Pressable onPress={pushNow} style={[s.btn, s.btnPrimary, { marginBottom: 4 }]}>
              <Text style={s.btnPrimaryText}>
                Send {queuedCount} queued report{queuedCount === 1 ? "" : "s"} now
              </Text>
            </Pressable>
          ) : null
        }
        ListEmptyComponent={
          <View style={[s.card, { alignItems: "center", paddingVertical: 40 }]}>
            <Text style={s.h2}>Nothing filed yet</Text>
            <Text style={[s.muted, { marginTop: 6, textAlign: "center" }]}>
              Reports you submit will appear here with their delivery state.
            </Text>
          </View>
        }
        renderItem={({ item }) => {
          const state = STATE[item._state] || STATE.queued;
          return (
            <View style={s.card}>
              <View style={[s.row, { justifyContent: "space-between" }]}>
                <View style={s.row}>
                  <View style={{
                    width: 10, height: 10, borderRadius: 5,
                    backgroundColor: severityColor(item.severity),
                  }} />
                  <Text style={s.h2}>{typeLabel(item.type)}</Text>
                  <Text style={s.muted}>S{item.severity}</Text>
                </View>
                <Text style={{ color: state.color, fontSize: 12, fontWeight: "600" }}>
                  {state.label}
                </Text>
              </View>

              {!!item.description && (
                <Text style={[s.body, { marginTop: 8 }]} numberOfLines={3}>
                  {item.description}
                </Text>
              )}

              <Text style={[s.muted, { marginTop: 8 }]}>
                {new Date(item.reported_at).toLocaleString()}
                {item.latitude ? ` · ${item.latitude.toFixed(3)}, ${item.longitude.toFixed(3)}` : ""}
              </Text>

              {/* Where the server put it. An off-network report is called out in warning
                  colour because it is the one case the reporter can still do something
                  about. */}
              {!!attributionLine(item.attribution) && (
                <Text
                  style={[
                    s.muted,
                    { marginTop: 6 },
                    item.attribution.on_network ? null : { color: T.warning },
                  ]}
                >
                  {attributionLine(item.attribution)}
                </Text>
              )}

              {item.last_error ? (
                <Text style={[s.muted, { marginTop: 6, color: T.criticalText }]}>
                  {item.last_error}
                </Text>
              ) : state.hint ? (
                <Text style={[s.muted, { marginTop: 6 }]}>{state.hint}</Text>
              ) : null}

              {item._state === "queued" && item.attempts > 0 && (
                <Text style={[s.muted, { marginTop: 4 }]}>
                  {item.attempts} send attempt{item.attempts === 1 ? "" : "s"} so far
                </Text>
              )}
            </View>
          );
        }}
      />
    </View>
  );
}
