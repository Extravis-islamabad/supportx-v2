// A template's form layout in the browser (WP-046a S5b; REQ-INC-036): the twin of the server's
// backend/app/modules/work_items/domain/form_layout.py `arrange`. A layout only arranges: what
// is shown or required stays with the template's field settings and form rules, so a field the
// layout does not place goes to the end of the last section, in the form's usual order, and a
// placed field that is not on the form now (hidden, or not the requester's) is left out.

export type LabelPosition = 'top' | 'start';
export type LayoutAudience = 'technician' | 'requester';

export interface LayoutSection {
  id: string;
  names?: Partial<Record<string, string>>;
  columns?: number;
  collapsible?: boolean;
  collapsed?: boolean;
  fields?: string[];
}

export interface LayoutPart {
  label_position?: LabelPosition;
  sections: LayoutSection[];
}

export interface FormLayout {
  technician: LayoutPart;
  requester?: LayoutPart | null;
}

export interface ArrangedSection {
  id: string;
  names: Partial<Record<string, string>>;
  columns: 1 | 2;
  collapsible: boolean;
  collapsed: boolean;
  fields: string[];
}

export interface ArrangedForm {
  labelPosition: LabelPosition;
  sections: ArrangedSection[];
}

/** `fields` (in the form's usual order) laid out for `audience`; null layout: one section. */
export function arrangeFields(
  layout: FormLayout | null | undefined,
  audience: LayoutAudience,
  fields: readonly string[],
): ArrangedForm {
  const part = layout
    ? ((audience === 'requester' ? layout.requester : null) ?? layout.technician)
    : null;
  if (!part) {
    return {
      labelPosition: 'top',
      sections: [
        {
          id: 'main',
          names: {},
          columns: 1,
          collapsible: false,
          collapsed: false,
          fields: [...fields],
        },
      ],
    };
  }
  const wanted = new Set(fields);
  const placed = new Set<string>();
  const sections: ArrangedSection[] = part.sections.map((raw) => {
    const own = (raw.fields ?? []).filter((f) => wanted.has(f));
    for (const f of own) placed.add(f);
    return {
      id: raw.id,
      names: { ...(raw.names ?? {}) },
      columns: raw.columns === 2 ? 2 : 1,
      collapsible: raw.collapsible === true,
      collapsed: raw.collapsed === true,
      fields: own,
    };
  });
  const rest = fields.filter((f) => !placed.has(f));
  const last = sections[sections.length - 1];
  if (rest.length > 0 && last !== undefined) last.fields.push(...rest);
  return { labelPosition: part.label_position ?? 'top', sections };
}
