import { DownloadOutlined } from '@ant-design/icons';
import { App, Button, Form, Modal, Radio, Tooltip } from 'antd';
import { useState } from 'react';

import { useRequestExport, type FilterExpression } from '@supportx/api-client';
import { FormProblem, useAccess, useAppearance, useFormProblem, useLabel } from '@supportx/ui';

import { MyExportsButton } from '../../reports/exports';

// The list exports what it shows (WP-020d): lane C's report export, never a second path. A
// built-in view becomes its filter equivalent (GET /incidents/view-filters), joined with the
// list's own filter; a view the filter language cannot say is not exported, and says why.

const FORMATS = ['xlsx', 'csv'] as const;
type Format = (typeof FORMATS)[number];

export function ListExport({
  title,
  filter,
}: {
  title: string;
  /** null: the active view cannot be exported. */
  filter: FilterExpression | undefined | null;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const request = useRequestExport();
  const problem = useFormProblem();
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<Format>('xlsx');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const language = (['en', 'ar', 'ur'] as const).find((l) => l === locale) ?? 'en';
  const why = !can('reports.export')
    ? t('incidents.export.no_permission')
    : filter === null
      ? t('incidents.export.view_not_exportable')
      : undefined;

  return (
    <>
      <Tooltip title={why}>
        <span>
          <Button
            icon={<DownloadOutlined />}
            disabled={why !== undefined}
            onClick={() => {
              setOpen(true);
            }}
            data-testid="inc-export"
          >
            {t('incidents.export.button')}
          </Button>
        </span>
      </Tooltip>
      {can('reports.export') && <MyExportsButton />}
      <Modal
        open={open}
        title={t('incidents.export.title')}
        okText={t('incidents.export.button')}
        cancelText={t('incidents.export.cancel')}
        okButtonProps={{ loading: request.isPending, 'data-testid': 'inc-export-start' }}
        onCancel={() => {
          setOpen(false);
          problem.clear();
        }}
        onOk={() => {
          problem.clear();
          request.mutate(
            {
              key,
              body: {
                title,
                format,
                content: 'records',
                language,
                definition: {
                  schema_version: 1,
                  entity: 'incident',
                  filter: filter ?? null,
                  group_by: [],
                  measures: ['count'],
                  order: 'key',
                  limit: null,
                  chart: 'table',
                  percent: false,
                },
              },
            },
            {
              onSuccess: () => {
                setOpen(false);
                setKey(crypto.randomUUID());
                void message.info(t('incidents.export.started'));
              },
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
      >
        <Form layout="vertical">
          <Form.Item label={t('incidents.export.format')}>
            <Radio.Group
              value={format}
              onChange={(event) => {
                setFormat(event.target.value as Format);
              }}
              options={FORMATS.map((f) => ({ value: f, label: t(`report_export_format.${f}`) }))}
              data-testid="inc-export-format"
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      </Modal>
    </>
  );
}
