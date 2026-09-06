# NER Field Reporter (Expo / React Native)

The mobile half of the platform. The web console is for the control room; this is for the
person standing at the obstruction.

## Why a separate app rather than the PWA

The web app is already an installable PWA and works on a phone. This exists because the field
job is a different job, not a smaller screen: capture a photograph and a GPS fix in under a
minute, on a connection that is usually absent, and be certain the report survives until
there is signal. Everything here is built around that one path. Verification, planning and
analysis stay on the web console, where there is a keyboard, a wide screen and a person whose
job is to decide.

## Screens

| Screen | Purpose |
|---|---|
| Report | Type, severity, automatic GPS, photo, description. Never blocks on the network. |
| My reports | Every report with its real delivery state: on the phone, sent, already known, refused. |
| Nearby corridors | Nearest corridors and their accessibility, cached for offline use. |
| Sign in | Optional. Attribution and withdrawal, plus the server address. |

## Offline behaviour

Submitting writes to AsyncStorage first and returns immediately; sending is a background
concern. Each report carries a client-generated UUID and the backend de-duplicates on it
(`POST /api/ner/incidents/sync` returns a per-item result), so retrying is always safe and a
lost response can never create a second landslide in the record. `reported_at` is stamped on
the device at the moment of observation, so a report that syncs six hours later still
describes the road as it was when it was seen.

A 4xx is treated as a rejection of the content and removed from the queue with its error kept
for the reporter to read; anything else stays queued, because the report is fine and the
network is not.

## Running it on an iPhone

You do not need a Mac. Expo Go runs the app on the phone; your laptop only serves the code.

**1. Start the backend** (separate terminal, leave it running):

```bash
cd routeOptimiserBackend
python main.py            # already binds 0.0.0.0, so the phone can reach it
```

**2. Start the app:**

```bash
cd nerFieldApp
npm install
npx expo start
```

**3. Install Expo Go** from the App Store, then scan the QR code in the terminal with the
iPhone **Camera** app (not from inside Expo Go — on iOS the Camera app is the way in).

**4. Set the backend address.** The app fills this in by itself from the address Expo is
serving on, which is your laptop. Open **Sign in / settings**, press **Test connection**, and
it will tell you plainly whether the backend is reachable. If not, press **Auto-detect**, or
type your laptop's LAN address (`http://192.168.1.20:5001`).

Sign-in is optional — reporting works without an account. To sign in: `reporter` /
`reporter123`.

## Making reports show up on the website

The app and the web console are not two databases that need syncing — they are two clients of
one backend, writing to the same `incidents` table through the same endpoints. So there is
exactly one thing to get right: **both must point at the same backend URL.**

| Client | Setting | Value |
|---|---|---|
| Website | `routeOptimiserFrontend/.env` → `VITE_API_BASE_URL` | the backend URL |
| This app | `nerFieldApp/.env` → `EXPO_PUBLIC_API_BASE_URL` | the same backend URL |

Copy `.env.example` to `.env`, set the URL, and restart `npx expo start` (Expo inlines
`EXPO_PUBLIC_*` at bundle time, so a running server will not pick it up). You can also set it
per-device on the **Sign in** screen, which is stored on the phone and overrides everything.

Left unset, the app infers the backend from the address Expo is serving on — your laptop. That
is the right default while developing against a local backend, and wrong as soon as the website
points at a deployed one: your reports go into the laptop's SQLite file, the deployed console
reads a different database, and both halves work while showing nothing the other filed. That is
what "the databases are not connected" almost always is.

**To check, rather than assume:** Sign in → **Test connection**. It reports the address and how
many reports that backend actually holds. If the website's review queue shows 40 and the app
says 0, they are on different backends.

Once they match, file a report here and open **Incident Review** on the website: it appears
within a minute (the queue polls), labelled *via field app*.

### If it will not open

| Symptom | Cause and fix |
|---|---|
| "Project is incompatible with this version of Expo Go" | Your Expo Go supports a different SDK. Check the version shown on Expo Go's home screen, then run `npx expo install expo@^<that major>.0.0 --fix`. |
| QR scans but never loads | College, hostel and office Wi-Fi usually block phone-to-laptop traffic. Run `npx expo start --tunnel` instead — it routes through Expo's servers and works on any network. |
| App loads, but every request fails | The phone cannot reach the backend. Both devices must be on the same Wi-Fi, and a laptop firewall may be blocking port 5001. Use **Test connection** on the Sign in screen to confirm. |
| Bundling errors after changing packages | `npx expo install --fix` realigns every dependency to your SDK. |

### On the SDK version

This project targets the Expo SDK current at the time of writing. Expo Go on the App Store
only runs one or two SDK versions at a time, and it moves every few months — so if the app
refuses to open, that mismatch is the first thing to check, not your setup. `npx expo install
--fix` after changing the `expo` version realigns everything else automatically.

### Building an installable app

Expo Go is for development. To hand a judge something that installs on its own:

```bash
npm install -g eas-cli
eas build -p ios --profile preview      # needs an Apple Developer account, distributes via TestFlight
eas build -p android --profile preview  # produces an .apk that installs directly — no account needed
```

Android is markedly easier for a demo: the `.apk` installs from a link with no developer
account and no TestFlight review.

## Building an installable APK

```bash
npm install -g eas-cli
eas build -p android --profile preview
```

`eas build` runs on Expo's servers and needs an Expo account; the resulting `.apk` installs
directly. For a local build instead, `npx expo prebuild` then `./gradlew assembleRelease`.

## What this app deliberately does not do

No verification, no routing, no analytics. Those need a role this app's users do not have and
a screen this app does not have. Keeping them out is what lets the reporting path stay one
minute long.
