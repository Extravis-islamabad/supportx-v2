import { Badge, Button, Card, Flex, Select, Table, Tag, Typography } from 'antd';
import { useState } from 'react';

import type { IncidentCatalogue, ReasonMode } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { statusLabel } from '../../incidents/labels';
import { useSettingsSave } from './helpers';
import { ValueDialog } from './shared';

type Status = IncidentCatalogue['statuses'][number];
type Transition = IncidentCatalogue['transitions'][number];
const MODES: ReasonMode[] = ['none', 'optional', 'required'];

/**
 * Statuses: labels and colours only; each status's category (which decides the SLA clock) and
 * the transitions stay as shipped until the life-cycle designer (D-056), and the screen says so.
 * Below, whether each transition asks for a reason (REQ-INC-047 AC3).
 */
export function StatusesTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, pending, problems, clear } = useSettingsSave();
  const [editing, setEditing] = useState<Status | null>(null);
  const close = () => {
    clear();
    setEditing(null);
  };
  const statuses = catalogue.statuses.filter((s) => !s.system);
  const name = (code: string | null) =>
    code === null ? t('settings.previous_status') : statusLabel(t, catalogue, code, locale);
  return (
    <Flex vertical gap={16}>
      <Card title={t('settings.statuses')} data-testid="settings-statuses">
        <Typography.Paragraph type="secondary">{t('settings.statuses_help')}</Typography.Paragraph>
        <Table
          size="small"
          rowKey="code"
          pagination={false}
          dataSource={statuses}
          columns={[
            {
              key: 'name',
              title: t('settings.name'),
              render: (_: unknown, status: Status) => (
                <Flex gap={8} align="center">
                  <Badge color={status.colour} />
                  <bdi dir="auto" data-testid={`status-name-${status.code}`}>
                    {name(status.code)}
                  </bdi>
                </Flex>
              ),
            },
            {
              key: 'category',
              title: t('settings.status_category'),
              render: (_: unknown, status: Status) => (
                <Tag>{t(`status_category.${status.category}`)}</Tag>
              ),
            },
            {
              key: 'actions',
              title: t('settings.actions'),
              width: 160,
              render: (_: unknown, status: Status) => (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    clear();
                    setEditing(status);
                  }}
                  data-testid={`status-edit-${status.code}`}
                >
                  {t('settings.rename')}
                </Button>
              ),
            },
          ]}
        />
      </Card>
      <Card title={t('settings.reason_prompts')} data-testid="settings-reason-prompts">
        <Typography.Paragraph type="secondary">
          {t('settings.reason_prompts_help')}
        </Typography.Paragraph>
        {editing === null && problems.length > 0 && (
          <Typography.Text type="danger" role="alert">
            {problems.join(' ')}
          </Typography.Text>
        )}
        <Table
          size="small"
          rowKey={(row: Transition) => `${row.from_status}.${row.action}`}
          pagination={false}
          dataSource={catalogue.transitions}
          columns={[
            {
              key: 'from',
              title: t('settings.from_status'),
              render: (_: unknown, row: Transition) => (
                <bdi dir="auto">{name(row.from_status)}</bdi>
              ),
            },
            {
              key: 'action',
              title: t('settings.status_action'),
              render: (_: unknown, row: Transition) => t(`work_item_action.${row.action}`),
            },
            {
              key: 'to',
              title: t('settings.to_status'),
              render: (_: unknown, row: Transition) => <bdi dir="auto">{name(row.to_status)}</bdi>,
            },
            {
              key: 'mode',
              title: t('settings.reason'),
              width: 220,
              render: (_: unknown, row: Transition) => (
                <Select<ReasonMode>
                  aria-label={t('settings.reason_for', {
                    action: t(`work_item_action.${row.action}`),
                    status: name(row.from_status),
                  })}
                  value={row.reason_mode}
                  disabled={pending}
                  style={{ width: '100%' }}
                  onChange={(mode) => {
                    save({
                      kind: 'transition',
                      from: row.from_status,
                      action: row.action,
                      reasonMode: mode,
                    });
                  }}
                  options={MODES.map((mode) => ({ value: mode, label: t(`reason_mode.${mode}`) }))}
                  data-testid={`prompt-${row.from_status}-${row.action}`}
                />
              ),
            },
          ]}
        />
      </Card>
      {editing !== null && (
        <ValueDialog
          open
          title={t('settings.rename_value', { name: name(editing.code) })}
          shippedKey={`work_item_status.${editing.code}`}
          labels={editing.labels ?? null}
          colour={editing.colour}
          withColour
          colourRequired
          pending={pending}
          problems={problems}
          onCancel={close}
          onSave={(labels, colour) => {
            save(
              {
                kind: 'status',
                code: editing.code,
                body: { labels, colour: colour ?? editing.colour },
              },
              close,
            );
          }}
          testId="status-dialog"
        />
      )}
    </Flex>
  );
}
