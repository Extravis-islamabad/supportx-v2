import { Flex, Tooltip, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { PANEL_WIDTH, SPACE, TYPE } from '../density';

export interface RecordHeaderProps {
  /** The record type's icon (decorative). */
  icon?: ReactNode;
  /** A meaningful badge before everything (the channel it came from); named by itself. */
  badge?: ReactNode;
  /** The record type's name beside the ID ("Incident"). */
  typeLabel?: string;
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

/**
 * The record's header (UI pass 2, docs/design/target): the channel badge, then the ID and type,
 * the subject as the page's title, and the tags and short facts below it.
 */
export function RecordHeader({
  icon,
  badge,
  typeLabel,
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
    <Flex gap={SPACE.md} align="flex-start" data-testid={testId} style={{ minWidth: 0 }}>
      {badge}
      {badge === undefined && icon !== undefined && (
        <span aria-hidden style={{ color: token.colorTextSecondary, fontSize: TYPE.section }}>
          {icon}
        </span>
      )}
      <Flex vertical gap={6} style={{ minWidth: 0, flex: 1 }}>
        <Flex align="center" gap={SPACE.xs} wrap style={{ fontSize: TYPE.meta }}>
          <Typography.Text
            strong
            copyable
            style={{ fontSize: TYPE.meta, whiteSpace: 'nowrap' }}
            data-testid={testIds.id}
          >
            {displayId}
          </Typography.Text>
          {typeLabel !== undefined && (
            <Typography.Text type="secondary" style={{ fontSize: TYPE.meta }}>
              · {typeLabel}
            </Typography.Text>
          )}
          {extra !== undefined && (
            <Flex gap={SPACE.xs} align="center" style={{ marginInlineStart: 'auto' }}>
              {extra}
            </Flex>
          )}
        </Flex>
        <Tooltip title={<bdi dir="auto">{title}</bdi>} placement="bottomLeft">
          <Typography.Title
            level={1}
            style={{ margin: 0, fontSize: TYPE.page, lineHeight: 1.3, minWidth: 0 }}
            ellipsis={{ rows: 2 }}
            data-testid={testIds.title}
          >
            <bdi dir="auto">{title}</bdi>
          </Typography.Title>
        </Tooltip>
        <Flex gap={SPACE.xs} wrap align="center">
          {tags}
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
        </Flex>
      </Flex>
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
  /** The child is a card of its own (title and actions): shown as the section, not inside one. */
  bare?: boolean;
}

/**
 * The properties panel (UI pass 2): one white card per section. Beside the tabs it is one
 * column; when the page is too narrow it wraps below them and its cards spread into columns
 * across the full width, so no space is left empty.
 */
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
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap: SPACE.sm,
        alignItems: 'start',
      }}
    >
      {sections.map((section) =>
        section.bare === true ? (
          <div key={section.key} data-testid={section.testId} style={{ minWidth: 0 }}>
            {section.children}
          </div>
        ) : (
          <section
            key={section.key}
            aria-labelledby={`panel-${section.key}`}
            style={{
              background: token.colorBgContainer,
              border: `1px solid ${token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
              minWidth: 0,
            }}
          >
            <div
              style={{
                padding: `${String(SPACE.sm)}px 14px`,
                borderBottom: `1px solid ${token.colorBorderSecondary}`,
              }}
            >
              <Typography.Title
                level={2}
                id={`panel-${section.key}`}
                style={{ margin: 0, fontSize: TYPE.body, fontWeight: 600 }}
              >
                {section.title}
              </Typography.Title>
            </div>
            <div
              data-testid={section.testId}
              style={{ padding: `${String(SPACE.xs)}px 14px 10px` }}
            >
              {section.children}
            </div>
          </section>
        ),
      )}
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
 * The record page (UI pass 2, docs/design/target): the header and its actions in one white card;
 * the tabs in a white card on the start side and the properties panel's cards on the end side.
 * Narrower, the panel wraps below the tabs and its cards spread into columns. RTL mirrors.
 */
export function RecordPage({ header, actions, alerts, children, panel, testId }: RecordPageProps) {
  const { token } = theme.useToken();
  const card = {
    background: token.colorBgContainer,
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadius,
  } as const;
  return (
    <Flex vertical gap={SPACE.md} data-testid={testId}>
      <section style={{ ...card, padding: `${String(SPACE.md)}px 18px` }}>
        <Flex wrap gap={SPACE.md} align="flex-start">
          <div style={{ flex: '999 1 420px', minWidth: 0 }}>{header}</div>
          {actions !== undefined && <div style={{ flex: '0 1 auto', minWidth: 0 }}>{actions}</div>}
        </Flex>
      </section>
      {alerts}
      <Flex wrap gap={SPACE.md} align="flex-start">
        <main
          style={{ ...card, flex: '999 1 500px', minWidth: 0, padding: `0 ${String(SPACE.sm)}px` }}
        >
          {children}
        </main>
        <div style={{ flex: `1 1 ${String(PANEL_WIDTH)}px`, minWidth: 0 }}>{panel}</div>
      </Flex>
    </Flex>
  );
}
