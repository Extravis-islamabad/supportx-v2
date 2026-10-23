import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

afterEach(() => {
  cleanup();
});

// jsdom has no matchMedia; Ant Design's responsive utilities need it. Left untyped on purpose:
// the legacy addListener/removeListener pair is still called by some Ant Design internals.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

// No realtime gateway in unit tests: the realtime package has its own tests with a fake client.
setDefaultClientFactory(inertClientFactory);
