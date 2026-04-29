/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      colors: {
        background: '#FFFFFF',
        surface: '#F8FAFC',
        surfaceHover: '#F1F5F9',
        border: '#E2E8F0',
        textPrimary: '#0F172A',
        textSecondary: '#64748B',
        primary: '#10B981',
        primaryLight: '#D1FAE5',
      },
    },
  },
  plugins: [],
};
