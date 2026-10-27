import { Input, Modal, Spin, Typography } from 'antd';
import { useMemo, useState } from 'react';

import { useLabel } from '../appearance';
import { EmptyText } from '../EmptyText';

export interface PaletteCommand {
  key: string;
  /** Translated title shown in the list. */
  title: string;
  /** A second line (e.g. a record's requester and status). */
  subtitle?: string;
  path: string;
}

/** Records found by the server for what is typed (or recent ones while nothing is typed). */
export interface PaletteRecords {
  /** Translated heading, e.g. "Incidents" or "Recently viewed". */
  title: string;
  items: PaletteCommand[];
  loading: boolean;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: PaletteCommand[];
  onNavigate: (path: string) => void;
  /** What is typed, for the caller's record search (WP-027). */
  onQueryChange?: (query: string) => void;
  records?: PaletteRecords;
}

interface Group {
  key: string;
  /** Shown above the group (only when records are searched, so pages get a heading too). */
  heading?: string;
  items: PaletteCommand[];
}

/**
 * Command palette (Ctrl+K): go to a page, or to a record found by search. Type to filter, arrows
 * to move, Enter to go. Pages are filtered here; records come from the server through `records`.
 * Plain listbox > group > option markup: a list component in between breaks the ARIA tree.
 */
export function CommandPalette({
  open,
  onOpenChange,
  commands,
  onNavigate,
  onQueryChange,
  records,
}: CommandPaletteProps) {
  const t = useLabel();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);

  const groups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const pages =
      needle === ''
        ? commands
        : commands.filter((command) => command.title.toLocaleLowerCase().includes(needle));
    const list: Group[] = [];
    if (pages.length > 0)
      list.push({
        key: 'pages',
        heading: records === undefined ? undefined : t('palette.pages'),
        items: pages,
      });
    if (records !== undefined && records.items.length > 0)
      list.push({ key: 'records', heading: records.title, items: records.items });
    return list;
  }, [commands, query, records, t]);
  const rows = groups.flatMap((group) => group.items);

  const close = () => {
    onOpenChange(false);
    setQuery('');
    setActive(0);
    onQueryChange?.('');
  };
  const go = (command: PaletteCommand | undefined) => {
    if (command === undefined) return;
    close();
    onNavigate(command.path);
  };

  return (
    <Modal
      open={open}
      onCancel={close}
      footer={null}
      closable={false}
      title={t('palette.title')}
      destroyOnHidden
    >
      <Input
        autoFocus
        role="combobox"
        aria-expanded={rows.length > 0}
        aria-controls={rows.length > 0 ? 'command-palette-list' : undefined}
        aria-activedescendant={rows.length > 0 ? `palette-option-${String(active)}` : undefined}
        aria-label={t('palette.placeholder')}
        placeholder={t(
          records === undefined ? 'palette.placeholder' : 'palette.placeholder_search',
        )}
        value={query}
        suffix={records?.loading === true ? <Spin size="small" /> : <span />}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          onQueryChange?.(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') setActive((index) => Math.min(index + 1, rows.length - 1));
          if (event.key === 'ArrowUp') setActive((index) => Math.max(index - 1, 0));
          if (event.key === 'Enter') go(rows[active]);
        }}
      />
      {rows.length === 0 ? (
        <div style={{ marginTop: 12 }}>
          <EmptyText>
            {t(records?.loading === true ? 'palette.searching' : 'palette.no_results')}
          </EmptyText>
        </div>
      ) : (
        <div
          id="command-palette-list"
          role="listbox"
          aria-label={t('palette.title')}
          style={{ marginTop: 12 }}
        >
          {groups.map((group, groupIndex) => {
            const offset = groups
              .slice(0, groupIndex)
              .reduce((count, before) => count + before.items.length, 0);
            return (
              <div
                key={group.key}
                role="group"
                aria-labelledby={
                  group.heading === undefined ? undefined : `palette-group-${group.key}`
                }
              >
                {group.heading !== undefined && (
                  <Typography.Text
                    id={`palette-group-${group.key}`}
                    type="secondary"
                    style={{ display: 'block', fontSize: 12, marginBlock: 8, paddingInline: 12 }}
                  >
                    {group.heading}
                  </Typography.Text>
                )}
                {group.items.map((command, position) => {
                  const index = offset + position;
                  return (
                    <div
                      key={command.key}
                      id={`palette-option-${String(index)}`}
                      role="option"
                      aria-selected={index === active}
                      data-testid={`palette-${command.key}`}
                      onClick={() => {
                        go(command);
                      }}
                      style={{
                        cursor: 'pointer',
                        paddingBlock: 8,
                        paddingInline: 12,
                        borderRadius: 6,
                        background:
                          index === active
                            ? 'var(--ant-control-item-bg-active, rgba(150,25,181,0.12))'
                            : undefined,
                      }}
                    >
                      <Typography.Text style={{ display: 'block' }}>
                        <bdi>{command.title}</bdi>
                      </Typography.Text>
                      {command.subtitle !== undefined && (
                        <Typography.Text
                          type="secondary"
                          style={{ display: 'block', fontSize: 12 }}
                        >
                          <bdi>{command.subtitle}</bdi>
                        </Typography.Text>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
