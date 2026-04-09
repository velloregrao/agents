/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       '#0F1117',
        surface:  '#1A1D27',
        border:   '#2A2D3A',
        accent:   '#3B82F6',
        positive: '#22C55E',
        negative: '#EF4444',
        warning:  '#F59E0B',
        muted:    '#6B7280',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Menlo', 'JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
