import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ApiError } from '@supportx/api-client';
import { problem } from '@supportx/api-client/testing';
import { en, label, type Locale } from '@supportx/labels';

import { AppearanceProvider } from './AppearanceProvider';
import { describeError, ErrorReporterProvider, markHandled, reportError } from './errors';

// WP-029-FIX: the WP-029 QA report's findings in the shared error handling, named after IDs.

const REFUSED = new ApiError(
  422,
  problem(422, 'rule_refused', {
    params: {
      rule: 'Printers need a site',
      message: 'Pick the site the printer is at.',
      message_ar: 'اختر موقع الطابعة.',
      message_ur: 'پرنٹر کی جگہ منتخب کریں۔',
    },
  }),
  'req-1',
);

const translate = (locale: Locale) => (key: string, params?: Record<string, unknown>) =>
  label(key, locale, params as never);

describe('BUG-01: error labels are filled from the problem params', () => {
  it.each([
    ['en', 'Pick the site the printer is at.'],
    ['ar', 'اختر موقع الطابعة.'],
    ['ur', 'پرنٹر کی جگہ منتخب کریں۔'],
  ] as const)('BUG-01: a rule refusal in %s reads the rule message', (locale, text) => {
    expect(describeError(REFUSED, translate(locale)).title).toBe(text);
  });

  it('BUG-01: every error label with a placeholder is filled for any code, not a named list', () => {
    const placeholder = /\{\{\s*(\w+)\s*\}\}/g;
    const unfilled: string[] = [];
    for (const [key, text] of Object.entries(en)) {
      if (!key.startsWith('errors.') || key.startsWith('errors.field.')) continue;
      const names = [...text.matchAll(placeholder)].map((m) => m[1] ?? '');
      if (names.length === 0) continue;
      const params = Object.fromEntries(names.map((n) => [n, `<${n}>`]));
      const code = key.slice('errors.'.length);
      const error = new ApiError(400, problem(400, code, { message_key: key, params }), null);
      const title = describeError(error, translate('en')).title;
      if (title.includes('{{') || names.some((n) => !title.includes(`<${n}>`))) unfilled.push(key);
    }
    expect(unfilled).toEqual([]);
  });
});

function toasts(): Element[] {
  return [...document.querySelectorAll('.ant-notification-notice')];
}

function Reporter() {
  return (
    <AppearanceProvider>
      <ErrorReporterProvider>
        <span>ready</span>
      </ErrorReporterProvider>
    </AppearanceProvider>
  );
}

describe('BUG-02: expected refusals are not error toasts', () => {
  afterEach(() => {
    for (const toast of toasts()) toast.remove();
  });

  it('BUG-02: an unhandled refusal is a neutral notice, without "Copy reference"', async () => {
    render(<Reporter />);
    await screen.findByText('ready');
    act(() => {
      reportError(REFUSED);
    });
    await waitFor(() => {
      expect(toasts()).toHaveLength(1);
    });
    const [toast] = toasts();
    expect(toast?.className).not.toContain('error');
    expect(toast?.getAttribute('role')).not.toBe('alert');
    expect(toast?.textContent).toContain('Pick the site the printer is at.');
    expect(toast?.textContent).not.toContain('Copy reference');
  });

  it('BUG-02: a real failure keeps the error toast with its reference', async () => {
    render(<Reporter />);
    await screen.findByText('ready');
    act(() => {
      reportError(new ApiError(500, problem(500, 'internal_error'), 'req-2'));
    });
    await waitFor(() => {
      expect(toasts()).toHaveLength(1);
    });
    expect(toasts()[0]?.className).toContain('error');
    expect(toasts()[0]?.textContent).toContain('Copy reference');
  });

  it('BUG-02: the same error reported twice shows once', async () => {
    render(<Reporter />);
    await screen.findByText('ready');
    const failure = new ApiError(500, problem(500, 'internal_error'), 'req-3');
    act(() => {
      reportError(failure);
      reportError(failure);
    });
    await waitFor(() => {
      expect(toasts()).toHaveLength(1);
    });
  });

  it('BUG-02: an error the screen shows itself is not reported again', async () => {
    render(<Reporter />);
    await screen.findByText('ready');
    const refused = new ApiError(422, problem(422, 'validation_failed'), 'req-4');
    act(() => {
      markHandled(refused);
      reportError(refused);
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(toasts()).toHaveLength(0);
  });
});
