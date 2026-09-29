/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 三档缺口的语义色，图表与卡片共用，避免同一种含义出现两种颜色
        must: '#dc2626',
        should: '#f59e0b',
        nice: '#0ea5e9',
        have: '#10b981',
        brand: '#4f46e5',
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          '"Segoe UI"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}
