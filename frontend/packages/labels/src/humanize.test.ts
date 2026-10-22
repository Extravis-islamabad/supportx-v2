import { describe, expect, it } from 'vitest';

import { humanize } from './humanize';

describe('humanize', () => {
  it.each([
    ['INCIDENT_MANAGEMENT', 'Incident Management'],
    ['incident_management', 'Incident Management'],
    ['awaiting_customer', 'Awaiting Customer'],
    ['cmdb.ci_type.network_switch', 'Network Switch'],
    ['p1_critical', 'P1 Critical'],
    ['incidentManagement', 'Incident Management'],
    ['change-request', 'Change Request'],
    ['open', 'Open'],
  ])('humanizes %s as %s', (code, expected) => {
    expect(humanize(code)).toBe(expected);
  });

  it('returns an empty string for an empty code', () => {
    expect(humanize('')).toBe('');
  });
});
