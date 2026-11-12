import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

// The rich-text editor (@tiptap/react) destroys itself on a 1 ms timer after unmount. Let that
// timer run here, while jsdom's window still exists: otherwise it can fire after the test file's
// environment is torn down ("window is not defined", an unhandled error that fails the whole
// run although every test passed; it dropped #249 from the merge queue). A test that left fake
// timers on has its pending ones run first and gets real timers back (lane A), so the flake
// cannot return through it.
async function settleEditors(): Promise<void> {
  if (vi.isFakeTimers()) {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  }
  await new Promise((resolve) => setTimeout(resolve, 5));
}

afterEach(async () => {
  cleanup();
  await settleEditors();
});

// Pages are lazy routes: the first test of a file also waits for the page module to be
// transformed, which takes over the default 1 s `findBy` budget on a cold CI runner (as in the
// console; the #178 merge-queue run failed on it).
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

// jsdom has no scrolling: a page that scrolls a field into view (a refused save naming it,
// QA10-P3-08) threw "scrollIntoView is not a function" as an unhandled error, failing every
// frontend run on main although the tests passed. A no-op is enough in tests.
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => undefined;
}

// A UI language remembered by one test's session never starts the next test's app (V-01).
afterEach(() => {
  window.localStorage.removeItem('supportx.locale');
});
