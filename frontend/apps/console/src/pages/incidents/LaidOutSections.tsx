import { Col, Collapse, Form, Row } from 'antd';
import { useState, type ReactElement } from 'react';

import type { ArrangedForm, ArrangedSection } from '@supportx/forms';
import { FormSection, useAppearance, useLabel } from '@supportx/ui';

// A template's create form drawn from the designer's layout (WP-046a S5b; REQ-INC-036): the
// sections in order, one or two columns, collapsible ones in a collapse panel, labels above or
// beside the fields. The fields themselves are the form's own elements (by name), so a layout
// changes where they are, never how they work: their rules, checks and test ids stay.

export interface PlacedField {
  element: ReactElement;
  /** Takes the whole row whatever the columns (description, long text). */
  wide: boolean;
}

/** A section's heading in the reader's language, else English, else the generic word. */
function sectionName(
  section: Pick<ArrangedSection, 'names'>,
  locale: string,
  fallback: string,
): string {
  return section.names[locale] ?? section.names.en ?? fallback;
}

export function LaidOutSections({
  arranged,
  fields,
  errored,
  testIdPrefix,
}: {
  arranged: ArrangedForm;
  fields: ReadonlyMap<string, PlacedField>;
  /** Fields with an error now: a collapsed section holding one opens, so it is seen (lane C). */
  errored: ReadonlySet<string>;
  testIdPrefix: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const beside = arranged.labelPosition === 'start';
  // Which collapsible sections the person has open (those not starting closed, at first).
  const [opened, setOpened] = useState<ReadonlySet<string>>(
    () => new Set(arranged.sections.filter((s) => !s.collapsed).map((s) => s.id)),
  );
  return (
    <>
      {arranged.sections.map((section) => {
        const placed = section.fields.flatMap((name) => {
          const found = fields.get(name);
          return found === undefined ? [] : [{ name, ...found }];
        });
        if (placed.length === 0) return null; // nothing of it is on the form now
        const content = (
          // Labels above or beside: a form context of its own (react-hook-form keeps the
          // values; this only lays out the items).
          <Form
            component={false}
            layout={beside ? 'horizontal' : 'vertical'}
            labelCol={beside ? { flex: '150px' } : undefined}
            wrapperCol={beside ? { flex: 1 } : undefined}
            labelWrap
            labelAlign="left"
            colon={false}
          >
            <Row gutter={16}>
              {placed.map(({ name, element, wide }) => (
                <Col key={name} xs={24} md={section.columns === 2 && !wide ? 12 : 24}>
                  {element}
                </Col>
              ))}
            </Row>
          </Form>
        );
        const title = sectionName(section, locale, t('templates.section_untitled'));
        const testId = `${testIdPrefix}-${section.id}`;
        if (section.collapsible) {
          const open = opened.has(section.id) || section.fields.some((f) => errored.has(f));
          return (
            <Collapse
              key={section.id}
              activeKey={open ? [section.id] : []}
              onChange={(keys) => {
                const next = new Set(opened);
                if ((Array.isArray(keys) ? keys : [keys]).includes(section.id)) {
                  next.add(section.id);
                } else next.delete(section.id);
                setOpened(next);
              }}
              // Mounted while closed too: its fields keep their values and checks.
              items={[{ key: section.id, label: title, children: content, forceRender: true }]}
              data-testid={testId}
            />
          );
        }
        return (
          <FormSection key={section.id} title={title} testId={testId}>
            {content}
          </FormSection>
        );
      })}
    </>
  );
}
