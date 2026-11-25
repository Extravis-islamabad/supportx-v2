import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// D-180 (0188): Sign-in and security › Vendor support › Give access. The "Hide people's names
// too" tick is off by default (names show) and, when ticked, is sent with the grant.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin'] });

async function giveAccess(tick: boolean) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/identity/vendor-support/setting': {
        body: { never_allow: false, version: 1 },
      },
      'GET /api/v1/identity/vendor-support/grants': { body: [] },
      'POST /api/v1/identity/vendor-support/grants': {
        status: 201,
        body: { id: 'g1', engineer_name: 'Omar Engineer', delivery: 'actions_email' },
      },
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', '/admin/security');
  render(<App />);
  const card = await screen.findByTestId('vendor-support-card');
  const open = within(card).getByTestId('vendor-support-grant');
  await waitFor(() => {
    expect(open.hasAttribute('disabled')).toBe(false);
  });
  fireEvent.click(open);
  const drawer = await screen.findByTestId('vendor-support-grant-drawer');
  const tickBox = within(drawer).getByTestId('vendor-support-mask-names');
  expect(drawer.textContent).toContain("Hide people's names too");
  expect((tickBox as HTMLInputElement).checked).toBe(false); // names show by default (D-180)
  fireEvent.change(within(drawer).getByTestId('vendor-support-name'), {
    target: { value: 'Omar Engineer' },
  });
  fireEvent.change(within(drawer).getByTestId('vendor-support-email'), {
    target: { value: 'omar@extravis.com' },
  });
  fireEvent.change(within(drawer).getByTestId('vendor-support-reason'), {
    target: { value: 'A workflow is stuck' },
  });
  if (tick) fireEvent.click(tickBox);
  // The card's button and the form's submit share the label; the form's is the later one.
  const submit = screen.getAllByRole('button', { name: 'Give access' }).at(-1);
  if (submit === undefined) throw new Error('no submit button');
  fireEvent.click(submit);
  await waitFor(() => {
    expect(fake.find('POST', '/api/v1/identity/vendor-support/grants')).toHaveLength(1);
  });
  const [sent] = fake.find('POST', '/api/v1/identity/vendor-support/grants');
  return sent?.body as { mask_names?: boolean; unmask_personal?: boolean };
}

describe('Vendor support › Give access › Hide names too', () => {
  it('sends the tick when the admin ticks it', async () => {
    const body = await giveAccess(true);
    expect(body.mask_names).toBe(true);
  });

  it('leaves names visible when it is not ticked', async () => {
    const body = await giveAccess(false);
    expect(body.mask_names).toBe(false);
  });
});
