import { App, Modal, Typography } from 'antd';
import { useState, type ReactNode } from 'react';

import {
  ApiError,
  useTakeIncident,
  type Incident,
  type IncidentActionState,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  markHandled,
  reportError,
  useConflict,
  useFormProblem,
  useLabel,
  type RecordAction,
} from '@supportx/ui';

import { useActionReason } from './actionReason';
import { incidentView, useIncidentFieldName } from './conflict';
import { GroupPicker } from './pickers';

/** Take it yourself (REQ-INC-054); in several groups and none set, choose which. */
export function useTakeAction(
  item: Incident,
  state: IncidentActionState | undefined,
): { action: RecordAction | null; dialogs: ReactNode } {
  const t = useLabel();
  const reasonText = useActionReason();
  const { message } = App.useApp();
  const take = useTakeIncident(item.id);
  const [choosing, setChoosing] = useState(false);
  const [group, setGroup] = useState<string | null>(null);
  const problem = useFormProblem();
  // Changed by someone after it was shown (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const fieldName = useIncidentFieldName();
  const [tried, setTried] = useState<{ groupId?: string; opened: Incident }>();
  const run = (groupId?: string, version = item.version) => {
    problem.clear();
    take.mutate(
      { version, groupId },
      {
        onSuccess: () => {
          setChoosing(false);
          void message.success(t('incidents.taken'));
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setTried({ groupId, opened: item });
            return;
          }
          if (
            error instanceof ApiError &&
            error.fieldErrors.some((e) => e.code === 'group_required')
          ) {
            markHandled(error); // the dialog asks which group
            setChoosing(true);
            return;
          }
          if (
            choosing &&
            error instanceof ApiError &&
            error.status === 422 &&
            error.fieldErrors.length > 0
          ) {
            markHandled(error); // shown in the dialog
            return;
          }
          // The one-click take has no form: its refusal is the app's neutral notice.
          if (choosing) problem.show(error);
          else reportError(error);
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
  const action: RecordAction | null =
    state === undefined
      ? null
      : {
          key: 'take',
          label: t('work_item_operation.take'),
          allowed: state.allowed,
          whyNot: !state.allowed && state.reason != null ? reasonText(state) : undefined,
          primary: true,
          rank: 2,
          loading: take.isPending && !choosing,
          testId: 'inc-op-take',
          onClick: () => {
            run();
          },
        };
  const dialogs = (
    <>
      <Modal
        open={choosing}
        title={t('incidents.take_choose_group')}
        okText={t('work_item_operation.take')}
        cancelText={t('actions.cancel')}
        confirmLoading={take.isPending}
        onCancel={() => {
          setChoosing(false);
          problem.clear();
          take.reset();
        }}
        onOk={() => {
          if (group !== null) run(group);
        }}
        okButtonProps={{ 'data-testid': 'inc-take-confirm' }}
        destroyOnHidden
      >
        <FormProblem problem={problem} />
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
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={fieldName}
        opened={incidentView(tried?.opened)}
        latest={incidentView(item)}
        onReload={() => {
          conflict.clear();
          take.reset();
          setTried(undefined);
          setChoosing(false);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) run(tried.groupId, conflict.latestVersion ?? item.version);
          setTried(undefined);
        }}
      />
    </>
  );
  return { action, dialogs };
}
