import { App, Button } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { AppearanceProvider } from '../AppearanceProvider';
import { AppHeader } from './AppHeader';
import { headerRole } from './headerRole';

// Full QA 2026-11-06, shell findings.

const t = (key: string) => key;

describe('QA6-SH-01: the top bar names the role, not the user type', () => {
  it('shows the most senior system role the person holds', () => {
    expect(headerRole(t, { roles: ['technician', 'tenant_admin'], user_type: 'technician' })).toBe(
      'role.tenant_admin',
    );
    expect(headerRole(t, { roles: ['technician'], user_type: 'technician' })).toBe(
      'role.technician',
    );
  });

  it('falls back to the user type when the person holds only custom roles', () => {
    expect(headerRole(t, { roles: ['night_shift'], user_type: 'technician' })).toBe(
      'user_type.technician',
    );
  });

  it('reads "Tenant administrator" for an admin in the header', () => {
    const session = fakeSession({ roles: ['technician', 'tenant_admin'] });
    render(
      <AppearanceProvider>
        <AppHeader appName="app.console.name" session={session} onLogout={() => undefined} />
      </AppearanceProvider>,
    );
    expect(screen.getByTestId('user-role').textContent).toBe('Tenant administrator');
  });
});

function Notify() {
  const { notification } = App.useApp();
  return (
    <Button
      onClick={() => {
        notification.error({ message: 'Authors cannot approve' });
      }}
    >
      notify
    </Button>
  );
}

describe('QA6-SH-02: error notifications open below the top bar', () => {
  it('places them under the 56 px header, as messages are (#204)', async () => {
    render(
      <AppearanceProvider>
        <Notify />
      </AppearanceProvider>,
    );
    fireEvent.click(screen.getByText('notify'));
    await waitFor(() => {
      const box = document.querySelector<HTMLElement>('.ant-notification');
      expect(box?.style.top).toBe('64px');
    });
  });
});
