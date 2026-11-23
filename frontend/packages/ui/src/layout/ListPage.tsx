import { CloseOutlined, FilterOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { Badge, Button, Card, Flex, Space, Typography, theme } from 'antd';
import { Drawer } from '../Drawer';
import { useState, type ReactNode } from 'react';

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
  /**
   * The selection bar (Haider, 2026-11-10): while rows are selected it takes the toolbar's
   * place, so the list never shows two control rows. Pass it only when something is selected.
   */
  selection?: ReactNode;
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
  selection,
  testId,
}: FilterBarProps) {
  const t = useLabel();
  if (selection !== undefined && selection !== null && selection !== false) {
    return (
      <Flex
        gap={SPACE.xs}
        wrap
        align="center"
        className="sx-list-toolbar"
        data-testid={testId === undefined ? undefined : `${testId}-selection`}
      >
        {selection}
      </Flex>
    );
  }
  return (
    <Flex gap={SPACE.xs} wrap align="center" className="sx-list-toolbar" data-testid={testId}>
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

/**
 * The list page every module uses (D-124): header, KPIs, filter bar, alerts, then the table.
 *
 * One spacing scale (Haider, 2026-11-10): 16 px between the page's sections (header, KPI
 * tiles, the list block), 12 px between the toolbar, its notice line and the table, 8 px
 * between the controls inside the toolbar (FilterBar).
 */
export function ListPage({ header, kpis, filters, alerts, children, testId }: ListPageProps) {
  return (
    <Flex vertical gap={SPACE.md} className="sx-list-page" data-testid={testId}>
      {header}
      {kpis}
      <Flex vertical gap={SPACE.sm}>
        {filters}
        {alerts}
        {children}
      </Flex>
    </Flex>
  );
}

export interface ListNoticeProps {
  /** One short line, e.g. "All open: 42 shown, 7 not in this view". */
  children: ReactNode;
  /** One link-style action, e.g. "Show all". */
  action?: ReactNode;
  /**
   * Kept closed for the browser session under this key (with the text, so a new count shows
   * again). Without it the line cannot be closed.
   */
  dismissKey?: string;
  testId?: string;
}

/**
 * A list's notice as one small line under the toolbar, never a full-width band (Haider,
 * 2026-11-10): an info icon, the text, an action, and a close button.
 */
export function ListNotice({ children, action, dismissKey, testId }: ListNoticeProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  const key = dismissKey === undefined ? undefined : `${dismissKey}|${textOf(children)}`;
  const [closed, setClosed] = useState(() => key !== undefined && readClosed().has(key));
  if (closed) return null;
  return (
    // One sentence that wraps as text (QA10V-26: at 390 px the icon, the text and "Show
    // everything" each took a line of their own): the icon stays beside the first line and the
    // action follows the text.
    <Flex
      align="flex-start"
      gap={SPACE.xs}
      role="status"
      data-testid={testId}
      style={{ fontSize: TYPE.meta, color: token.colorTextSecondary, minHeight: 24 }}
    >
      <InfoCircleOutlined
        aria-hidden
        style={{ color: token.colorInfo, flex: 'none', lineHeight: 1, marginBlockStart: 3 }}
      />
      <span style={{ flex: '1 1 auto', minWidth: 0 }}>
        {children}
        {action !== undefined && action !== null && action !== false && <> {action}</>}
      </span>
      {key !== undefined && (
        <Button
          type="text"
          size="small"
          icon={<CloseOutlined />}
          aria-label={t('layout.dismiss')}
          data-testid={testId === undefined ? undefined : `${testId}-close`}
          onClick={() => {
            setClosed(true);
            writeClosed(key);
          }}
        />
      )}
    </Flex>
  );
}

const CLOSED_KEY = 'supportx.list-notices.closed';

function textOf(node: ReactNode): string {
  return typeof node === 'string' || typeof node === 'number' ? String(node) : '';
}

function readClosed(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(CLOSED_KEY);
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : []);
  } catch {
    return new Set(); // storage blocked: the line simply shows again
  }
}

function writeClosed(key: string) {
  try {
    const keys = [...readClosed(), key].slice(-50);
    window.sessionStorage.setItem(CLOSED_KEY, JSON.stringify(keys));
  } catch {
    // storage blocked: closed for this page view only
  }
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
