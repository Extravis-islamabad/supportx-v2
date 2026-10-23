import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

afterEach(() => {
  cleanup();
});

// Pages are lazy routes: the first test of a file also waits for the page module to be
// transformed, which takes over the default 1 s `findBy` budget on a cold CI runner.
configure({ asyncUtilTimeout: 5000 });

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
