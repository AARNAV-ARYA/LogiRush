import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Pre-bundle the heavy dependencies once at start-up instead of discovering them
    // mid-navigation. Without this the first visit to the map or the dashboard stalls while
    // Vite optimises Leaflet or Recharts on demand and then reloads the page.
    warmup: {
      clientFiles: ['./src/main.jsx', './src/App.jsx', './src/pages/Home.jsx'],
    },
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'leaflet', 'react-leaflet'],
  },
  build: {
    // Source maps cost build time and ship a second copy of the app; nothing here needs
    // them in production.
    sourcemap: false,
    rollupOptions: {
      output: {
        /*
          Three vendor chunks rather than one.

          Leaflet is the bulk of this application's third-party JavaScript and is needed by
          exactly two screens. Split out, it is fetched only by the routes that import it
          and — because its contents change only when the dependency is upgraded — stays in
          the browser cache across every deploy that touches application code. React gets the
          same treatment for the same reason.

          (The charts are hand-written SVG, on purpose: see components/charts.jsx. Recharts
          and lucide-react were listed as dependencies but imported by nothing, which cost
          37 MB of install and a pre-bundling pass on every dev start to ship no bytes.)
        */
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          leaflet: ['leaflet', 'react-leaflet'],
        },
      },
    },
  },
})
