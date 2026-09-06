import { Suspense, lazy } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import AppShell from "./components/AppShell";
import { AuthProvider } from "./context/AuthContext";
import { SyncProvider } from "./context/SyncContext";
import Home from "./pages/Home";

/*
  Route-level code splitting.

  Every page used to be imported at the top of this file, so opening the site downloaded the
  whole platform before it could draw anything: Leaflet and its CSS, Recharts, the planner,
  the review queue. On a field connection — the connection this product is actually for —
  that is a long stare at a blank page to read a landing page that needs none of it.

  Home stays eagerly imported because it is the first thing most people see and splitting it
  would only add a round trip. Everything else arrives when its route does, which puts the
  two heavy libraries behind the two screens that genuinely need them: Recharts loads with
  the dashboard, Leaflet with the map.

  Vite emits one chunk per lazy import and preloads a chunk's dependencies alongside it, so
  navigation costs one request, not a waterfall.
*/
const About = lazy(() => import("./pages/About"));
const Contact = lazy(() => import("./pages/Contact"));
const Login = lazy(() => import("./pages/Login"));
const Signup = lazy(() => import("./pages/Signup"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const AccessibilityMap = lazy(() => import("./pages/AccessibilityMap"));
const ShipmentPlanner = lazy(() => import("./pages/ShipmentPlanner"));
const Shipments = lazy(() => import("./pages/Shipments"));
const Incidents = lazy(() => import("./pages/Incidents"));
const ReportIncident = lazy(() => import("./pages/ReportIncident"));
const DataSources = lazy(() => import("./pages/DataSources"));

/* Shown only while a route's chunk is in flight. It deliberately holds the layout's height
   rather than collapsing it, so arriving content does not shove the page around. */
const RouteFallback = () => (
  <div className="max-w-6xl mx-auto px-4 py-8" role="status" aria-live="polite">
    <span className="sr-only">Loading…</span>
    <div className="h-8 w-52 skeleton rounded-lg" />
    <div className="h-64 mt-4 skeleton rounded-xl" />
  </div>
);

const App = () => (
  <Router>
    <AuthProvider>
      <SyncProvider>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[2000] focus:bg-accent focus:px-3 focus:py-2 focus:rounded focus:font-medium"
          style={{ color: "var(--bg-contrast)" }}
        >
          Skip to content
        </a>
        <AppShell>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              {/* NER Logistics Intelligence Platform (SIH) */}
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/accessibility-map" element={<AccessibilityMap />} />
              <Route path="/shipment-planner" element={<ShipmentPlanner />} />
              <Route path="/shipments" element={<Shipments />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/report-incident" element={<ReportIncident />} />
              <Route path="/data-sources" element={<DataSources />} />

              {/* Original cross-border route selector, unchanged */}
              <Route path="/" element={<Home />} />
              <Route path="/about" element={<About />} />
              <Route path="/contact" element={<Contact />} />
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
            </Routes>
          </Suspense>
        </AppShell>
      </SyncProvider>
    </AuthProvider>
  </Router>
);

export default App;
