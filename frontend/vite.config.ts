import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: '.',           // Project root is /frontend
  publicDir: 'public', // PWA manifest and icons live here
  build: {
    outDir: 'dist',    // Vercel serves from here
    emptyOutDir: true,
    // Output as a single JS and single CSS file for maximum caching efficiency
    rollupOptions: {
      input: resolve(__dirname, 'index.html'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Proxy API calls to the Python backend during local development
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
