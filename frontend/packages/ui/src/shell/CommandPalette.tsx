import { Input, List, Modal, Spin, Typography } from 'antd';
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

interface Row {
  command: PaletteCommand;
  heading?: string;
}

/**
 * Command palette (Ctrl+K): go to a page, or to a record found by search. Type to filter, arrows
 * to move, Enter to go. Pages are filtered here; records come from the server through `records`.
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

  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const pages =
      needle === ''
        ? commands
        : commands.filter((command) => command.title.toLocaleLowerCase().includes(needle));
    const list: Row[] = pages.map((command, index) => ({
      command,
      heading: index === 0 && records !== undefined ? t('palette.pages') : undefined,
    }));
    for (const [index, command] of (records?.items ?? []).entries()) {
      list.push({ command, heading: index === 0 ? records?.title : undefined });
    }
    return list;
  }, [commands, query, records, t]);

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
        aria-expanded
        aria-controls="command-palette-list"
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
          if (event.key === 'Enter') go(rows[active]?.command);
        }}
      />
      <div id="command-palette-list" role="listbox" aria-label={t('palette.title')}>
        <List
          style={{ marginTop: 12 }}
          dataSource={rows}
          locale={{
            emptyText: (
              <EmptyText>
                {t(records?.loading === true ? 'palette.searching' : 'palette.no_results')}
              </EmptyText>
            ),
          }}
          renderItem={({ command, heading }, index) => (
            <>
              {heading !== undefined && (
                <Typography.Text
                  type="secondary"
                  role="presentation"
                  style={{ display: 'block', fontSize: 12, marginBlock: 8, paddingInline: 12 }}
                >
                  {heading}
                </Typography.Text>
              )}
              <List.Item
                role="option"
                aria-selected={index === active}
                aria-label={
                  command.subtitle === undefined
                    ? command.title
                    : `${command.title}, ${command.subtitle}`
                }
                data-testid={`palette-${command.key}`}
                onClick={() => {
                  go(command);
                }}
                style={{
                  cursor: 'pointer',
                  paddingInline: 12,
                  borderRadius: 6,
                  display: 'block',
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
                  <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                    <bdi>{command.subtitle}</bdi>
                  </Typography.Text>
                )}
              </List.Item>
            </>
          )}
        />
      </div>
    </Modal>
  );
}
