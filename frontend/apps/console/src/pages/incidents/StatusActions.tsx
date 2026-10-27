import { App, Flex, Input, Modal, Select, Space, Tooltip, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIncidentAction,
  type Incident,
  type IncidentAction,
  type IncidentActionState,
  type IncidentCatalogue,
} from '@supportx/api-client';
import { reportError, useAppearance, useLabel, WriteButton, lengthLimit } from '@supportx/ui';

import { labelled } from './labels';
import { GroupPicker } from './pickers';

const REASON_MAX = 500;

interface Pending {
  action: IncidentAction;
  reasonCode?: string;
  reasonText?: string;
}

/**
 * Status actions in their one fixed order (REQ-WI-010, REQ-INC-046): an action the life cycle
 * does not allow now, or that the user may not run, stays in place, disabled, with the reason.
 * Actions that need a reason ask for it first (REQ-INC-047). Start work on an unassigned
 * incident takes it for the user; in several groups they choose which first (QA BUG-05).
 */
export function StatusActions({
  item,
  catalogue,
}: {
  item: Incident;
  catalogue: IncidentCatalogue | undefined;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const act = useIncidentAction(item.id);
  const [asking, setAsking] = useState<IncidentActionState | null>(null);
  // The action waiting for "which of your groups" (start work on an unassigned incident).
  const [choosing, setChoosing] = useState<Pending | null>(null);
  const [group, setGroup] = useState<string | null>(null);
  const run = (pending: Pending, groupId?: string) => {
    act.mutate(
      { ...pending, version: item.version, groupId },
      {
        onSuccess: () => {
          setAsking(null);
          setChoosing(null);
          void message.success(t(`incidents.done.${pending.action}`));
        },
        onError: (error) => {
          if (
            error instanceof ApiError &&
            error.fieldErrors.some((e) => e.code === 'group_required')
          ) {
            setAsking(null);
            setChoosing(pending);
            return;
          }
          if (
            (asking !== null || choosing !== null) &&
            error instanceof ApiError &&
            error.fieldErrors.length > 0
          ) {
            return; // shown in the dialog
          }
          reportError(error);
        },
      },
    );
  };
  return (
    <Flex gap={8} wrap data-testid="inc-actions">
      {item.actions.map((state) => {
        const action = state.action as IncidentAction;
        const button = (
          <WriteButton
            key={action}
            disabled={!state.allowed || act.isPending}
            type={action === 'resolve' ? 'primary' : 'default'}
            loading={act.isPending && act.variables.action === action}
            data-testid={`inc-action-${action}`}
            onClick={() => {
              if (state.reason_mode === 'none') run({ action });
              else setAsking(state);
            }}
          >
            {t(`work_item_action.${action}`)}
          </WriteButton>
        );
        return state.allowed || state.reason == null ? (
          button
        ) : (
          <Tooltip key={action} title={t(`action_reason.${state.reason}`)}>
            <span data-testid={`inc-action-${action}-reason`} data-reason={state.reason}>
              {button}
            </span>
          </Tooltip>
        );
      })}
      {asking !== null && (
        <ReasonDialog
          state={asking}
          catalogue={catalogue}
          pending={act.isPending}
          error={act.error}
          onCancel={() => {
            setAsking(null);
            act.reset();
          }}
          onConfirm={(code, text) => {
            run({ action: asking.action as IncidentAction, reasonCode: code, reasonText: text });
          }}
        />
      )}
      <Modal
        open={choosing !== null}
        title={t('incidents.start_choose_group')}
        okText={t('work_item_action.start_work')}
        cancelText={t('actions.cancel')}
        confirmLoading={act.isPending}
        okButtonProps={{ disabled: group === null, 'data-testid': 'inc-start-confirm' }}
        onCancel={() => {
          setChoosing(null);
          act.reset();
        }}
        onOk={() => {
          if (choosing !== null && group !== null) run(choosing, group);
        }}
        destroyOnHidden
      >
        <GroupPicker
          value={group}
          onChange={setGroup}
          testId="inc-start-group"
          ariaLabel={t('work_item.field.group_id')}
        />
      </Modal>
    </Flex>
  );
}

/** Title and buttons of the reason dialog; cancelling an incident needs its own words (BUG-06). */
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

function ReasonDialog({
  state,
  catalogue,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  state: IncidentActionState;
  catalogue: IncidentCatalogue | undefined;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: (code: string | undefined, text: string) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [code, setCode] = useState<string>();
  const [text, setText] = useState('');
  const [touched, setTouched] = useState(false);
  const list = state.reason_list;
  // Retired reasons label old records but are not offered (REQ-ADM-043).
  const options = (catalogue?.reasons ?? [])
    .filter((r) => r.list === list && !r.disabled)
    .map((r) => {
      const label = labelled(r.labels, locale, () => t(`reason.${r.list}.${r.code}`));
      return { value: r.code, label, 'aria-label': label };
    });
  const required = state.reason_mode === 'required';
  // The same rules the server applies; the server's field errors are shown too.
  const missingCode = required && list !== null && code === undefined;
  const missingText =
    (required && list === null && text.trim() === '') || (code === 'other' && text.trim() === '');
  const server =
    error instanceof ApiError ? error.fieldErrors.map((e) => t(e.message_key, e.params)) : [];
  const words = dialogWords(t, state.action);
  // "Other" is only mentioned where there is a list to pick it from (QA C6).
  const detailsLabel =
    list !== null
      ? t('incidents.reason_text')
      : required
        ? `${t('incidents.details')} *`
        : t('incidents.reason_text_optional');
  return (
    <Modal
      open
      title={words.title}
      okText={words.ok}
      cancelText={words.dismiss}
      confirmLoading={pending}
      onCancel={onCancel}
      onOk={() => {
        setTouched(true);
        if (missingCode || missingText) return;
        onConfirm(code, text);
      }}
      okButtonProps={{ 'data-testid': 'inc-reason-confirm' }}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }}>
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
        {server.length > 0 && (
          <Typography.Text type="danger" role="alert" data-testid="inc-reason-server-error">
            {server.join(' ')}
          </Typography.Text>
        )}
      </Space>
    </Modal>
  );
}
