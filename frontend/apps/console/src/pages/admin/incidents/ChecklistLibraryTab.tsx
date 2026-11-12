import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Flex, Form, Input, List, Switch, Typography, Upload } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  checklistKeys,
  useChecklistLibraryAll,
  useImportChecklistItems,
  useLibraryChange,
  type ChecklistImport,
  type ChecklistLibraryEntry,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  EditDrawer,
  EmptyText,
  lengthLimit,
  reportError,
  SettingsCard,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { labelled } from '../../incidents/labels';

// Admin › Incidents › Checklists (WP-046a S2; REQ-INC-077/078): the library a record's
// checklists are copied from. Items are typed one per line, or read from a CSV first: the file
// is only read (nothing is saved), its good rows fill the items and its bad rows are listed by
// row number and reason, for the admin to review before saving. Live: the type's settings event.

const NAME_MAX = 200;
const SETTINGS_CHANGED = 'work_items.settings_changed';

export function ChecklistLibraryTab() {
  const t = useLabel();
  const { locale } = useAppearance();
  const queryClient = useQueryClient();
  const all = useChecklistLibraryAll('incidents');
  const change = useLibraryChange('incidents');
  const [editing, setEditing] = useState<ChecklistLibraryEntry | 'new' | null>(null);
  useTenantChannel((event) => {
    if (event.type === SETTINGS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: checklistKeys.library('incidents') });
    }
  });
  const rows = all.data ?? [];
  return (
    <SettingsCard
      title={t('settings.checklists.title')}
      description={t('settings.checklists.help')}
      testId="settings-checklists"
    >
      <Flex vertical gap={12}>
        <WriteButton
          icon={<PlusOutlined />}
          style={{ alignSelf: 'flex-start' }}
          onClick={() => {
            setEditing('new');
          }}
          data-testid="checklist-library-new"
        >
          {t('settings.checklists.add')}
        </WriteButton>
        <List
          dataSource={rows}
          loading={all.isPending}
          locale={{ emptyText: <EmptyText>{t('settings.checklists.none')}</EmptyText> }}
          renderItem={(entry) => (
            <List.Item
              key={entry.id}
              data-testid={`checklist-library-${entry.id}`}
              actions={[
                <Switch
                  key="on"
                  checked={!entry.disabled}
                  loading={change.isPending}
                  aria-label={t('settings.checklists.enabled_named', {
                    name: labelled(entry.labels, locale, () => entry.name),
                  })}
                  onChange={(on) => {
                    change.mutate(
                      {
                        kind: 'update',
                        libraryId: entry.id,
                        version: entry.version,
                        body: { disabled: !on },
                      },
                      { onError: reportError },
                    );
                  }}
                />,
                <Button
                  key="edit"
                  size="small"
                  onClick={() => {
                    setEditing(entry);
                  }}
                >
                  {t('actions.edit')}
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={labelled(entry.labels, locale, () => entry.name)}
                description={t('settings.checklists.items_count', { count: entry.items.length })}
              />
            </List.Item>
          )}
        />
      </Flex>
      {editing !== null && (
        <LibraryEditor
          entry={editing === 'new' ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </SettingsCard>
  );
}

function LibraryEditor({
  entry,
  onClose,
}: {
  entry: ChecklistLibraryEntry | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const change = useLibraryChange('incidents');
  const reader = useImportChecklistItems('incidents');
  const [name, setName] = useState(entry?.name ?? '');
  const [text, setText] = useState((entry?.items ?? []).join('\n'));
  const [read, setRead] = useState<ChecklistImport | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const items = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '');
  const dirty = name !== (entry?.name ?? '') || text !== (entry?.items ?? []).join('\n');
  const save = () => {
    change.mutate(
      entry === undefined
        ? { kind: 'create', body: { name: name.trim(), items } }
        : {
            kind: 'update',
            libraryId: entry.id,
            version: entry.version,
            body: { name: name.trim(), items },
          },
      { onSuccess: onClose, onError: reportError },
    );
  };
  const importFile = (file: File) => {
    setFailure(null);
    reader.mutate(file, {
      onSuccess: (found) => {
        setRead(found);
        setText([...items, ...found.items].join('\n'));
      },
      onError: (error) => {
        // A whole-file refusal (too big, not a CSV ...) names its reason in place.
        const code =
          error instanceof ApiError ? (error.problem?.errors?.[0]?.message_key ?? null) : null;
        if (code !== null) setFailure(t(code));
        else reportError(error);
      },
    });
    return false; // the file goes as the request body, never through Upload's own request
  };
  return (
    <EditDrawer
      open
      title={entry === undefined ? t('settings.checklists.add') : entry.name}
      okText={entry === undefined ? t('settings.checklists.add') : t('actions.save')}
      saving={change.isPending}
      okDisabled={name.trim() === ''}
      okWhyNot={name.trim() === '' ? t('settings.checklists.why.name') : undefined}
      dirty={dirty}
      onCancel={onClose}
      onOk={save}
      testId="checklist-library-editor"
    >
      <Form layout="vertical">
        <Form.Item label={t('settings.checklists.name')} required htmlFor="library-name">
          <Input
            id="library-name"
            value={name}
            count={lengthLimit(NAME_MAX)}
            onChange={(e) => {
              setName(e.target.value);
            }}
            data-testid="library-name"
          />
        </Form.Item>
        <Form.Item
          label={t('settings.checklists.items')}
          htmlFor="library-items"
          extra={t('settings.checklists.items_help')}
        >
          <Input.TextArea
            id="library-items"
            value={text}
            autoSize={{ minRows: 4, maxRows: 14 }}
            onChange={(e) => {
              setText(e.target.value);
            }}
            data-testid="library-items"
          />
        </Form.Item>
        <Upload accept=".csv,text/csv" showUploadList={false} beforeUpload={importFile}>
          <Button icon={<UploadOutlined />} loading={reader.isPending} data-testid="library-import">
            {t('settings.checklists.import')}
          </Button>
        </Upload>
        {failure !== null && (
          <Alert type="error" showIcon style={{ marginTop: 12 }} message={failure} />
        )}
        {read !== null && (
          <Alert
            type={read.rejected.length > 0 ? 'warning' : 'success'}
            showIcon
            style={{ marginTop: 12 }}
            data-testid="library-import-result"
            message={t('settings.checklists.imported', {
              items: read.items.length,
              rejected: read.rejected.length,
            })}
            description={
              read.rejected.length > 0 && (
                <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                  {read.rejected.map((row) => (
                    <li key={row.row}>
                      <Typography.Text>
                        {t('settings.checklists.rejected_row', {
                          row: row.row,
                          reason: t(`checklist_import_reason.${row.reason}`),
                        })}
                      </Typography.Text>
                    </li>
                  ))}
                </ul>
              )
            }
          />
        )}
      </Form>
    </EditDrawer>
  );
}
