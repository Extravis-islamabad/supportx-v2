import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderUi } from '../test/render';
import { FormPage, FormSection } from './FormPage';

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
