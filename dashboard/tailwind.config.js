/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui"],
        display: ['"Space Grotesk"', "ui-sans-serif", "system-ui"],
      },
      colors: {
        midnight: "#081120",
        aurora: "#5eead4",
        ember: "#fb7185",
        slateglass: "rgba(15, 23, 42, 0.72)",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(94, 234, 212, 0.18), 0 20px 40px rgba(8, 17, 32, 0.45)",
      },
    },
  },
  plugins: [],
};
