<div align="center">

<img src="https://img.shields.io/badge/LogiRush-NER%20Logistics%20Platform-0f172a?style=for-the-badge&logoColor=white" alt="LogiRush" />

# LogiRush — NER Smart Logistics & Accessibility Intelligence Platform

**Disaster-resilient logistics for India's North Eastern Region**  
Risk-aware routing · Live weather · ML disaster prediction · Community incident reporting

[![CI](https://github.com/AARNAV-ARYA/LogiRush/actions/workflows/ci.yml/badge.svg)](https://github.com/AARNAV-ARYA/LogiRush/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev)
[![Expo](https://img.shields.io/badge/Expo-SDK%2057-000020?style=flat&logo=expo&logoColor=white)](https://expo.dev)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

### 🌐 Live Deployment

| Service | URL | Status |
|---|---|---|
| **Control-Room Console** | [logirush-console.onrender.com](https://logirush-console.onrender.com) | [![Uptime](https://img.shields.io/badge/status-live-brightgreen)](https://logirush-console.onrender.com/health) |
| **Backend API** | [logirush-console.onrender.com/health](https://logirush-console.onrender.com/health) | [![API](https://img.shields.io/badge/API-REST-blue)](https://logirush-console.onrender.com/health) |
| **Field App** | Expo Go — scan QR in [DEPLOY.md](DEPLOY.md) | React Native · iOS · Android |

> **Demo credentials** — `controller` / `control123` · `verifier.as` / `verify123`  
> These are published demo accounts for evaluation. See [DEPLOY.md](DEPLOY.md) before any production rollout.

---

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/AARNAV-ARYA/LogiRush)
&nbsp;
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FAARNAV-ARYA%2FLogiRush&root-directory=routeOptimiserFrontend&project-name=logirush&env=VITE_API_BASE_URL&envDescription=URL%20of%20your%20deployed%20backend%2C%20no%20trailing%20slash)

</div>

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Running the Full Stack](#running-the-full-stack)
- [Testing](#testing)
- [Deployment](#deployment)
- [Data & Disclaimers](#data--disclaimers)
- [Contributing](#contributing)

---

## Overview

LogiRush is built for **Smart India Hackathon 2026** — a full-stack platform addressing disaster-resilient logistics across the eight states of India's North Eastern Region (NER). Landslides, floods, and extreme rainfall routinely disrupt road corridors here; LogiRush gives control rooms and field teams the shared situational awareness to respond.

The core insight is simple: **a report filed on a phone must immediately reach the review queue the control room is watching**. That entire link is one matching URL in each client.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        LogiRush Platform                      │
├─────────────────┬───────────────────────┬────────────────────┤
│  Control-Room   │      Backend API       │   Field Reporter   │
│    Console      │                        │       App          │
│                 │   Flask · SQLAlchemy   │                    │
│  React 18       │   scikit-learn         │  Expo SDK 57       │
│  Vite · Leaflet │   NetworkX · gunicorn  │  React Native      │
│  Tailwind CSS   │                        │  expo-router       │
│                 │   PostgreSQL / SQLite  │  AsyncStorage      │
│  Vercel         │   Render               │  Expo Go / EAS     │
└─────────────────┴───────────────────────┴────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │      One Database          │
              │   (Neon · PostgreSQL)      │
              │                            │
              │  incidents · shipments     │
              │  users · audit_trail       │
              └────────────────────────────┘
```

```
Data Flow

Open-Meteo (live rainfall)
        │
        ▼
 Weather Provider ──► Accessibility Engine ──► A* Router
        │                      │                    │
        │              Disaster Prediction           │
        │               (Random Forest)              │
        ▼                      ▼                    ▼
   NER Routes API ◄──────────────────────────────────
        │
        ├──► React Console  (dashboard · map · planner · review queue)
        └──► React Native   (GPS report · photo · offline queue)
```

---

## Features

### Routing & Intelligence
- **Risk-aware A\* routing** — multi-objective with Pareto pruning over the NER corridor graph, weighted by cargo profile (medicines, food, fuel, general) and urgency
- **Accessibility scoring** — deterministic, auditable formula applied per corridor:  
  `score = 100 − (0.25·weather + 0.30·landslide + 0.20·flood + 0.15·incident + 0.10·delay)`
- **Disaster prediction** — explainable Random Forest predicting corridor disruption probability; the only ML component

### Live Data
- **Real rainfall** from Open-Meteo read at each corridor's midpoint, feeding the disaster model and accessibility scores in real time. Falls back to a shipped snapshot on failure and reports which one is active
- **OpenStreetMap place search** via Photon and Overpass for origin/destination lookup (ODbL attribution in every response)

### Incident Lifecycle
- **Community reporting** — anyone may file a report with GPS coordinates and a photograph, with or without an account
- **Human verification with dual countersign** — closing a corridor requires two independent verifiers, each within their jurisdiction. Single accounts cannot act alone — by design
- **Immutable audit trail** — every decision is appended, never overwritten

### Resilience
- **Offline-first field app** — reports queue on-device via AsyncStorage and sync idempotently on reconnect using a client-generated UUID. A replayed submission never duplicates a landslide report
- **Schema reconciliation** — tables are created or updated at startup; no manual migration step on upgrade

---

## Project Structure

```
LogiRush/
├── routeOptimiserBackend/       # Flask API
│   ├── src/
│   │   ├── api/                 # Blueprints: auth, NER routes, shipments
│   │   ├── data_processing/     # Weather provider, graph builder, data sources
│   │   ├── db/                  # SQLAlchemy models, session, roster, schema sync
│   │   ├── modeling/            # Accessibility engine, cargo profiles, RF prediction
│   │   ├── optimization/        # Multi-objective A*, NER router
│   │   └── services/            # Service layer
│   ├── data/
│   │   ├── raw/ner/             # NER locations, road segments, segment features (CSV)
│   │   └── processed/models/    # Persisted Random Forest models (.joblib)
│   ├── main.py                  # Entry point
│   ├── requirements.txt
│   └── Dockerfile
│
├── routeOptimiserFrontend/      # React control-room console
│   ├── src/
│   │   ├── components/          # Map, dashboard widgets, planner, incident queue
│   │   └── pages/               # Route views
│   ├── vite.config.js
│   └── vercel.json
│
├── nerFieldApp/                 # Expo React Native field app
│   ├── app/                     # expo-router screens
│   │   ├── index.jsx            # Home
│   │   ├── signin.jsx           # Auth + connection test
│   │   ├── reports.jsx          # Filed reports
│   │   └── nearby.jsx           # Nearby incidents
│   └── src/lib/                 # API client, offline queue, theme
│
├── nerLogisticsPlugin/          # Claude Code MCP plugin
│   └── mcp/server.py
│
├── e2e/                         # End-to-end tests (Playwright)
├── docker-compose.yml           # Full local stack (Postgres + backend)
├── render.yaml                  # Render deploy blueprint
└── .github/workflows/ci.yml     # CI: backend tests + frontend build + E2E
```

---

## Getting Started

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Expo CLI | via `npx` |

### Clone

```bash
git clone https://github.com/AARNAV-ARYA/LogiRush.git
cd LogiRush
```

---

## Running the Full Stack

### 1 — Backend

```bash
cd routeOptimiserBackend
pip install -r requirements.txt
python seed_demo_data.py      # optional: loads demo incidents and shipments
python main.py                # → http://localhost:5001
```

Health check: `curl http://localhost:5001/health`  
Expected: `{"status":"ok","service":"logirush-ner-platform"}`

### 2 — Console (web)

```bash
cd routeOptimiserFrontend
npm install
echo "VITE_API_BASE_URL=http://localhost:5001" > .env
npm run dev                   # → http://localhost:5173
```

### 3 — Field App (mobile)

Find your LAN IP: `ipconfig getifaddr en0` (macOS) or `hostname -I` (Linux).

```bash
cd nerFieldApp
npm install
echo "EXPO_PUBLIC_API_BASE_URL=http://<your-lan-ip>:5001" > .env
npx expo start                # scan QR with Expo Go on your phone
```

The API base URL is also editable per-device on the **Sign in → Settings** screen without restarting.

### Full stack with Docker (Postgres)

```bash
docker compose up --build
docker compose exec backend python seed_demo_data.py
```

The frontend is not containerised — run it with `npm run dev` pointed at `http://localhost:5001`.

---

## Environment Variables

### Backend (`routeOptimiserBackend/.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Production | SQLite fallback | PostgreSQL connection string |
| `CORS_ORIGINS` | Production | `*` | Comma-separated allowed origins |
| `NER_DISABLE_DEMO_SEED` | Public deploy | unset | Set `1` to skip seeding demo accounts |
| `PORT` | No | `5001` | HTTP port |
| `MAX_CONTENT_MB` | No | `16` | Max request body (reports carry photos) |
| `NER_LIVE_WEATHER` | No | on | Set `0` to pin shipped rainfall snapshot |
| `WEATHER_CACHE_TTL_S` | No | `900` | Rainfall cache window (seconds) |
| `WEATHER_TIMEOUT_S` | No | `4.0` | Rainfall fetch timeout before fallback |
| `FLASK_DEBUG` | No | off | Set `1` for development reloader |

### Console (`routeOptimiserFrontend/.env`)

| Variable | Required | Description |
|---|---|---|
| `VITE_API_BASE_URL` | Yes | Backend URL — baked at build time |

### Field App (`nerFieldApp/.env`)

| Variable | Required | Description |
|---|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | Yes | Backend URL — bundled at build time |

---

## Testing

```bash
# Backend — 165 unit + integration tests
cd routeOptimiserBackend && python -m pytest

# Frontend — production build check
cd routeOptimiserFrontend && npm run build

# E2E — requires both servers running
python e2e/test_e2e.py \
  --base-url http://127.0.0.1:4173 \
  --api-url http://127.0.0.1:5001
```

CI runs all three on every push via [`.github/workflows/ci.yml`](.github/workflows/ci.yml), including a real Playwright browser against a live backend.

---

## Deployment

Full walkthrough: [DEPLOY.md](DEPLOY.md)

### Quick path

```
Neon (Postgres)  →  Render (backend)  →  Vercel (console)  →  Expo Go / EAS (field app)
```

**1. Database** — create a free Postgres instance on [neon.tech](https://neon.tech). Copy the connection string.

**2. Backend → Render**

Click **Deploy to Render** above. Set:
- `DATABASE_URL` — Neon connection string
- `CORS_ORIGINS` — your Vercel URL
- `NER_DISABLE_DEMO_SEED` — `1` for any public deployment

**3. Console → Vercel**

Click **Deploy with Vercel** above. Set root directory to `routeOptimiserFrontend` and `VITE_API_BASE_URL` to your Render URL.

**4. Field app**

```bash
cd nerFieldApp
echo "EXPO_PUBLIC_API_BASE_URL=https://<your-render-service>.onrender.com" > .env
npx expo start
# or build a standalone APK / IPA:
eas build --platform android --profile preview
```

> **Security note:** `seed_users.py` ships demo accounts with passwords in this repository. Set `NER_DISABLE_DEMO_SEED=1` and provision a real roster before any public deployment. See [DEPLOY.md § Read this before deploying publicly](DEPLOY.md#2-backend--render).

---

## Data & Disclaimers

| Component | Status |
|---|---|
| Accessibility formula & scoring | ✅ Real, deterministic, unit-tested |
| Risk-aware A\* routing | ✅ Real working algorithm |
| Incident reporting & verification lifecycle | ✅ Real, database-backed |
| **Rainfall** | ✅ **Live** — Open-Meteo (not an IMD product) |
| NER road network | ⚠️ Sample data — real corridor names, hand-built topology |
| Landslide / flood risk figures | ⚠️ Synthetic — not from GSI, CWC, NDMA or ASDMA |
| Disaster prediction model | ⚠️ Real Random Forest, trained on synthetic data |

Every API response carries `"data_source"` provenance. The dashboard shows the model's training origin inline. Do not present any figure from this system as official government data.

Place search uses OpenStreetMap via Photon and Overpass. OSM data is [ODbL-licensed](https://www.openstreetmap.org/copyright); attribution is carried in every response.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "feat: description"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

Please run `python -m pytest` and `npm run build` before submitting.

---

<div align="center">

Built for **Smart India Hackathon 2026** · Eight states · One platform · Zero duplicated landslides

[Live Demo](https://logirush-console.onrender.com) · [API Health](https://logirush-console.onrender.com/health) · [Deploy Guide](DEPLOY.md) · [Engineering Docs](NER_PLATFORM.md)

</div>
