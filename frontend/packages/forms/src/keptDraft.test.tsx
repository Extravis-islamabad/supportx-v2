import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { afterEach, describe, expect, it } from 'vitest';

import { clearKeptDraft, useKeptDraft } from './keptDraft';

// WP-039 session 3 (REQ-SEC-029 AC2): input survives a session timeout in the same tab.

function Form({ draftKey }: { draftKey: string }) {
  const form = useForm<{ title: string; note: string }>({ defaultValues: { title: '', note: '' } });
  const { restored, discard } = useKeptDraft(form, draftKey);
  return (
    <form>
      {restored && <p data-testid="restored">restored</p>}
      <input data-testid="title" {...form.register('title')} />
      <button type="button" data-testid="saved" onClick={discard}>
        saved
      </button>
    </form>
  );
}

afterEach(() => {
  clearKeptDraft('incident-new');
  window.sessionStorage.clear();
});

describe('useKeptDraft', () => {
  it('keeps typed input and puts it back when the form opens again', async () => {
    const first = render(<Form draftKey="incident-new" />);
    fireEvent.change(screen.getByTestId('title'), { target: { value: 'Printer on fire' } });
    await waitFor(() => {
      expect(window.sessionStorage.getItem('supportx.draft.incident-new')).toContain('Printer');
    });
    first.unmount(); // the session timed out; the person signs in again
    render(<Form draftKey="incident-new" />);
    expect(await screen.findByTestId('restored')).toBeDefined();
    expect(screen.getByTestId<HTMLInputElement>('title').value).toBe('Printer on fire');
  });

  it('a successful save forgets the draft', async () => {
    window.sessionStorage.setItem(
      'supportx.draft.incident-new',
      JSON.stringify({ title: 'Old', note: '' }),
    );
    render(<Form draftKey="incident-new" />);
    await screen.findByTestId('restored');
    act(() => {
      fireEvent.click(screen.getByTestId('saved'));
    });
    expect(window.sessionStorage.getItem('supportx.draft.incident-new')).toBeNull();
  });
});
