import { App, Alert, Checkbox, Input, Modal, Select, Space, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
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
import { reportError, useAppearance, useLabel, lengthLimit } from '@supportx/ui';

import { OperationButton } from './operations';
import { labelled } from './labels';
import { GroupPicker, TechnicianPicker } from './pickers';

/**
 * Assign or reassign (REQ-INC-053/055). The technician list shows only the chosen group's
 * members. Moving between groups needs a reason. If the change would take the incident out of
 * the user's own reach, the server says so first (409 would_lose_access) and the user confirms
 * the hand-over (D-053), keeping it followed by default (D-068); the history records both.
 *
 * Always the current assignment (QA BUG-01): the dialog is built when it opens, re-reads the
 * incident, and fields the user has not touched follow live changes while it is open. Only
 * what the user changed is changed: an untouched technician is sent back as it is now, and the
 * version is the one the user's change was based on (a newer save by someone else is a conflict,
 * never silently overwritten).
 */
export function AssignDialog({
  item,
  open,
  onClose,
  refresh,
}: {
  item: Incident;
  open: boolean;
  onClose: () => void;
  /** Re-read the incident (the dialog opens on the latest assignment). */
  refresh: () => Promise<unknown>;
}) {
  if (!open) return null;
  return <AssignBody item={item} onClose={onClose} refresh={refresh} />;
}

interface Choice {
  touched: boolean;
  value: string | null;
}

function AssignBody({
  item,
  onClose,
  refresh,
}: {
  item: Incident;
  onClose: () => void;
  refresh: () => Promise<unknown>;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const catalogue = useIncidentCatalogue();
  const groups = useUnits('groups');
  const assign = useAssignIncident(item.id);
  const [groupChoice, setGroupChoice] = useState<Choice>({ touched: false, value: null });
  const [techChoice, setTechChoice] = useState<Choice>({ touched: false, value: null });
  const [reasonCode, setReasonCode] = useState<string>();
  const [reasonText, setReasonText] = useState('');
  const [handover, setHandover] = useState(false);
  // The version the user's first change was made on; until then, the latest one.
  const basedOn = useRef<number | null>(null);
  const reread = useRef(refresh);
  useEffect(() => {
    void reread.current();
  }, []);
  const group = groupChoice.touched ? groupChoice.value : item.group_id;
  const technician = techChoice.touched
    ? techChoice.value
    : groupChoice.touched && groupChoice.value !== item.group_id
      ? null // another group: its own technicians
      : item.technician_id;
  const touch = () => {
    basedOn.current ??= item.version;
  };
  const movingGroups = item.group_id !== null && group !== item.group_id;
  const reasons = (catalogue.data?.reasons ?? [])
    .filter((r) => r.list === 'reassign' && !r.disabled)
    .map((r) => {
      const label = labelled(r.labels, locale, () => t(`reason.reassign.${r.code}`));
      return { value: r.code, label, 'aria-label': label };
    });
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
  const close = () => {
    assign.reset();
    onClose();
  };
  const send = (confirmLoseAccess: boolean, keepFollowing?: boolean) => {
    assign.mutate(
      {
        version: basedOn.current ?? item.version,
        groupId: group,
        technicianId: technician,
        reasonCode,
        reasonText,
        confirmLoseAccess,
        keepFollowing,
      },
      {
        onSuccess: (saved) => {
          setHandover(false);
          onClose();
          if (saved.visible && confirmLoseAccess) {
            void message.success(
              t('incidents.handed_over_following', { id: item.display_id, group: groupName }),
            );
          } else if (saved.visible) {
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
        open={!handover}
        title={t('work_item_operation.assign')}
        okText={t('work_item_operation.assign')}
        cancelText={t('actions.cancel')}
        confirmLoading={assign.isPending}
        onCancel={close}
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
              touch();
              setGroupChoice({ touched: true, value: next });
              setTechChoice({ touched: true, value: null }); // the list depends on the group
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
            onChange={(next) => {
              touch();
              setTechChoice({ touched: true, value: next });
            }}
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
              <Input.TextArea
                aria-label={t('incidents.reason_text')}
                placeholder={t('incidents.reason_text')}
                dir="auto"
                rows={2}
                count={lengthLimit(500)}
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
        onConfirm={(keepFollowing) => {
          send(true, keepFollowing);
        }}
      />
    </>
  );
}

/**
 * D-053 and D-068: before the incident leaves the user's reach, say plainly what happens. By
 * default they keep following it (they can open it, see updates and add private notes, and can
 * unfollow later); unticked, they lose sight of it.
 */
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
  onConfirm: (keepFollowing: boolean) => void;
}) {
  const t = useLabel();
  const catalogue = useIncidentCatalogue();
  const fallback = catalogue.data?.keep_following_on_handover ?? true;
  const [keep, setKeep] = useState<boolean | null>(null);
  const following = keep ?? fallback;
  return (
    <Modal
      open={open}
      title={t('incidents.handover_title', { id: displayId })}
      okText={t(following ? 'incidents.handover_confirm_following' : 'incidents.handover_confirm')}
      okButtonProps={{
        danger: !following,
        ...({ 'data-testid': 'inc-handover-confirm' } as Record<string, string>),
      }}
      cancelText={t('actions.cancel')}
      confirmLoading={pending}
      onCancel={() => {
        setKeep(null);
        onCancel();
      }}
      onOk={() => {
        setKeep(null);
        onConfirm(following);
      }}
      destroyOnHidden
    >
      <Space direction="vertical" data-testid="inc-handover-warning">
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          {t('incidents.handover_moves', { id: displayId, group })}
        </Typography.Paragraph>
        <Checkbox
          checked={following}
          onChange={(event) => {
            setKeep(event.target.checked);
          }}
          data-testid="inc-handover-keep-following"
        >
          {t('incidents.handover_keep_following')}
        </Checkbox>
        <Alert
          type={following ? 'info' : 'warning'}
          showIcon
          data-testid="inc-handover-outcome"
          message={t(following ? 'incidents.handover_following_text' : 'incidents.handover_text', {
            id: displayId,
            group,
          })}
        />
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
