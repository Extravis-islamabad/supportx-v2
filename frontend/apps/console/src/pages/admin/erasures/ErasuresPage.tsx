import { useQueryClient } from '@tanstack/react-query';
import { Select, Table, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ERASURE_STATES,
  OPEN_ERASURE_STATES,
  erasureKeys,
  useErasures,
  type Erasure,
  type ErasureState,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  FilterBar,
  ListPage,
  NoAccess,
  PageHeader,
  ToneTag,
  loadedEmpty,
  useAccess,
  useDateTime,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { ERASE, STATE_TONES } from './erasureText';
import { PersonName, StepProgress } from './words';
type View = 'open' | 'closed' | 'all';
const CLOSED: readonly ErasureState[] = ERASURE_STATES.filter(
  (s) => !(OPEN_ERASURE_STATES as readonly string[]).includes(s),
);
const IN_VIEW: Record<View, readonly ErasureState[]> = {
  open: OPEN_ERASURE_STATES,
  closed: CLOSED,
  all: ERASURE_STATES,
};

/**
 * Admin › Erasures (ADR-052, D-171; template C): every erasure of the tenant, newest first, with
 * its state, progress and who asked and decided. Live: an erasure that moves on refetches the
 * list (the `person_erasures` channel names the erasure only).
 */
export function ErasuresPage() {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const queryClient = useQueryClient();
  const allowed = can(ERASE);
  const [view, setView] = useState<View>('open');
  const [state, setState] = useState<ErasureState>();
  const found = useErasures({ states: state === undefined ? IN_VIEW[view] : [state] }, allowed);
  usePageCrumbs([{ label: t('people_erasure.title') }]);
  useListChannel(allowed ? 'person_erasures' : null, (message) => {
    if (message.type !== 'person_erasures.changed') return;
    void queryClient.invalidateQueries({ queryKey: ['erasures', 'list'] });
    for (const id of message.ids) {
      void queryClient.invalidateQueries({ queryKey: erasureKeys.detail(id) });
    }
  });
  if (!allowed) return <NoAccess titleKey="people_erasure.title" />;
  const rows = found.data?.items ?? [];
  return (
    <ListPage
      testId="erasures"
      header={
        <PageHeader
          title={t('people_erasure.title')}
          count={found.data === undefined ? undefined : String(rows.length)}
          testId="erasures-header"
        />
      }
      filters={
        <FilterBar
          testId="erasures-filters"
          view={
            <Select<View>
              style={{ minWidth: 150 }}
              prefix={`${t('people_erasure.view_label')}:`}
              aria-label={t('people_erasure.view_label')}
              value={view}
              onChange={(next) => {
                setView(next);
                setState(undefined);
              }}
              options={(['open', 'closed', 'all'] as const).map((v) => ({
                value: v,
                label: t(`people_erasure.view.${v}`),
              }))}
              data-testid="erasures-view"
            />
          }
          quick={
            <Select<ErasureState>
              allowClear
              style={{ minWidth: 190 }}
              aria-label={t('people_erasure.state_label')}
              placeholder={t('people_erasure.any_state')}
              value={state}
              onChange={(next: ErasureState | undefined) => {
                setState(next);
              }}
              options={IN_VIEW[view].map((s) => ({
                value: s,
                label: t(`people_erasure.state.${s}`),
              }))}
              data-testid="erasures-state"
            />
          }
        />
      }
    >
      <Table<Erasure>
        rowKey="id"
        data-testid="erasures-table"
        loading={found.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 860 }}
        locale={{ emptyText: loadedEmpty(found.isPending, t('people_erasure.none')) }}
        columns={[
          {
            key: 'person',
            title: t('people_erasure.column.person'),
            render: (_, r) => (
              <Link to={`/admin/erasures/${r.id}`} data-testid={`erasure-link-${r.id}`}>
                <PersonName id={r.person_id} erased={r.state === 'done'} />
              </Link>
            ),
          },
          {
            key: 'state',
            title: t('people_erasure.column.state'),
            render: (_, r) => (
              <ToneTag tone={STATE_TONES[r.state]} testId={`erasure-state-${r.id}`}>
                {t(`people_erasure.state.${r.state}`)}
              </ToneTag>
            ),
          },
          {
            key: 'progress',
            title: t('people_erasure.column.progress'),
            render: (_, r) => <StepProgress step={r.step} steps={r.steps} />,
          },
          {
            key: 'requested',
            title: t('people_erasure.column.requested'),
            render: (_, r) => (
              <span>
                <PersonName id={r.requested_by} />
                <Typography.Text type="secondary">
                  {' · '}
                  <span title={dates.format(r.requested_at)}>{dates.relative(r.requested_at)}</span>
                </Typography.Text>
              </span>
            ),
          },
          {
            key: 'expires',
            title: t('people_erasure.column.expires'),
            render: (_, r) =>
              r.state === 'requested' ? (
                <span title={dates.format(r.expires_at)}>{dates.relative(r.expires_at)}</span>
              ) : null,
          },
          {
            key: 'approved',
            title: t('people_erasure.approved_by'),
            render: (_, r) => <PersonName id={r.approved_by ?? null} />,
          },
        ]}
      />
    </ListPage>
  );
}
