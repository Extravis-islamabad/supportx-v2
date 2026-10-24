import { App, Alert, Modal, Select, Space, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  useAssignIncident,
  useIncidentCatalogue,
  useTakeIncident,
  useUnits,
  type Incident,
  type IncidentActionState,
} from '@supportx/api-client';
import { reportError, useAppearance, useLabel } from '@supportx/ui';

import { OperationButton } from './operations';
import { labelled } from './labels';
import { GroupPicker, TechnicianPicker } from './pickers';

/**
 * Assign or reassign (REQ-INC-053/055). The technician list shows only the chosen group's
 * members. Moving between groups needs a reason. If the change would take the incident out of
 * the user's own reach, the server says so first (409 would_lose_access) and the user confirms
 * the hand-over (D-053); the history records it.
 */
export function AssignDialog({
  item,
  open,
  onClose,
}: {
  item: Incident;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const catalogue = useIncidentCatalogue();
  const groups = useUnits('groups');
  const assign = useAssignIncident(item.id);
  const [group, setGroup] = useState<string | null>(item.group_id);
  const [technician, setTechnician] = useState<string | null>(item.technician_id);
  const [reasonCode, setReasonCode] = useState<string>();
  const [reasonText, setReasonText] = useState('');
  const [handover, setHandover] = useState(false);
  const movingGroups = item.group_id !== null && group !== item.group_id;
  const reasons = (catalogue.data?.reasons ?? [])
    .filter((r) => r.list === 'reassign')
    .map((r) => ({
      value: r.code,
      label: labelled(r.labels, locale, () => t(`reason.reassign.${r.code}`)),
    }));
  const fieldErrors =
    assign.error instanceof ApiError && assign.error.status === 422
      ? assign.error.fieldErrors.map((e) => t(e.message_key, e.params))
      : [];
  const current =
    item.technician_id === null
      ? null
      : {
          id: item.technician_id,
          name: item.people[item.technician_id]?.display_name ?? '',
          email: item.people[item.technician_id]?.email ?? '',
        };
  const groupName = groups.data?.find((g) => g.id === group)?.name ?? t('incidents.no_group');
  const send = (confirmLoseAccess: boolean) => {
    assign.mutate(
      {
        version: item.version,
        groupId: group,
        technicianId: technician,
        reasonCode,
        reasonText,
        confirmLoseAccess,
      },
      {
        onSuccess: (saved) => {
          setHandover(false);
          onClose();
          if (saved.visible) {
            void message.success(t('incidents.assigned'));
          } else {
            void message.success(
              t('incidents.handed_over', { id: item.display_id, group: groupName }),
            );
            void navigate('/incidents');
          }
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === 'would_lose_access') {
            setHandover(true);
            return;
          }
          if (error instanceof ApiError && error.status === 422) return; // shown in the dialog
          reportError(error);
        },
      },
    );
  };
  return (
    <>
      <Modal
        open={open && !handover}
        title={t('work_item_operation.assign')}
        okText={t('work_item_operation.assign')}
        cancelText={t('actions.cancel')}
        confirmLoading={assign.isPending}
        onCancel={() => {
          assign.reset();
          onClose();
        }}
        onOk={() => {
          send(false);
        }}
        okButtonProps={{ 'data-testid': 'inc-assign-confirm' }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <label htmlFor="inc-assign-group">
            <Typography.Text>{t('work_item.field.group_id')}</Typography.Text>
          </label>
          <GroupPicker
            id="inc-assign-group"
            value={group}
            onChange={(next) => {
              setGroup(next);
              setTechnician(null); // the list depends on the group
            }}
            testId="inc-assign-group"
            ariaLabel={t('work_item.field.group_id')}
          />
          <label htmlFor="inc-assign-technician">
            <Typography.Text>{t('work_item.field.technician_id')}</Typography.Text>
          </label>
          <TechnicianPicker
            id="inc-assign-technician"
            groupId={group}
            value={technician}
            current={technician === item.technician_id ? current : null}
            onChange={setTechnician}
            testId="inc-assign-technician"
            ariaLabel={t('work_item.field.technician_id')}
          />
          {movingGroups && (
            <>
              <label htmlFor="inc-assign-reason">
                <Typography.Text>{t('incidents.reassign_reason')} *</Typography.Text>
              </label>
              <Select
                id="inc-assign-reason"
                value={reasonCode}
                onChange={setReasonCode}
                options={reasons}
                style={{ width: '100%' }}
                data-testid="inc-assign-reason"
              />
              <textarea
                className="ant-input"
                aria-label={t('incidents.reason_text')}
                placeholder={t('incidents.reason_text')}
                rows={2}
                maxLength={500}
                value={reasonText}
                onChange={(event) => {
                  setReasonText(event.target.value);
                }}
                data-testid="inc-assign-reason-text"
              />
            </>
          )}
          {fieldErrors.length > 0 && (
            <Typography.Text type="danger" role="alert" data-testid="inc-assign-error">
              {fieldErrors.join(' ')}
            </Typography.Text>
          )}
        </Space>
      </Modal>
      <HandOverWarning
        open={handover}
        displayId={item.display_id}
        group={groupName}
        pending={assign.isPending}
        onCancel={() => {
          setHandover(false);
          assign.reset();
        }}
        onConfirm={() => {
          send(true);
        }}
      />
    </>
  );
}

/** D-053: say plainly that the user will lose sight of the incident, before it happens. */
export function HandOverWarning({
  open,
  displayId,
  group,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  displayId: string;
  group: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useLabel();
  return (
    <Modal
      open={open}
      title={t('incidents.handover_title')}
      okText={t('incidents.handover_confirm')}
      okButtonProps={{
        danger: true,
        ...({ 'data-testid': 'inc-handover-confirm' } as Record<string, string>),
      }}
      cancelText={t('actions.cancel')}
      confirmLoading={pending}
      onCancel={onCancel}
      onOk={onConfirm}
      destroyOnHidden
    >
      <Space direction="vertical" data-testid="inc-handover-warning">
        <Alert
          type="warning"
          showIcon
          message={t('incidents.handover_text', { id: displayId, group })}
        />
        <Typography.Text type="secondary">{t('incidents.handover_follow_later')}</Typography.Text>
      </Space>
    </Modal>
  );
}

/** Take it yourself (REQ-INC-054); in several groups and none set, choose which. */
export function TakeButton({
  item,
  state,
}: {
  item: Incident;
  state: IncidentActionState | undefined;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const take = useTakeIncident(item.id);
  const [choosing, setChoosing] = useState(false);
  const [group, setGroup] = useState<string | null>(null);
  const run = (groupId?: string) => {
    take.mutate(
      { version: item.version, groupId },
      {
        onSuccess: () => {
          setChoosing(false);
          void message.success(t('incidents.taken'));
        },
        onError: (error) => {
          if (
            error instanceof ApiError &&
            error.fieldErrors.some((e) => e.code === 'group_required')
          ) {
            setChoosing(true);
            return;
          }
          if (choosing && error instanceof ApiError && error.status === 422) return;
          reportError(error);
        },
      },
    );
  };
  const errors =
    choosing && take.error instanceof ApiError
      ? take.error.fieldErrors
          .filter((e) => e.code !== 'group_required')
          .map((e) => t(e.message_key))
      : [];
  return (
    <>
      <OperationButton
        state={state}
        label={t('work_item_operation.take')}
        testId="inc-op-take"
        loading={take.isPending && !choosing}
        onClick={() => {
          run();
        }}
      />
      <Modal
        open={choosing}
        title={t('incidents.take_choose_group')}
        okText={t('work_item_operation.take')}
        cancelText={t('actions.cancel')}
        confirmLoading={take.isPending}
        onCancel={() => {
          setChoosing(false);
          take.reset();
        }}
        onOk={() => {
          if (group !== null) run(group);
        }}
        okButtonProps={{ 'data-testid': 'inc-take-confirm' }}
        destroyOnHidden
      >
        <GroupPicker
          value={group}
          onChange={setGroup}
          testId="inc-take-group"
          ariaLabel={t('work_item.field.group_id')}
        />
        {errors.length > 0 && (
          <Typography.Text type="danger" role="alert">
            {errors.join(' ')}
          </Typography.Text>
        )}
      </Modal>
    </>
  );
}
