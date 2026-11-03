import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Select, Space, Table } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  serviceRequestKeys,
  useCatalogItems,
  useServiceRequests,
  useServiceRequestViews,
  type ApprovalStatus,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  PageHeader,
  reportError,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { itemName } from './items';

const APPROVAL: ApprovalStatus[] = ['pending', 'approved', 'rejected', 'withdrawn', 'not_needed'];

/**
 * Service requests (WP-030, REQ-SR-009): the list with the item and the approval status, a filter
 * by approval status, the built-in views with counts, live through the list channel. The full record page arrives with the
 * approval engine; a row opens the request's summary.
 */
export function RequestsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const { can } = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [approval, setApproval] = useState<ApprovalStatus | undefined>(undefined);
  const [view, setView] = useState<string | undefined>(undefined);
  const list = useServiceRequests({ approval_status: approval, view });
  const views = useServiceRequestViews();
  const items = useCatalogItems();
  const byId = new Map((items.data ?? []).map((i) => [i.id, i]));
  useListChannel('service-requests', () => {
    void queryClient.invalidateQueries({ queryKey: [...serviceRequestKeys.all, 'list'] });
  });
  if (list.error) reportError(list.error);
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <PageHeader
        title={t('nav.requests')}
        extra={
          can('requests.create') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => void navigate('/requests/new')}
              data-testid="sr-new"
            >
              {t('requests.new')}
            </Button>
          )
        }
      />
      <Space wrap>
        <Select
          allowClear
          value={view}
          onChange={(value: string | undefined) => {
            setView(value);
          }}
          placeholder={t('requests.view_filter')}
          aria-label={t('requests.view_filter')}
          style={{ minWidth: 260 }}
          options={(views.data ?? []).map((v) => ({
            value: v.view,
            label: `${t(`work_item_view.${v.view}`)} (${String(v.count)}${v.capped ? '+' : ''})`,
          }))}
          data-testid="sr-view-filter"
        />
        <Select
          allowClear
          value={approval}
          onChange={(value: ApprovalStatus | undefined) => {
            setApproval(value);
          }}
          placeholder={t('requests.approval_filter')}
          aria-label={t('requests.approval_filter')}
          style={{ minWidth: 220 }}
          options={APPROVAL.map((code) => ({ value: code, label: t(`approval_status.${code}`) }))}
          data-testid="sr-approval-filter"
        />
      </Space>
      <Table
        rowKey="id"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        pagination={false}
        data-testid="sr-list"
        columns={[
          {
            key: 'id',
            title: t('incidents.col.id'),
            render: (_, row) => (
              <Link to={`/requests/${row.id}`} data-testid={`sr-row-${row.display_id}`}>
                <span dir="ltr">{row.display_id}</span>
              </Link>
            ),
          },
          { key: 'subject', title: t('incidents.col.subject'), dataIndex: 'subject' },
          {
            key: 'item',
            title: t('requests.item'),
            render: (_, row) => itemName(byId.get(row.catalog_item_id ?? ''), locale),
          },
          {
            key: 'status',
            title: t('incidents.col.status'),
            render: (_, row) => t(`work_item_status.${row.status}`),
          },
          {
            key: 'approval',
            title: t('requests.approval'),
            render: (_, row) =>
              row.approval_status == null ? '' : t(`approval_status.${row.approval_status}`),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            render: (_, row) => format(row.updated_at),
          },
        ]}
      />
    </Space>
  );
}
