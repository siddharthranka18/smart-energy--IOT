import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxy = {
    '/api': {
      target: process.env.ENERGY_API_URL || env.ENERGY_API_URL || 'http://127.0.0.1:8000',
      rewrite: (path) => path.replace(/^\/api/, ''),
    },
  };
  return { server: { proxy }, preview: { proxy } };
});
