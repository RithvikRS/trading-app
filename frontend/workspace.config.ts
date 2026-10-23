import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { assertProtectedModules } from './workspace-boundary.ts'

const root = fileURLToPath(new URL('./workspace', import.meta.url))
const demo = fileURLToPath(new URL('./src', import.meta.url)).replaceAll('\\', '/')

export default defineConfig({
  root, publicDir: false, envPrefix: [],
  plugins: [react(), {
    name: 'protected-build-boundary',
    generateBundle() {
      assertProtectedModules(this.getModuleIds(), demo)
    },
  }],
  build: { sourcemap: false, assetsInlineLimit: 0 },
})
