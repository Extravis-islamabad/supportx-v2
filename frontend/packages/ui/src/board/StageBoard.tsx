import { Button, Card, Dropdown, Flex, Typography } from 'antd';
import { useState, type DragEvent, type ReactNode } from 'react';

import { useLabel } from '../appearance';

export interface BoardColumn {
  key: string;
  title: string;
}

export interface BoardCard {
  id: string;
  /** The column the card is in now. */
  column: string;
  /** What the card is called, for "Move … to …" and the screen reader. */
  name: string;
}

/**
 * A board of cards in columns (REQ-REL-056; WP-046 reuses it): a staged record's stages, or one
 * stage's statuses. Domain-free: the page says what a card shows and what a move means.
 *
 * A card moves by dragging it onto a column, or from its "Move to" menu (the keyboard's way,
 * in either direction of the page). `onMove` answers null when the move goes ahead (the page
 * opens its own dialog), or the reason in words when it is refused: the board then leaves the
 * card where it is and says why, where a screen reader hears it (AC1).
 */
export function StageBoard<C extends BoardCard>({
  columns,
  cards,
  renderCard,
  onMove,
  label,
  testId = 'stage-board',
}: {
  columns: readonly BoardColumn[];
  cards: readonly C[];
  renderCard: (card: C) => ReactNode;
  onMove: (card: C, column: string) => Promise<string | null>;
  /** The board's name for assistive technology ("Releases by stage"). */
  label: string;
  testId?: string;
}) {
  const t = useLabel();
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const move = async (card: C, column: string) => {
    if (card.column === column || busy) return;
    setBusy(true);
    setRefusal(null);
    try {
      setRefusal(await onMove(card, column));
    } finally {
      setBusy(false);
    }
  };
  const dropOn = (column: string) => (event: DragEvent) => {
    event.preventDefault();
    setOver(null);
    const card = cards.find((c) => c.id === event.dataTransfer.getData('text/plain'));
    setDragging(null);
    if (card !== undefined) void move(card, column);
  };
  return (
    <Flex vertical gap={8} data-testid={testId}>
      {/* Polite: a refused move is said once, and the board stays where it is. */}
      <Typography.Text
        type="danger"
        role="status"
        aria-live="polite"
        data-testid={`${testId}-refusal`}
      >
        {refusal ?? ''}
      </Typography.Text>
      <div
        role="region"
        aria-label={label}
        tabIndex={0}
        style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBlockEnd: 8 }}
      >
        {columns.map((column) => {
          const inColumn = cards.filter((c) => c.column === column.key);
          return (
            <section
              key={column.key}
              aria-label={column.title}
              onDragOver={(event) => {
                if (dragging === null) return;
                event.preventDefault(); // a drop target while a card is dragged
                setOver(column.key);
              }}
              onDragLeave={() => {
                setOver((now) => (now === column.key ? null : now));
              }}
              onDrop={dropOn(column.key)}
              style={{
                flex: '0 0 260px',
                minHeight: 160,
                padding: 8,
                borderRadius: 8,
                background: 'var(--ant-color-fill-quaternary, rgba(0,0,0,0.02))',
                outline:
                  over === column.key ? '2px dashed var(--ant-color-primary, #722ed1)' : 'none',
              }}
              data-testid={`${testId}-column-${column.key}`}
            >
              <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
                <Typography.Text strong>{column.title}</Typography.Text>
                <Typography.Text type="secondary">{inColumn.length}</Typography.Text>
              </Flex>
              <Flex vertical gap={8}>
                {inColumn.map((card) => (
                  <Card
                    key={card.id}
                    size="small"
                    draggable={!busy}
                    onDragStart={(event) => {
                      event.dataTransfer.setData('text/plain', card.id);
                      event.dataTransfer.effectAllowed = 'move';
                      setDragging(card.id);
                    }}
                    onDragEnd={() => {
                      setDragging(null);
                      setOver(null);
                    }}
                    style={{ cursor: busy ? 'progress' : 'grab' }}
                    data-testid={`${testId}-card-${card.id}`}
                  >
                    <Flex vertical gap={4}>
                      {renderCard(card)}
                      <Dropdown
                        trigger={['click']}
                        disabled={busy}
                        menu={{
                          items: columns
                            .filter((c) => c.key !== card.column)
                            .map((c) => ({ key: c.key, label: c.title })),
                          onClick: ({ key }) => void move(card, key),
                        }}
                      >
                        <Button
                          size="small"
                          type="link"
                          style={{ paddingInline: 0, alignSelf: 'flex-start' }}
                          // The name starts with the visible words (WCAG 2.5.3), then the card.
                          aria-label={`${t('board.move_to')} ${card.name}`}
                          data-testid={`${testId}-move-${card.id}`}
                        >
                          {t('board.move_to')}
                        </Button>
                      </Dropdown>
                    </Flex>
                  </Card>
                ))}
              </Flex>
            </section>
          );
        })}
      </div>
    </Flex>
  );
}
