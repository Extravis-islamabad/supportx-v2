import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AppearanceProvider } from '../AppearanceProvider';

import { PropertyList } from './PropertyList';
import { RestrictedValue } from './RestrictedValue';
import { restrictionOf } from './restriction';

// ADR-047 slice c: a field the person's roles withhold says so (lane C's review conditions).

describe('RestrictedValue', () => {
  it('says it in words, the icon carrying no meaning of its own', () => {
    render(
      <AppearanceProvider>
        <RestrictedValue kind="hidden" />
        <RestrictedValue kind="masked" />
      </AppearanceProvider>,
    );
    expect(screen.getByTestId('restricted-hidden').textContent).toBe('Not shown to you');
    expect(screen.getByTestId('restricted-masked').textContent).toBe('Masked');
    for (const icon of document.querySelectorAll('[role="img"]')) {
      expect(icon.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('reads the record: hidden before masked, nothing for other fields', () => {
    const record = { hidden_fields: ['custom.salary'], masked_fields: ['impact_details'] };
    expect(restrictionOf(record, 'custom.salary')).toBe('hidden');
    expect(restrictionOf(record, 'impact_details')).toBe('masked');
    expect(restrictionOf(record, 'urgency')).toBeUndefined();
    expect(restrictionOf({}, 'urgency')).toBeUndefined();
  });
});

describe('PropertyList with a restricted row', () => {
  it('shows the row at once, never behind "Add details", never its editor', () => {
    render(
      <AppearanceProvider>
        <PropertyList
          testId="props"
          items={[
            { key: 'urgency', label: 'Urgency', content: 'High', filled: true },
            {
              key: 'custom.salary',
              label: 'Salary band',
              content: <button type="button">Edit salary</button>,
              filled: false,
              restricted: 'hidden',
            },
            { key: 'tags', label: 'Tags', content: 'none', filled: false },
          ]}
        />
      </AppearanceProvider>,
    );
    expect(screen.getByText('Salary band')).toBeDefined();
    expect(screen.getByTestId('restricted-hidden')).toBeDefined();
    expect(screen.queryByText('Edit salary')).toBeNull();
    // Only the one truly empty row waits behind "Add details".
    expect(screen.getByTestId('props-add').textContent).toContain('1');
    fireEvent.click(screen.getByTestId('props-add'));
    expect(screen.queryByText('Edit salary')).toBeNull();
  });
});
