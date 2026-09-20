import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'probe/.out']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    // The smoke probe (npm run smoke) is a Node script that BUILDS a browser environment
    // rather than running in one, so it legitimately uses both global sets — and it assigns
    // to browser globals (window, document, ResizeObserver) on purpose, which the browser
    // config reads as redefining a read-only global. It also isn't a React component module,
    // so react-refresh's component-export rule doesn't apply.
    files: ['probe/**/*.{js,jsx}'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: {
      'no-global-assign': 'off',
      'react-refresh/only-export-components': 'off',
    },
  },
])
