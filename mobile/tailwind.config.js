/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        surface: '#0f172a',
        panel: '#1e293b',
        border: '#334155',
        muted: '#64748b',
        text: '#f1f5f9',
        accent: '#3b82f6',
        danger: '#ef4444',
        warn: '#f59e0b',
        ok: '#22c55e',
      },
    },
  },
  plugins: [],
};
