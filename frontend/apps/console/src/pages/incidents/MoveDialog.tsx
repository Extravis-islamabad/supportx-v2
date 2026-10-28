import { Alert, Button, Input, Modal, Select, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useSession,
  type IncidentActionState,
  type IncidentCatalogue,
} from '@supportx/api-client';
import {
  FormProblem,
  RichTextField,
  RichTextView,
  useAppearance,
  useLabel,
  lengthLimit,
  type FormProblemState,
} from '@supportx/ui';

import { useIncidentFieldName } from './conflict';
import { labelled, listValueLabel } from './labels';

const REASON_MAX = 500;
// The dialog's own fields: a refusal naming one of these is shown at that field.
const OWN_FIELDS = new Set(['reason_code', 'reason_text', 'resolution', 'closure_code']);
// Record fields the closure rules still need (REQ-INC-094): filled on the record, not here.
const RECORD_FIELD_CODES = new Set(['required_to_resolve', 'required_to_close']);

/** What the move dialog sends. */
export interface MoveInput {
  reasonCode?: string;
  reasonText: string;
  resolution?: string;
  closureCode?: string;
}

/** Open work the server asked to confirm (409 open_work_unconfirmed, REQ-INC-095). */
export interface OpenWork {
  count: number;
  items: string;
}

/** Title and buttons of the dialog; cancelling an incident needs its own words (BUG-06). */
function dialogWords(t: (key: string) => string, action: string) {
  if (action === 'cancel') {
    return {
      title: t('incidents.cancel_title'),
      ok: t('incidents.cancel_confirm'),
      dismiss: t('incidents.cancel_keep'),
    };
  }
  const name = t(`work_item_action.${action}`);
  return { title: name, ok: name, dismiss: t('actions.cancel') };
}

/**
 * The dialog of a status move that asks for something first: a reason (REQ-INC-047), and for
 * resolve the resolution (REQ-INC-090) and for close a closure code (REQ-INC-093). It names the
 * record fields the closure rules still need (REQ-INC-094) and asks before going ahead while
 * work is still open (REQ-INC-095). Refusals are shown here, where the user is looking.
 */
export function MoveDialog({
  state,
  current,
  catalogue,
  pending,
  error,
  problem,
  openWork,
  onCancel,
  onConfirm,
}: {
  state: IncidentActionState;
  /**
   * The record's resolution and closure code now (a rule may ask for either on either move), and
   * the resolution it had before a reopen, offered for reuse (D-107).
   */
  current: { resolution: string | null; closure_code: string | null; previous?: string | null };
  catalogue: IncidentCatalogue | undefined;
  pending: boolean;
  error: unknown;
  problem: FormProblemState;
  openWork: OpenWork | null;
  onCancel: () => void;
  onConfirm: (input: MoveInput) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const fieldName = useIncidentFieldName();
  const me = useSession().data?.user.id;
  const [code, setCode] = useState<string>();
  const [text, setText] = useState('');
  const [resolution, setResolution] = useState('');
  const [closureCode, setClosureCode] = useState<string>();
  const [touched, setTouched] = useState(false);
  const action = state.action;
  const resolving = action === 'resolve';
  const closing = action === 'close';
  const asksReason = state.reason_mode !== 'none';
  const list = asksReason ? (state.reason_list ?? null) : null;
  // Retired reasons label old records but are not offered (REQ-ADM-043).
  const options = (catalogue?.reasons ?? [])
    .filter((r) => r.list === list && !r.disabled)
    .map((r) => {
      const label = labelled(r.labels, locale, () => t(`reason.${r.list}.${r.code}`));
      return { value: r.code, label, 'aria-label': label };
    });
  // Retired closure codes stay on old records but are not offered (REQ-INC-093).
  const closureOptions = (catalogue?.closure_codes ?? [])
    .filter((v) => !v.disabled)
    .map((v) => {
      const label = listValueLabel(t, 'closure_code', v, locale);
      return { value: v.code, label, 'aria-label': label };
    });
  const required = state.reason_mode === 'required';
  // Resolve asks for the resolution, close for the closure code; either also asks for the other
  // when this move's rules require it and the record has none (they are not record fields).
  const rules = resolving ? catalogue?.closure.resolve_requires : catalogue?.closure.close_requires;
  const asksResolution =
    resolving || (closing && (rules?.includes('resolution') ?? false) && !current.resolution);
  const asksClosureCode =
    closing || (resolving && (rules?.includes('closure_code') ?? false) && !current.closure_code);
  const resolutionRequired = asksResolution && (rules?.includes('resolution') ?? resolving);
  const closureCodeRequired = asksClosureCode && (rules?.includes('closure_code') ?? closing);
  // The same rules the server applies; the server's field errors are shown too.
  const missingCode = required && list !== null && code === undefined;
  const missingText =
    asksReason &&
    ((required && list === null && text.trim() === '') || (code === 'other' && text.trim() === ''));
  const missingResolution = resolutionRequired && resolution === '';
  const missingClosureCode = closureCodeRequired && closureCode === undefined;
  const fieldErrors = error instanceof ApiError ? error.fieldErrors : [];
  const field = (e: { field: string }) => e.field.replace(/^body\./, '');
  const serverAt = (name: string) =>
    fieldErrors.filter((e) => field(e) === name).map((e) => t(e.message_key, e.params ?? {}));
  const reasonServer = [...serverAt('reason_code'), ...serverAt('reason_text')];
  // Fields to fill on the record first: as the record says now, and as the server refused.
  const recordFields = [
    ...new Set([
      ...(state.missing ?? []),
      ...fieldErrors
        .filter((e) => !OWN_FIELDS.has(field(e)) && RECORD_FIELD_CODES.has(e.code))
        .map(field),
    ]),
  ];
  const otherServer = fieldErrors
    .filter((e) => !OWN_FIELDS.has(field(e)) && !RECORD_FIELD_CODES.has(e.code))
    .map((e) => `${fieldName(field(e))}: ${t(e.message_key, e.params ?? {})}`);
  const words = dialogWords(t, action);
  // "Other" is only mentioned where there is a list to pick it from (QA C6).
  const detailsLabel =
    list !== null
      ? t('incidents.reason_text')
      : required
        ? `${t('incidents.details')} *`
        : t('incidents.reason_text_optional');
  const resolutionError =
    touched && missingResolution
      ? [t('incidents.closing.resolution_required')]
      : serverAt('resolution');
  const closureCodeError =
    touched && missingClosureCode
      ? [t('incidents.closing.closure_code_required')]
      : serverAt('closure_code');
  return (
    <Modal
      open
      title={words.title}
      okText={openWork === null ? words.ok : t('incidents.closing.confirm_open_work')}
      cancelText={words.dismiss}
      confirmLoading={pending}
      onCancel={onCancel}
      onOk={() => {
        setTouched(true);
        if (missingCode || missingText || missingResolution || missingClosureCode) return;
        onConfirm({
          reasonCode: code,
          reasonText: text,
          ...(asksResolution && resolution !== '' ? { resolution } : {}),
          ...(asksClosureCode && closureCode !== undefined ? { closureCode } : {}),
        });
      }}
      okButtonProps={{
        // Nothing to send while the record lacks what the closure rules need.
        disabled: recordFields.length > 0,
        'data-testid': 'inc-reason-confirm',
      }}
      width={asksResolution ? 720 : undefined}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <FormProblem problem={problem} />
        {recordFields.length > 0 && (
          <Alert
            type="warning"
            showIcon
            role="alert"
            message={t('incidents.closing.missing', {
              fields: recordFields.map(fieldName).join(t('list.separator')),
            })}
            data-testid="inc-closing-missing"
          />
        )}
        {openWork !== null && (
          <Alert
            type="warning"
            showIcon
            role="alert"
            message={t('incidents.closing.open_work_title', { count: openWork.count })}
            description={
              <>
                <bdi dir="auto" data-testid="inc-open-work-items">
                  {openWork.items}
                </bdi>
                <br />
                {t('incidents.closing.open_work_confirm')}
              </>
            }
            data-testid="inc-open-work"
          />
        )}
        {asksResolution && (
          <>
            <Typography.Text>
              {t('work_item.field.resolution')}
              {resolutionRequired ? ' *' : ''}
            </Typography.Text>
            {current.previous != null && resolution === '' && (
              <Alert
                type="info"
                data-testid="inc-previous-resolution"
                message={t('incidents.closing.previous_resolution')}
                description={<RichTextView html={current.previous} />}
                action={
                  <Button
                    size="small"
                    onClick={() => {
                      setResolution(current.previous ?? '');
                    }}
                    data-testid="inc-previous-resolution-reuse"
                  >
                    {t('incidents.closing.reuse')}
                  </Button>
                }
              />
            )}
            <RichTextField
              label={t('work_item.field.resolution')}
              value={resolution}
              onChange={setResolution}
              invalid={resolutionError.length > 0}
              placeholder={t('incidents.closing.resolution_placeholder')}
              testId="inc-resolution-editor"
              imageOwnerId={me}
              autoFocus
            />
            {resolutionError.length > 0 && (
              <Typography.Text type="danger" role="alert" data-testid="inc-resolution-error">
                {resolutionError.join(' ')}
              </Typography.Text>
            )}
          </>
        )}
        {asksClosureCode && (
          <>
            <label htmlFor="inc-closure-code">
              <Typography.Text>
                {t('work_item.field.closure_code')}
                {closureCodeRequired ? ' *' : ''}
              </Typography.Text>
            </label>
            <Select
              id="inc-closure-code"
              value={closureCode}
              onChange={setClosureCode}
              options={closureOptions}
              style={{ width: '100%' }}
              status={closureCodeError.length > 0 ? 'error' : undefined}
              data-testid="inc-closure-code"
            />
            {closureCodeError.length > 0 && (
              <Typography.Text type="danger" role="alert" data-testid="inc-closure-code-error">
                {closureCodeError.join(' ')}
              </Typography.Text>
            )}
          </>
        )}
        {list !== null && (
          <>
            <label htmlFor="inc-reason-code">
              <Typography.Text>
                {t('incidents.reason')}
                {required ? ' *' : ''}
              </Typography.Text>
            </label>
            <Select
              id="inc-reason-code"
              value={code}
              onChange={setCode}
              options={options}
              style={{ width: '100%' }}
              status={touched && missingCode ? 'error' : undefined}
              data-testid="inc-reason-code"
            />
            {touched && missingCode && (
              <Typography.Text type="danger" role="alert" data-testid="inc-reason-code-error">
                {t('incidents.reason_required')}
              </Typography.Text>
            )}
          </>
        )}
        {asksReason && (
          <>
            <label htmlFor="inc-reason-text">
              <Typography.Text>{detailsLabel}</Typography.Text>
            </label>
            <Input.TextArea
              id="inc-reason-text"
              dir="auto"
              rows={3}
              count={lengthLimit(REASON_MAX, true)}
              value={text}
              status={touched && missingText ? 'error' : undefined}
              onChange={(event) => {
                setText(event.target.value);
              }}
              // The counter sits under the box; keep it clear of the buttons (QA C1).
              style={{ marginBottom: 20 }}
              data-testid="inc-reason-text"
            />
            {touched && missingText && (
              <Typography.Text type="danger" role="alert" data-testid="inc-reason-error">
                {t('incidents.reason_text_required')}
              </Typography.Text>
            )}
          </>
        )}
        {[...reasonServer, ...otherServer].length > 0 && (
          <Typography.Text type="danger" role="alert" data-testid="inc-reason-server-error">
            {[...reasonServer, ...otherServer].join(' ')}
          </Typography.Text>
        )}
      </Space>
    </Modal>
  );
}
