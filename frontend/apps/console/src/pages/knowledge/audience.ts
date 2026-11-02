import { useMemo } from 'react';

import { useStructure, useUnits } from '@supportx/api-client';

import type { UnitNames } from './model';

/** The audience fields of a topic or an article (REQ-KB-044, 045). */
export interface AudienceValue {
  tech_all: boolean;
  tech_groups: string[];
  requesters: 'none' | 'all' | 'selected';
  req_groups: string[];
  req_sites: string[];
  req_departments: string[];
}

export const EVERYONE_STAFF: AudienceValue = {
  tech_all: true,
  tech_groups: [],
  requesters: 'none',
  req_groups: [],
  req_sites: [],
  req_departments: [],
};

/** Group, site and department names, for putting an audience in words. */
export function useUnitNames(): UnitNames {
  const groups = useUnits('groups');
  const sites = useUnits('sites');
  const departments = useStructure('departments', true, true);
  return useMemo(
    () => ({
      groups: new Map((groups.data ?? []).map((g) => [g.id, g.name])),
      sites: new Map((sites.data ?? []).map((s) => [s.id, s.name])),
      departments: new Map((departments.data ?? []).map((d) => [d.id, d.name])),
    }),
    [groups.data, sites.data, departments.data],
  );
}
