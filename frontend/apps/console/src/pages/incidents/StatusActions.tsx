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
import { reportError, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { labelled } from './labels';

const REASON_MAX = 500;

/**
 * Status actions in their one fixed order (REQ-WI-010, REQ-INC-046): an action the life cycle
 * does not allow now, or that the user may not run, stays in place, disabled, with the reason.
 * Actions that need a reason ask for it first (REQ-INC-047).
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
  const run = (action: IncidentAction, reasonCode?: string, reasonText?: string) => {
    act.mutate(
      { action, version: item.version, reasonCode, reasonText },
      {
        onSuccess: () => {
          setAsking(null);
          void message.success(t(`incidents.done.${action}`));
        },
        onError: (error) => {
          if (asking !== null && error instanceof ApiError && error.fieldErrors.length > 0) return;
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
            disabled={!state.allowed}
            type={action === 'resolve' ? 'primary' : 'default'}
            loading={act.isPending && act.variables.action === action}
            data-testid={`inc-action-${action}`}
            onClick={() => {
              if (state.reason_mode === 'none') run(action);
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
            run(asking.action as IncidentAction, code, text);
          }}
        />
      )}
    </Flex>
  );
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
  const options = (catalogue?.reasons ?? [])
    .filter((r) => r.list === list)
    .map((r) => ({
      value: r.code,
      label: labelled(r.labels, locale, () => t(`reason.${r.list}.${r.code}`)),
    }));
  const required = state.reason_mode === 'required';
  // The same rules the server applies; the server's field errors are shown too.
  const missingCode = required && list !== null && code === undefined;
  const missingText =
    (required && list === null && text.trim() === '') || (code === 'other' && text.trim() === '');
  const server =
    error instanceof ApiError ? error.fieldErrors.map((e) => t(e.message_key, e.params)) : [];
  const action = state.action;
  return (
    <Modal
      open
      title={t(`work_item_action.${action}`)}
      okText={t(`work_item_action.${action}`)}
      cancelText={t('actions.cancel')}
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
          </>
        )}
        <label htmlFor="inc-reason-text">
          <Typography.Text>{t('incidents.reason_text')}</Typography.Text>
        </label>
        <Input.TextArea
          id="inc-reason-text"
          rows={3}
          maxLength={REASON_MAX}
          showCount
          value={text}
          status={touched && missingText ? 'error' : undefined}
          onChange={(event) => {
            setText(event.target.value);
          }}
          data-testid="inc-reason-text"
        />
        {touched && (missingCode || missingText) && (
          <Typography.Text type="danger" role="alert" data-testid="inc-reason-error">
            {t(missingCode ? 'incidents.reason_required' : 'incidents.reason_text_required')}
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
