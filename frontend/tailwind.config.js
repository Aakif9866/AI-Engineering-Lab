/** Design language: ~/.claude/skills/frontend-design-aesthetic (Klyro-derived).
 * teal = the one workhorse accent; indigo->purple->pink gradient = brand + one primary CTA per screen;
 * ink.* = near-black elevation ladder for dark mode (page / card / popover). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: { ink: { page: "#0a0a0a", card: "#141414", pop: "#1c1c1c" } },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "none" } },
      },
      animation: { rise: "rise 400ms ease-out both" },
    },
  },
  plugins: [],
};
