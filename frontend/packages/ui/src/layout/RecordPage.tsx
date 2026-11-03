import { Collapse, Flex, Grid, Tooltip, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { PANEL_WIDTH, SPACE, TYPE } from '../density';

export interface RecordHeaderProps {
  /** The record type's icon. */
  icon?: ReactNode;
  /** The human ID (INC-1042), copyable. */
  displayId: string;
  /** The subject; what people typed reads in its own direction. */
  title: string;
  /** Status, priority and similar compact tags. */
  tags?: ReactNode;
  /** Short facts: requester, created. */
  meta?: ReactNode[];
  /** On the end side: presence, follow. */
  extra?: ReactNode;
  testId?: string;
  /** Test ids of the ID and the title (screens keep their own). */
  testIds?: { id?: string; title?: string };
}

/** The record page's one-line header (D-124); it wraps on narrow screens. */
export function RecordHeader({
  icon,
  displayId,
  title,
  tags,
  meta = [],
  extra,
  testId,
  testIds = {},
}: RecordHeaderProps) {
  const { token } = theme.useToken();
  return (
    <Flex
      align="center"
      gap={SPACE.xs}
      wrap
      data-testid={testId}
      style={{ minHeight: 36, rowGap: SPACE.xxs }}
    >
      {icon !== undefined && (
        <span aria-hidden style={{ color: token.colorTextSecondary, fontSize: TYPE.section }}>
          {icon}
        </span>
      )}
      <Typography.Text
        type="secondary"
        copyable
        style={{ fontSize: TYPE.body, whiteSpace: 'nowrap' }}
        data-testid={testIds.id}
      >
        {displayId}
      </Typography.Text>
      <Tooltip title={<bdi dir="auto">{title}</bdi>} placement="bottomLeft">
        <Typography.Title
          level={1}
          style={{
            margin: 0,
            fontSize: TYPE.record,
            lineHeight: 1.4,
            minWidth: 0,
            flex: '1 1 240px',
            maxWidth: 'min(720px, 100%)',
          }}
          ellipsis
          data-testid={testIds.title}
        >
          <bdi dir="auto">{title}</bdi>
        </Typography.Title>
      </Tooltip>
      {tags !== undefined && (
        <Flex gap={SPACE.xxs} wrap align="center">
          {tags}
        </Flex>
      )}
      {meta.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: TYPE.data }}>
          {meta.map((part, index) => (
            <span key={index}>
              {index > 0 && ' · '}
              {part}
            </span>
          ))}
        </Typography.Text>
      )}
      {extra !== undefined && (
        <Flex gap={SPACE.xs} align="center" style={{ marginInlineStart: 'auto' }}>
          {extra}
        </Flex>
      )}
    </Flex>
  );
}

export interface PanelSection {
  key: string;
  title: ReactNode;
  children: ReactNode;
  /** Open at first (default true). */
  open?: boolean;
  testId?: string;
}

/** The permanent properties panel's sections, each folding (D-124). */
export function PropertiesPanel({
  sections,
  testId,
}: {
  sections: PanelSection[];
  testId?: string;
}) {
  const { token } = theme.useToken();
  return (
    <aside
      data-testid={testId}
      style={{
        background: token.colorBgContainer,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadiusLG,
      }}
    >
      <Collapse
        ghost
        size="small"
        defaultActiveKey={sections.filter((s) => s.open !== false).map((s) => s.key)}
        items={sections.map((section) => ({
          key: section.key,
          label: (
            <Typography.Text strong style={{ fontSize: TYPE.body }}>
              {section.title}
            </Typography.Text>
          ),
          children: <div data-testid={section.testId}>{section.children}</div>,
        }))}
      />
    </aside>
  );
}

/** One property: label and value side by side (13 px data). */
export function PropertyRow({
  label,
  children,
  testId,
}: {
  label: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <Flex gap={SPACE.xs} align="baseline" style={{ minHeight: 28 }} data-testid={testId}>
      <Typography.Text type="secondary" style={{ flex: '0 0 40%', fontSize: TYPE.data }}>
        {label}
      </Typography.Text>
      <div style={{ flex: 1, minWidth: 0, fontSize: TYPE.data, overflowWrap: 'anywhere' }}>
        {children}
      </div>
    </Flex>
  );
}

export interface RecordPageProps {
  header: ReactNode;
  actions?: ReactNode;
  /** The alert strip (live changes, warnings). */
  alerts?: ReactNode;
  /** The tabs. */
  children: ReactNode;
  /** The permanent right-hand panel (properties, SLA, assignment, followers, associations). */
  panel: ReactNode;
  testId?: string;
}

/**
 * The record page every module uses (D-124): header, actions and alerts across the top; tabs on
 * the start side, the properties panel on the end side, on every tab. Below 992 px the panel
 * folds into one "Properties" section above the tabs. RTL mirrors through the grid.
 */
export function RecordPage({ header, actions, alerts, children, panel, testId }: RecordPageProps) {
  const t = useLabel();
  const screens = Grid.useBreakpoint();
  const wide = screens.lg === true;
  return (
    <div data-testid={testId}>
      {header}
      {actions}
      {alerts}
      {wide ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `minmax(0, 1fr) ${String(PANEL_WIDTH)}px`,
            gap: SPACE.md,
            alignItems: 'start',
            marginTop: SPACE.xs,
          }}
        >
          <main style={{ minWidth: 0 }}>{children}</main>
          <div
            style={{
              position: 'sticky',
              top: SPACE.md,
              maxHeight: `calc(100vh - ${String(SPACE.xl * 2)}px)`,
              overflowY: 'auto',
            }}
          >
            {panel}
          </div>
        </div>
      ) : (
        <Flex vertical gap={SPACE.sm} style={{ marginTop: SPACE.xs }}>
          <Collapse
            size="small"
            defaultActiveKey={['panel']}
            items={[
              // Rendered while folded: fields keep their state, and links and tests reach them.
              { key: 'panel', label: t('layout.properties'), children: panel, forceRender: true },
            ]}
          />
          <main style={{ minWidth: 0 }}>{children}</main>
        </Flex>
      )}
    </div>
  );
}
