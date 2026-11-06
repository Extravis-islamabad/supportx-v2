import { Button } from 'antd';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AppearanceProvider } from '../AppearanceProvider';
import { EditDialog, EditDrawer } from './EditDrawer';
import { FormErrorSummary } from './FormErrorSummary';
import { RowActions } from './RowActions';
import { SettingsPageHeader } from './SettingsPageHeader';
import { StickySaveBar } from './StickySaveBar';
import { TranslatedField } from './TranslatedField';

// The settings layout (settings QA 2026-11-06, QA6S-SHELL-01..10).

const ui = (node: React.ReactNode) => render(<AppearanceProvider>{node}</AppearanceProvider>);

describe('QA6S-SHELL-01: one settings page header', () => {
  it('shows the title, one line of description and at most four actions, one primary', async () => {
    const actions = ['a', 'b', 'c', 'd'].map((key) => ({
      key,
      label: `Act ${key}`,
      onClick: vi.fn(),
    }));
    ui(
      <SettingsPageHeader
        title="Sites"
        description="Where your people work."
        primaryAction={<Button type="primary">Add site</Button>}
        actions={[...actions, { key: 'x', label: 'Delete all', onClick: vi.fn(), danger: true }]}
      />,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Sites' })).toBeTruthy();
    expect(screen.getByText('Where your people work.')).toBeTruthy();
    // Primary + 2 secondary + the "…" menu: four controls.
    expect(screen.getAllByRole('button')).toHaveLength(4);
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    const menu = await screen.findByRole('menu');
    const items = within(menu)
      .getAllByRole('menuitem')
      .map((i) => i.textContent);
    expect(items).toEqual(['Act c', 'Act d', 'Delete all']); // destructive last
  });
});

describe('QA6S-SHELL-05: one save model', () => {
  it('appears only with changes, counts them and offers Discard then Save', () => {
    const save = vi.fn();
    const { rerender } = ui(<StickySaveBar changes={0} onDiscard={vi.fn()} onSave={save} />);
    expect(screen.queryByTestId('settings-save-bar')).toBeNull();
    rerender(
      <AppearanceProvider>
        <StickySaveBar changes={3} onDiscard={vi.fn()} onSave={save} />
      </AppearanceProvider>,
    );
    expect(screen.getByTestId('settings-save-bar').textContent).toContain('3 unsaved changes');
    fireEvent.click(screen.getByTestId('settings-save'));
    expect(save).toHaveBeenCalledTimes(1);
  });
});

describe('QA6S-SHELL-06: one add and edit pattern', () => {
  it.each([
    ['drawer', EditDrawer],
    ['dialog', EditDialog],
  ] as const)('the %s puts Cancel before the primary in its footer', async (_kind, Surface) => {
    const cancel = vi.fn();
    ui(
      <Surface open title="Add site" okText="Add" onCancel={cancel} onOk={vi.fn()}>
        <span>fields</span>
      </Surface>,
    );
    const ok = await screen.findByTestId('edit-ok');
    const back = screen.getByTestId('edit-cancel');
    expect(back.compareDocumentPosition(ok) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ok.textContent).toBe('Add');
    fireEvent.click(back);
    expect(cancel).toHaveBeenCalled();
  });
});

describe('QA6S-SHELL-07: one error pattern', () => {
  it('lists the fields by label and moves focus to the first', async () => {
    ui(
      <>
        <input id="site-name" aria-label="Name" />
        <FormErrorSummary
          problems={[{ fieldId: 'site-name', label: 'Name', message: 'Required.' }]}
        />
      </>,
    );
    expect(screen.getByTestId('form-error-summary').textContent).toContain('Name: Required.');
    await waitFor(() => {
      expect(document.activeElement?.id).toBe('site-name');
    });
  });
});

describe('QA6S-SHELL-10: one way to act on a row', () => {
  it('offers the main action as a link and the rest in a menu named for the row, destructive last', async () => {
    ui(
      <RowActions
        rowName="Dubai office"
        primary={{ key: 'edit', label: 'Edit', onClick: vi.fn() }}
        more={[
          { key: 'remove', label: 'Remove', onClick: vi.fn(), danger: true },
          { key: 'copy', label: 'Copy', onClick: vi.fn() },
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'More actions for Dubai office' }));
    const items = within(await screen.findByRole('menu'))
      .getAllByRole('menuitem')
      .map((i) => i.textContent);
    expect(items).toEqual(['Copy', 'Remove']);
  });
});

describe('TranslatedField', () => {
  it('names each language and writes each in its own direction', () => {
    const change = vi.fn();
    ui(<TranslatedField label="Name" value={{ en: 'Printers' }} onChange={change} testId="name" />);
    expect(screen.getByTestId('name-en').getAttribute('dir')).toBe('ltr');
    fireEvent.click(screen.getByRole('tab', { name: /Urdu|اردو/ }));
    fireEvent.change(screen.getByTestId('name-ur'), { target: { value: 'پرنٹر' } });
    expect(change).toHaveBeenLastCalledWith({ en: 'Printers', ur: 'پرنٹر' });
    expect(screen.getByTestId('name-ur').getAttribute('dir')).toBe('rtl');
  });
});

describe('lanes A and B asks on #258', () => {
  it('a drawer takes header actions, a wide width, and says why its primary is disabled', async () => {
    ui(
      <EditDrawer
        open
        wide
        title="Edit Amal"
        extra={<button type="button">Account actions</button>}
        okDisabled
        okWhyNot="Choose a role first."
        onCancel={vi.fn()}
        onOk={vi.fn()}
      >
        <span>fields</span>
      </EditDrawer>,
    );
    expect(await screen.findByRole('button', { name: 'Account actions' })).toBeTruthy();
    expect(screen.getByLabelText('Save: Choose a role first.')).toBeTruthy();
  });

  it('asks before discarding unsaved input on Cancel', async () => {
    const cancel = vi.fn();
    ui(
      <EditDialog open dirty title="Add value" onCancel={cancel} onOk={vi.fn()}>
        <span>fields</span>
      </EditDialog>,
    );
    fireEvent.click(await screen.findByTestId('edit-cancel'));
    expect(cancel).not.toHaveBeenCalled();
    const titles = await screen.findAllByText('Discard your changes?');
    // One question, however its title is also announced.
    expect(document.querySelectorAll('.ant-modal-confirm')).toHaveLength(1);
    const ask = titles[0]?.closest<HTMLElement>('.ant-modal');
    if (!ask) throw new Error('no discard dialog');
    fireEvent.click(within(ask).getByRole('button', { name: 'Discard' }));
    await waitFor(() => {
      expect(cancel).toHaveBeenCalledTimes(1);
    });
  });

  it('the error summary names the section and lets the caller show its tab first', async () => {
    const select = vi.fn();
    ui(
      <>
        <input id="group" aria-label="Group" />
        <FormErrorSummary
          problems={[
            { fieldId: 'group', label: 'Group', message: 'Required.', section: 'Fulfilment' },
          ]}
          onSelect={select}
        />
      </>,
    );
    expect(screen.getByTestId('form-error-summary').textContent).toContain(
      'Fulfilment › Group: Required.',
    );
    await waitFor(() => {
      expect(select).toHaveBeenCalledWith('group');
    });
  });

  it('a disabled row action says why, and a language error marks its tab', async () => {
    ui(
      <>
        <RowActions
          rowName="Laptop"
          more={[
            {
              key: 'delete',
              label: 'Delete',
              onClick: vi.fn(),
              danger: true,
              disabled: true,
              whyNot: 'In use: retire it instead.',
            },
          ]}
        />
        <TranslatedField label="Name" onChange={vi.fn()} error={{ ar: 'Too long.' }} testId="tn" />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'More actions for Laptop' }));
    expect(await screen.findByText('In use: retire it instead.')).toBeTruthy();
    expect(screen.getByTestId('tn').textContent).toMatch(/Too long\./);
    expect(screen.getByTestId('tn').querySelector('.ant-badge-status-error')).not.toBeNull();
  });
});
