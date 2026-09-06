import { useCallback, useEffect, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import * as Location from "expo-location";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "../src/lib/api";
import { T } from "../src/lib/theme";
import { s } from "../src/lib/ui";

/*
  Which roads near me are in trouble.

  Deliberately a list and not a map. A map needs tiles, and tiles need the connection this
  user does not have; a list of the nearest corridors with a distance and a score survives
  being offline entirely. The last fetch is cached so the screen still answers on the drive
  back, with the age of the data stated rather than implied — stale figures presented as
  current are worse than none when someone is deciding whether a road is passable.
*/

const CACHE_KEY = "ner.segments.cache";

const km = (a, b) => {
  const R = 6371, rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
};

const scoreColor = (score) =>
  score >= 80 ? T.imp[0] : score >= 60 ? T.imp[1] : score >= 40 ? T.imp[2]
  : score >= 20 ? T.imp[3] : T.imp[4];

export default function NearbyScreen() {
  const [segments, setSegments] = useState([]);
  const [here, setHere] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [stale, setStale] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const { status } = await Location.getForegroundPermissionsAsync();
      if (status === "granted") {
        const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
        setHere({ lat: p.coords.latitude, lon: p.coords.longitude });
      }
    } catch { /* position is a nicety here, not a requirement */ }

    try {
      const response = await api.getSegments();
      setSegments(response.segments || []);
      const now = new Date().toISOString();
      setFetchedAt(now);
      setStale(false);
      await AsyncStorage.setItem(CACHE_KEY, JSON.stringify({ at: now, segments: response.segments }));
    } catch {
      const cached = await AsyncStorage.getItem(CACHE_KEY);
      if (cached) {
        const { at, segments: saved } = JSON.parse(cached);
        setSegments(saved || []);
        setFetchedAt(at);
        setStale(true);
      }
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const ranked = segments
    .map((seg) => ({
      ...seg,
      _km: here && seg.source_coords
        ? km(here, { lat: seg.source_coords[0], lon: seg.source_coords[1] })
        : null,
    }))
    .sort((a, b) => {
      if (a._km != null && b._km != null) return a._km - b._km;
      return a.accessibility_score - b.accessibility_score;
    })
    .slice(0, 40);

  return (
    <View style={s.screen}>
      <FlatList
        data={ranked}
        keyExtractor={(item) => item.id}
        contentContainerStyle={[s.pad, { gap: 10, paddingBottom: 40 }]}
        refreshControl={<RefreshControl refreshing={busy} onRefresh={load} tintColor={T.accent} />}
        ListHeaderComponent={
          <View style={{ marginBottom: 6 }}>
            <Text style={s.body}>
              {here ? "Corridors nearest you first." : "Worst-scoring corridors first."}
            </Text>
            {fetchedAt && (
              <Text style={[s.muted, { marginTop: 4, color: stale ? T.warning : T.inkMuted }]}>
                {stale ? "Offline — showing data saved " : "Updated "}
                {new Date(fetchedAt).toLocaleString()}
                {stale ? ". Conditions may have changed." : ""}
              </Text>
            )}
            {/* These scores are arithmetic over demonstration risk values, not an official
                road status. A reporter deciding whether to drive a corridor deserves to know
                that from the screen showing the number, not from a document. */}
            <Text style={[s.muted, { marginTop: 6 }]}>
              Scores combine demonstration risk data with real reports filed here. They are
              not an official road status.
            </Text>
          </View>
        }
        ListEmptyComponent={
          <View style={[s.card, { alignItems: "center", paddingVertical: 40 }]}>
            <Text style={s.h2}>No corridor data</Text>
            <Text style={[s.muted, { marginTop: 6, textAlign: "center" }]}>
              Connect once to download the network; it is then kept on this phone.
            </Text>
          </View>
        }
        renderItem={({ item }) => (
          <View style={s.card}>
            <View style={[s.row, { justifyContent: "space-between" }]}>
              <Text style={[s.h2, { flex: 1 }]} numberOfLines={1}>
                {item.source_name} → {item.destination_name}
              </Text>
              <View style={[s.row, { gap: 6 }]}>
                <View style={{
                  width: 8, height: 8, borderRadius: 4,
                  backgroundColor: item.impassable ? T.critical : scoreColor(item.accessibility_score),
                }} />
                <Text style={{ color: T.ink, fontWeight: "600" }}>
                  {Math.round(item.accessibility_score)}
                </Text>
              </View>
            </View>
            <Text style={[s.muted, { marginTop: 4 }]}>
              {item.highway_corridor} · {Math.round(item.distance_km)} km
              {item._km != null ? ` · ${item._km.toFixed(0)} km from you` : ""}
            </Text>
            {item.impassable && (
              <Text style={{ color: T.criticalText, fontSize: 12, marginTop: 6, fontWeight: "600" }}>
                Closed — not usable for routing
              </Text>
            )}
          </View>
        )}
      />
    </View>
  );
}
