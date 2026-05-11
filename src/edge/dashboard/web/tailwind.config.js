/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Slightly warmer dark palette so this doesn't feel like a generic
        // Tailwind admin template.
        ink: {
          950: "#0b0f14",
          900: "#11161c",
          800: "#1a212a",
          700: "#252e39",
          600: "#34404e",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
