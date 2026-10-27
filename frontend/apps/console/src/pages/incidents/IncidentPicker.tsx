import { useQueryClient } from '@tanstack/react-query';
import { Select, Space, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  queryKeys,
  useIncidentCatalogue,
  useIncidentSearch,
  useSession,
  type IncidentListItem,
  type IncidentPerson,
  type StatusCategory,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAppearance, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { personName, statusLabel } from './labels';
import { recentIncidents } from './recent';

const CATEGORIES: StatusCategory[] = ['open', 'paused', 'resolved', 'closed', 'canceled'];

export interface IncidentPickerProps {
  id?: string;
  value: string | null;
  onChange: (id: string | null, item: IncidentListItem | null) => void;
  /**
   * The record the pick is for (a link or merge from it): left out of the results, and its
   * requester's other incidents are offered before anything is typed.
   */
  from?: { id: string; requesterId: string; requesterName: string };
  testId: string;
  ariaLabel: string;
}

interface Group {
  label: string;
  items: IncidentListItem[];
}

/**
 * Pick an incident (REQ-INC-085), for links, merges and parents: search everything the user may
 * see, exactly as the lists do, by display ID, words, requester or status. Before anything is
 * typed it offers recently viewed incidents and the same requester's, never a narrow default
 * view that hides the right record. Results stay live (any change to incidents refreshes them).
 */
export function IncidentPicker({
  id,
  value,
  onChange,
  from,
  testId,
  ariaLabel,
}: IncidentPickerProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const me = useSession().data?.user.id ?? null;
  const catalogue = useIncidentCatalogue();
  const [typed, setTyped] = useState('');
  const [categories, setCategories] = useState<StatusCategory[]>([]);
  const text = useDebounced(typed.trim());
  const searching = text !== '';
  const statusCategories = categories.length === 0 ? undefined : categories;
  const results = useIncidentSearch({ q: text, statusCategories, limit: 20 }, searching);
  const recentIds = useMemo(
    () => recentIncidents(me).filter((other) => other !== from?.id),
    [me, from?.id],
  );
  const recent = useIncidentSearch({ ids: recentIds, statusCategories }, !searching);
  const same = useIncidentSearch(
    { requesterId: from?.requesterId, statusCategories, limit: 10 },
    !searching && from !== undefined,
  );

  const queryClient = useQueryClient();
  useListChannel('incidents', () => {
    refreshList(queryClient, [...queryKeys.incidents.all, 'list', 'search']);
  });

  const people: Record<string, IncidentPerson> = {
    ...recent.data?.people,
    ...same.data?.people,
    ...results.data?.people,
  };
  const groups: Group[] = searching
    ? [{ label: t('search.results'), items: results.data?.items ?? [] }]
    : [
        {
          label: t('search.recent'),
          // In the order they were viewed, not the order the server returned them.
          items: [...(recent.data?.items ?? [])].sort(
            (a, b) => recentIds.indexOf(a.id) - recentIds.indexOf(b.id),
          ),
        },
        ...(from === undefined
          ? []
          : [
              {
                label: t('search.same_requester', { name: from.requesterName }),
                items: same.data?.items ?? [],
              },
            ]),
      ];
  const shown = new Set<string>();
  const byId = new Map<string, IncidentListItem>();
  const options = groups
    .map((group) => ({
      label: group.label,
      title: group.label,
      options: group.items
        .filter((item) => item.id !== from?.id && !shown.has(item.id) && shown.add(item.id))
        .map((item) => {
          byId.set(item.id, item);
          const requester = personName(people, item.requester_id);
          const statusText = statusLabel(t, catalogue.data, item.status, locale);
          return {
            value: item.id,
            name: `${item.display_id} ${item.subject}`,
            'aria-label': `${item.display_id}, ${item.subject}, ${requester}, ${statusText}`,
            label: (
              <Space
                direction="vertical"
                size={0}
                data-testid={`${testId}-option-${item.display_id}`}
              >
                <Typography.Text>
                  <bdi>{item.display_id}</bdi> <bdi>{item.subject}</bdi>
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  <bdi>{requester}</bdi> · {statusText}
                </Typography.Text>
              </Space>
            ),
          };
        }),
    }))
    .filter((group) => group.options.length > 0);
  const loading = searching ? results.isFetching : recent.isFetching || same.isFetching;

  return (
    <Space.Compact style={{ width: '100%' }}>
      <Select
        id={id}
        showSearch
        allowClear
        filterOption={false}
        value={value}
        aria-label={ariaLabel}
        placeholder={t('search.find_incident')}
        searchValue={typed}
        onSearch={setTyped}
        onChange={(next: string | undefined) => {
          onChange(next ?? null, next === undefined ? null : (byId.get(next) ?? null));
        }}
        options={options}
        optionLabelProp="name"
        loading={loading}
        notFoundContent={t(searching ? 'search.nothing_found' : 'search.type_to_search')}
        data-testid={testId}
        style={{ flex: 1, minWidth: 0 }}
      />
      <Select
        mode="multiple"
        allowClear
        maxTagCount="responsive"
        value={categories}
        onChange={setCategories}
        aria-label={t('search.status_filter')}
        placeholder={t('search.status_filter')}
        options={CATEGORIES.map((code) => ({ value: code, label: t(`status_category.${code}`) }))}
        data-testid={`${testId}-status`}
        style={{ width: 160 }}
      />
    </Space.Compact>
  );
}
