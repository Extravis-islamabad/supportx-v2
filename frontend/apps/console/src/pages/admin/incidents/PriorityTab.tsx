import { Alert, Badge, Button, Card, Flex, Select, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import type { IncidentCatalogue, IncidentScale, Priority } from '@supportx/api-client';
import { useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { scaleLabel } from '../../incidents/labels';
import { useDraft, useSettingsSave } from './helpers';
import { Problems, ValueDialog } from './shared';

const SCALES: Record<IncidentScale, readonly string[]> = {
  impact: ['one_person', 'team', 'department_or_site', 'organisation'],
  urgency: ['low', 'medium', 'high', 'critical'],
  priority: ['p1', 'p2', 'p3', 'p4'],
};
type ScaleValue = IncidentCatalogue['scales'][number];
type Matrix = Record<string, Priority>;
const cellKey = (impact: string, urgency: string) => `${impact}|${urgency}`;

/**
 * Impact, urgency and priority (REQ-INC-008/009): the values are fixed (D-056) and admins
 * name and colour them; the matrix maps every impact and urgency to a priority. It is saved
 * whole, and the server refuses a matrix with a gap (AC4).
 */
export function PriorityTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  return (
    <Flex vertical gap={16}>
      <MatrixCard catalogue={catalogue} />
      {(['priority', 'impact', 'urgency'] as const).map((scale) => (
        <ScaleCard key={scale} scale={scale} catalogue={catalogue} />
      ))}
    </Flex>
  );
}

function MatrixCard({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, pending, problems } = useSettingsSave();
  const source: Matrix = Object.fromEntries(
    catalogue.matrix.map((c) => [cellKey(c.impact, c.urgency), c.priority]),
  );
  const { draft, edit, reset, stale, dirty } = useDraft(source, catalogue.version);
  const changed = Object.keys(draft).filter((k) => draft[k] !== source[k]).length;
  const label = (scale: IncidentScale, code: string) =>
    scaleLabel(t, catalogue, scale, code, locale);
  const colour = (code: string) =>
    catalogue.scales.find((v) => v.scale === 'priority' && v.code === code)?.colour ?? undefined;
  return (
    <Card title={t('settings.matrix')} data-testid="settings-matrix">
      {stale && (
        <Alert
          type="warning"
          showIcon
          role="status"
          style={{ marginBottom: 12 }}
          message={t('settings.stale')}
          action={
            <Button size="small" onClick={reset}>
              {t('live.reload')}
            </Button>
          }
        />
      )}
      <Problems problems={problems} />
      <Typography.Paragraph type="secondary">{t('settings.matrix_help')}</Typography.Paragraph>
      <Table
        size="small"
        bordered
        pagination={false}
        rowKey={(impact: string) => impact}
        dataSource={[...SCALES.impact]}
        scroll={{ x: true }}
        columns={[
          {
            key: 'impact',
            title: t('settings.impact_by_urgency'),
            render: (_: unknown, impact: string) => (
              <Typography.Text strong>{label('impact', impact)}</Typography.Text>
            ),
          },
          ...SCALES.urgency.map((urgency) => ({
            key: urgency,
            title: label('urgency', urgency),
            render: (_: unknown, impact: string) => {
              const k = cellKey(impact, urgency);
              return (
                <Select<Priority>
                  aria-label={t('settings.matrix_cell', {
                    impact: label('impact', impact),
                    urgency: label('urgency', urgency),
                  })}
                  value={draft[k]}
                  style={{ minWidth: 120, width: '100%' }}
                  onChange={(next) => {
                    edit({ ...draft, [k]: next });
                  }}
                  options={SCALES.priority.map((p) => ({
                    value: p as Priority,
                    label: (
                      <Flex gap={6} align="center">
                        <Badge color={colour(p)} />
                        {label('priority', p)}
                      </Flex>
                    ),
                  }))}
                  data-testid={`matrix-${impact}-${urgency}`}
                />
              );
            },
          })),
        ]}
      />
      <Space style={{ marginTop: 12 }}>
        <WriteButton
          type="primary"
          loading={pending}
          disabled={!dirty || changed === 0}
          onClick={() => {
            save(
              {
                kind: 'matrix',
                cells: SCALES.impact.flatMap((impact) =>
                  SCALES.urgency.map((urgency) => ({
                    impact: impact as never,
                    urgency: urgency as never,
                    priority: draft[cellKey(impact, urgency)] ?? 'p3',
                  })),
                ),
              },
              reset,
            );
          }}
          data-testid="matrix-save"
        >
          {changed > 0 ? t('settings.save_cells', { count: changed }) : t('actions.save')}
        </WriteButton>
        <Button disabled={!dirty} onClick={reset}>
          {t('actions.reset')}
        </Button>
      </Space>
    </Card>
  );
}

function ScaleCard({ scale, catalogue }: { scale: IncidentScale; catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, pending, problems, clear } = useSettingsSave();
  const [editing, setEditing] = useState<ScaleValue | null>(null);
  const values = SCALES[scale].map(
    (code) =>
      catalogue.scales.find((v) => v.scale === scale && v.code === code) ?? {
        scale,
        code,
        rank: 0,
        colour: null,
        labels: null,
      },
  );
  const close = () => {
    clear();
    setEditing(null);
  };
  return (
    <Card title={t(`scale.${scale}`)} data-testid={`settings-scale-${scale}`}>
      <Typography.Paragraph type="secondary">
        {t(`settings.scale_help.${scale}`)}
      </Typography.Paragraph>
      <Table
        size="small"
        rowKey="code"
        pagination={false}
        dataSource={values}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, value: ScaleValue) => (
              <Flex gap={8} align="center">
                {value.colour !== null && <Badge color={value.colour} />}
                <bdi dir="auto" data-testid={`scale-${scale}-name-${value.code}`}>
                  {scaleLabel(t, catalogue, scale, value.code, locale)}
                </bdi>
              </Flex>
            ),
          },
          {
            key: 'actions',
            title: t('settings.actions'),
            width: 160,
            render: (_: unknown, value: ScaleValue) => (
              <Button
                type="link"
                size="small"
                onClick={() => {
                  clear();
                  setEditing(value);
                }}
                data-testid={`scale-${scale}-edit-${value.code}`}
              >
                {t('settings.rename')}
              </Button>
            ),
          },
        ]}
      />
      {editing !== null && (
        <ValueDialog
          open
          title={t('settings.rename_value', {
            name: scaleLabel(t, catalogue, scale, editing.code, locale),
          })}
          shipped={t(`${scale}.${editing.code}`)}
          labels={editing.labels ?? null}
          colour={editing.colour ?? null}
          withColour
          pending={pending}
          problems={problems}
          onCancel={close}
          onSave={(labels, colour) => {
            save({ kind: 'scale', scale, code: editing.code, body: { labels, colour } }, close);
          }}
          testId={`scale-${scale}-dialog`}
        />
      )}
    </Card>
  );
}
