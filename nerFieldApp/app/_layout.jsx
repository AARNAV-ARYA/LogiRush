import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { T } from "../src/lib/theme";

export default function Layout() {
  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: T.surfaceSunken },
          headerTintColor: T.ink,
          headerTitleStyle: { fontSize: 16, fontWeight: "600" },
          contentStyle: { backgroundColor: T.plane },
        }}
      >
        <Stack.Screen name="index" options={{ title: "Report an incident" }} />
        <Stack.Screen name="reports" options={{ title: "My reports" }} />
        <Stack.Screen name="signin" options={{ title: "Sign in" }} />
        <Stack.Screen name="nearby" options={{ title: "Nearby corridors" }} />
      </Stack>
    </>
  );
}
