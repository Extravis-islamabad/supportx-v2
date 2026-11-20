import {
  useIncident,
  useIncidentAssignees,
  useIncidentBoard,
  useIncidentCatalogue,
  useIncidents,
  useUnits,
  type BoardGroupBy,
  type FilterExpression,
  type IncidentCatalogue,
  type IncidentListItem,
} from '@supportx/api-client';
import {
  StageBoard,
  useAppearance,
  useLabel,
  type BoardCard,
  type BoardColumn,
} from '@supportx/ui';
import { Button, Dropdown, Flex, Segmented, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import { AssignDialog } from '../assign';
import { scaleLabel, statusLabel } from '../labels';
import { useStatusActions } from '../StatusActions';
import { BOARD_COLUMNS_SHOWN, both, columnCondition } from './boardModel';
import { PriorityMoveDialog } from './PriorityMoveDialog';

/** Each column's first page (lane C's condition 1); "Show more" loads the next. */
const PAGE = 25;
const NONE = '__none__';

interface Card extends BoardCard {
  row: IncidentListItem;
}

interface Loaded {
  rows: IncidentListItem[];
  people: Record<string, { display_name: string }>;
  more: boolean;
  loadMore: () => void;
}

/** One column's records: the view's own query plus the column's condition, a page at a time. */
function ColumnRows({
  view,
  tag,
  filter,
  groupBy,
  columnKey,
  onLoaded,
}: {
  view?: string;
  tag?: string;
  filter?: FilterExpression;
  groupBy: BoardGroupBy;
  columnKey: string | null;
  onLoaded: (column: string, loaded: Loaded) => void;
}) {
  const list = useIncidents({
    view,
    tag,
    filter: both(filter, columnCondition(groupBy, columnKey)),
    limit: PAGE,
  });
  const { data, hasNextPage, fetchNextPage } = list;
  useEffect(() => {
    onLoaded(columnKey ?? NONE, {
      rows: (data?.pages ?? []).flatMap((p) => p.items),
      people: Object.assign({}, ...(data?.pages ?? []).map((p) => p.people)) as Loaded['people'],
      more: hasNextPage,
      loadMore: () => void fetchNextPage(),
    });
  }, [data, hasNextPage, fetchNextPage, columnKey, onLoaded]);
  return null;
}

/**
 * A status move (REQ-INC-111): the record's own action that leads to the column, through the
 * record page's own action handling, so its reason, resolution and confirmation dialogs ask
 * exactly as they do there. Answers the board once: null when the action goes ahead (its dialog,
 * if any, is open), or why it cannot, in words. The server still decides.
 */
function StatusMove({
  id,
  target,
  catalogue,
  answer,
  done,
}: {
  id: string;
  target: string;
  catalogue: IncidentCatalogue | undefined;
  answer: (reason: string | null) => void;
  done: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const item = useIncident(id);
  const answered = useRef(false);
  const failed = item.isError;
  useEffect(() => {
    // Gone or out of reach since the list was read: said in words, and nothing moves.
    if (!failed || answered.current) return;
    answered.current = true;
    answer(t('incidents.board.unavailable'));
    done();
  }, [failed, answer, done, t]);
  if (item.data === undefined) return null;
  return (
    <StatusMoveFor
      item={item.data}
      target={target}
      catalogue={catalogue}
      answer={(reason) => {
        if (answered.current) return;
        answered.current = true;
        answer(reason);
      }}
      done={done}
      names={(code) => statusLabel(t, catalogue, code, locale)}
    />
  );
}

function StatusMoveFor({
  item,
  target,
  catalogue,
  answer,
  done,
  names,
}: {
  item: NonNullable<ReturnType<typeof useIncident>['data']>;
  target: string;
  catalogue: IncidentCatalogue | undefined;
  answer: (reason: string | null) => void;
  done: () => void;
  names: (code: string) => string;
}) {
  const t = useLabel();
  const { actions, dialogs } = useStatusActions(item, catalogue);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const leading = (catalogue?.transitions ?? []).filter(
      (tr) =>
        tr.from_status === item.status &&
        tr.to_status === target &&
        tr.lifecycle === item.lifecycle,
    );
    const action = actions.find((a) => leading.some((tr) => tr.action === a.key));
    if (action === undefined) {
      answer(t('incidents.board.no_move', { from: names(item.status), to: names(target) }));
      done();
    } else if (!action.allowed) {
      answer(
        action.whyNot ??
          t('incidents.board.no_move', { from: names(item.status), to: names(target) }),
      );
      done();
    } else {
      answer(null); // the action asks its own questions; the list refreshes when it is made
      action.onClick();
    }
  }, [actions, answer, catalogue, done, item, names, t, target]);
  return <>{dialogs}</>;
}

/**
 * The incident list as a board (REQ-INC-111; WP-046b S3b): grouped by status, priority,
 * technician or group, each column the view's own query plus its condition, a page at a time,
 * its count the server's (records you may see). A move runs the real action: the status's
 * transition, assign (D-154: the group rule on the server), or the priority change with its
 * reason. Nothing moves that you could not do on the record; a refused move stays and says why.
 */
export function IncidentBoard({
  view,
  tag,
  filter,
  groupBy,
  onGroupBy,
}: {
  view?: string;
  tag?: string;
  filter?: FilterExpression;
  groupBy: BoardGroupBy;
  onGroupBy: (next: BoardGroupBy) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const catalogue = useIncidentCatalogue();
  const groups = useUnits('groups');
  // People's names for a board by technician: those who can be assigned, then the loaded rows'
  // (a column under "More columns" has no rows loaded; matrix run 44751058148 named one
  // "someone you can't see").
  const assignable = useIncidentAssignees(null, '', groupBy === 'technician');
  const counts = useIncidentBoard({ view, tag, filter }, groupBy);
  // Kept by the query they were asked for: a new grouping or query reads afresh, never an
  // older answer (by the filter's text, not its identity).
  const asked = JSON.stringify([groupBy, view ?? null, tag ?? null, filter ?? null]);
  const [loadedBy, setLoaded] = useState<Record<string, Loaded>>({});
  const [extraBy, setExtra] = useState<Record<string, string[]>>({});
  const extra = extraBy[asked] ?? [];
  const loaded: Record<string, Loaded> = Object.fromEntries(
    Object.entries(loadedBy)
      .filter(([k]) => k.startsWith(`${asked}|`))
      .map(([k, v]) => [k.slice(asked.length + 1), v]),
  );
  const [moving, setMoving] = useState<
    | { kind: 'status'; id: string; target: string; answer: (r: string | null) => void }
    | { kind: 'assign' | 'priority'; card: Card; target: string | null }
    | null
  >(null);
  const onLoaded = useCallback(
    (column: string, next: Loaded) => {
      setLoaded((now) => ({ ...now, [`${asked}|${column}`]: next }));
    },
    [asked],
  );

  const all = useMemo(() => counts.data ?? [], [counts.data]);
  // Statuses and priorities: every one, in their order. People and groups: the first twelve in
  // their stable order, plus any picked from "More columns".
  const fixed = groupBy === 'status' || groupBy === 'priority';
  const shown = fixed
    ? all
    : all.filter((c, i) => i < BOARD_COLUMNS_SHOWN || extra.includes(c.key ?? NONE));
  const hidden = fixed ? [] : all.filter((c) => !shown.includes(c));
  const people = Object.assign(
    {},
    ...Object.values(loaded).map((l) => l.people),
  ) as Loaded['people'];
  const title = (key: string | null): string => {
    if (key === null) return t(`incidents.board.none_${groupBy}`);
    if (groupBy === 'status') return statusLabel(t, catalogue.data, key, locale);
    if (groupBy === 'priority') return scaleLabel(t, catalogue.data, 'priority', key, locale);
    if (groupBy === 'group')
      return groups.data?.find((g) => g.id === key)?.name ?? t('incidents.board.unknown_group');
    return (
      assignable.data?.find((p) => p.id === key)?.display_name ??
      people[key]?.display_name ??
      t('incidents.board.unknown_person')
    );
  };
  const columns: BoardColumn[] = shown.map((c) => ({
    key: c.key ?? NONE,
    title: title(c.key),
    count: c.count,
  }));
  const cards: Card[] = shown.flatMap((c) =>
    (loaded[c.key ?? NONE]?.rows ?? []).map((row) => ({
      id: row.id,
      column: c.key ?? NONE,
      name: row.display_id,
      row,
    })),
  );

  const onMove = (card: Card, column: string): Promise<string | null> => {
    const target = column === NONE ? null : column;
    if (groupBy === 'status') {
      if (target === null) return Promise.resolve(t('incidents.board.unavailable'));
      return new Promise((resolve) => {
        setMoving({ kind: 'status', id: card.id, target, answer: resolve });
      });
    }
    setMoving({ kind: groupBy === 'priority' ? 'priority' : 'assign', card, target });
    return Promise.resolve(null); // its dialog asks; the server decides
  };

  return (
    <Flex vertical gap={8} data-testid="inc-board">
      <Flex gap={8} wrap align="center" justify="space-between">
        <Segmented<BoardGroupBy>
          aria-label={t('incidents.board.group_by')}
          value={groupBy}
          onChange={onGroupBy}
          options={(['status', 'priority', 'technician', 'group'] as const).map((value) => ({
            value,
            label: t(`board_group_by.${value}`),
          }))}
          data-testid="inc-board-group-by"
        />
        {hidden.length > 0 && (
          // A real button with a menu (lane C): keyboard and screen reader alike.
          <Dropdown
            trigger={['click']}
            menu={{
              items: hidden.map((c) => ({
                key: c.key ?? NONE,
                label: `${title(c.key)} (${String(c.count)})`,
              })),
              onClick: ({ key }) => {
                setExtra((now) => ({ ...now, [asked]: [...(now[asked] ?? []), key] }));
              },
            }}
          >
            <Button data-testid="inc-board-more-columns">
              {t('incidents.board.more_columns', { count: hidden.length })}
            </Button>
          </Dropdown>
        )}
      </Flex>
      {shown.map((c) => (
        <ColumnRows
          key={`${groupBy}:${c.key ?? NONE}`}
          view={view}
          tag={tag}
          filter={filter}
          groupBy={groupBy}
          columnKey={c.key}
          onLoaded={onLoaded}
        />
      ))}
      {/* Its own sideways scroll (StageBoard's region): at 390 the page itself never scrolls. */}
      <div style={{ maxWidth: '100%', minWidth: 0 }}>
        <StageBoard<Card>
          columns={columns}
          cards={cards}
          label={t('incidents.board.label', { by: t(`board_group_by.${groupBy}`) })}
          testId="inc-board-stage"
          onMove={onMove}
          whyNot={(_card, column) =>
            // Only what the list already knows; the action itself refuses everything else.
            groupBy === 'status' && column === NONE ? t('incidents.board.unavailable') : null
          }
          footer={(column) => {
            const l = loaded[column.key];
            return l?.more === true ? (
              <Button
                type="link"
                size="small"
                onClick={l.loadMore}
                data-testid={`inc-board-show-more-${column.key}`}
              >
                {t('incidents.board.show_more', { title: column.title })}
              </Button>
            ) : null;
          }}
          renderCard={(card) => (
            <Typography.Link onClick={() => void navigate(`/incidents/${card.id}`)}>
              <bdi dir="ltr" style={{ fontWeight: 600 }}>
                {card.row.display_id}
              </bdi>{' '}
              {card.row.subject}
            </Typography.Link>
          )}
        />
      </div>
      {moving?.kind === 'status' && (
        <StatusMove
          id={moving.id}
          target={moving.target}
          catalogue={catalogue.data}
          answer={moving.answer}
          done={() => {
            setMoving(null);
          }}
        />
      )}
      {moving !== null && moving.kind !== 'status' && (
        <CardDialog
          kind={moving.kind}
          id={moving.card.id}
          groupBy={groupBy}
          target={moving.target}
          onClose={() => {
            setMoving(null);
          }}
        />
      )}
    </Flex>
  );
}

/** Assign or priority for a moved card: the record's own dialog, preset to the column. */
function CardDialog({
  kind,
  id,
  groupBy,
  target,
  onClose,
}: {
  kind: 'assign' | 'priority';
  id: string;
  groupBy: BoardGroupBy;
  target: string | null;
  onClose: () => void;
}) {
  const item = useIncident(id);
  if (item.data === undefined) return null;
  return kind === 'assign' ? (
    <AssignDialog
      item={item.data}
      open
      onClose={onClose}
      refresh={() => item.refetch()}
      preset={groupBy === 'group' ? { groupId: target } : { technicianId: target }}
    />
  ) : (
    <PriorityMoveDialog item={item.data} priority={target} onClose={onClose} />
  );
}
