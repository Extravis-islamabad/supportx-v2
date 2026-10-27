import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

afterEach(() => {
  cleanup();
  // Forms keep what was typed in session storage (useKeptDraft): never into the next test.
  window.sessionStorage.clear();
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

// jsdom has no layout: the rich-text editor (ProseMirror) measures the caret when it scrolls to
// an insertion (templates, typed text). Empty rectangles are enough for tests.
const noRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] });
for (const proto of [Range.prototype, Element.prototype, Text.prototype] as object[]) {
  Object.assign(proto, {
    getClientRects: noRects,
    getBoundingClientRect: () => new DOMRect(0, 0, 0, 0),
  });
}
