import { StarFilled, StarOutlined } from '@ant-design/icons';
import { Button, Empty, Flex, Input, Tabs, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

/** One entry of a library: a report, an article, a dashboard. */
export interface LibraryItem {
  /** Stable key; also what the favourites list holds. */
  key: string;
  /** The name, usually a link that opens it. */
  title: ReactNode;
  /** Plain text the search looks in (name and description, in the user's language). */
  searchText: string;
  description?: ReactNode;
  /** A tag or two after the name (shared, draft ...). */
  tags?: ReactNode;
  /** Short facts at the end of the row (owner, updated). */
  meta?: ReactNode;
  testId?: string;
}

/** A module's section: its tab, and the group shown under "All". */
export interface LibraryGroup {
  key: string;
  label: ReactNode;
  items: readonly LibraryItem[];
  /** Shown when the group has nothing yet (a module whose reports come later). */
  empty?: ReactNode;
  /** The tab's own body instead of rows (knowledge: its topic tree and article table). */
  content?: ReactNode;
  /** The number on the tab; the visible rows by default, none when the page has no count. */
  count?: number | null;
}

export interface LibraryPageProps {
  header: ReactNode;
  groups: readonly LibraryGroup[];
  search: string;
  onSearch: (value: string) => void;
  searchLabel: string;
  /** Keys of the user's favourites; with `onStar`, every row has a star. */
  favourites?: ReadonlySet<string>;
  onStar?: (key: string, starred: boolean) => void;
  /** The open tab: "all" or a group's key; uncontrolled when left out. */
  tab?: string;
  onTab?: (tab: string) => void;
  /** Filters or controls next to the search. */
  extra?: ReactNode;
  /** While the library loads: no empty texts yet. */
  loading?: boolean;
  /** The server searches (knowledge): rows are shown as given, not filtered here. */
  searchOnServer?: boolean;
  /** An "All" tab first (default); off when the tabs are views of one list. */
  withAll?: boolean;
  testId?: string;
}

export const LIBRARY_ALL = 'all';

const matches = (item: LibraryItem, needle: string) =>
  needle === '' || item.searchText.toLocaleLowerCase().includes(needle);

/**
 * Template D, the library page (D-147): reports, knowledge, the dashboards list. Search and the
 * user's favourites on top; then one tab per module, "All" first, each a full-width table of
 * rows (star, name with its description, facts at the end). A module with nothing yet keeps its
 * tab and says why, so every module is always there.
 */
export function LibraryPage({
  header,
  groups,
  search,
  onSearch,
  searchLabel,
  favourites,
  onStar,
  tab,
  onTab,
  extra,
  loading = false,
  searchOnServer = false,
  withAll = true,
  testId = 'library',
}: LibraryPageProps) {
  const t = useLabel();
  const needle = searchOnServer ? '' : search.trim().toLocaleLowerCase();
  const shown = groups.map((g) => ({ ...g, items: g.items.filter((i) => matches(i, needle)) }));
  const starred = shown.flatMap((g) => g.items).filter((i) => favourites?.has(i.key) === true);
  const total = shown.reduce((n, g) => n + g.items.length, 0);
  const row = (item: LibraryItem) => (
    <LibraryRow
      key={item.key}
      item={item}
      starred={favourites?.has(item.key) === true}
      onStar={onStar}
    />
  );
  const section = (group: (typeof shown)[number], titled: boolean) => (
    <LibrarySection
      key={group.key}
      title={titled ? group.label : undefined}
      testId={`${testId}-group-${group.key}`}
    >
      {group.content ??
        (group.items.length > 0
          ? group.items.map(row)
          : !loading && (
              <Typography.Text type="secondary" style={{ display: 'block', padding: SPACE.sm }}>
                {needle !== ''
                  ? t('layout.library_no_match')
                  : (group.empty ?? t('layout.library_empty'))}
              </Typography.Text>
            ))}
    </LibrarySection>
  );

  return (
    <div data-testid={testId}>
      {header}
      <Flex gap={SPACE.xs} wrap align="center" style={{ marginBottom: SPACE.sm }}>
        <div style={{ flex: '1 1 260px', maxWidth: 420 }}>
          <Input.Search
            allowClear
            aria-label={searchLabel}
            placeholder={searchLabel}
            value={search}
            onChange={(event) => {
              onSearch(event.target.value);
            }}
            data-testid={`${testId}-search`}
          />
        </div>
        {extra !== undefined && (
          <Flex gap={SPACE.xs} wrap align="center" style={{ marginInlineStart: 'auto' }}>
            {extra}
          </Flex>
        )}
      </Flex>
      {starred.length > 0 && (
        <LibrarySection title={t('layout.favourites')} testId={`${testId}-favourites`}>
          {starred.map(row)}
        </LibrarySection>
      )}
      <Tabs
        activeKey={tab}
        defaultActiveKey={withAll ? LIBRARY_ALL : groups[0]?.key}
        onChange={onTab}
        // One copy of each row on the page: "All" and a module's tab show the same entries.
        destroyOnHidden
        data-testid={`${testId}-tabs`}
        items={[
          ...(withAll
            ? [
                {
                  key: LIBRARY_ALL,
                  label: <TabLabel label={t('layout.library_all')} count={total} />,
                  children:
                    needle !== '' && total === 0 && !loading ? (
                      <Empty description={t('layout.library_no_match')} />
                    ) : (
                      shown
                        .filter((g) => needle === '' || g.items.length > 0)
                        .map((g) => section(g, true))
                    ),
                },
              ]
            : []),
          ...shown.map((g) => ({
            key: g.key,
            label: (
              <TabLabel label={g.label} count={g.count === undefined ? g.items.length : g.count} />
            ),
            children: g.content !== undefined ? g.content : section(g, false),
          })),
        ]}
      />
    </div>
  );
}

function TabLabel({ label, count }: { label: ReactNode; count: number | null }) {
  if (count === null) return <span>{label}</span>;
  return (
    <span>
      {label}{' '}
      <Typography.Text type="secondary" style={{ fontSize: TYPE.meta }}>
        {count}
      </Typography.Text>
    </span>
  );
}

/** A titled, full-width block of rows. */
function LibrarySection({
  title,
  testId,
  children,
}: {
  title?: ReactNode;
  testId?: string;
  children: ReactNode;
}) {
  const { token } = theme.useToken();
  return (
    <section
      data-testid={testId}
      style={{
        background: token.colorBgContainer,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        marginBottom: SPACE.md,
        minWidth: 0,
      }}
    >
      {title !== undefined && (
        <Typography.Title
          level={3}
          style={{
            margin: 0,
            padding: `${String(SPACE.sm)}px ${String(SPACE.md)}px`,
            fontSize: TYPE.section,
            fontWeight: 600,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          {title}
        </Typography.Title>
      )}
      <div role="list">{children}</div>
    </section>
  );
}

function LibraryRow({
  item,
  starred,
  onStar,
}: {
  item: LibraryItem;
  starred: boolean;
  onStar?: (key: string, starred: boolean) => void;
}) {
  const t = useLabel();
  const { token } = theme.useToken();
  return (
    <Flex
      role="listitem"
      align="center"
      gap={SPACE.sm}
      data-testid={item.testId}
      className="sx-library-row"
      style={{
        padding: `${String(SPACE.xs)}px ${String(SPACE.md)}px`,
        borderBottom: `1px solid ${token.colorSplit}`,
        minWidth: 0,
      }}
    >
      {onStar !== undefined && (
        <Button
          type="text"
          size="small"
          aria-label={t(starred ? 'layout.unstar' : 'layout.star')}
          aria-pressed={starred}
          icon={starred ? <StarFilled style={{ color: token.colorWarning }} /> : <StarOutlined />}
          onClick={() => {
            onStar(item.key, !starred);
          }}
          data-testid={item.testId === undefined ? undefined : `${item.testId}-star`}
        />
      )}
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <Flex gap={SPACE.xs} align="center" wrap>
          <span style={{ fontWeight: 500 }}>{item.title}</span>
          {item.tags}
        </Flex>
        {item.description !== undefined && (
          <Typography.Text
            type="secondary"
            style={{ fontSize: TYPE.data, display: 'block' }}
            ellipsis
          >
            {item.description}
          </Typography.Text>
        )}
      </div>
      {item.meta !== undefined && (
        <Typography.Text type="secondary" style={{ fontSize: TYPE.meta, flex: 'none' }}>
          {item.meta}
        </Typography.Text>
      )}
    </Flex>
  );
}
