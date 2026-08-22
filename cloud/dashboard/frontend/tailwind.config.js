/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "../backend/app/static/components/**/*.{js,jsx}",
    "../backend/app/static/assets/**/*.{js,html}",
    "./cloud/dashboard/frontend/index.html",
    "./cloud/dashboard/frontend/src/**/*.{js,ts,jsx,tsx}",
    "./cloud/dashboard/backend/app/static/components/**/*.{js,jsx}",
    "./cloud/dashboard/backend/app/static/assets/**/*.{js,html}",
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
