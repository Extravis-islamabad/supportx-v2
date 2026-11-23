import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-046a S5b: the form designer and the form rule editor in Admin › Incidents › Templates
// (REQ-INC-036, REQ-INC-037). Keyboard first: every move is a button or a choice.

const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const TEMPLATE = fakeIncidentTemplate({ id: 't-1', code: null, labels: { en: 'Mail' } });
const PATH = '/api/v1/incidents/templates/t-1';
const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [TEMPLATE] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/custom-fields': { body: [] },
  [`PATCH ${PATH}`]: { body: TEMPLATE },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

async function openEditor() {
  const fake = consoleApi({ me: ADMIN, routes: ROUTES });
  restore = fake.restore;
  window.history.pushState({}, '', '/admin/incidents/templates');
  render(<App />);
  fireEvent.click(await screen.findByTestId('tpl-admin-edit-t-1'));
  await screen.findByTestId('tpl-layout');
  return fake;
}

describe('Template form designer', () => {
  it('REQ-INC-036 AC1: sections arranged with buttons are saved as the layout', async () => {
    const fake = await openEditor();
    fireEvent.click(screen.getByTestId('tpl-layout-on'));
    // Every field starts in one section; a second section takes the description.
    fireEvent.click(await screen.findByTestId('tpl-section-add'));
    const first = screen.getByTestId('tpl-section-0');
    const subject = within(first).getByTestId('tpl-section-0-field-subject');
    // Move the subject down one place, by keyboard-reachable button.
    fireEvent.click(within(subject).getByRole('button', { name: /Move .* down/ }));
    fireEvent.click(screen.getByRole('button', { name: /Take Description out of this section/ }));
    fireEvent.click(screen.getByTestId('tpl-editor-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
    const body = fake.find('PATCH', PATH)[0]?.body as {
      layout: { technician: { sections: { fields: string[] }[] } } | null;
    };
    const sections = body.layout?.technician.sections ?? [];
    expect(sections).toHaveLength(2);
    expect(sections[0]?.fields.slice(0, 2)).toEqual(['requester_id', 'subject']);
    expect(sections[0]?.fields).not.toContain('description');
    expect(sections[1]?.fields).toEqual([]);
  });

  it('REQ-INC-036 AC3: the preview shows both layouts in both directions', async () => {
    await openEditor();
    fireEvent.click(screen.getByTestId('tpl-layout-on'));
    fireEvent.click(await screen.findByTestId('tpl-layout-preview'));
    const form = await screen.findByTestId('tpl-preview-form');
    expect(form.getAttribute('dir')).toBe('ltr');
    fireEvent.click(within(screen.getByTestId('tpl-preview-direction')).getByText('Right to left'));
    await waitFor(() => {
      expect(screen.getByTestId('tpl-preview-form').getAttribute('dir')).toBe('rtl');
    });
    fireEvent.click(
      within(screen.getByTestId('tpl-preview-audience')).getByText('Requesters (portal)'),
    );
    expect(screen.getByTestId('tpl-preview-form')).toBeDefined();
  });

  it('REQ-INC-037: a rule built in the editor is saved as the template rules', async () => {
    const fake = await openEditor();
    fireEvent.click(screen.getByTestId('tpl-frule-add'));
    expect(await screen.findByTestId('tpl-frule-0')).toBeDefined();
    fireEvent.click(screen.getByTestId('tpl-editor-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
    const body = fake.find('PATCH', PATH)[0]?.body as {
      form_rules: { when: { field: string; op: string }; then: { do: string; field: string }[] }[];
    };
    expect(body.form_rules).toHaveLength(1);
    expect(body.form_rules[0]?.when).toEqual({ field: 'category_id', op: 'is_not_null' });
    expect(body.form_rules[0]?.then).toEqual([{ do: 'require', field: 'on_behalf_of_id' }]);
  });
});
