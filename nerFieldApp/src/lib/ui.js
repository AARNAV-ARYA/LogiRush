import { StyleSheet } from "react-native";
import { T } from "./theme";

/* Shared primitives. Touch targets are 48 px rather than the 44 px minimum: this is used
   one-handed, in rain, sometimes in gloves, by someone who is not looking carefully. */
export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: T.plane },
  pad: { padding: 16 },
  h1: { color: T.ink, fontSize: 22, fontWeight: "700", letterSpacing: -0.3 },
  h2: { color: T.ink, fontSize: 15, fontWeight: "600" },
  label: {
    color: T.inkMuted, fontSize: 11, fontWeight: "600",
    textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 6,
  },
  body: { color: T.inkSecondary, fontSize: 14, lineHeight: 20 },
  muted: { color: T.inkMuted, fontSize: 12 },
  card: {
    backgroundColor: T.surface, borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: T.hairline,
  },
  input: {
    backgroundColor: T.surfaceSunken, borderWidth: 1, borderColor: T.hairlineStrong,
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12,
    color: T.ink, fontSize: 16, minHeight: 48,
  },
  btn: {
    minHeight: 52, borderRadius: 12, alignItems: "center", justifyContent: "center",
    flexDirection: "row", gap: 8, paddingHorizontal: 18,
  },
  btnPrimary: { backgroundColor: T.accent },
  btnPrimaryText: { color: T.onAccent, fontWeight: "700", fontSize: 16 },
  btnGhost: { borderWidth: 1, borderColor: T.hairlineStrong },
  btnGhostText: { color: T.inkSecondary, fontWeight: "600", fontSize: 15 },
  chip: {
    minHeight: 48, paddingHorizontal: 14, borderRadius: 10, borderWidth: 1,
    borderColor: T.hairlineStrong, alignItems: "center", justifyContent: "center",
  },
  chipOn: { borderColor: T.accent, backgroundColor: "rgba(56,189,248,0.12)" },
  chipText: { color: T.inkSecondary, fontSize: 14, fontWeight: "500" },
  chipTextOn: { color: T.accent },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  divider: { height: 1, backgroundColor: T.hairline },
});
