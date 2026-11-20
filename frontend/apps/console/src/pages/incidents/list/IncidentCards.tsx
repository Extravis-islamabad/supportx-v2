import type { IncidentListItem } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';
import { Card, Checkbox, Flex, Segmented, Typography, theme } from 'antd';
import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import type { ColumnContext, ColumnSpec } from './columns';

type CardDensity = 'comfortable' | 'compact';

/**
 * The incident list as cards (REQ-INC-111): the same rows, order, selection and bulk bar as the
 * table, with S3a's cues (lane C): the unread dot with "Unread" in words and bold, and the row's
 * colour mark at the card's start.
 */
export function IncidentCards({
  rows,
  specs,
  context,
  unread,
  markOf,
  selected,
  onSelect,
  empty,
  footer,
}: {
  rows: readonly IncidentListItem[];
  specs: readonly ColumnSpec[];
  context: ColumnContext;
  unread: ReadonlySet<string>;
  markOf: (row: IncidentListItem) => string | undefined;
  selected: ReadonlySet<string> | null;
  onSelect: ((id: string, on: boolean) => void) | null;
  empty: ReactNode;
  footer?: ReactNode;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [density, setDensity] = useState<CardDensity>('comfortable');
  const compact = density === 'compact';
  return (
    <Flex vertical gap={8} data-testid="inc-cards">
      <Segmented<CardDensity>
        aria-label={t('incidents.cards.density')}
        value={density}
        onChange={(next) => {
          setDensity(next);
        }}
        options={[
          { value: 'comfortable', label: t('incidents.cards.comfortable') },
          { value: 'compact', label: t('incidents.cards.compact') },
        ]}
        style={{ alignSelf: 'end' }}
        data-testid="inc-cards-density"
      />
      {rows.length === 0 ? (
        empty
      ) : (
        <div
          role="list"
          aria-label={t('incidents.cards.label')}
          style={{
            display: 'grid',
            gap: compact ? 6 : 12,
            gridTemplateColumns: `repeat(auto-fill, minmax(min(${String(compact ? 220 : 280)}px, 100%), 1fr))`,
          }}
        >
          {rows.map((row) => {
            const isUnread = unread.has(row.id);
            const mark = markOf(row);
            return (
              <Card
                key={row.id}
                role="listitem"
                size="small"
                data-testid={`inc-card-${row.display_id}`}
                data-row-mark={mark}
                styles={{ body: { padding: compact ? 8 : 12 } }}
                style={{
                  borderInlineStart: mark === undefined ? undefined : `4px solid ${mark}`,
                }}
              >
                <Flex gap={8} align="start">
                  {onSelect !== null && selected !== null && (
                    <Checkbox
                      checked={selected.has(row.id)}
                      onChange={(event) => {
                        onSelect(row.id, event.target.checked);
                      }}
                      aria-label={t('incidents.bulk.select_row', { id: row.display_id })}
                    />
                  )}
                  <Flex vertical gap={compact ? 2 : 6} style={{ minWidth: 0, flex: 1 }}>
                    <Typography.Link
                      onClick={() => void navigate(`/incidents/${row.id}`)}
                      strong={isUnread}
                      data-testid={`inc-card-open-${row.display_id}`}
                      style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
                    >
                      {isUnread && (
                        <>
                          <span
                            aria-hidden="true"
                            data-testid="inc-unread-dot"
                            style={{
                              display: 'inline-block',
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              background: token.colorPrimary,
                              marginInlineEnd: 6,
                            }}
                          />
                          <span className="sx-visually-hidden">{t('incidents.unread')}</span>
                        </>
                      )}
                      <bdi dir="ltr" style={{ fontWeight: 600 }}>
                        {row.display_id}
                      </bdi>{' '}
                      {row.subject}
                    </Typography.Link>
                    <Flex gap={compact ? 6 : 12} wrap>
                      {specs.map((spec) => (
                        <Flex key={spec.key} gap={4} align="center" style={{ minWidth: 0 }}>
                          {!compact && (
                            <Typography.Text type="secondary">
                              {spec.title(context)}:
                            </Typography.Text>
                          )}
                          {compact && (
                            // The field's name for a screen reader (no aria-label on a plain
                            // span: axe aria-prohibited-attr).
                            <span className="sx-visually-hidden">{spec.title(context)}: </span>
                          )}
                          <span>{spec.render(row, context)}</span>
                        </Flex>
                      ))}
                    </Flex>
                  </Flex>
                </Flex>
              </Card>
            );
          })}
        </div>
      )}
      {footer}
    </Flex>
  );
}
