import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { ActionBar } from './ActionBar';
import { EditableValue, PropertyList } from './PropertyList';
import { sectionsBeforeProperties } from './panelOrder';
import { RecordHeader } from './RecordPage';

// D-147 template A: the record page's properties, in-place editing, title and actions row.
describe('template A (record page)', () => {
  const items = [
    { key: 'site', label: 'Site', content: 'Lahore', filled: true },
    { key: 'urgency', label: 'Urgency', content: 'Add', filled: false },
    { key: 'impact', label: 'Impact', content: 'Add', filled: false },
    { key: 'group', label: 'Group', content: 'None', filled: false, always: true },
  ];

  it('shows filled fields at once and the empty ones behind Add details', () => {
    renderUi(<PropertyList items={items} testId="props" />);
    expect(screen.getByText('Site')).toBeTruthy();
    expect(screen.getByText('Group')).toBeTruthy(); // always shown
    expect(screen.queryByText('Urgency')).toBeNull();
    const add = screen.getByTestId('props-add');
    expect(add.textContent).toContain('2');
    expect(add.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(add);
    expect(screen.getByText('Urgency')).toBeTruthy();
    expect(screen.getByText('Impact')).toBeTruthy();
    expect(screen.getByTestId('props-add').getAttribute('aria-expanded')).toBe('true');
  });

  it('has no Add details when every field is filled', () => {
    renderUi(<PropertyList items={items.slice(0, 1)} testId="props" />);
    expect(screen.queryByTestId('props-add')).toBeNull();
  });

  it('edits a value on a click, or with its own Edit button, never inside a role=button', () => {
    const onEdit = vi.fn();
    renderUi(
      <EditableValue label="Requester" onEdit={onEdit} testId="edit-requester">
        <span>Saad</span> <a href="/people/1">profile</a>
      </EditableValue>,
    );
    const button = screen.getByTestId('edit-requester');
    expect(button.tagName).toBe('BUTTON');
    expect(button.getAttribute('aria-label')).toBe('Edit Requester');
    const value = screen.getByText('Saad');
    expect(value.closest('[role="button"]')).toBeNull(); // the value reads as itself
    fireEvent.click(value);
    fireEvent.click(button);
    expect(onEdit).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByText('profile')); // the link inside does its own thing
    expect(onEdit).toHaveBeenCalledTimes(2);
  });

  it('reads "Add" for an empty value', () => {
    renderUi(
      <EditableValue label="Impact" onEdit={() => undefined} empty testId="edit-impact">
        {null}
      </EditableValue>,
    );
    expect(screen.getByText('Add')).toBeTruthy();
  });

  it('copies the ID, but not a stand-in such as "No tag"', () => {
    const view = renderUi(
      <RecordHeader displayId="INC-1" title="Printer down" testIds={{ id: 'id' }} />,
    );
    expect(screen.getByTestId('id').querySelector('.ant-typography-copy')).not.toBeNull();
    view.unmount();
    renderUi(
      <RecordHeader displayId="No tag" copyable={false} title="Laptop" testIds={{ id: 'id' }} />,
    );
    expect(screen.getByTestId('id').querySelector('.ant-typography-copy')).toBeNull();
  });

  it('lets a screen wrap the title (to edit it in place)', () => {
    renderUi(
      <RecordHeader
        displayId="INC-1"
        title="Printer down"
        testIds={{ title: 'heading' }}
        renderTitle={(shown) => <div data-testid="wrapped">{shown}</div>}
      />,
    );
    expect(screen.getByTestId('wrapped').contains(screen.getByTestId('heading'))).toBe(true);
  });

  it('puts the lead (presence, Follow) on the actions row, before the buttons', () => {
    renderUi(
      <ActionBar
        testId="bar"
        lead={<button type="button">Follow</button>}
        actions={[
          { key: 'reply', label: 'Reply', allowed: true, primary: true, onClick: () => undefined },
        ]}
      />,
    );
    const bar = screen.getByTestId('bar');
    const buttons = [...bar.querySelectorAll('button')].map((b) => b.textContent);
    expect(buttons[0]).toBe('Follow');
    expect(buttons[1]).toBe('Reply');
  });
});

describe('panel order (V-13)', () => {
  const card = (key: string, bare = false) => ({ key, title: key, children: null, bare });
  it('names a carded section that comes before Properties; a bare summary may lead', () => {
    expect(
      sectionsBeforeProperties([card('summary', true), card('properties'), card('sla')]),
    ).toEqual([]);
    expect(sectionsBeforeProperties([card('requester'), card('properties')])).toEqual([
      'requester',
    ]);
    // A panel without Properties (a release's own cards) has no such rule.
    expect(sectionsBeforeProperties([card('release'), card('schedule')])).toEqual([]);
  });
});
