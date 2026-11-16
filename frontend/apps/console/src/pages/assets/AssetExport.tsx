import { DownloadOutlined } from '@ant-design/icons';
import { App, Button, Form, Modal, Radio, Tooltip, Typography } from 'antd';
import { useState } from 'react';

import { useRequestExport, type FilterExpression } from '@supportx/api-client';
import { FormProblem, useAccess, useAppearance, useFormProblem, useLabel } from '@supportx/ui';

import { exportColumns } from './batch';

// The asset list exports what it shows (WP-049b S4b; REQ-AST-053, after REQ-INC-116): the
// reports export, never a second path. Money columns (price, tax, book value, total cost) go in
// only for people with assets.view_financials (D-157); the server refuses them to anyone else.

const FORMATS = ['xlsx', 'csv'] as const;
type Format = (typeof FORMATS)[number];
export function AssetListExport({
  filter,
  title,
}: {
  /** null: the active view cannot be said as a filter, so it is not exported (and says why). */
  filter: FilterExpression | null | undefined;
  title: string;
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
  const seesMoney = can('assets.view_financials');
  const language = (['en', 'ar', 'ur'] as const).find((l) => l === locale) ?? 'en';
  const why = !can('reports.export')
    ? t('assets.export.no_permission')
    : filter === null
      ? t('assets.export.view_not_exportable')
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
            data-testid="assets-export"
          >
            {t('assets.export.button')}
          </Button>
        </span>
      </Tooltip>
      <Modal
        open={open}
        title={t('assets.export.title')}
        okText={t('assets.export.button')}
        cancelText={t('actions.cancel')}
        okButtonProps={{ loading: request.isPending, 'data-testid': 'assets-export-start' }}
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
                  entity: 'asset',
                  filter: filter ?? null,
                  group_by: [],
                  measures: ['count'],
                  order: 'key',
                  limit: null,
                  chart: 'table',
                  percent: false,
                  columns: exportColumns(seesMoney),
                  sort: [{ field: 'updated_at', desc: true }],
                },
              },
            },
            {
              onSuccess: () => {
                setOpen(false);
                setKey(crypto.randomUUID());
                void message.info(t('assets.export.started'));
              },
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
        destroyOnHidden
        data-testid="assets-export-dialog"
      >
        <Form layout="vertical" component="div">
          <Form.Item label={t('assets.export.format')}>
            <Radio.Group
              value={format}
              onChange={(event) => {
                setFormat(event.target.value as Format);
              }}
              options={FORMATS.map((f) => ({ value: f, label: t(`report_export_format.${f}`) }))}
              data-testid="assets-export-format"
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
        <Typography.Text type="secondary" data-testid="assets-export-money">
          {seesMoney ? t('assets.export.money') : t('assets.export.no_money')}
        </Typography.Text>
      </Modal>
    </>
  );
}
