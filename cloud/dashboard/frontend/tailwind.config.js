/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./cloud/dashboard/frontend/index.html",
    "./cloud/dashboard/frontend/src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        slate: {
          950: '#020617',
        },
        emerald: {
          500: '#10b981',
          600: '#059669',
        }
      }
    },
  },
  plugins: [],
}
