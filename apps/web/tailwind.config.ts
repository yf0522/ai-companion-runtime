import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        border: "var(--border)",
        primary: "var(--primary)",
        signal: "var(--signal)",
        human: "var(--human)",
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
      },
    },
  },
  plugins: [],
};
export default config;
