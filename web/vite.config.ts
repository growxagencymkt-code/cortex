import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// CORTEX web frontend. The FastAPI backend (§5) runs on :8000.
// /api/* and /health are proxied there so the SPA never makes cross-origin calls.
// Override the target with CORTEX_API_TARGET in a .env file if the API lives elsewhere.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'CORTEX_');
  const apiTarget = env.CORTEX_API_TARGET || 'http://localhost:8000';

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/health': { target: apiTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  };
});
