import {
  App,
  Button,
  Card,
  Flex,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIncidentTemplateChange,
  useIncidentTemplates,
  type IncidentTemplate,
  type Labels,
  type TemplateChange,
} from '@supportx/api-client';
import { useLabelsIn } from '@supportx/labels';
import { EmptyText, reportError, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { templateLabel } from '../../incidents/labels';
import { TemplateEditor } from './TemplateEditor';
import { cleanLabels } from './helpers';
import { LabelsFields, Problems } from './shared';
import { templateProblems } from './helpers';

/**
 * Incident templates (REQ-INC-035): searchable and grouped, with the default first; copy (a
 * marked, independent copy: AC3), make default, disable (not offered, still named on old
 * incidents: AC2) and edit in a drawer.
 */
export function TemplatesTab() {
  const t = useLabel();
  const tIn = useLabelsIn();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const templates = useIncidentTemplates();
  const change = useIncidentTemplateChange();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<IncidentTemplate | 'new' | null>(null);
  const [copying, setCopying] = useState<IncidentTemplate | null>(null);
  const [copyName, setCopyName] = useState<Labels>({});
  const [copyProblems, setCopyProblems] = useState<string[]>([]);
  const all = templates.data ?? [];
  const byId = new Map(all.map((x) => [x.id, x]));
  const name = (x: IncidentTemplate) => templateLabel(t, x, locale);
  const shown = all.filter((x) => {
    const q = search.trim().toLocaleLowerCase();
    return q === '' || `${name(x)} ${x.group_name ?? ''}`.toLocaleLowerCase().includes(q);
  });
  const run = (next: TemplateChange) => {
    change.mutate(next, {
      onSuccess: () => {
        void message.success(t('settings.saved'));
      },
      onError: (error) => {
        if (error instanceof ApiError && error.isConflict) {
          void message.warning(t('settings.changed_elsewhere'));
          return;
        }
        const problems = templateProblems(t, error);
        if (problems.length > 0) void message.error(problems.join(' '));
        else reportError(error);
      },
    });
  };
  return (
    <Card
      title={t('settings.templates')}
      extra={
        <WriteButton
          type="primary"
          onClick={() => {
            setEditing('new');
          }}
          data-testid="tpl-admin-new"
        >
          {t('templates.new')}
        </WriteButton>
      }
      data-testid="settings-templates"
    >
      <Typography.Paragraph type="secondary">{t('templates.help')}</Typography.Paragraph>
      <Input.Search
        allowClear
        aria-label={t('templates.search')}
        placeholder={t('templates.search')}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        style={{ maxWidth: 360, marginBottom: 12 }}
        data-testid="tpl-admin-search"
      />
      <Table
        size="small"
        rowKey="id"
        loading={templates.isPending}
        pagination={false}
        dataSource={shown}
        locale={{ emptyText: <EmptyText>{t('templates.none_found')}</EmptyText> }}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, x: IncidentTemplate) => (
              <Flex gap={6} align="center" wrap>
                <bdi dir="auto" data-testid={`tpl-admin-name-${x.id}`}>
                  {name(x)}
                </bdi>
                {x.is_default && <Tag color="blue">{t('templates.default')}</Tag>}
                {x.disabled && <Tag>{t('templates.disabled')}</Tag>}
                {x.copied_from_id !== null && (
                  <Tag data-testid={`tpl-admin-copy-tag-${x.id}`}>
                    {t('templates.copy_of', {
                      name: byId.has(x.copied_from_id)
                        ? name(byId.get(x.copied_from_id) as IncidentTemplate)
                        : t('templates.another_template'),
                    })}
                  </Tag>
                )}
              </Flex>
            ),
          },
          {
            key: 'group',
            title: t('templates.group'),
            render: (_: unknown, x: IncidentTemplate) => <bdi dir="auto">{x.group_name ?? ''}</bdi>,
          },
          {
            key: 'portal',
            title: t('templates.for_requesters'),
            render: (_: unknown, x: IncidentTemplate) =>
              x.for_requesters ? t('settings.yes') : t('settings.no'),
          },
          {
            key: 'actions',
            title: t('settings.actions'),
            render: (_: unknown, x: IncidentTemplate) => (
              <Space size={0} wrap>
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setEditing(x);
                  }}
                  data-testid={`tpl-admin-edit-${x.id}`}
                >
                  {t('actions.edit')}
                </Button>
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setCopyProblems([]);
                    // A name in every language the original has one in, each in its own
                    // language (QA BUG-05, D-086); a built-in template has all of them, so the
                    // required English name is always there, whatever the UI language.
                    setCopyName(
                      Object.fromEntries(
                        (['en', 'ar', 'ur'] as const).flatMap((language) => {
                          const base =
                            x.labels?.[language] ??
                            (x.code === null
                              ? undefined
                              : tIn(language, `incident_template.${x.code}`));
                          return base === undefined
                            ? []
                            : [[language, tIn(language, 'templates.copy_name', { name: base })]];
                        }),
                      ),
                    );
                    setCopying(x);
                  }}
                  data-testid={`tpl-admin-copy-${x.id}`}
                >
                  {t('templates.copy')}
                </Button>
                {!x.is_default && !x.disabled && (
                  <Button
                    type="link"
                    size="small"
                    disabled={change.isPending}
                    onClick={() => {
                      run({
                        kind: 'update',
                        id: x.id,
                        version: x.version,
                        body: { is_default: true },
                      });
                    }}
                    data-testid={`tpl-admin-default-${x.id}`}
                  >
                    {t('templates.make_default')}
                  </Button>
                )}
                {x.disabled ? (
                  <Button
                    type="link"
                    size="small"
                    disabled={change.isPending}
                    onClick={() => {
                      run({
                        kind: 'update',
                        id: x.id,
                        version: x.version,
                        body: { disabled: false },
                      });
                    }}
                    data-testid={`tpl-admin-enable-${x.id}`}
                  >
                    {t('templates.enable')}
                  </Button>
                ) : (
                  !x.is_default && (
                    <Popconfirm
                      title={t('templates.disable_confirm', { name: name(x) })}
                      description={t('templates.disable_explained')}
                      okText={t('templates.disable')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        run({
                          kind: 'update',
                          id: x.id,
                          version: x.version,
                          body: { disabled: true },
                        });
                      }}
                    >
                      <Button type="link" size="small" data-testid={`tpl-admin-disable-${x.id}`}>
                        {t('templates.disable')}
                      </Button>
                    </Popconfirm>
                  )
                )}
              </Space>
            ),
          },
        ]}
      />
      {editing !== null && (
        <TemplateEditor
          template={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      <Modal
        open={copying !== null}
        title={t('templates.copy_title', { name: copying === null ? '' : name(copying) })}
        okText={t('templates.copy')}
        cancelText={t('actions.cancel')}
        confirmLoading={change.isPending}
        onCancel={() => {
          setCopying(null);
        }}
        onOk={() => {
          if (copying === null) return;
          change.mutate(
            { kind: 'copy', id: copying.id, labels: cleanLabels(copyName) ?? {} },
            {
              onSuccess: () => {
                void message.success(t('templates.copied'));
                setCopying(null);
              },
              onError: (error) => {
                const problems = templateProblems(t, error);
                if (problems.length > 0) setCopyProblems(problems);
                else reportError(error);
              },
            },
          );
        }}
        destroyOnHidden
        data-testid="tpl-copy-dialog"
      >
        <Problems problems={copyProblems} />
        <Form layout="vertical" component="div">
          <LabelsFields value={copyName} onChange={setCopyName} testId="tpl-copy-name" />
        </Form>
      </Modal>
    </Card>
  );
}
