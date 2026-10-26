import { Input, List, Modal, Typography } from 'antd';
import { useMemo, useState } from 'react';

import { useLabel } from '../appearance';
import { EmptyText } from '../EmptyText';

export interface PaletteCommand {
  key: string;
  /** Translated title shown in the list. */
  title: string;
  path: string;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: PaletteCommand[];
  onNavigate: (path: string) => void;
}

/**
 * Command palette skeleton: type to filter, arrows to move, Enter to go. Navigation only for
 * now; actions (create ticket, search records) join as modules arrive.
 */
export function CommandPalette({ open, onOpenChange, commands, onNavigate }: CommandPaletteProps) {
  const t = useLabel();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle === ''
      ? commands
      : commands.filter((command) => command.title.toLocaleLowerCase().includes(needle));
  }, [commands, query]);

  const close = () => {
    onOpenChange(false);
    setQuery('');
    setActive(0);
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
        placeholder={t('palette.placeholder')}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown')
            setActive((index) => Math.min(index + 1, matches.length - 1));
          if (event.key === 'ArrowUp') setActive((index) => Math.max(index - 1, 0));
          if (event.key === 'Enter') go(matches[active]);
        }}
      />
      <div id="command-palette-list" role="listbox" aria-label={t('palette.title')}>
        <List
          style={{ marginTop: 12 }}
          dataSource={matches}
          locale={{ emptyText: <EmptyText>{t('palette.no_results')}</EmptyText> }}
          renderItem={(command, index) => (
            <List.Item
              role="option"
              aria-selected={index === active}
              onClick={() => {
                go(command);
              }}
              style={{
                cursor: 'pointer',
                paddingInline: 12,
                borderRadius: 6,
                background:
                  index === active
                    ? 'var(--ant-control-item-bg-active, rgba(150,25,181,0.12))'
                    : undefined,
              }}
            >
              <Typography.Text>{command.title}</Typography.Text>
            </List.Item>
          )}
        />
      </div>
    </Modal>
  );
}
