import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { api, getBase, getInferredBase, loadSession, setBase, setToken } from "../src/lib/api";
import { T } from "../src/lib/theme";
import { s } from "../src/lib/ui";

/*
  Signing in is optional here, on purpose.

  A field reporter does not need an account to file a report — a stranded driver with no
  login is exactly who this platform most needs to hear from, and putting a sign-up wall in
  front of that would lose the reports that matter. What an account buys the reporter is
  attribution: a named report can be followed up, and it can be withdrawn if they got it
  wrong. Verification is a different job on a different screen, for a different role.

  The server address is editable because the most common failure when running this against a
  laptop is simply pointing at the wrong host — an emulator reaches it at 10.0.2.2, a real
  handset needs the laptop's LAN address, and neither should require rebuilding the app.
*/

export default function SignInScreen() {
  const [form, setForm] = useState({ username: "", password: "" });
  const [server, setServer] = useState("");
  const [user, setUser] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    loadSession().then(async ({ token }) => {
      setServer(getBase());
      if (token) {
        try {
          setUser((await api.me()).user);
        } catch {
          await setToken(null);
        }
      }
    });
  }, []);

  const saveServer = async () => {
    await setBase(server.trim());
    setMessage({ tone: "good", text: `Server set to ${getBase()}` });
  };

  const signIn = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await setBase(server.trim());
      const result = await api.login(form.username.trim().toLowerCase(), form.password);
      await setToken(result.token);
      setUser(result.user);
      setForm({ username: "", password: "" });
    } catch (e) {
      setMessage({ tone: "bad", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    await setToken(null);
    setUser(null);
  };

  return (
    <ScrollView style={s.screen} contentContainerStyle={[s.pad, { gap: 16 }]}>
      <View style={s.card}>
        <Text style={s.label}>Server</Text>
        <TextInput
          style={s.input}
          value={server}
          onChangeText={setServer}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="http://10.0.2.2:5001"
          placeholderTextColor={T.inkMuted}
        />
        <Text style={[s.muted, { marginTop: 8 }]}>
          This address decides which database your reports land in. Point it at the same
          backend the web console uses and everything you file here appears in the review
          queue there.
        </Text>
        <Text style={[s.muted, { marginTop: 6 }]}>
          Filled in automatically from the address Expo is serving this app on — normally your
          laptop on this Wi-Fi. Change it only if the backend runs somewhere else, or if you
          started Expo with --tunnel.
        </Text>
        <View style={[s.row, { marginTop: 12 }]}>
          <Pressable onPress={saveServer} style={[s.btn, s.btnGhost, { flex: 1 }]}>
            <Text style={s.btnGhostText}>Save</Text>
          </Pressable>
          <Pressable
            onPress={() => setServer(getInferredBase())}
            style={[s.btn, s.btnGhost, { flex: 1 }]}
          >
            <Text style={s.btnGhostText}>Auto-detect</Text>
          </Pressable>
        </View>
        <Pressable
          onPress={async () => {
            setMessage(null);
            try {
              await setBase(server.trim());
              /* Ask for the report count rather than just a 200. "Reachable" only proves
                 something answered; the number is what tells a reporter they are looking at
                 the same shared record the control room is — and a surprising 0 is the
                 clearest possible sign of pointing at the wrong backend. */
              const { total } = await api.getIncidents(1);
              setMessage({
                tone: "good",
                text:
                  `Connected to ${getBase()}. This backend holds ` +
                  `${total === 1 ? "1 report" : `${total ?? 0} reports`}, shared with the web console.`,
              });
            } catch (e) {
              setMessage({
                tone: "bad",
                text: `Cannot reach ${getBase()} — ${e.message}. Check the laptop and phone are on the same Wi-Fi and the backend is running.`,
              });
            }
          }}
          style={[s.btn, s.btnGhost, { marginTop: 8 }]}
        >
          <Text style={s.btnGhostText}>Test connection</Text>
        </Pressable>
      </View>

      {user ? (
        <View style={s.card}>
          <Text style={s.h2}>{user.full_name}</Text>
          <Text style={[s.muted, { marginTop: 4, textTransform: "capitalize" }]}>
            {user.role}
            {user.jurisdiction?.length ? ` · ${user.jurisdiction.join(", ")}` : ""}
          </Text>
          {!!user.organisation && (
            <Text style={[s.muted, { marginTop: 2 }]}>{user.organisation}</Text>
          )}
          <Text style={[s.body, { marginTop: 12 }]}>
            Your reports are filed under your name and can be followed up.
          </Text>
          <Pressable onPress={signOut} style={[s.btn, s.btnGhost, { marginTop: 12 }]}>
            <Text style={s.btnGhostText}>Sign out</Text>
          </Pressable>
        </View>
      ) : (
        <View style={s.card}>
          <Text style={s.h2}>Sign in (optional)</Text>
          <Text style={[s.body, { marginTop: 6, marginBottom: 14 }]}>
            You can report without an account. Signing in attaches your name so a verifier can
            follow up, and lets you withdraw a report you got wrong.
          </Text>

          <Text style={s.label}>Username</Text>
          <TextInput
            style={s.input}
            autoCapitalize="none"
            value={form.username}
            onChangeText={(username) => setForm({ ...form, username })}
          />

          <Text style={[s.label, { marginTop: 12 }]}>Password</Text>
          <TextInput
            style={s.input}
            secureTextEntry
            value={form.password}
            onChangeText={(password) => setForm({ ...form, password })}
          />

          {message && (
            <Text style={{
              marginTop: 12, fontSize: 13,
              color: message.tone === "bad" ? T.criticalText : T.goodText,
            }}>{message.text}</Text>
          )}

          <Pressable onPress={signIn} style={[s.btn, s.btnPrimary, { marginTop: 16 }]} disabled={busy}>
            {busy ? <ActivityIndicator color={T.onAccent} /> : null}
            <Text style={s.btnPrimaryText}>Sign in</Text>
          </Pressable>

          <Text style={[s.muted, { marginTop: 12 }]}>
            Demonstration account: reporter / reporter123
          </Text>
        </View>
      )}
    </ScrollView>
  );
}
