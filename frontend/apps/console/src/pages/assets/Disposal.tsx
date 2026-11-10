import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Select,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useRef, useState } from 'react';

import {
  ApiError,
  fileLink,
  uploadFile,
  useAssetActions,
  useAssetDisposal,
  useRecordFiles,
  type AssetDisposal,
  type AssetDisposalInput,
  type AssetRecord,
} from '@supportx/api-client';
import {
  EmptyText,
  lengthLimit,
  pickerFormat,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';

const METHODS: AssetDisposalInput['method'][] = [
  'resale',
  'recycling',
  'donation',
  'destruction',
  'returned_to_vendor',
  'other',
];
const REASON_MAX = 1000;

type Fields = Partial<
  Record<'disposed_on' | 'method' | 'reason' | 'cost' | 'currency' | 'approved_by', string>
>;

/** Field problems of a 422, by field; anything else is reported or shown as one message. */
function problemsOf(
  t: ReturnType<typeof useLabel>,
  error: unknown,
): { fields: Fields; message: string | null } {
  if (!(error instanceof ApiError)) {
    reportError(error);
    return { fields: {}, message: null };
  }
  const fields: Fields = {};
  for (const problem of error.fieldErrors) {
    const name = problem.field.split('.').at(-1) as keyof Fields;
    fields[name] = t(`errors.field.${problem.code}`, problem.params ?? {});
  }
  if (Object.keys(fields).length > 0) return { fields, message: null };
  if (error.problem !== null) return { fields, message: t(error.messageKey, error.params) };
  reportError(error);
  return { fields, message: null };
}

/**
 * Dispose of an asset with its record (REQ-AST-017): when, how, why, the cost and who approved
 * it; the asset moves to the disposed state in the same step and is read-only after.
 */
export function DisposeAssetDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { dates } = useAppearance();
  const { dispose } = useAssetActions();
  const [when, setWhen] = useState<Dayjs | null>(dayjs());
  const [method, setMethod] = useState<AssetDisposalInput['method']>();
  const [reason, setReason] = useState('');
  const [cost, setCost] = useState<number | null>(null);
  const [currency, setCurrency] = useState(asset.currency ?? '');
  const [approver, setApprover] = useState<string | null>(null);
  const [fields, setFields] = useState<Fields>({});
  const [message, setMessage] = useState<string | null>(null);
  const close = () => {
    setFields({});
    setMessage(null);
    onClose();
  };
  const submit = () => {
    const local: Fields = {};
    if (when === null) local.disposed_on = t('errors.field.required');
    if (method === undefined) local.method = t('errors.field.required');
    if (reason.trim() === '') local.reason = t('errors.field.required');
    setFields(local);
    if (Object.keys(local).length > 0 || when === null || method === undefined) return;
    setMessage(null);
    dispose.mutate(
      {
        id: asset.id,
        version: asset.version,
        body: {
          disposed_on: when.format('YYYY-MM-DD'),
          method,
          reason: reason.trim(),
          cost: cost === null ? null : cost.toFixed(2),
          currency: cost === null || currency.trim() === '' ? null : currency.trim().toUpperCase(),
          approved_by: approver,
        },
      },
      {
        onSuccess: close,
        onError: (error) => {
          const found = problemsOf(t, error);
          setFields(found.fields);
          setMessage(found.message);
        },
      },
    );
  };
  const item = (name: keyof Fields) =>
    fields[name] === undefined ? {} : { validateStatus: 'error' as const, help: fields[name] };
  return (
    <Modal
      open={open}
      title={t('assets.dispose.title', { name: asset.name })}
      okText={t('assets.dispose.ok')}
      okButtonProps={{ danger: true }}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={close}
      confirmLoading={dispose.isPending}
      destroyOnHidden
      data-testid="asset-dispose-dialog"
    >
      {message !== null && (
        <Alert type="error" showIcon message={message} style={{ marginBottom: 12 }} />
      )}
      <Typography.Paragraph type="secondary">{t('assets.dispose.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.dispose.on')} required {...item('disposed_on')}>
          <DatePicker
            value={when}
            onChange={setWhen}
            format={pickerFormat(dates, false)}
            disabledDate={(day) => day.isAfter(dayjs(), 'day')}
            data-testid="asset-dispose-on"
          />
        </Form.Item>
        <Form.Item label={t('assets.dispose.method')} required {...item('method')}>
          <Select
            value={method}
            onChange={setMethod}
            data-testid="asset-dispose-method"
            options={METHODS.map((m) => ({ value: m, label: t(`asset_disposal_method.${m}`) }))}
          />
        </Form.Item>
        <Form.Item label={t('assets.move.reason')} required {...item('reason')}>
          <Input.TextArea
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
            }}
            rows={3}
            count={lengthLimit(REASON_MAX)}
            data-testid="asset-dispose-reason"
          />
        </Form.Item>
        <Flex gap={12} wrap>
          <Form.Item label={t('assets.dispose.cost')} {...item('cost')}>
            <InputNumber
              min={0}
              precision={2}
              value={cost}
              onChange={setCost}
              data-testid="asset-dispose-cost"
            />
          </Form.Item>
          <Form.Item label={t('assets.dispose.currency')} {...item('currency')}>
            <Input
              value={currency}
              onChange={(event) => {
                setCurrency(event.target.value);
              }}
              count={lengthLimit(3)}
              style={{ width: 96 }}
              dir="ltr"
              data-testid="asset-dispose-currency"
            />
          </Form.Item>
        </Flex>
        <Form.Item label={t('assets.dispose.approved_by')} {...item('approved_by')}>
          <UserPicker
            value={approver}
            onChange={setApprover}
            testId="asset-dispose-approver"
            ariaLabel={t('assets.dispose.approved_by')}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** The disposal record on a disposed asset, with its certificate (a file of the record). */
export function DisposalCard({ asset, canManage }: { asset: AssetRecord; canManage: boolean }) {
  const t = useLabel();
  const dates = useDateTime();
  const { intlLocale } = useAppearance();
  const disposal = useAssetDisposal(asset.id);
  const files = useRecordFiles('asset', disposal.data === undefined ? undefined : asset.id);
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  if (disposal.data === undefined) return null;
  const record: AssetDisposal = disposal.data;
  // The reason a person typed (free text), not a code.
  const statedWhy = record.reason;
  const certificates = (files.data ?? []).filter((f) => f.owner_type === 'asset_disposal');
  const money =
    record.cost === null
      ? '—'
      : record.currency === null
        ? new Intl.NumberFormat(intlLocale, { minimumFractionDigits: 2 }).format(
            Number(record.cost),
          )
        : new Intl.NumberFormat(intlLocale, {
            style: 'currency',
            currency: record.currency,
          }).format(Number(record.cost));
  const upload = (file: File) => {
    setUploading(true);
    uploadFile(file, { ownerType: 'asset_disposal', ownerId: record.id })
      .done.then(() => files.refetch())
      .catch(reportError)
      .finally(() => {
        setUploading(false);
      });
  };
  return (
    <Card title={t('assets.dispose.record')} data-testid="asset-disposal">
      <Descriptions
        column={{ xs: 1, md: 2 }}
        size="small"
        items={[
          {
            key: 'on',
            label: t('assets.dispose.on'),
            children: dates.formatDay(record.disposed_on),
          },
          {
            key: 'method',
            label: t('assets.dispose.method'),
            children: t(`asset_disposal_method.${record.method}`),
          },
          { key: 'cost', label: t('assets.dispose.cost'), children: money },
          {
            key: 'reason',
            label: t('assets.move.reason'),
            children: <bdi dir="auto">{statedWhy}</bdi>,
          },
        ]}
      />
      <Typography.Text strong>{t('assets.dispose.certificate')}</Typography.Text>
      <List
        size="small"
        dataSource={certificates}
        locale={{ emptyText: <EmptyText>{t('assets.dispose.no_certificate')}</EmptyText> }}
        renderItem={(file) => (
          <List.Item key={file.id}>
            <Button
              type="link"
              onClick={() => {
                void fileLink(file.id, 'attachment').then((url) => {
                  window.location.assign(url);
                }, reportError);
              }}
            >
              <bdi dir="auto">{file.name}</bdi>
            </Button>
          </List.Item>
        )}
      />
      {canManage && (
        <>
          <input
            ref={input}
            type="file"
            hidden
            aria-hidden
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              if (chosen !== undefined) upload(chosen);
              event.target.value = '';
            }}
            data-testid="asset-certificate-input"
          />
          <WriteButton
            loading={uploading}
            onClick={() => input.current?.click()}
            data-testid="asset-certificate-add"
          >
            {t('assets.dispose.add_certificate')}
          </WriteButton>
        </>
      )}
    </Card>
  );
}
