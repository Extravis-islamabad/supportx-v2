import { App, Alert, Checkbox, Input, Modal, Select, Space, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  useAssignIncident,
  useAssignProblem,
  useIncidentCatalogue,
  useProblemCatalogue,
  useUnits,
  type Incident,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  markHandled,
  useAppearance,
  useConflict,
  useFormProblem,
  useLabel,
  lengthLimit,
  type FormProblemState,
} from '@supportx/ui';

import { incidentView, useIncidentFieldName } from './conflict';
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
  base = 'incidents',
}: {
  item: Incident;
  open: boolean;
  onClose: () => void;
  /** Re-read the record (the dialog opens on the latest assignment). */
  refresh: () => Promise<unknown>;
  /** The record type's prefix (WP-044c: a problem's group and owner, the same dialog). */
  base?: 'incidents' | 'problems';
}) {
  if (!open) return null;
  return <AssignBody item={item} onClose={onClose} refresh={refresh} base={base} />;
}

interface Choice {
  touched: boolean;
  value: string | null;
}

function AssignBody({
  item,
  onClose,
  refresh,
  base,
}: {
  item: Incident;
  onClose: () => void;
  refresh: () => Promise<unknown>;
  base: 'incidents' | 'problems';
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const { message } = App.useApp();
  // Both types' hooks are called (hooks never depend on a condition); the type's own is used.
  const incidentCatalogue = useIncidentCatalogue(base === 'incidents');
  const problemCatalogue = useProblemCatalogue(base === 'problems');
  const catalogue = base === 'problems' ? problemCatalogue : incidentCatalogue;
  const groups = useUnits('groups');
  const assignIncident = useAssignIncident(item.id);
  const assignProblem = useAssignProblem(item.id);
  const assign = base === 'problems' ? assignProblem : assignIncident;
  const [groupChoice, setGroupChoice] = useState<Choice>({ touched: false, value: null });
  const [techChoice, setTechChoice] = useState<Choice>({ touched: false, value: null });
  const [reasonCode, setReasonCode] = useState<string>();
  const [reasonText, setReasonText] = useState('');
  const [handover, setHandover] = useState(false);
  // D-154a: the person picked and their groups; someone outside the chosen group is assigned
  // by moving the record to their group (picked here when they are in several).
  const [person, setPerson] = useState<{ id: string; name: string; groupIds: string[] }>();
  const [targetGroup, setTargetGroup] = useState<string>();
  // A refusal (a rule, a limit) is shown in the open dialog, once (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // The version the user's first change was made on; until then, the latest one.
  const basedOn = useRef<number | null>(null);
  // The incident as it was at the user's first change, and a save someone else beat (409):
  // the shared dialog says who, when and what (QA WP-029 BUG-05).
  const [opened, setOpened] = useState<Incident>();
  const conflict = useConflict();
  const fieldName = useIncidentFieldName();
  const [tried, setTried] = useState<{ confirmLoseAccess: boolean; keepFollowing?: boolean }>();
  const reread = useRef(refresh);
  useEffect(() => {
    void reread.current();
  }, []);
  const chosenGroup = groupChoice.touched ? groupChoice.value : item.group_id;
  const outsider =
    person !== undefined &&
    techChoice.touched &&
    techChoice.value === person.id &&
    chosenGroup !== null &&
    !person.groupIds.includes(chosenGroup)
      ? person
      : undefined;
  // Their only group, or the one picked among several; none yet when they are in several.
  const moveTo =
    outsider === undefined
      ? undefined
      : outsider.groupIds.length === 1
        ? outsider.groupIds[0]
        : targetGroup !== undefined && outsider.groupIds.includes(targetGroup)
          ? targetGroup
          : undefined;
  const group = outsider === undefined ? chosenGroup : (moveTo ?? chosenGroup);
  const technician = techChoice.touched
    ? techChoice.value
    : groupChoice.touched && groupChoice.value !== item.group_id
      ? null // another group: its own technicians
      : item.technician_id;
  const touch = () => {
    basedOn.current ??= item.version;
    setOpened((was) => was ?? item);
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
  const nameOf = (id: string | null | undefined) =>
    groups.data?.find((g) => g.id === id)?.name ?? t('incidents.no_group');
  const groupName = nameOf(group);
  const close = () => {
    assign.reset();
    onClose();
  };
  const send = (confirmLoseAccess: boolean, keepFollowing?: boolean) => {
    problem.clear();
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
            void navigate(`/${base}`);
          }
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setOpened((was) => was ?? item);
            setTried({ confirmLoseAccess, keepFollowing });
            return;
          }
          if (error instanceof ApiError && error.code === 'would_lose_access') {
            markHandled(error); // the hand-over warning asks
            setHandover(true);
            return;
          }
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error); // shown in the dialog
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  return (
    <>
      <Modal
        open={!handover}
        title={t('work_item_operation.assign')}
        okText={
          // Until their group is picked the button stays "Assign"; the notice above asks.
          outsider === undefined || moveTo === undefined
            ? t('work_item_operation.assign')
            : t('incidents.move_and_assign', { group: nameOf(moveTo), person: outsider.name })
        }
        cancelText={t('actions.cancel')}
        confirmLoading={assign.isPending}
        onCancel={close}
        onOk={() => {
          send(false);
        }}
        okButtonProps={{
          'data-testid': 'inc-assign-confirm',
          // Someone in several groups: the group to move to is picked first (said below).
          disabled: outsider !== undefined && moveTo === undefined,
        }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <FormProblem problem={problem} />
          <label htmlFor="inc-assign-group">
            <Typography.Text>{t('work_item.field.group_id')}</Typography.Text>
          </label>
          <GroupPicker
            id="inc-assign-group"
            value={chosenGroup}
            onChange={(next) => {
              touch();
              setGroupChoice({ touched: true, value: next });
              setTechChoice({ touched: true, value: null }); // the list depends on the group
              setPerson(undefined);
              setTargetGroup(undefined);
            }}
            testId="inc-assign-group"
            ariaLabel={t('work_item.field.group_id')}
          />
          <label htmlFor="inc-assign-technician">
            <Typography.Text>{t('work_item.field.technician_id')}</Typography.Text>
          </label>
          <TechnicianPicker
            id="inc-assign-technician"
            groupId={chosenGroup}
            everyone
            value={technician}
            current={technician === item.technician_id ? current : null}
            onChange={(next) => {
              touch();
              setTechChoice({ touched: true, value: next });
            }}
            onPerson={(picked) => {
              setPerson(picked ?? undefined);
              setTargetGroup(undefined);
            }}
            testId="inc-assign-technician"
            base={base}
            ariaLabel={t('work_item.field.technician_id')}
          />
          {outsider !== undefined && (
            <Alert
              type="info"
              showIcon
              role="status"
              data-testid="inc-assign-outside"
              message={t('incidents.assign_outside_group', {
                person: outsider.name,
                group: nameOf(chosenGroup),
              })}
              description={
                outsider.groupIds.length > 1 ? (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <label htmlFor="inc-assign-move-to">
                      <Typography.Text>{t('incidents.move_to_which_group')}</Typography.Text>
                    </label>
                    <Select
                      id="inc-assign-move-to"
                      value={moveTo}
                      onChange={(next: string) => {
                        setTargetGroup(next);
                      }}
                      options={outsider.groupIds.map((id) => ({
                        value: id,
                        label: nameOf(id),
                        'aria-label': nameOf(id),
                      }))}
                      style={{ width: '100%' }}
                      data-testid="inc-assign-move-to"
                    />
                  </Space>
                ) : undefined
              }
            />
          )}
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
        problem={problem}
        onCancel={() => {
          setHandover(false);
          problem.clear();
          assign.reset();
        }}
        onConfirm={(keepFollowing) => {
          send(true, keepFollowing);
        }}
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={fieldName}
        opened={incidentView(opened)}
        latest={incidentView(item)}
        onReload={() => {
          // My choices dropped: the dialog shows the assignment as it is now.
          conflict.clear();
          assign.reset();
          basedOn.current = null;
          setOpened(undefined);
          setTried(undefined);
          setGroupChoice({ touched: false, value: null });
          setPerson(undefined);
          setTargetGroup(undefined);
          setTechChoice({ touched: false, value: null });
          setReasonCode(undefined);
          setReasonText('');
          setHandover(false);
        }}
        onKeepMine={() => {
          conflict.clear();
          basedOn.current = conflict.latestVersion ?? item.version;
          setOpened(item);
          if (tried !== undefined) send(tried.confirmLoseAccess, tried.keepFollowing);
          setTried(undefined);
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
  problem,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  /** The incident's ID; null for one not saved yet ("this incident", QA WP-029 C1). */
  displayId: string | null;
  group: string;
  pending: boolean;
  /** Why the hand-over was refused, shown in this dialog. */
  problem?: FormProblemState;
  onCancel: () => void;
  onConfirm: (keepFollowing: boolean) => void;
}) {
  const t = useLabel();
  const catalogue = useIncidentCatalogue();
  const fallback = catalogue.data?.keep_following_on_handover ?? true;
  const [keep, setKeep] = useState<boolean | null>(null);
  const following = keep ?? fallback;
  // A record not saved yet has no ID: the `_new` labels say "this incident" in the sentence.
  const context = displayId === null ? 'new' : undefined;
  return (
    <Modal
      open={open}
      title={t('incidents.handover_title', { id: displayId, context })}
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
        {problem !== undefined && <FormProblem problem={problem} />}
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          {t('incidents.handover_moves', { id: displayId, group, context })}
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
            context,
          })}
        />
      </Space>
    </Modal>
  );
}
