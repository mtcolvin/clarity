import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // The published static demo is served from a SUBPATH on GitHub Pages
  // (https://<user>.github.io/<repo>/), so root-absolute asset URLs like
  // /assets/index.js would resolve against the domain root and 404 — a blank page, with
  // nothing in the UI to suggest why. './' makes every emitted URL relative, which works
  // at the domain root, in a subdirectory, and from a file:// checkout alike.
  // Unchanged for dev and the normal build.
  base: mode === 'static' ? './' : '/',
}))
