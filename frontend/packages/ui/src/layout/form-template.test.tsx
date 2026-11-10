import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { FormFooter, FormPage, FormSection } from './FormPage';

// D-147 template B: sections in cards and one sticky footer, Cancel before the primary action.
describe('template B (form page)', () => {
  it('puts every action in one sticky footer, Cancel before the primary one', () => {
    renderUi(
      <FormPage
        testId="form"
        title="New announcement"
        notice={<span>Nothing saved yet</span>}
        cancel={<button type="button">Cancel</button>}
        primary={<button type="button">Save draft</button>}
      >
        <FormSection title="Message" testId="section">
          <input aria-label="Title" />
        </FormSection>
      </FormPage>,
    );
    const footer = screen.getByTestId('form-footer');
    expect(footer.style.position).toBe('sticky');
    expect(footer.style.bottom).toBe('0px');
    const buttons = [...footer.querySelectorAll('button')].map((b) => b.textContent);
    expect(buttons).toEqual(['Cancel', 'Save draft']);
    expect(footer.textContent).toContain('Nothing saved yet');
    // No action inside the sections.
    expect(screen.getByTestId('section').querySelector('button')).toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: 'Message' })).toBeTruthy();
  });
});

describe('FormFooter on a phone (lane A, #351)', () => {
  const footer = () =>
    renderUi(
      <FormFooter
        testId="footer"
        notice={<span data-testid="why">Give the issue a subject to send it.</span>}
        cancel={<button type="button">Cancel</button>}
        primary={<button type="button">Send</button>}
      />,
    );
  const wide = (on: boolean) => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: on,
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
  };
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('puts the notice on its own line above the buttons below 576 px', () => {
    wide(false);
    footer();
    const why = screen.getByTestId('why');
    const send = screen.getByRole('button', { name: 'Send' });
    // The notice's line holds no button; the buttons sit in a row of their own below it.
    expect(why.parentElement?.querySelector('button')).toBeNull();
    expect(why.compareDocumentPosition(send) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(send.parentElement?.contains(why)).toBe(false);
  });

  it('keeps the notice beside the buttons when wide', () => {
    wide(true);
    footer();
    const why = screen.getByTestId('why');
    const send = screen.getByRole('button', { name: 'Send' });
    expect(why.parentElement?.parentElement).toBe(send.parentElement);
  });
});
