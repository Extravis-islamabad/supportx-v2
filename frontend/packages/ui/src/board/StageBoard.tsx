import { Button, Card, Dropdown, Flex, Typography } from 'antd';
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react';

import { useLabel } from '../appearance';

export interface BoardColumn {
  key: string;
  title: string;
  /**
   * How many records the column holds in all, when it shows only its first page (WP-046b S3b).
   * Absent: the cards it shows are all of them.
   */
  count?: number;
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
  whyNot,
  footer,
}: {
  columns: readonly BoardColumn[];
  cards: readonly C[];
  renderCard: (card: C) => ReactNode;
  onMove: (card: C, column: string) => Promise<string | null>;
  /** The board's name for assistive technology ("Releases by stage"). */
  label: string;
  testId?: string;
  /**
   * Why a card cannot move to a column, in words, or null when it may (WP-046b S3b). Such a
   * column stays in "Move to", reachable by keyboard with the reason in its name; choosing it, or
   * dropping on it, says the reason and never calls `onMove`. The server still decides.
   */
  whyNot?: (card: C, column: string) => string | null;
  /** Under a column's cards ("Show more"), when it shows only its first page. */
  footer?: (column: BoardColumn) => ReactNode;
}) {
  const t = useLabel();
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  // After a move, moved or refused, focus goes back to the card's "Move to"; when the card has
  // left the board (the view no longer shows it), to the column it went to, never the page.
  const moved = useRef<{ id: string; column: string } | null>(null);
  // The card may leave later, when the list refetches after the move: then its column's heading.
  useEffect(() => {
    const last = moved.current;
    if (last === null || cards.some((c) => c.id === last.id)) return;
    moved.current = null;
    // Focus somewhere real (a dialog the move opened, another control) is left where it is.
    const active = document.activeElement;
    if (active !== null && active !== document.body && active.isConnected) return;
    root.current
      ?.querySelector<HTMLElement>(`[data-testid="${testId}-heading-${CSS.escape(last.column)}"]`)
      ?.focus();
  }, [cards, testId]);
  const refocus = (card: C, column: string) => {
    moved.current = { id: card.id, column };
    requestAnimationFrame(() => {
      const scope = root.current;
      if (scope === null) return;
      const button = scope.querySelector<HTMLElement>(
        `[data-testid="${testId}-move-${CSS.escape(card.id)}"]`,
      );
      const heading = scope.querySelector<HTMLElement>(
        `[data-testid="${testId}-heading-${CSS.escape(column)}"]`,
      );
      (button ?? heading)?.focus();
    });
  };
  const move = async (card: C, column: string) => {
    if (card.column === column || busy) return;
    const reason = whyNot?.(card, column) ?? null;
    if (reason !== null) {
      setRefusal(reason); // said, and the card stays: onMove is never called
      refocus(card, column);
      return;
    }
    setBusy(true);
    setRefusal(null);
    try {
      setRefusal(await onMove(card, column));
    } finally {
      setBusy(false);
      refocus(card, column);
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
    <Flex vertical gap={8} data-testid={testId} ref={root}>
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
                <Typography.Text
                  strong
                  tabIndex={-1}
                  data-testid={`${testId}-heading-${column.key}`}
                >
                  {column.title}
                </Typography.Text>
                <Typography.Text type="secondary" data-testid={`${testId}-count-${column.key}`}>
                  {column.count !== undefined && column.count > inColumn.length
                    ? t('board.count_of', { shown: inColumn.length, count: column.count })
                    : (column.count ?? inColumn.length)}
                </Typography.Text>
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
                            .map((c) => {
                              const reason = whyNot?.(card, c.key) ?? null;
                              // Not antd's `disabled`: that skips the item on the keyboard, so
                              // the reason would never be heard (lane C). Focusable, marked
                              // unavailable, the reason in its name.
                              return reason === null
                                ? { key: c.key, label: c.title }
                                : {
                                    key: c.key,
                                    // rc-menu sets aria-disabled from `disabled` itself, so the
                                    // item stays enabled and says why in its own name.
                                    label: (
                                      <span>
                                        {c.title}
                                        <Typography.Text type="secondary">
                                          {' '}
                                          {/* eslint-disable-next-line supportx/no-raw-enum -- `reason` is the caller's own sentence in words (whyNot's contract), never a code */}
                                          ({reason})
                                        </Typography.Text>
                                      </span>
                                    ),
                                    'data-testid': `${testId}-unavailable-${c.key}`,
                                  };
                            }),
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
              {footer?.(column)}
            </section>
          );
        })}
      </div>
    </Flex>
  );
}
