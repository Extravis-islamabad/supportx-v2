import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';
import { needsRole, runAsWarning } from './runAs';

// A workflow's run-as identity (ADR-043 §6; the coordinator's plan, 2026-11-11): steps that
// change the record act as it, publishing gives it no role, the canvas and the publish say so,
// and its roles are given in "Runs as" from the server's own list.

const FLOW_ID = '01a1a2b3-0000-7000-8000-0000000f0501';
const ROLE_ID = '01a1a2b3-0000-7000-8000-0000000f0601';

const draft = {
  format: 1,
  nodes: [
    { id: 'start', type: 'start', config: {}, position: { x: 0, y: 0 } },
    { id: 'note', type: 'note', config: { text: { en: 'Hi' } }, position: { x: 0, y: 140 } },
    { id: 'end', type: 'end', config: {}, position: { x: 0, y: 280 } },
  ],
  links: [
    { from: 'start', port: 'next', to: 'note' },
    { from: 'note', port: 'next', to: 'end' },
  ],
  variables: [],
};

const technician = { id: ROLE_ID, key: 'technician', name: 'technician', system: true };

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

function api(runAs: object, published: number | null) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['admin'] },
      {
        permissions: ['workflows.manage'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/automation/workflows/${FLOW_ID}`]: {
        body: {
          id: FLOW_ID,
          record_type: 'incident',
          name: 'Note it',
          description: null,
          enabled: false,
          published_version: published,
          running: 0,
          version: 3,
          draft,
          problems: [],
          start_templates: [],
        },
        headers: { ETag: '"3"' },
      },
      [`GET /api/v1/automation/workflows/${FLOW_ID}/run-as`]: { body: runAs },
      [`PUT /api/v1/automation/workflows/${FLOW_ID}/run-as/roles/${ROLE_ID}`]: { status: 204 },
      [`POST /api/v1/automation/workflows/${FLOW_ID}/publish`]: {
        body: { id: FLOW_ID, version: 4, published_version: 1 },
      },
      'GET /api/v1/automation/workflows/node-types': { body: [] },
      'POST /api/v1/automation/workflows/node-ports': { body: [] },
      'GET /api/v1/automation/fields': { body: [] },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [] } },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('the run-as warning', () => {
  it('is only for steps that change the record, and only while no role is held', () => {
    expect(needsRole(['start', 'notify', 'approval', 'end'])).toBe(false);
    expect(needsRole(['start', 'note', 'end'])).toBe(true);
    expect(runAsWarning(['note'], undefined)).toBe('workflows.run_as.warning');
    expect(runAsWarning(['note'], [])).toBe('workflows.run_as.warning');
    expect(runAsWarning(['note'], [technician])).toBeUndefined();
    expect(runAsWarning(['notify'], [])).toBeUndefined();
  });
});

describe('console: a workflow’s run-as identity', () => {
  it('a note with no role shown is warned on the canvas, and publishing asks first', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api({ made: false, name: null, active: false, roles: [], offered: [] }, null);
    render(<App />);
    expect(await screen.findByTestId('designer-run-as-warning')).toBeTruthy();
    fireEvent.click(screen.getByTestId('designer-publish'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('Publish without a role?');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Publish anyway' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW_ID}/publish`)).toHaveLength(1);
    });
  });

  it('Runs as gives a role from the server’s list, by its name', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api(
      { made: true, name: 'Workflow: Note it', active: true, roles: [], offered: [technician] },
      1,
    );
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Runs as' }));
    const panel = await screen.findByTestId('designer-run-as');
    expect(panel.textContent).toContain('Workflow: Note it');
    expect(panel.textContent).toContain('No role yet');
    const box = within(panel)
      .getByTestId('run-as-add')
      .closest('.ant-select')
      ?.querySelector('.ant-select-selector');
    if (box === null || box === undefined) throw new Error('no role picker');
    fireEvent.mouseDown(box);
    const option = (await screen.findAllByTitle('Technician')).at(-1);
    if (option === undefined) throw new Error('no Technician option');
    fireEvent.click(option);
    await waitFor(() => {
      expect(
        fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/run-as/roles/${ROLE_ID}`),
      ).toHaveLength(1);
    });
  });
});
