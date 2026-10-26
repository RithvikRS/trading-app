import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const contentPolicy = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'"
const headers = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'static-content-policy',
      apply: 'build',
      transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: contentPolicy }, injectTo: 'head-prepend' }],
    },
  ],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    allowedHosts: ['localhost'],
    cors: { origin: /^http:\/\/(127\.0\.0\.1|localhost):5173$/ },
    fs: { strict: true, allow: [fileURLToPath(new URL('.', import.meta.url))] },
    headers: { ...headers, 'Content-Security-Policy': contentPolicy.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'").replace("connect-src 'self'", "connect-src 'self' ws://127.0.0.1:5173 ws://localhost:5173") + "; frame-ancestors 'none'" },
  },
  preview: {
    host: '127.0.0.1', port: 4173, strictPort: true,
    allowedHosts: ['localhost'],
    headers: { ...headers, 'Content-Security-Policy': contentPolicy + "; frame-ancestors 'none'" },
  },
  build: { sourcemap: false },
  test: {
    environment: 'jsdom', setupFiles: './src/test/setup.ts', restoreMocks: true,
    pool: process.platform === 'win32' ? 'threads' : 'forks',
    isolate: true, maxWorkers: 1,
  },
})
