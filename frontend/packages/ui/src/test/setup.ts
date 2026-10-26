import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

afterEach(() => {
  cleanup();
});

// The rich-text editor loads lazily and ProseMirror is slow in jsdom on a busy runner: waits get
// the same 5 s as the console's app tests (apps/console/src/test/setup.ts).
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

// jsdom has no clipboard; "Copy reference" writes to it.
Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: { writeText: () => Promise.resolve() },
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
