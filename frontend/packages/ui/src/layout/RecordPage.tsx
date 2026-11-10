import { Flex, Tooltip, Typography, theme } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';

import { useAppearance } from '../appearance';
import { PANEL_WIDTH, SPACE, TYPE } from '../density';
import { clampLineHeight } from '../fonts/fonts';

/** The record types with a tile of their own (D-155: one header for every type). */
export type RecordKind =
  | 'incident'
  | 'service_request'
  | 'problem'
  | 'change'
  | 'release'
  | 'asset'
  | 'announcement'
  | 'article';

// Each type's tint: icon colour and its pale tile, at least 4.5:1 for the icon on its tile in
// both themes (the same measure as the channel looks).
const KIND_TINTS: Record<RecordKind, { fg: string; bg: string; dark: { fg: string; bg: string } }> =
  {
    incident: { fg: '#B42318', bg: '#FEF3F2', dark: { fg: '#FDA29B', bg: '#55160C' } },
    service_request: { fg: '#175CD3', bg: '#EFF8FF', dark: { fg: '#84CAFF', bg: '#102A56' } },
    problem: { fg: '#B54708', bg: '#FFFAEB', dark: { fg: '#FEC84B', bg: '#4E1D09' } },
    change: { fg: '#5925DC', bg: '#F4F3FF', dark: { fg: '#BDB4FE', bg: '#27115F' } },
    release: { fg: '#067647', bg: '#ECFDF3', dark: { fg: '#75E0A7', bg: '#053321' } },
    asset: { fg: '#0E7090', bg: '#ECFDFF', dark: { fg: '#67E3F9', bg: '#0D2D3A' } },
    announcement: { fg: '#C11574', bg: '#FDF2FA', dark: { fg: '#FAA7E0', bg: '#4E0D30' } },
    article: { fg: '#3538CD', bg: '#EEF4FF', dark: { fg: '#A4BCFD', bg: '#1F235B' } },
  };

export interface RecordHeaderProps {
  /** The record type's icon (decorative), drawn in the type's tinted tile when `kind` is set. */
  icon?: ReactNode;
  /** The record's type: its tile's tint (D-155). */
  kind?: RecordKind;
  /** A meaningful chip first in the chips row (the channel it came from); named by itself. */
  badge?: ReactNode;
  /** The record type's name beside the ID ("Incident"). */
  typeLabel?: string;
  /** The human ID (INC-1042), copyable. */
  displayId: string;
  /** False when `displayId` is a stand-in ("No tag"), not an ID worth copying. */
  copyable?: boolean;
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
  /**
   * Wraps the title, so a screen can make it edit in place (template A: the subject is edited
   * here, not repeated in the properties).
   */
  renderTitle?: (title: ReactNode) => ReactNode;
}

/**
 * The record's header (UI pass 2, docs/design/target): the channel badge, then the ID and type,
 * the subject as the page's title, and the tags and short facts below it.
 */
export function RecordHeader({
  icon,
  kind,
  badge,
  typeLabel,
  displayId,
  copyable = true,
  title,
  tags,
  meta = [],
  extra,
  testId,
  testIds = {},
  renderTitle = (shown) => shown,
}: RecordHeaderProps) {
  const { token } = theme.useToken();
  const { urduScript, mode } = useAppearance();
  const tint = kind === undefined ? undefined : KIND_TINTS[kind];
  const colours = tint === undefined ? undefined : mode === 'dark' ? tint.dark : tint;
  return (
    <Flex gap={SPACE.md} align="flex-start" data-testid={testId} style={{ minWidth: 0 }}>
      {icon !== undefined &&
        (colours === undefined ? (
          <span aria-hidden style={{ color: token.colorTextSecondary, fontSize: TYPE.section }}>
            {icon}
          </span>
        ) : (
          // The type's tile (D-155): the same place and size on every record.
          <span
            aria-hidden
            data-testid="record-kind-tile"
            data-kind={kind}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: 10,
              background: colours.bg,
              color: colours.fg,
              fontSize: 22,
            }}
          >
            {icon}
          </span>
        ))}
      <Flex vertical gap={6} style={{ minWidth: 0, flex: 1 }}>
        <Flex align="center" gap={SPACE.xs} wrap style={{ fontSize: TYPE.meta }}>
          <Typography.Text
            strong
            copyable={copyable}
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
        {renderTitle(
          <Tooltip title={<bdi dir="auto">{title}</bdi>} placement="bottomLeft">
            <Typography.Title
              level={1}
              style={{
                margin: 0,
                fontSize: TYPE.page,
                // Room for the dots below Arabic-script letters: the two-line clamp cuts the rest.
                lineHeight: clampLineHeight(title, 1.3, urduScript),
                minWidth: 0,
              }}
              ellipsis={{ rows: 2 }}
              data-testid={testIds.title}
            >
              <bdi dir="auto">{title}</bdi>
            </Typography.Title>
          </Tooltip>,
        )}
        {(badge !== undefined || tags !== undefined) && (
          <Flex gap={SPACE.xs} wrap align="center" data-testid="record-chips">
            {badge}
            {tags}
          </Flex>
        )}
        {/* One line of key facts under the chips (D-155): requester, created. */}
        {meta.length > 0 && (
          <Typography.Text
            type="secondary"
            style={{ fontSize: TYPE.data }}
            data-testid="record-facts"
          >
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
  const [columns, setColumns] = useState<HTMLDivElement | null>(null);
  const side = useSideBySide(columns);
  return (
    <Flex vertical gap={SPACE.md} data-testid={testId}>
      <section style={{ ...card, padding: `${String(SPACE.md)}px 18px` }}>
        <Flex wrap gap={SPACE.md} align="flex-start">
          <div style={{ flex: '999 1 420px', minWidth: 0 }}>{header}</div>
          {actions !== undefined && <div style={{ flex: '0 1 auto', minWidth: 0 }}>{actions}</div>}
        </Flex>
      </section>
      {alerts}
      <div
        ref={setColumns}
        data-layout={side ? 'side' : 'stacked'}
        style={
          side
            ? {
                display: 'grid',
                gridTemplateColumns: `minmax(0, 1fr) ${String(PANEL_WIDTH)}px`,
                gap: SPACE.md,
                // Each column ends where its content ends (no empty white card below a short
                // conversation); the panel beside it stays in view and scrolls itself, so the
                // page is never longer than the longer of the two (D-147 template A, #293).
                alignItems: 'start',
              }
            : { display: 'flex', flexDirection: 'column', gap: SPACE.md }
        }
      >
        <main style={{ ...card, minWidth: 0, padding: `0 ${String(SPACE.sm)}px` }}>{children}</main>
        <div
          data-testid={testId === undefined ? undefined : `${testId}-panel`}
          style={
            side
              ? {
                  // Beside the tabs the panel stays in view while a long conversation scrolls,
                  // and scrolls itself when it is taller than the window.
                  alignSelf: 'start',
                  position: 'sticky',
                  top: SPACE.md,
                  maxHeight: `calc(100vh - ${String(2 * SPACE.md)}px)`,
                  overflowY: 'auto',
                  minWidth: 0,
                }
              : { minWidth: 0 }
          }
        >
          {panel}
        </div>
      </div>
    </Flex>
  );
}

/** Room for the tabs (500 px) and the panel side by side; below that the panel goes under. */
const SIDE_BY_SIDE_MIN = 500 + PANEL_WIDTH + SPACE.md;

function useSideBySide(element: HTMLElement | null): boolean {
  const [side, setSide] = useState(true);
  useEffect(() => {
    if (element === null) return undefined;
    const measure = () => {
      setSide(element.getBoundingClientRect().width >= SIDE_BY_SIDE_MIN);
    };
    measure();
    // jsdom (unit tests) has no ResizeObserver: the first measure stands.
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [element]);
  return side;
}
