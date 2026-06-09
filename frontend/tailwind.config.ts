import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0a0c10",
        panel: "#11151c",
        panel2: "#161b24",
        edge: "#1f2733",
        edge2: "#2a3442",
        ink: "#e8edf2",
        body: "#b7c1cd",
        muted: "#6b7686",
        signal: "#f5b642", // amber accent
        ok: "#5ad19a",
        warn: "#f5b642",
        danger: "#ef6b6b",
        info: "#5cc8e6",
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      keyframes: {
        blink: { "0%,49%": { opacity: "1" }, "50%,100%": { opacity: "0" } },
        rise: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseDot: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        blink: "blink 1.1s step-end infinite",
        rise: "rise 0.3s ease-out both",
        pulseDot: "pulseDot 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
