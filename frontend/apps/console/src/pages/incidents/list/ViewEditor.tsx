import {
  App,
  Alert,
  Button,
  Drawer,
  Flex,
  Input,
  Popconfirm,
  Radio,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useSavedViewChange,
  useUnits,
  type FilterExpression,
  type IncidentListField,
  type ListColumn,
  type SavedView,
} from '@supportx/api-client';
import { FilterBuilder, rowProblems, toDsl } from '@supportx/forms';
import { lengthLimit, reportError, useLabel, WriteButton } from '@supportx/ui';

import type { ReportWords } from '../../reports/names';
import { builderFields, type ViewDraft } from './model';

// Custom views (REQ-INC-106): built with the shared filter builder (lane C, packages/forms), so a
// view is the same filter the list API, reports and rules take. "Apply" only changes this screen
// (AC2); "Save" stores the filter exactly as the list is sent it (AC3).

export function ViewEditor({
  draft,
  onClose,
  onApply,
  onSaved,
  fields,
  words,
  columns,
  sort,
}: {
  draft: ViewDraft | null;
  onClose: () => void;
  /** Use the filter on this screen only (nothing saved). */
  onApply: (filter: FilterExpression | undefined) => void;
  onSaved: (view: SavedView | null) => void;
  fields: IncidentListField[];
  words: ReportWords;
  columns: ListColumn[];
  sort: string;
}) {
  return (
    <Drawer
      open={draft !== null}
      onClose={onClose}
      width={640}
      destroyOnHidden
      data-testid="inc-view-editor"
      title={null}
    >
      {draft !== null && (
        <EditorBody
          initial={draft}
          onClose={onClose}
          onApply={onApply}
          onSaved={onSaved}
          fields={fields}
          words={words}
          columns={columns}
          sort={sort}
        />
      )}
    </Drawer>
  );
}

function EditorBody({
  initial,
  onClose,
  onApply,
  onSaved,
  fields,
  words,
  columns,
  sort,
}: {
  initial: ViewDraft;
  onClose: () => void;
  onApply: (filter: FilterExpression | undefined) => void;
  onSaved: (view: SavedView | null) => void;
  fields: IncidentListField[];
  words: ReportWords;
  columns: ListColumn[];
  sort: string;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const change = useSavedViewChange();
  const groups = useUnits('groups');
  const [draft, setDraft] = useState(initial);
  const problems = rowProblems(draft.filter);
  const nameMissing = draft.name.trim() === '';
  const groupsMissing = draft.visibility === 'groups' && draft.groupIds.length === 0;
  const filter = toDsl(draft.filter) as FilterExpression | undefined;
  const editing = draft.id !== undefined && draft.version !== undefined;
  const save = () => {
    const view = {
      name: draft.name.trim(),
      visibility: draft.visibility,
      group_ids: draft.visibility === 'groups' ? draft.groupIds : [],
      filter: (filter ?? null) as Record<string, unknown> | null,
      columns,
      sort,
    };
    change.mutate(
      editing
        ? { kind: 'update', id: draft.id ?? '', version: draft.version ?? 0, view }
        : { kind: 'create', view },
      {
        onSuccess: (saved) => {
          void message.success(t('incidents.views.saved'));
          onSaved(saved);
        },
        onError: reportError,
      },
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Title level={2} style={{ margin: 0 }}>
        {t(editing ? 'incidents.views.edit' : 'incidents.views.new')}
      </Typography.Title>
      <label>
        <Typography.Text strong>{t('incidents.views.name')}</Typography.Text>
        <Input
          value={draft.name}
          count={lengthLimit(120)}
          onChange={(event) => {
            setDraft({ ...draft, name: event.target.value });
          }}
          status={nameMissing ? 'warning' : undefined}
          data-testid="inc-view-name"
        />
      </label>
      <Radio.Group
        value={draft.visibility}
        onChange={(event) => {
          setDraft({ ...draft, visibility: event.target.value as ViewDraft['visibility'] });
        }}
        aria-label={t('incidents.views.who')}
        data-testid="inc-view-visibility"
      >
        <Radio value="private">{t('incidents.views.private')}</Radio>
        <Radio value="groups">{t('incidents.views.groups')}</Radio>
        <Radio value="everyone">{t('incidents.views.shared')}</Radio>
      </Radio.Group>
      {draft.visibility === 'groups' && (
        <Select<string[]>
          mode="multiple"
          aria-label={t('incidents.views.which_groups')}
          placeholder={t('incidents.views.which_groups')}
          value={draft.groupIds}
          onChange={(groupIds) => {
            setDraft({ ...draft, groupIds });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          optionFilterProp="label"
          status={groupsMissing ? 'warning' : undefined}
          data-testid="inc-view-groups"
        />
      )}
      <FilterBuilder
        fields={builderFields(fields, words)}
        value={draft.filter}
        onChange={(next) => {
          setDraft({ ...draft, filter: next });
        }}
        testId="inc-view-filter"
      />
      {problems.size > 0 && (
        <Alert type="warning" showIcon message={t('incidents.views.fix_filter')} />
      )}
      <Typography.Text type="secondary">{t('incidents.views.columns_note')}</Typography.Text>
      <Flex gap={8} wrap justify="space-between">
        <Space wrap>
          <Button
            disabled={problems.size > 0}
            onClick={() => {
              onApply(filter);
            }}
            data-testid="inc-view-try"
          >
            {t('incidents.views.try')}
          </Button>
          <WriteButton
            type="primary"
            loading={change.isPending}
            disabled={problems.size > 0 || nameMissing || groupsMissing}
            title={
              nameMissing
                ? t('incidents.views.name_needed')
                : groupsMissing
                  ? t('incidents.views.groups_needed')
                  : undefined
            }
            onClick={save}
            data-testid="inc-view-save"
          >
            {t('incidents.views.save')}
          </WriteButton>
          <Button onClick={onClose}>{t('incidents.views.cancel')}</Button>
        </Space>
        {editing && (
          <Popconfirm
            title={t('incidents.views.delete_confirm', { name: draft.name })}
            okText={t('incidents.views.delete')}
            cancelText={t('incidents.views.cancel')}
            onConfirm={() => {
              change.mutate(
                { kind: 'delete', id: draft.id ?? '', version: draft.version ?? 0 },
                {
                  onSuccess: () => {
                    onSaved(null);
                  },
                  onError: reportError,
                },
              );
            }}
          >
            <Button danger data-testid="inc-view-delete">
              {t('incidents.views.delete')}
            </Button>
          </Popconfirm>
        )}
      </Flex>
    </Space>
  );
}
