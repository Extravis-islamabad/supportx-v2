import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { ActionBar } from './ActionBar';
import { EditableValue, PropertyList } from './PropertyList';
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

  it('edits a value on a click or the keyboard, with no pencil', () => {
    const onEdit = vi.fn();
    renderUi(
      <EditableValue label="Urgency" onEdit={onEdit} testId="edit-urgency">
        High
      </EditableValue>,
    );
    const value = screen.getByTestId('edit-urgency');
    expect(value.getAttribute('role')).toBe('button');
    expect(value.getAttribute('aria-label')).toBe('Edit Urgency');
    expect(value.querySelector('.anticon-edit')).toBeNull();
    fireEvent.click(value);
    fireEvent.keyDown(value, { key: 'Enter' });
    fireEvent.keyDown(value, { key: ' ' });
    expect(onEdit).toHaveBeenCalledTimes(3);
  });

  it('reads "Add" for an empty value', () => {
    renderUi(
      <EditableValue label="Impact" onEdit={() => undefined} empty testId="edit-impact">
        {null}
      </EditableValue>,
    );
    expect(screen.getByTestId('edit-impact').textContent).toBe('Add');
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
