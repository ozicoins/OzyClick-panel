import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev'de /api, /ws ve /health backend'e proxy'lenir → frontend ile API same-origin
// olur ve httpOnly cookie sorunsuz çalışır. host: 'localhost' → yalnızca yerel arayüz.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: 'localhost',
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
});
