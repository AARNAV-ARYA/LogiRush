/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      // Tokens live as CSS variables in index.css so the map, charts, badges and tables
      // physically cannot disagree about what a colour means.
      //
      // Each is wired through `rgb(var(--x-rgb) / <alpha-value>)` rather than a bare
      // `var(--x)`. That placeholder is what lets Tailwind produce a valid colour for an
      // opacity modifier: with a finished colour it emits an invalid declaration and
      // `bg-accent/10` renders as nothing at all.
      colors: {
        plane: "rgb(var(--plane-rgb) / <alpha-value>)",
        surface: {
          DEFAULT: "rgb(var(--surface-rgb) / <alpha-value>)",
          raised: "rgb(var(--surface-raised-rgb) / <alpha-value>)",
          sunken: "rgb(var(--surface-sunken-rgb) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink-rgb) / <alpha-value>)",
          secondary: "rgb(var(--ink-secondary-rgb) / <alpha-value>)",
          muted: "rgb(var(--ink-muted-rgb) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent-rgb) / <alpha-value>)",
          dim: "rgb(var(--accent-dim-rgb) / <alpha-value>)",
        },
        imp: {
          1: "rgb(var(--imp-1-rgb) / <alpha-value>)",
          2: "rgb(var(--imp-2-rgb) / <alpha-value>)",
          3: "rgb(var(--imp-3-rgb) / <alpha-value>)",
          4: "rgb(var(--imp-4-rgb) / <alpha-value>)",
          5: "rgb(var(--imp-5-rgb) / <alpha-value>)",
        },
        status: {
          good: "rgb(var(--status-good-rgb) / <alpha-value>)",
          warning: "rgb(var(--status-warning-rgb) / <alpha-value>)",
          serious: "rgb(var(--status-serious-rgb) / <alpha-value>)",
          critical: "rgb(var(--status-critical-rgb) / <alpha-value>)",
        },
        series: {
          1: "rgb(var(--series-1-rgb) / <alpha-value>)",
          2: "rgb(var(--series-2-rgb) / <alpha-value>)",
          3: "rgb(var(--series-3-rgb) / <alpha-value>)",
          4: "rgb(var(--series-4-rgb) / <alpha-value>)",
        },
      },
      borderColor: { DEFAULT: "var(--hairline)" },
    },
  },
  plugins: [],
};
