// Shared flat config for every app and package in the workspace.
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import supportx from './packages/eslint-plugin/index.js';

export default tseslint.config(
  // schema.ts is generated from the OpenAPI contract by openapi-typescript (D-022).
  { ignores: ['**/dist/**', '**/coverage/**', 'packages/api-client/src/schema.ts'] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        // vite.chunks.ts is shared by both apps' vite configs and belongs to no tsconfig.
        projectService: { allowDefaultProject: ['vite.chunks.ts'] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
    },
  },
  {
    // Labels, not enums (architecture.md §9.5, CLAUDE.md rule d): no raw codes and no
    // hard-coded text on screen. Tests may use literal strings to build fixtures.
    files: ['apps/**/*.tsx', 'packages/**/*.tsx'],
    ignores: ['**/*.test.tsx', '**/test/**'],
    plugins: { supportx },
    rules: {
      'supportx/no-raw-enum': 'error',
      'supportx/no-literal-text': 'error',
    },
  },
  {
    // Plain JS config files are not part of any tsconfig project.
    files: ['**/*.js'],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
);
