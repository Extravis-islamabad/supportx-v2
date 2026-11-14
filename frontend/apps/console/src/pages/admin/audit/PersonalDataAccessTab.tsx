import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Select, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  queryKeys,
  usePersonalDataAccess,
  type PersonalDataAccessEntry,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';
import { EmptyText, useDateTime, useLabel } from '@supportx/ui';

import { UserPicker } from '../../incidents/pickers';

const PERIODS = ['week', 'month', 'quarter', 'year', 'all'] as const;
type Period = (typeof PERIODS)[number];
const PERIOD_DAYS: Record<Period, number | null> = {
  week: 7,
  month: 30,
  quarter: 91,
  year: 365,
  all: null,
};

function sinceFor(period: Period): string | undefined {
  const days = PERIOD_DAYS[period];
  return days === null ? undefined : new Date(Date.now() - days * 86_400_000).toISOString();
}

/**
 * Audit › Personal data access (WP-057 S3b-1, REQ-AUD-017): for a data subject request, everyone
 * who viewed or exported one person's personal data in a period, with time and screen (AC2).
 * Codes only, never values. Needs audit.view_personal_data_access; each query is audited by the
 * server. Live: a new entry refetches the open list.
 */
export function PersonalDataAccessTab() {
  const t = useLabel();
  const listFormat = useListFormat();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const [person, setPerson] = useState<string>();
  const [period, setPeriod] = useState<Period>('month');
  // Fixed when chosen: a moving "now" would refetch on every render.
  const [since, setSince] = useState<string | undefined>(() => sinceFor('month'));
  const access = usePersonalDataAccess(person, since);
  useListChannel('personal_data_access', () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.audit.personalDataAccessAll });
  });
  const rows = useMemo(() => access.data?.pages.flatMap((page) => page.items) ?? [], [access.data]);

  return (
    <Flex vertical gap={16} data-testid="personal-data-access">
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('audit.personal_access.intro')}
      </Typography.Paragraph>
      <Flex gap={8} wrap>
        <div style={{ minWidth: 260, flex: 1 }}>
          <UserPicker
            id="personal-access-person"
            value={person ?? null}
            onChange={(next) => {
              setPerson(next ?? undefined);
            }}
            ariaLabel={t('audit.personal_access.person')}
            testId="personal-access-person"
          />
        </div>
        <Select<Period>
          aria-label={t('audit.personal_access.period')}
          style={{ minWidth: 180 }}
          value={period}
          options={PERIODS.map((p) => ({
            value: p,
            label: t(`audit.personal_access.period.${p}`),
          }))}
          onChange={(next) => {
            setPeriod(next);
            setSince(sinceFor(next));
          }}
          data-testid="personal-access-period"
        />
      </Flex>
      {person === undefined ? (
        <EmptyText>{t('audit.personal_access.choose')}</EmptyText>
      ) : (
        <>
          <Table<PersonalDataAccessEntry>
            rowKey="id"
            size="small"
            loading={access.isLoading}
            dataSource={rows}
            pagination={false}
            scroll={{ x: true }}
            locale={{ emptyText: <EmptyText>{t('audit.personal_access.none')}</EmptyText> }}
            data-testid="personal-access-list"
            columns={[
              {
                key: 'when',
                title: t('audit.personal_access.when'),
                render: (_, row) => dates.format(row.occurred_at),
              },
              {
                key: 'who',
                title: t('audit.personal_access.who'),
                render: (_, row) => row.accessor_name ?? t(`audit_actor_type.${row.accessor_type}`),
              },
              {
                key: 'kind',
                title: t('audit.personal_access.kind'),
                render: (_, row) => t(`access_kind.${row.kind}`),
              },
              {
                key: 'where',
                title: t('audit.personal_access.where'),
                render: (_, row) => t(`access_purpose.${row.purpose}`),
              },
              {
                key: 'fields',
                title: t('audit.personal_access.fields'),
                render: (_, row) =>
                  listFormat(row.fields.map((field) => t(`access_field.${field}`))),
              },
            ]}
          />
          {access.hasNextPage && (
            <Button
              onClick={() => void access.fetchNextPage()}
              loading={access.isFetchingNextPage}
              data-testid="personal-access-more"
            >
              {t('audit.ui.load_more')}
            </Button>
          )}
        </>
      )}
    </Flex>
  );
}
