import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Image, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, Text, TextInput, View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";
import { loadSession } from "../src/lib/api";
import { enqueue, getQueue, isOnline, sync } from "../src/lib/queue";
import { INCIDENT_TYPES, SEVERITY_HINTS, T, severityColor } from "../src/lib/theme";
import { s } from "../src/lib/ui";
import { attributionLine } from "../src/lib/format";

/*
  The report form — the whole reason for a separate mobile app.

  Everything here is shaped by one assumption: the person using it is standing outdoors at
  the obstruction, on a bad connection or none, possibly one-handed, and wants to be done in
  under a minute. So:

    * Submitting never blocks on the network. The report is written to the device and the
      screen says so; sending is a background concern, not the reporter's problem.
    * Severity is five big buttons, not a slider. A slider needs a careful drag and gives no
      feedback about what the value means; these are thumb-sized and each says what it means.
    * Location is captured automatically on open, because the coordinates are the single most
      valuable field and the one a person is least able to type accurately.
*/

const EMPTY = { type: "landslide", severity: 3, description: "", reporter_name: "" };

export default function ReportScreen() {
  const router = useRouter();
  const [form, setForm] = useState(EMPTY);
  const [coords, setCoords] = useState(null);
  const [locating, setLocating] = useState(true);
  const [locError, setLocError] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [queued, setQueued] = useState(0);
  const [online, setOnline] = useState(true);
  const [banner, setBanner] = useState(null);

  const refresh = useCallback(async () => {
    setQueued((await getQueue()).length);
    setOnline(await isOnline());
  }, []);

  useEffect(() => {
    loadSession();
    captureLocation();
  }, []);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));

  async function captureLocation() {
    setLocating(true);
    setLocError(null);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        setLocError("Location permission denied — you can still report, but a verifier will not know exactly where.");
        return;
      }
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setCoords({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
      });
    } catch {
      setLocError("Could not get a fix. Move to open sky, or report without coordinates.");
    } finally {
      setLocating(false);
    }
  }

  async function attachPhoto() {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== "granted") {
      Alert.alert("Camera unavailable", "Grant camera access to attach a photograph.");
      return;
    }
    // Downscaled hard: a raw phone JPEG will not survive a 2G uplink from a valley, and the
    // queue has to hold it on the device until then.
    const result = await ImagePicker.launchCameraAsync({ quality: 0.35, base64: true });
    if (!result.canceled && result.assets?.[0]?.base64) {
      setPhoto(`data:image/jpeg;base64,${result.assets[0].base64}`);
    }
  }

  async function submit() {
    if (!coords) {
      Alert.alert(
        "No location yet",
        "A report without coordinates cannot be matched to a corridor. Submit anyway?",
        [
          { text: "Wait for a fix", style: "cancel" },
          { text: "Submit anyway", onPress: () => doSubmit() },
        ]
      );
      return;
    }
    doSubmit();
  }

  async function doSubmit() {
    await enqueue({
      type: form.type,
      severity: form.severity,
      description: form.description.trim(),
      reporter_name: form.reporter_name.trim() || undefined,
      latitude: coords?.latitude ?? 0,
      longitude: coords?.longitude ?? 0,
      image_url: photo || undefined,
    });

    setForm(EMPTY);
    setPhoto(null);
    await refresh();

    // Try immediately, but the report is already safe either way — the message says which
    // happened rather than making the reporter guess.
    const result = await sync();
    const landed = attributionLine(result.lastAttribution);
    setBanner(
      result.sent > 0
        ? {
            // Naming the corridor it matched turns "sent" into something the reporter can
            // check. If it matched nothing, that is the more important message of the two.
            tone: result.lastAttribution && !result.lastAttribution.on_network ? "warn" : "good",
            text: landed
              ? `Report sent. ${landed}`
              : "Report sent. A verifier will review it before it can affect routing.",
          }
        : { tone: "warn", text: "Saved on this device. It will send by itself when you have signal." }
    );
    await refresh();
    setTimeout(() => setBanner(null), 6000);
  }

  return (
    <KeyboardAvoidingView
      style={s.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView contentContainerStyle={[s.pad, { paddingBottom: 48, gap: 16 }]}>
        {/* connectivity + queue: always visible, because a reporter needs to know whether
            what they just filed has actually left the phone */}
        <View style={[s.row, { justifyContent: "space-between" }]}>
          <View style={s.row}>
            <View style={{
              width: 8, height: 8, borderRadius: 4,
              backgroundColor: online ? T.good : T.warning,
            }} />
            <Text style={s.muted}>{online ? "Online" : "Offline — reports will queue"}</Text>
          </View>
          <Pressable onPress={() => router.push("/reports")} hitSlop={12}>
            <Text style={{ color: T.accent, fontSize: 13, fontWeight: "600" }}>
              My reports{queued > 0 ? ` (${queued} queued)` : ""}
            </Text>
          </Pressable>
        </View>

        {banner && (
          <View style={[s.card, {
            borderColor: banner.tone === "good" ? "rgba(12,163,12,0.4)" : "rgba(250,178,25,0.4)",
            backgroundColor: banner.tone === "good" ? "rgba(12,163,12,0.1)" : "rgba(250,178,25,0.08)",
          }]}>
            <Text style={{ color: banner.tone === "good" ? T.goodText : T.warning, fontSize: 14 }}>
              {banner.text}
            </Text>
          </View>
        )}

        {/* type */}
        <View>
          <Text style={s.label}>What is blocking the road?</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {INCIDENT_TYPES.map((type) => {
              const on = form.type === type.id;
              return (
                <Pressable
                  key={type.id}
                  onPress={() => setForm({ ...form, type: type.id })}
                  style={[s.chip, on && s.chipOn]}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: on }}
                >
                  <Text style={[s.chipText, on && s.chipTextOn]}>{type.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {/* severity — the field a verifier leans on most, so it gets the most room */}
        <View>
          <Text style={s.label}>How bad is it?</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {[1, 2, 3, 4, 5].map((level) => {
              const on = form.severity === level;
              return (
                <Pressable
                  key={level}
                  onPress={() => setForm({ ...form, severity: level })}
                  style={[s.chip, { flex: 1, minHeight: 56 },
                          on && { borderColor: severityColor(level), backgroundColor: "rgba(255,255,255,0.05)" }]}
                  accessibilityLabel={`Severity ${level}: ${SEVERITY_HINTS[level]}`}
                >
                  <Text style={{
                    color: on ? severityColor(level) : T.inkMuted,
                    fontSize: 18, fontWeight: "700",
                  }}>{level}</Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={[s.muted, { marginTop: 8 }]}>{SEVERITY_HINTS[form.severity]}</Text>
          {form.severity === 5 && (
            <Text style={[s.muted, { marginTop: 4, color: T.warning }]}>
              Severity 5 can close the road to convoys — but only after two verifiers agree.
            </Text>
          )}
        </View>

        {/* location */}
        <View style={s.card}>
          <Text style={s.label}>Location</Text>
          {locating ? (
            <View style={s.row}>
              <ActivityIndicator color={T.accent} />
              <Text style={s.body}>Getting a fix…</Text>
            </View>
          ) : coords ? (
            <>
              <Text style={{ color: T.ink, fontSize: 15 }}>
                {coords.latitude.toFixed(5)}, {coords.longitude.toFixed(5)}
              </Text>
              <Text style={[s.muted, { marginTop: 4 }]}>
                ±{Math.round(coords.accuracy || 0)} m · attached automatically
              </Text>
            </>
          ) : (
            <Text style={[s.body, { color: T.warning }]}>{locError}</Text>
          )}
          <Pressable onPress={captureLocation} style={[s.btn, s.btnGhost, { marginTop: 12 }]}>
            <Text style={s.btnGhostText}>{coords ? "Update location" : "Try again"}</Text>
          </Pressable>
        </View>

        {/* description */}
        <View>
          <Text style={s.label}>What did you see?</Text>
          <TextInput
            style={[s.input, { minHeight: 96, textAlignVertical: "top" }]}
            placeholder="Boulders across both lanes just past the bridge; nothing getting through."
            placeholderTextColor={T.inkMuted}
            multiline
            value={form.description}
            onChangeText={(description) => setForm({ ...form, description })}
          />
        </View>

        {/* photo */}
        <View>
          <Text style={s.label}>Photograph (optional)</Text>
          {photo ? (
            <View>
              <Image
                source={{ uri: photo }}
                style={{ width: "100%", height: 180, borderRadius: 12 }}
                resizeMode="cover"
              />
              <Pressable onPress={() => setPhoto(null)} style={[s.btn, s.btnGhost, { marginTop: 8 }]}>
                <Text style={s.btnGhostText}>Remove photo</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable onPress={attachPhoto} style={[s.btn, s.btnGhost]}>
              <Text style={s.btnGhostText}>Take a photo of the obstruction</Text>
            </Pressable>
          )}
          <Text style={[s.muted, { marginTop: 6 }]}>
            A verifier deciding whether to close a highway is otherwise going on your
            description alone.
          </Text>
        </View>

        <View>
          <Text style={s.label}>Your name (optional)</Text>
          <TextInput
            style={s.input}
            placeholder="So a verifier can follow up"
            placeholderTextColor={T.inkMuted}
            value={form.reporter_name}
            onChangeText={(reporter_name) => setForm({ ...form, reporter_name })}
          />
        </View>

        <Pressable onPress={submit} style={[s.btn, s.btnPrimary]}>
          <Text style={s.btnPrimaryText}>Submit report</Text>
        </Pressable>

        <Text style={[s.muted, { textAlign: "center" }]}>
          Works with no signal. Your report is saved on this phone and sends itself when you
          are back in coverage.
        </Text>

        <View style={[s.row, { justifyContent: "center", gap: 20, marginTop: 4 }]}>
          <Pressable onPress={() => router.push("/nearby")} hitSlop={12}>
            <Text style={{ color: T.accent, fontSize: 13 }}>Nearby corridors</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/signin")} hitSlop={12}>
            <Text style={{ color: T.accent, fontSize: 13 }}>Sign in / settings</Text>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
