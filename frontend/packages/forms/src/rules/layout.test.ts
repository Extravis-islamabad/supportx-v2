import { describe, expect, it } from 'vitest';

import { arrangeFields, type FormLayout } from './layout';

// The same cases as the server's test_form_layout_domain.py (REQ-INC-036).
const FIELDS = ['subject', 'requester_id', 'category_id', 'site_id', 'description', 'custom.cost'];
const TECH: FormLayout['technician'] = {
  label_position: 'start',
  sections: [
    { id: 'who', names: { en: 'Who', ar: 'من' }, fields: ['requester_id', 'subject'] },
    {
      id: 'where',
      columns: 2,
      collapsible: true,
      collapsed: true,
      fields: ['site_id', 'category_id'],
    },
  ],
};

describe('form layout', () => {
  it('AC1: fields land in their sections and unplaced ones go last', () => {
    const laid = arrangeFields({ technician: TECH, requester: null }, 'technician', FIELDS);
    expect(laid.labelPosition).toBe('start');
    expect(laid.sections.map((s) => s.id)).toEqual(['who', 'where']);
    expect(laid.sections[0]?.fields).toEqual(['requester_id', 'subject']);
    expect(laid.sections[1]?.fields).toEqual([
      'site_id',
      'category_id',
      'description',
      'custom.cost',
    ]);
    expect([laid.sections[1]?.columns, laid.sections[1]?.collapsed]).toEqual([2, true]);
  });

  it('the requester layout falls back, and fields not on the form are left out', () => {
    const portal = ['subject', 'requester_id', 'description'];
    let laid = arrangeFields({ technician: TECH, requester: null }, 'requester', portal);
    expect(laid.sections.map((s) => s.fields)).toEqual([
      ['requester_id', 'subject'],
      ['description'],
    ]);
    laid = arrangeFields(
      {
        technician: TECH,
        requester: { sections: [{ id: 'only', fields: ['description', 'subject'] }] },
      },
      'requester',
      portal,
    );
    expect(laid.sections.map((s) => s.fields)).toEqual([
      ['description', 'subject', 'requester_id'],
    ]);
    expect(laid.labelPosition).toBe('top');
  });

  it('no layout is one plain section', () => {
    expect(arrangeFields(null, 'technician', FIELDS).sections.map((s) => s.fields)).toEqual([
      FIELDS,
    ]);
  });
});
