// The mobile app's lint: the web workspace's rules (frontend/eslint.config.js) on React Native.
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import supportx from '../frontend/packages/eslint-plugin/index.js';

export default tseslint.config(
  { ignores: ['node_modules/**', 'android/**', 'ios/**', '.expo/**', 'coverage/**'] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      globals: { ...globals.browser, __DEV__: 'readonly' },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    // Labels, not enums (architecture.md §9.5, CLAUDE.md rule d): no raw codes and no
    // hard-coded text on screen. Tests may use literal strings to build fixtures.
    files: ['**/*.tsx'],
    ignores: ['**/*.test.tsx'],
    plugins: { supportx },
    rules: { 'supportx/no-raw-enum': 'error', 'supportx/no-literal-text': 'error' },
  },
  {
    // Plain JS config files (Metro, Jest) are CommonJS and part of no tsconfig project.
    files: ['**/*.{js,mjs}'],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.js'],
    languageOptions: { sourceType: 'commonjs' },
    rules: { '@typescript-eslint/no-require-imports': 'off' },
  },
);
