import { FilterOutlined } from '@ant-design/icons';
import { Badge, Button, Card, Drawer, Flex, Space, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

export interface FilterBarProps {
  /** The view picker. */
  view?: ReactNode;
  /** The search box. */
  search?: ReactNode;
  /** A few quick filters (chips or small selects). */
  quick?: ReactNode;
  /** How many drawer filters are set; the "Filters" button shows it. */
  filtersCount?: number;
  onOpenFilters?: () => void;
  /** Controls on the end side (columns, sort, per page). */
  extra?: ReactNode;
  testId?: string;
}

/** The list's one filter bar (D-124): view, search, quick filters, then "Filters (n)". */
export function FilterBar({
  view,
  search,
  quick,
  filtersCount = 0,
  onOpenFilters,
  extra,
  testId,
}: FilterBarProps) {
  const t = useLabel();
  return (
    <Flex
      gap={SPACE.xs}
      wrap
      align="center"
      data-testid={testId}
      style={{ marginBottom: SPACE.xs }}
    >
      {view}
      {search !== undefined && <div style={{ flex: '1 1 220px', maxWidth: 360 }}>{search}</div>}
      {quick}
      {onOpenFilters !== undefined && (
        <Badge count={filtersCount} size="small" offset={[-4, 4]}>
          <Button
            icon={<FilterOutlined />}
            onClick={onOpenFilters}
            data-testid={testId === undefined ? undefined : `${testId}-filters`}
          >
            {t('layout.filters')}
          </Button>
        </Badge>
      )}
      {extra !== undefined && (
        <Flex gap={SPACE.xs} wrap align="center" style={{ marginInlineStart: 'auto' }}>
          {extra}
        </Flex>
      )}
    </Flex>
  );
}

export interface FiltersDrawerProps {
  open: boolean;
  onClose: () => void;
  onReset?: () => void;
  children: ReactNode;
  testId?: string;
}

/** Every filter that does not fit the bar, in a drawer (D-124). Filters apply as they change. */
export function FiltersDrawer({ open, onClose, onReset, children, testId }: FiltersDrawerProps) {
  const t = useLabel();
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('layout.filters')}
      width={360}
      data-testid={testId}
      footer={
        <Flex justify="space-between">
          {onReset === undefined ? (
            <span />
          ) : (
            <Button onClick={onReset}>{t('actions.reset')}</Button>
          )}
          <Button type="primary" onClick={onClose}>
            {t('layout.done')}
          </Button>
        </Flex>
      }
    >
      <Space direction="vertical" size={SPACE.md} style={{ width: '100%' }}>
        {children}
      </Space>
    </Drawer>
  );
}

export interface ListPageProps {
  header: ReactNode;
  /** KPI chips or tiles. */
  kpis?: ReactNode;
  filters?: ReactNode;
  alerts?: ReactNode;
  children: ReactNode;
  testId?: string;
}

/** The list page every module uses (D-124): header, KPIs, filter bar, alerts, then the table. */
export function ListPage({ header, kpis, filters, alerts, children, testId }: ListPageProps) {
  return (
    <div data-testid={testId}>
      {header}
      {kpis !== undefined && <div style={{ marginBottom: SPACE.sm }}>{kpis}</div>}
      {filters}
      {alerts}
      {children}
    </div>
  );
}

export interface KpiTileProps {
  label: ReactNode;
  value: ReactNode;
  /** A short line under the number (trend, target). */
  hint?: ReactNode;
  /** Opens the list behind the number. */
  onClick?: () => void;
  /** Colour of the number for a state (overdue in red). */
  tone?: 'default' | 'danger' | 'warning' | 'success';
  testId?: string;
}

/** A dashboard number (D-124): large value, compact height (88 px), opens its list. */
export function KpiTile({ label, value, hint, onClick, tone = 'default', testId }: KpiTileProps) {
  const { token } = theme.useToken();
  const colour = {
    default: token.colorText,
    danger: token.colorError,
    warning: token.colorWarningText,
    success: token.colorSuccessText,
  }[tone];
  const body = (
    <Flex vertical justify="center" style={{ minHeight: 64 }}>
      <Typography.Text type="secondary" style={{ fontSize: TYPE.data }} ellipsis>
        {label}
      </Typography.Text>
      <span style={{ fontSize: 28, fontWeight: 600, lineHeight: 1.2, color: colour }}>{value}</span>
      {hint !== undefined && (
        <Typography.Text type="secondary" style={{ fontSize: TYPE.meta }} ellipsis>
          {hint}
        </Typography.Text>
      )}
    </Flex>
  );
  return (
    <Card
      size="small"
      hoverable={onClick !== undefined}
      styles={{ body: { padding: `${String(SPACE.xs)}px ${String(SPACE.sm)}px` } }}
      onClick={onClick}
      onKeyDown={(event) => {
        if (onClick !== undefined && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          onClick();
        }
      }}
      tabIndex={onClick === undefined ? undefined : 0}
      role={onClick === undefined ? undefined : 'link'}
      data-testid={testId}
    >
      {body}
    </Card>
  );
}
