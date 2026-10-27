import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { afterEach, describe, expect, it } from 'vitest';

import { useSession, type MeResponse } from '@supportx/api-client';
import { fakeApi, fakeSession } from '@supportx/api-client/testing';

import { clearAllKeptDrafts, useKeptDraft } from './keptDraft';

// WP-039 session 3 (REQ-SEC-029 AC2): input survives a session timeout in the same tab, for the
// same person in the same organisation only (lane A's review of #87).

const EMPTY = { title: '', note: '' };
const ANNA = fakeSession({ id: 'u-anna', display_name: 'Anna' });
const BILAL = fakeSession({ id: 'u-bilal', display_name: 'Bilal' });

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  window.sessionStorage.clear();
});

function Form() {
  const form = useForm<typeof EMPTY>({ defaultValues: EMPTY });
  const { restored, discard, startEmpty } = useKeptDraft(form, 'incident-new');
  return (
    <form>
      {restored && <p data-testid="restored">restored</p>}
      <input data-testid="title" {...form.register('title')} />
      <button type="button" data-testid="saved" onClick={discard}>
        saved
      </button>
      <button
        type="button"
        data-testid="empty"
        onClick={() => {
          startEmpty(EMPTY);
        }}
      >
        empty
      </button>
    </form>
  );
}

/** As in the apps: forms render only inside the session gate, once the session is known. */
function Gate() {
  return useSession().data ? <Form /> : null;
}

function signedIn(me: MeResponse) {
  restore();
  const fake = fakeApi({ 'GET /api/v1/auth/me': { body: me } });
  restore = fake.restore;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <Gate />
    </QueryClientProvider>,
  );
}

function kept(): string[] {
  return Object.keys(window.sessionStorage).filter((k) => k.startsWith('supportx.draft.'));
}

async function typeTitle(value: string) {
  fireEvent.change(await screen.findByTestId('title'), { target: { value } });
  await waitFor(() => {
    const [found] = kept();
    expect(found === undefined ? null : window.sessionStorage.getItem(found)).toContain(value);
  });
}

describe('useKeptDraft', () => {
  it('keeps typed input and puts it back for the same person after a timeout', async () => {
    const first = signedIn(ANNA);
    await typeTitle('Printer on fire');
    first.unmount(); // the session timed out; Anna signs in again
    signedIn(ANNA);
    expect(await screen.findByTestId('restored')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('title').value).toBe('Printer on fire');
    });
  });

  it("never gives one person's draft to someone else on the same tab", async () => {
    const first = signedIn(ANNA);
    await typeTitle('Salary question');
    first.unmount();
    signedIn(BILAL);
    await screen.findByTestId('title');
    expect(screen.queryByTestId('restored')).toBeNull();
    expect(screen.getByTestId<HTMLInputElement>('title').value).toBe('');
  });

  it('an explicit sign-out forgets every draft', async () => {
    const first = signedIn(ANNA);
    await typeTitle('Draft');
    first.unmount();
    clearAllKeptDrafts();
    expect(kept()).toEqual([]);
  });

  it('an untouched form keeps nothing; "start empty" forgets the draft', async () => {
    signedIn(ANNA);
    await typeTitle('x');
    fireEvent.change(screen.getByTestId('title'), { target: { value: '' } });
    await waitFor(() => {
      expect(kept()).toEqual([]);
    });
    await typeTitle('again');
    fireEvent.click(screen.getByTestId('empty'));
    expect(screen.getByTestId<HTMLInputElement>('title').value).toBe('');
    await waitFor(() => {
      expect(kept()).toEqual([]);
    });
  });
});
