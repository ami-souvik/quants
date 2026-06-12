import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Fontshare-inspired dark palette
        bg:       "#0f0f0f",
        surface:  "#181818",
        surface2: "#222222",
        border:   "#2a2a2a",
        "border-light": "#222222",
        text:     "#f0f0f0",
        muted:    "#666666",
        subtle:   "#999999",
        accent:   "#c8c0a8",   // warm beige — active/highlight state
        "accent-fg": "#111111", // text on accent background
      },
      fontFamily: {
        sans: ["'Inter'", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["'JetBrains Mono'", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
