import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AppearanceProvider } from '../AppearanceProvider';

import { ServiceRolesSection } from './ServiceRolesSection';

// The shared roles section of a service identity (a workflow's run-as, a connector's next).

const tech = { id: 't', key: 'technician', name: 'technician', system: true };
const notes = { id: 'n', key: 'custom_1', name: 'Workflow notes', system: false };

function show(data: Parameters<typeof ServiceRolesSection>[0]['data'], onTake = vi.fn()) {
  render(
    <AppearanceProvider initialMode="light">
      <ServiceRolesSection
        data={data}
        help="Help"
        notMade="Not made yet"
        readOnly={false}
        pending={false}
        onGive={vi.fn()}
        onTake={onTake}
      />
    </AppearanceProvider>,
  );
}

describe('ServiceRolesSection', () => {
  it('says what shows before the identity exists', () => {
    show({ made: false, name: null, active: false, roles: [], offered: [tech] });
    expect(screen.getByText('Not made yet')).toBeTruthy();
    expect(screen.queryByTestId('service-roles-add')).toBeNull();
  });

  it('names system roles by their label and custom ones as written, and takes one', () => {
    const onTake = vi.fn();
    show(
      { made: true, name: 'Workflow: X', active: true, roles: [notes], offered: [tech, notes] },
      onTake,
    );
    expect(screen.getByTestId('service-roles-held').textContent).toContain('Workflow notes');
    fireEvent.click(screen.getByLabelText('Take the role Workflow notes'));
    expect(onTake).toHaveBeenCalledWith('n');
  });
});
