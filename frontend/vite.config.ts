import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
// Note: Vite uses tsconfig.app.json (ESNext module) for compilation.
// tsconfig.json (commonjs) is kept for Jest / ts-jest.

const LAMBDA_URL = 'https://l7xnpjosjvyrlx55dxrwdvx5g40okeyd.lambda-url.us-east-1.on.aws';
const FRONTEND_URL = 'http://airbrake.s3-website-us-east-1.amazonaws.com';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget      = env.VITE_API_BASE_URL  || LAMBDA_URL;
  const frontendTarget = env.VITE_FRONTEND_URL  || FRONTEND_URL;

  return {
    base: '/',
    plugins: [react()],
    resolve: {
      alias: {
        '@portal/shared': path.resolve(__dirname, '../shared/src/index.ts'),
      },
    },
    build: {
      emptyOutDir: true, // Clean dist before build to remove any stale files
    },
    // Inject API base URL as a build-time constant — works in both Vite and Jest
    define: {
      __API_BASE_URL__:      JSON.stringify(apiTarget),
      __FRONTEND_BASE_URL__: JSON.stringify(frontendTarget),
    },
    // Tell Vite to use the ESNext tsconfig for type-checking
    esbuild: {
      tsconfigRaw: { extends: './tsconfig.app.json' },
    },
    server: {
      port: 3000,
      host: '0.0.0.0',
      proxy: {
        // REST API — proxied to Lambda (avoids CORS issues in local dev)
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: true,
        },
        // WebSocket — proxied to Lambda (if Lambda supports WS)
        '/ws': {
          target: apiTarget.replace(/^https/, 'wss').replace(/^http/, 'ws'),
          ws: true,
          changeOrigin: true,
          secure: true,
        },
      },
    },
  };
});
