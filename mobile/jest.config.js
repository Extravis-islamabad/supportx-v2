// jest-expo runs the app's tests on the React Native preset (Vitest has no proper RN support,
// docs/architecture/mobile.md).
const path = require('node:path');

/** @type {import('jest').Config} */
module.exports = {
  preset: 'jest-expo',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  // One copy of every library, the app's (see jest.resolver.js).
  resolver: '<rootDir>/jest.resolver.js',
  moduleNameMapper: {
    // openapi-fetch's default entry is ESM (.mjs), which the preset does not transform.
    '^openapi-fetch$': path.join(__dirname, 'node_modules/openapi-fetch/dist/index.cjs'),
  },
  // The first test of a file also pays for loading React Native.
  testTimeout: 20_000,
  testPathIgnorePatterns: ['/node_modules/', '/android/', '/ios/'],
};
