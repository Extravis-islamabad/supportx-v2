import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  InboxOutlined,
  PlusOutlined,
  UserAddOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Empty, Flex, Form, Select, Skeleton, Table, theme } from 'antd';
import type { ReactNode } from 'react';
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
  ChannelIcon,
  PageHeader,
  ToneTag,
  reportError,
  useAccess,
  useAppearance,
  useColumnWidths,
  useDateTime,
  useLabel,
  type Tone,
} from '@supportx/ui';

import { itemName } from './items';

const APPROVAL: ApprovalStatus[] = ['pending', 'approved', 'rejected', 'withdrawn', 'not_needed'];
// The views shown as tiles (UI pass 2, QA 2026-11-04 #6): the work a desk acts on first. Every
// other built-in view stays in the "View" picker.
type TileTone = 'error' | 'warning' | 'info' | 'success' | 'purple';
const TILES: { view: string; icon: ReactNode; tone: TileTone }[] = [
  { view: 'my_open', icon: <InboxOutlined />, tone: 'info' },
  { view: 'pending_approval', icon: <ClockCircleOutlined />, tone: 'warning' },
  { view: 'awaiting_fulfilment', icon: <CheckCircleOutlined />, tone: 'success' },
  { view: 'unassigned_in_my_groups', icon: <UserAddOutlined />, tone: 'purple' },
  { view: 'overdue', icon: <WarningOutlined />, tone: 'error' },
];
const STATUS_TONES: Record<string, Tone> = {
  open: 'info',
  waiting: 'warning',
  resolved: 'success',
  closed: 'default',
  canceled: 'default',
};

/** The view counts as tiles: the number large, the view's name below; pressing one filters. */
function ViewTiles({ active, onPick }: { active?: string; onPick: (view?: string) => void }) {
  const t = useLabel();
  const { token } = theme.useToken();
  const views = useServiceRequestViews();
  const counts = new Map((views.data ?? []).map((v) => [v.view, v]));
  const shown = TILES.filter((tile) => counts.has(tile.view));
  if (views.isLoading) return <Skeleton.Input active block style={{ height: 64 }} />;
  if (shown.length === 0) return null;
  // Theme tokens, so each mode (light, dark, high contrast) picks a readable pair.
  const tint: Record<TileTone, { bg: string; fg: string }> = {
    error: { bg: token.colorErrorBg, fg: token.colorErrorText },
    warning: { bg: token.colorWarningBg, fg: token.colorWarningText },
    info: { bg: token.colorInfoBg, fg: token.colorInfoText },
    success: { bg: token.colorSuccessBg, fg: token.colorSuccessText },
    purple: { bg: token.purple1, fg: token.purple7 },
  };
  return (
    <div
      role="group"
      aria-label={t('requests.views_title')}
      data-testid="sr-tiles"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
        gap: 12,
      }}
    >
      {shown.map((tile) => {
        const found = counts.get(tile.view);
        const on = active === tile.view;
        return (
          <button
            key={tile.view}
            type="button"
            aria-pressed={on}
            onClick={() => {
              onPick(on ? undefined : tile.view);
            }}
            data-testid={`sr-tile-${tile.view}`}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '12px 14px',
              textAlign: 'start',
              font: 'inherit',
              color: token.colorText,
              cursor: 'pointer',
              background: on ? token.colorPrimaryBg : token.colorBgContainer,
              border: `1px solid ${on ? token.colorPrimary : token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
            }}
          >
            <span
              aria-hidden
              style={{
                width: 36,
                height: 36,
                flexShrink: 0,
                borderRadius: 8,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: tint[tile.tone].bg,
                color: tint[tile.tone].fg,
                fontSize: 18,
              }}
            >
              {tile.icon}
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}>
                {found === undefined ? '' : `${String(found.count)}${found.capped ? '+' : ''}`}
              </span>
              <span style={{ fontSize: 12, fontWeight: 500, color: token.colorTextSecondary }}>
                {t(`work_item_view.${tile.view}`)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Service requests (WP-030, REQ-SR-009; UI pass 2 style from WP-031): the view counts as tiles,
 * a labelled view picker and approval filter, the list with the channel, item, status and
 * approval, live through the list channel. While it loads it shows a loading state, never the
 * empty one; an empty view says so and offers to raise a request.
 */
const SUBJECT_MIN = 180; // the subject stays readable however narrow it is dragged

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
  const rows = list.data?.items ?? [];
  const create = can('requests.create');
  // Each person's column widths, per view (Haider, 2026-11-10): drag or arrow keys on a header.
  // Service requests keep their own settings, apart from incidents' (lane A).
  const titles: Record<string, string> = {
    id: t('incidents.col.id'),
    subject: t('work_item.field.subject'),
    item: t('requests.item'),
    status: t('work_item.field.status'),
    approval: t('requests.approval'),
    updated: t('incidents.col.updated'),
  };
  const widths = useColumnWidths({
    kind: 'service-requests',
    viewKey: view ?? 'all',
    keys: Object.keys(titles),
    defaults: { id: 150 },
    minWidths: { subject: SUBJECT_MIN },
    label: (key) => t('layout.resize_column', { column: titles[key] ?? '' }),
  });
  return (
    <Flex vertical gap={16} style={{ width: '100%' }}>
      <PageHeader
        title={t('nav.requests')}
        extra={
          create && (
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
      <ViewTiles active={view} onPick={setView} />
      <Form layout="inline" component="div" style={{ rowGap: 8 }}>
        <Form.Item label={t('requests.view_filter')} htmlFor="sr-view-filter">
          <Select
            id="sr-view-filter"
            allowClear
            value={view}
            onChange={(value: string | undefined) => {
              setView(value);
            }}
            placeholder={t('requests.any_view')}
            style={{ minWidth: 260 }}
            options={(views.data ?? []).map((v) => ({
              value: v.view,
              label: `${t(`work_item_view.${v.view}`)} (${String(v.count)}${v.capped ? '+' : ''})`,
            }))}
            data-testid="sr-view-filter"
          />
        </Form.Item>
        <Form.Item label={t('requests.approval_filter')} htmlFor="sr-approval-filter">
          <Select
            id="sr-approval-filter"
            allowClear
            value={approval}
            onChange={(value: ApprovalStatus | undefined) => {
              setApproval(value);
            }}
            placeholder={t('requests.any_approval')}
            style={{ minWidth: 220 }}
            options={APPROVAL.map((code) => ({ value: code, label: t(`approval_status.${code}`) }))}
            data-testid="sr-approval-filter"
          />
        </Form.Item>
        {widths.changed && (
          <Form.Item>
            <Button onClick={widths.reset} data-testid="sr-reset-widths">
              {t('layout.reset_widths')}
            </Button>
          </Form.Item>
        )}
      </Form>
      <Table
        rowKey="id"
        loading={list.isLoading}
        dataSource={rows}
        pagination={false}
        data-testid="sr-list"
        components={widths.components}
        locale={{
          // An empty state only once the answer is in (QA 2026-11-04 #5 on incidents, same here).
          emptyText: list.isLoading ? (
            <span />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                view === undefined && approval === undefined
                  ? 'requests.empty'
                  : 'requests.empty_view',
              )}
              data-testid="sr-empty"
            >
              {create && (
                // The header's New request is the screen's one primary button.
                <Button onClick={() => void navigate('/requests/new')}>{t('requests.new')}</Button>
              )}
            </Empty>
          ),
        }}
        columns={[
          {
            key: 'id',
            title: t('incidents.col.id'),
            width: widths.width('id'),
            onHeaderCell: () => widths.header('id'),
            render: (_, row) => (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <ChannelIcon channel={row.channel} />
                <Link to={`/requests/${row.id}`} data-testid={`sr-row-${row.display_id}`}>
                  <strong dir="ltr">{row.display_id}</strong>
                </Link>
              </span>
            ),
          },
          {
            key: 'subject',
            title: t('work_item.field.subject'),
            width: widths.width('subject'),
            onHeaderCell: () => widths.header('subject'),
            render: (_, row) => <bdi dir="auto">{row.subject}</bdi>,
          },
          {
            key: 'item',
            title: t('requests.item'),
            width: widths.width('item'),
            onHeaderCell: () => widths.header('item'),
            render: (_, row) => itemName(byId.get(row.catalog_item_id ?? ''), locale),
          },
          {
            key: 'status',
            title: t('work_item.field.status'),
            width: widths.width('status'),
            onHeaderCell: () => widths.header('status'),
            render: (_, row) => (
              <ToneTag tone={STATUS_TONES[row.status_category] ?? 'default'}>
                {t(`work_item_status.${row.status}`)}
              </ToneTag>
            ),
          },
          {
            key: 'approval',
            title: t('requests.approval'),
            width: widths.width('approval'),
            onHeaderCell: () => widths.header('approval'),
            render: (_, row) =>
              row.approval_status == null || row.approval_status === 'not_needed'
                ? ''
                : t(`approval_status.${row.approval_status}`),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            width: widths.width('updated'),
            onHeaderCell: () => widths.header('updated'),
            render: (_, row) => format(row.updated_at),
          },
        ]}
      />
    </Flex>
  );
}
