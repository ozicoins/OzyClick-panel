/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // OzyClick teması — SİYAH zemin + YEŞİL yazı/çizgi/aksan (terminal). Arka planlar NÖTR siyah
        // (yeşil tint YOK — "çok yeşil" olmasın); yeşil sadece metin/kenarlık/vurguda.
        iuNavy: '#0a0a0a',        // ana yüzey — near-black (nötr)
        iuGold: '#2ee66b',        // birincil AKSAN/metin — terminal yeşili
        iuGoldHover: '#25c95c',
        iuGoldLight: '#7bf0a5',
        iuDark: '#050505',        // en derin zemin — siyah
        iuCard: '#0d0d0d',        // kart yüzeyi — near-black
        iuBorder: '#1d4d30',      // YEŞİL çizgi/kenarlık (görünür)
        iuTeal: '#14b8a6',        // ikincil yeşil-teal
        iuAccent: '#34d399',      // emerald vurgusu
        // Metinler yeşil-tonlu olsun diye slate gri skalası yeşile kaydırıldı (bileşenler text-slate-*
        // kullanıyor → tek yerden hepsi yeşil-yazı olur). bg-slate kullanımı yok denecek kadar az.
        slate: {
          200: '#cdeed8',
          300: '#a6dcb8',
          400: '#77b892',
          500: '#547f65',
          600: '#3a5a47',
          700: '#2a4234',
        },
      },
      fontFamily: {
        heading: ['Outfit', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        gold: '0 0 26px rgba(46, 230, 107, 0.18)',
        'gold-strong': '0 8px 30px -8px rgba(46, 230, 107, 0.45)',
        card: 'inset 0 1px 0 0 rgba(255,255,255,0.045), 0 12px 34px -14px rgba(0,0,0,0.7)',
      },
      backgroundImage: {
        'gold-gradient': 'linear-gradient(135deg, #4dff8f 0%, #2ee66b 55%, #22c55e 100%)',
      },
      animation: {
        'fade-up': 'fade-up 0.45s cubic-bezier(0.2,0.7,0.3,1) both',
        'fade-in': 'fade-in 0.5s ease both',
      },
      keyframes: {
        'fade-up': { from: { opacity: '0', transform: 'translateY(10px)' }, to: { opacity: '1', transform: 'none' } },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
      },
    },
  },
  plugins: [],
}
