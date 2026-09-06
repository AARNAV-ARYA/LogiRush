# Deploying LogiRush

Three things get deployed and they must agree on one backend URL and one database. Get that
wrong and every part works in isolation while showing nothing the others filed — see
[One database, two clients](README.md#one-database-two-clients).

```
   Neon / Postgres  ←──  Render (Flask API)  ──→  Vercel (React console)
                                 ↑
                          Expo (field app)
```

Order matters: database, then backend, then the two clients that point at it.

---

## 1. Database — Neon (free tier)

1. Create a project at [neon.tech](https://neon.tech) → copy the **connection string**.
2. Keep it handy as `DATABASE_URL`. It looks like
   `postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require`.

A `postgres://`-style URL from Render or Heroku is rewritten to `postgresql://` automatically,
so either form works.

**Why not SQLite in production.** Without `DATABASE_URL` the backend falls back to a SQLite
file. On a host with an ephemeral filesystem — Render's free tier included — that file, and
every incident report in it, is discarded on the next restart. It also cannot be shared
between instances.

## 2. Backend — Render

1. [dashboard.render.com](https://dashboard.render.com) → **New ▸ Blueprint** → connect this
   repository. Render reads [`render.yaml`](render.yaml) and proposes the service.
2. Set the environment variables it asks for:

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | the Neon string from step 1 | the shared record |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://logirush.vercel.app` | leaving it `*` lets any site call your API |
| `NER_DISABLE_DEMO_SEED` | `1` | **see the warning below** |
| `PORT` | `10000` | already in the blueprint |

3. Deploy, then check `https://<your-service>.onrender.com/health` returns
   `{"status":"ok"}`, and `.../api/ner/weather` returns `"live": true` — that confirms the
   host can reach Open-Meteo. If it returns `"live": false`, rainfall has fallen back to the
   shipped snapshot and the response carries the reason; the platform still works, it is just
   no longer live on that input.

Tables are created at startup and an existing database is reconciled in place (columns added,
outgrown `VARCHAR` widened), so there is no migration step for the first deploy or for an
upgrade.

> ### Read this before deploying publicly
>
> `seed_users.py` ships demonstration accounts — `controller` / `control123` among them — and
> the backend seeds them on first run. **Their passwords are in this public repository.**
> Anyone who can read it could otherwise sign in to your deployment as a controller and close
> roads.
>
> There is no self-signup: the console's Sign Up page is a stub, because in the field these
> accounts would come from the state's own directory rather than be created by whoever finds
> the URL. So a real roster is created directly, once, in the Render shell:
>
> ```python
> # Render dashboard ▸ your service ▸ Shell ▸ python
> from src.api.auth import hash_password
> from src.db.models import User
> from src.db.session import get_session
>
> session = get_session()
> session.add(User(
>     username="a.baruah",
>     full_name="Anjali Baruah",
>     password_hash=hash_password("<a real password, not this>"),
>     role="verifier",                 # reporter | verifier | controller
>     organisation="DDMA Assam",
>     jurisdiction="Assam,Meghalaya",  # verifiers act only inside these states
> ))
> session.commit()
> ```
>
> Create **at least two verifiers**: closing a corridor requires a countersign from a second,
> different verifier, so a single account cannot do it — by design.
>
> Keeping the demo roster is also defensible, for a judged demo that everyone understands to be
> a demonstration with nothing operational depending on it. What is not defensible is the
> default: a public deployment with published controller credentials, unremarked.

**Free tier note.** Render spins a free service down after inactivity, so the first request
after a quiet period takes ~30 s while it wakes. The backend warms its model and network
assessment on a background thread at boot, so it is fast once awake.

## 3. Console — Vercel

1. [vercel.com/new](https://vercel.com/new) → import this repository.
2. **Set Root Directory to `routeOptimiserFrontend`.** This is the step people miss: the repo
   is a monorepo and Vercel defaults to the root, where there is no `package.json`.
   Framework preset (Vite), build command and output directory come from
   [`vercel.json`](routeOptimiserFrontend/vercel.json).
3. Environment variable:

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | your Render URL, no trailing slash |

4. Deploy. Then go back to Render and set `CORS_ORIGINS` to the Vercel URL you were given.

Vite inlines `VITE_*` at build time, so **changing this variable requires a redeploy** — it is
not read at runtime.

## 4. Field app — Expo

The app is not deployed to a URL; it runs on a phone. What it needs is the same backend.

```bash
cd nerFieldApp
echo "EXPO_PUBLIC_API_BASE_URL=https://<your-service>.onrender.com" > .env
npx expo start        # scan the QR with the iPhone Camera app
```

Expo inlines `EXPO_PUBLIC_*` at bundle time, so restart `expo start` after changing `.env`.
The address is also editable per-device on the app's **Sign in** screen, which overrides the
bundled value.

For a standalone build (TestFlight or an APK), use EAS:

```bash
npm install -g eas-cli
eas login && eas build:configure
eas build --platform android --profile preview
```

## 5. Confirm the loop actually closes

The point of the whole setup is that a report filed on a phone reaches the console. Check it,
rather than assuming:

1. In the app: **Sign in → Test connection.** It names the backend and how many reports it
   holds. If that number disagrees with the console's review queue, the two are on different
   backends — fix that before anything else.
2. File a report from the app.
3. Open `/incidents` on the Vercel console. Within a minute (the queue polls) the report
   appears, labelled **via field app**, and the header count of reports filed from the app
   goes up.

If step 3 fails, the cause is almost always one of three things, in this order: the app's
`EXPO_PUBLIC_API_BASE_URL` still points at a laptop; `CORS_ORIGINS` does not include the
console's origin (the browser console will say so); or `DATABASE_URL` is unset on Render and
each restart is discarding the SQLite file.

## Environment variables, all together

| Where | Variable | Required | Notes |
|---|---|---|---|
| Render | `DATABASE_URL` | yes in production | Postgres; unset means ephemeral SQLite |
| Render | `CORS_ORIGINS` | yes in production | comma-separated; defaults to `*` |
| Render | `NER_DISABLE_DEMO_SEED` | yes for a public deploy | `1` to skip the published demo roster |
| Render | `PORT` | provided by host | |
| Render | `MAX_CONTENT_MB` | no | request body cap, default 16 (reports carry photos inline) |
| Render | `NER_LIVE_WEATHER` | no | live rainfall from Open-Meteo, on by default; `0` pins the shipped snapshot |
| Render | `WEATHER_CACHE_TTL_S` | no | how long a rainfall fetch is reused, default 900 |
| Render | `WEATHER_TIMEOUT_S` | no | how long a fetch may block before falling back, default 4.0 |
| Vercel | `VITE_API_BASE_URL` | yes | build-time; redeploy to change |
| Expo | `EXPO_PUBLIC_API_BASE_URL` | yes to share data | bundle-time; restart to change |
