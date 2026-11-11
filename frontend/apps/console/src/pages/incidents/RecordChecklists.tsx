import { DeleteOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Card,
  Checkbox,
  Flex,
  Input,
  List,
  Popconfirm,
  Progress,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useChecklistChange,
  useChecklistLibrary,
  useChecklists,
  type Checklist,
  type ChecklistBase,
} from '@supportx/api-client';
import {
  EmptyText,
  lengthLimit,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { labelled } from './labels';

// A record's checklists (WP-046a S2; REQ-INC-040): several per record, typed or taken from the
// library, each with its progress. Ticking an item is a working action, not an edit of the
// record, so anyone who may work the record ticks; adding and removing need the edit right.
// Live: the record's `work_items.part_changed` ("checklist") refetches this list (IncidentPage).

const TITLE_MAX = 200;
const ITEM_MAX = 500;

export function RecordChecklists({
  recordId,
  base = 'incidents',
  canEdit,
}: {
  recordId: string;
  base?: ChecklistBase;
  canEdit: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const found = useChecklists(recordId, base);
  const library = useChecklistLibrary(base, canEdit);
  const change = useChecklistChange(recordId, base);
  const [title, setTitle] = useState('');
  const [fromLibrary, setFromLibrary] = useState<string | null>(null);
  const lists = found.data ?? [];
  const sayDropped = (dropped: number) => {
    // The record's item limit (closing settings) left some out: say how many, never silently.
    if (dropped > 0) void message.warning(t('checklists.dropped', { count: dropped }));
  };
  const add = () => {
    change.mutate(
      fromLibrary !== null ? { kind: 'add', libraryId: fromLibrary } : { kind: 'add', title },
      {
        onSuccess: (dropped) => {
          sayDropped(dropped);
          setTitle('');
          setFromLibrary(null);
        },
        onError: reportError,
      },
    );
  };
  const offered = (library.data ?? []).filter((entry) => !entry.disabled);
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="checklists">
      {lists.length === 0 && !found.isPending && <EmptyText>{t('checklists.none')}</EmptyText>}
      {lists.map((list) => (
        <ChecklistCard
          key={list.id}
          list={list}
          canEdit={canEdit}
          onAddItems={(items) => {
            change.mutate(
              { kind: 'items', checklistId: list.id, items },
              { onSuccess: sayDropped, onError: reportError },
            );
          }}
          onTick={(itemId, version, done) => {
            change.mutate({ kind: 'tick', itemId, version, done }, { onError: reportError });
          }}
          onRemove={() => {
            change.mutate(
              { kind: 'remove', checklistId: list.id, version: list.version },
              { onError: reportError },
            );
          }}
        />
      ))}
      {canEdit && (
        <Flex gap={8} wrap align="center" data-testid="checklist-add">
          <Select
            allowClear
            style={{ minWidth: 220 }}
            value={fromLibrary ?? undefined}
            onChange={(value: string | undefined) => {
              setFromLibrary(value ?? null);
            }}
            placeholder={t('checklists.from_library')}
            aria-label={t('checklists.from_library')}
            loading={library.isPending}
            data-testid="checklist-library-pick"
            options={offered.map((entry) => ({
              value: entry.id,
              label: labelled(entry.labels, locale, () => entry.name),
            }))}
          />
          <Typography.Text type="secondary">{t('checklists.or')}</Typography.Text>
          <Input
            style={{ flex: '1 1 220px', maxWidth: 360 }}
            value={title}
            disabled={fromLibrary !== null}
            count={lengthLimit(TITLE_MAX)}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
            onPressEnter={() => {
              if (title.trim() !== '') add();
            }}
            placeholder={t('checklists.title_placeholder')}
            aria-label={t('checklists.title_placeholder')}
            data-testid="checklist-title"
          />
          <WriteButton
            onClick={add}
            loading={change.isPending}
            disabled={fromLibrary === null && title.trim() === ''}
            whyDisabled={t('checklists.why.title')}
            data-testid="checklist-add-button"
          >
            {t('checklists.add')}
          </WriteButton>
        </Flex>
      )}
    </Space>
  );
}

function ChecklistCard({
  list,
  canEdit,
  onAddItems,
  onTick,
  onRemove,
}: {
  list: Checklist;
  canEdit: boolean;
  onAddItems: (items: string[]) => void;
  onTick: (itemId: string, version: number, done: boolean) => void;
  onRemove: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const [text, setText] = useState('');
  const percent = list.total === 0 ? 0 : Math.round((list.done / list.total) * 100);
  const addItem = () => {
    const item = text.trim();
    if (item === '') return;
    onAddItems([item]);
    setText('');
  };
  return (
    <Card
      size="small"
      title={list.title}
      data-testid={`checklist-${String(list.position)}`}
      extra={
        canEdit && (
          <Popconfirm
            title={t('checklists.remove_confirm', { title: list.title })}
            okText={t('checklists.remove')}
            cancelText={t('actions.cancel')}
            onConfirm={onRemove}
          >
            <Button
              size="small"
              type="text"
              icon={<DeleteOutlined />}
              aria-label={t('checklists.remove_named', { title: list.title })}
              data-testid={`checklist-remove-${String(list.position)}`}
            />
          </Popconfirm>
        )
      }
    >
      <Flex vertical gap={8}>
        <Flex align="center" gap={12}>
          <Progress
            percent={percent}
            size="small"
            style={{ flex: 1, margin: 0 }}
            aria-label={t('checklists.progress', { done: list.done, total: list.total })}
          />
          <Typography.Text type="secondary" aria-live="polite">
            {t('checklists.progress', { done: list.done, total: list.total })}
          </Typography.Text>
        </Flex>
        <List
          size="small"
          dataSource={list.items}
          locale={{ emptyText: <EmptyText>{t('checklists.no_items')}</EmptyText> }}
          renderItem={(item) => (
            <List.Item key={item.id} data-testid={`checklist-item-${item.id}`}>
              <Checkbox
                checked={item.done_at !== null}
                onChange={(e) => {
                  onTick(item.id, item.version, e.target.checked);
                }}
              >
                <Typography.Text delete={item.done_at !== null}>{item.text}</Typography.Text>
              </Checkbox>
              {item.done_at !== null && (
                <Typography.Text type="secondary">
                  {item.done_by === null
                    ? t('checklists.done_on_close', { at: dates.format(item.done_at) })
                    : dates.format(item.done_at)}
                </Typography.Text>
              )}
            </List.Item>
          )}
        />
        {canEdit && (
          <Flex gap={8}>
            <Input
              value={text}
              count={lengthLimit(ITEM_MAX)}
              onChange={(e) => {
                setText(e.target.value);
              }}
              onPressEnter={addItem}
              placeholder={t('checklists.item_placeholder')}
              aria-label={t('checklists.item_placeholder')}
              data-testid={`checklist-item-input-${String(list.position)}`}
            />
            <Button onClick={addItem} disabled={text.trim() === ''}>
              {t('checklists.add_item')}
            </Button>
          </Flex>
        )}
      </Flex>
    </Card>
  );
}
