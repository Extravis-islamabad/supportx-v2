import { Alert, App, Flex, Form, Radio, Select, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  useCiMergePreview,
  useCiPicker,
  useCiStates,
  useCustomFields,
  useMergeCis,
  type Ci,
  type CiMergeField,
  type CiMergeSide,
} from '@supportx/api-client';
import { Drawer, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { problemText } from '../assets/problemText';
import { fieldName } from '../customFields/values';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';
import { nameOf } from './names';
import { refText } from './refNames';

// Merge a duplicate into this CI (WP-053 S4b; REQ-CMDB-017; template B, a drawer). This CI is
// kept; the duplicate goes to the trash and its ID then opens this one. The preview comes from
// the server: a custom field you may not read is never listed, and stays this CI's (lane C (9)).
// Relationships, business views and subscribers move here, duplicates collapsed.

// Custom field types whose values are plain text to show; any other reads "Set" (never a code).
const PLAIN = new Set(['text', 'textarea', 'number', 'url', 'email']);
const IMPACTS = new Set(['business_impact', 'criticality']);

export function CiMergeDrawer({ ci, onClose }: { ci: Ci; onClose: () => void }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const states = useCiStates();
  const custom = useCustomFields('ci', false, true, { typeId: ci.type_id });
  const [search, setSearch] = useState('');
  const typed = useDebounced(search, SEARCH_DELAY_MS);
  const picker = useCiPicker(typed, ci.type_id);
  const [other, setOther] = useState<string>();
  const [choices, setChoices] = useState<Record<string, CiMergeSide>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [key] = useState(() => crypto.randomUUID());
  const preview = useCiMergePreview(other === undefined ? undefined : ci.id, other);
  const merge = useMergeCis();
  const fields = preview.data?.fields ?? [];
  // This CI is the survivor whatever the suggestion says; the preview is read this way round.
  const survivor = preview.data?.swapped ? preview.data.merged : preview.data?.survivor;
  const duplicate = preview.data?.swapped ? preview.data.survivor : preview.data?.merged;
  const sideOf = (f: CiMergeField): CiMergeSide => {
    const chosen = choices[f.field];
    if (chosen !== undefined) return chosen;
    if (!preview.data?.swapped) return f.side;
    return f.side === 'survivor' ? 'merged' : 'survivor';
  };
  const valueOf = (f: CiMergeField, side: 'this' | 'duplicate') =>
    (side === 'this') !== Boolean(preview.data?.swapped) ? f.survivor : f.merged;
  const definition = (field: string) =>
    (custom.data ?? []).find((x) => `custom.${x.key}` === field);
  const fieldLabel = (field: string) => {
    if (!field.startsWith('custom.')) return t(`cmdb.field.${field}`);
    const found = definition(field);
    return found === undefined ? t('cmdb.merge.custom_field') : fieldName(found, locale);
  };
  /** A value in words, as the reader may see it: never an ID or a code (rule d). */
  const shown = (f: CiMergeField, side: 'this' | 'duplicate'): string => {
    const value: unknown = valueOf(f, side);
    if (value === null || value === undefined || value === '') return t('cmdb.merge.empty');
    if (f.field === 'state_id') {
      const state = states.data?.items.find((x) => x.id === value);
      return state === undefined
        ? t('cmdb.versions.set')
        : nameOf(t, locale, state, 'cmdb_ci_state');
    }
    if (IMPACTS.has(f.field) && typeof value === 'string') return t(`cmdb_impact.${value}`);
    if (f.field.endsWith('_id')) {
      const record = side === 'this' ? ci : duplicate;
      return refText(t, record?.names, value);
    }
    if (f.field.startsWith('custom.')) {
      const type = definition(f.field)?.field_type;
      if (type === undefined || !PLAIN.has(type)) return t('cmdb.merge.value_set');
    }
    return typeof value === 'string' || typeof value === 'number'
      ? String(value)
      : t('cmdb.merge.value_set');
  };
  const submit = () => {
    if (survivor === undefined || duplicate === undefined) return;
    setProblem(null);
    merge.mutate(
      {
        key,
        survivor: { id: survivor.id, version: survivor.version },
        merged: { id: duplicate.id, version: duplicate.version },
        choices: Object.fromEntries(fields.map((f) => [f.field, sideOf(f)])),
      },
      {
        onSuccess: () => {
          void message.success(t('cmdb.merge.done', { id: duplicate.display_id }));
          onClose();
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Drawer
      open
      title={t('cmdb.merge.title')}
      width="min(720px, 100vw)"
      destroyOnHidden
      onClose={onClose}
      data-testid="ci-merge-drawer"
      footer={
        <Flex justify="end">
          <WriteButton
            type="primary"
            danger
            disabled={survivor === undefined}
            whyDisabled={survivor === undefined ? t('cmdb.merge.pick') : undefined}
            loading={merge.isPending}
            onClick={submit}
            data-testid="ci-merge-submit"
          >
            {t('cmdb.merge.submit')}
          </WriteButton>
        </Flex>
      }
    >
      <Flex vertical gap={16}>
        <Typography.Text type="secondary">{t('cmdb.merge.help')}</Typography.Text>
        {problem !== null && (
          <Alert type="error" showIcon message={problem} data-testid="ci-merge-problem" />
        )}
        <Form layout="vertical" component="div">
          <Form.Item label={t('cmdb.merge.pick')}>
            <Select
              showSearch
              filterOption={false}
              onSearch={setSearch}
              value={other}
              onChange={(value: string) => {
                setOther(value);
                setChoices({});
              }}
              loading={picker.isFetching}
              options={(picker.data?.items ?? [])
                .filter((x) => x.id !== ci.id)
                .map((x) => ({ value: x.id, label: `${x.display_id} · ${x.name}` }))}
              data-testid="ci-merge-pick"
            />
          </Form.Item>
        </Form>
        {preview.isError && (
          <Alert
            type="error"
            showIcon
            message={problemText(t, preview.error)}
            data-testid="ci-merge-preview-problem"
          />
        )}
        {preview.data !== undefined && (
          <Table<CiMergeField>
            size="small"
            rowKey="field"
            pagination={false}
            dataSource={fields}
            data-testid="ci-merge-fields"
            columns={[
              {
                key: 'field',
                title: t('cmdb.merge.field'),
                render: (_, f) => fieldLabel(f.field),
              },
              {
                key: 'choice',
                title: t('cmdb.merge.keep'),
                render: (_, f) => (
                  <Radio.Group
                    value={sideOf(f)}
                    onChange={(event) => {
                      setChoices((c) => ({ ...c, [f.field]: event.target.value as CiMergeSide }));
                    }}
                    data-testid={`ci-merge-choice-${f.field}`}
                  >
                    <Radio value="survivor">
                      <bdi dir="auto">{shown(f, 'this')}</bdi>
                    </Radio>
                    <Radio value="merged">
                      <bdi dir="auto">{shown(f, 'duplicate')}</bdi>
                    </Radio>
                  </Radio.Group>
                ),
              },
            ]}
          />
        )}
      </Flex>
    </Drawer>
  );
}
