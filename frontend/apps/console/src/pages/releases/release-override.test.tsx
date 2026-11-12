import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident } from '@supportx/api-client/testing';
import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { consoleApi } from '../../test/api';
import { ReleaseOverride } from './ReleaseConflicts';

// REQ-REL-040 AC2, the dialog's part (the calendar's is release-calendar.test.tsx): a reason,
// the release's version as If-Match, the refusing freezes, then done.

const REL_ID = '01a1a2b3-0000-7000-8000-00000058b001';
const FREEZE = '01a1a2b3-0000-7000-8000-00000058c101';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function Dialog({ onDone }: { onDone: () => void }) {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <AppearanceProvider>
        <ReleaseOverride
          id={REL_ID}
          windowIds={[FREEZE]}
          onDone={onDone}
          onClose={() => undefined}
        />
      </AppearanceProvider>
    </QueryClientProvider>
  );
}

describe('the release freeze override dialog', () => {
  it('REQ-REL-040 AC2: sends the reason and the freezes with If-Match, then is done', async () => {
    const fake = consoleApi({
      routes: {
        [`GET /api/v1/releases/${REL_ID}`]: {
          body: {
            ...fakeIncident({ id: REL_ID, display_id: 'REL-7' }),
            type: 'release',
            version: 9,
          },
          headers: { ETag: '"9"' },
        },
        [`POST /api/v1/releases/${REL_ID}/freeze-override`]: { body: { version: 10 } },
      },
    });
    restore = fake.restore;
    const onDone = vi.fn();
    render(<Dialog onDone={onDone} />);
    fireEvent.change(await screen.findByTestId('release-override-reason'), {
      target: { value: 'Payroll must go out' },
    });
    // Ready: the release (its If-Match) has arrived, so the button no longer loads.
    await waitFor(() => {
      const ok = screen.getByTestId('release-override-ok');
      expect(ok.hasAttribute('disabled')).toBe(false);
      expect(ok.classList.contains('ant-btn-loading')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('release-override-ok'));
    await waitFor(() => {
      expect(onDone).toHaveBeenCalledTimes(1);
    });
    const [passed] = fake.find('POST', `/api/v1/releases/${REL_ID}/freeze-override`);
    expect(passed?.body).toEqual({ reason: 'Payroll must go out', window_ids: [FREEZE] });
    expect(passed?.headers.get('If-Match')).toBe('"9"');
  });
});
