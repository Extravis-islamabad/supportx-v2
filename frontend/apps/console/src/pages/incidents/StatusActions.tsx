import { App, Modal } from 'antd';
import { useState, type ReactNode } from 'react';

import {
  ApiError,
  attachDrafts,
  type ConversationBase,
  useIncidentAction,
  type Incident,
  type IncidentAction,
  type IncidentActionState,
  type IncidentCatalogue,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  ConflictDialog,
  FormProblem,
  inlineImageIds,
  markHandled,
  reportError,
  useAppearance,
  useConflict,
  useFormProblem,
  useLabel,
  type RecordAction,
} from '@supportx/ui';

import { useActionReason } from './actionReason';
import { usePreviousResolution } from './previousResolution';
import { incidentView, useIncidentFieldName } from './conflict';
import { MoveDialog, type OpenWork } from './MoveDialog';
import { GroupPicker } from './pickers';

// Resolve asks for the resolution, close for the closure code (WP-020f): always a dialog.
const CLOSING = new Set<string>(['resolve', 'close']);
// Destructive moves sit apart, last in "More actions", and always confirm (REQ-WI-010 AC4).
const DESTRUCTIVE = new Set<string>(['cancel']);
// Which available moves earn one of the four buttons (D-124); the rest stay in the menu.
const RANK: Record<string, number> = {
  resolve: 1,
  // Problems (WP-044a): the next step of the life cycle earns a button (REQ-PRB-025 AC1).
  investigate: 2,
  analyse: 2,
  confirm_root_cause: 2,
  await_fix: 2,
  start_review: 2,
  start_work: 3,
  reopen: 4,
  resume: 5,
  close: 6,
  wait_requester: 7,
  wait_third_party: 8,
};

interface Pending {
  action: IncidentAction;
  reasonCode?: string;
  reasonText?: string;
  resolution?: string;
  closureCode?: string;
  confirmOpenWork?: boolean;
}

/**
 * Status actions in their one fixed order (REQ-WI-010, REQ-INC-046, D-124): every move keeps
 * its place in "More actions", disabled with the reason when the life cycle or the user's rights
 * do not allow it now; the available everyday ones also get a button.
 * Actions that need a reason ask for it first (REQ-INC-047). Start work on an unassigned
 * incident takes it for the user; in several groups they choose which first (QA BUG-05).
 */
export function useStatusActions(
  item: Incident,
  catalogue: IncidentCatalogue | undefined,
  /** Another type's action mutation (problems, WP-044a); the incident one by default. */
  override?: ReturnType<typeof useIncidentAction>,
  /**
   * Whose resolution templates the resolution editor offers (WP-046a S5a): the incident's by
   * default, another type's route prefix when it passes one, none when it passes null.
   */
  templateBase: ConversationBase | null = override === undefined ? 'incidents' : null,
): { actions: RecordAction[]; dialogs: ReactNode } {
  const t = useLabel();
  const reasonText = useActionReason();
  const previousResolution = usePreviousResolution(item);
  const { message, modal } = App.useApp();
  const { locale } = useAppearance();
  const incidentAct = useIncidentAction(item.id);
  const act = override ?? incidentAct;
  const [asking, setAsking] = useState<IncidentActionState | null>(null);
  // The action waiting for "which of your groups" (start work on an unassigned incident).
  const [choosing, setChoosing] = useState<Pending | null>(null);
  const [group, setGroup] = useState<string | null>(null);
  // Work still open that the user is asked to confirm before resolving or closing (REQ-INC-095).
  const [openWork, setOpenWork] = useState<OpenWork | null>(null);
  // The record's own, live state of the move being asked for (its missing fields change live).
  const askingNow =
    asking === null ? null : (item.actions.find((a) => a.action === asking.action) ?? asking);
  // A refused move with a dialog open is shown in that dialog (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // Changed by someone after it was shown (409): the shared dialog says who, when and what
  // (QA WP-029 BUG-05); "Keep my changes" runs the move again on the saved version.
  const conflict = useConflict();
  const fieldName = useIncidentFieldName();
  const listFormat = useListFormat();
  const [tried, setTried] = useState<{ pending: Pending; groupId?: string; opened: Incident }>();
  const run = (pending: Pending, groupId?: string, version = item.version) => {
    problem.clear();
    act.mutate(
      { ...pending, version, groupId },
      {
        onSuccess: () => {
          setAsking(null);
          setChoosing(null);
          setOpenWork(null);
          // Images pasted into the resolution were the author's drafts: attach them (WP-022).
          if (pending.resolution !== undefined) {
            attachDrafts('work_item', item.id, inlineImageIds(pending.resolution)).catch(
              reportError,
            );
          }
          void message.success(t(`incidents.done.${pending.action}`));
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setTried({ pending, groupId, opened: item });
            return;
          }
          if (
            error instanceof ApiError &&
            error.fieldErrors.some((e) => e.code === 'group_required')
          ) {
            markHandled(error); // the dialog asks which group
            setAsking(null);
            setChoosing(pending);
            return;
          }
          if (
            asking !== null &&
            error instanceof ApiError &&
            error.code === 'open_work_unconfirmed'
          ) {
            markHandled(error); // the dialog lists the open work and asks to confirm
            const count = Number(error.params.count ?? 0);
            setOpenWork({ count, items: String(error.params.items ?? '') });
            return;
          }
          if (asking !== null && error instanceof ApiError && error.fieldErrors.length > 0) {
            markHandled(error); // shown at the reason fields
            return;
          }
          if (asking !== null || choosing !== null) {
            problem.show(error);
            return;
          }
          // A move without a dialog refused for empty fields names them (QA10-P1-04), never
          // the bare "Some things are needed".
          if (
            error instanceof ApiError &&
            error.code === 'closure_rules' &&
            error.fieldErrors.length > 0
          ) {
            markHandled(error);
            void message.error(
              t('incidents.closing.missing', {
                fields: listFormat(
                  error.fieldErrors.map((e) => fieldName(e.field.replace(/^body\./, ''))),
                  'conjunction',
                ),
              }),
            );
            return;
          }
          reportError(error);
        },
      },
    );
  };
  const actions: RecordAction[] = item.actions.map((state) => {
    const action = state.action as IncidentAction;
    const go = () => {
      if (state.reason_mode === 'none' && !CLOSING.has(action)) run({ action });
      else {
        setOpenWork(null);
        setAsking(state);
      }
    };
    return {
      key: action,
      label: t(`work_item_action.${action}`),
      allowed: state.allowed && !act.isPending,
      whyNot: !state.allowed && state.reason != null ? reasonText(state) : undefined,
      primary: !DESTRUCTIVE.has(action),
      rank: RANK[action] ?? 50,
      danger: DESTRUCTIVE.has(action),
      // Asked exactly once: by its reason dialog, by the admin's confirmation, or else here.
      confirm:
        DESTRUCTIVE.has(action) &&
        state.reason_mode === 'none' &&
        state.confirmation?.[locale] === undefined &&
        state.confirmation?.en === undefined
          ? t('incidents.cancel_title')
          : undefined,
      confirmOk: t('incidents.cancel_confirm'),
      confirmCancel: t('incidents.cancel_keep'),
      loading: act.isPending && act.variables.action === action,
      testId: `inc-action-${action}`,
      onClick: () => {
        // The admin's confirmation for this move, in the reader's language (REQ-WF-003).
        const text = state.confirmation?.[locale] ?? state.confirmation?.en;
        if (text === undefined) {
          go();
          return;
        }
        modal.confirm({
          title: t(`work_item_action.${action}`),
          content: <bdi data-testid="inc-action-confirmation">{text}</bdi>,
          okText: t(`work_item_action.${action}`),
          cancelText: t('actions.cancel'),
          onOk: go,
        });
      },
    };
  });
  const dialogs = (
    <>
      {askingNow !== null && (
        <MoveDialog
          state={askingNow}
          current={{
            resolution: item.resolution,
            closure_code: item.closure_code,
            previous: previousResolution,
          }}
          catalogue={catalogue}
          templates={
            templateBase === null
              ? undefined
              : { recordId: item.id, categoryId: item.category_id, base: templateBase }
          }
          pending={act.isPending}
          error={act.error}
          problem={problem}
          openWork={openWork}
          onCancel={() => {
            setAsking(null);
            setOpenWork(null);
            problem.clear();
            act.reset();
          }}
          onConfirm={(input) => {
            run({
              action: askingNow.action as IncidentAction,
              reasonCode: input.reasonCode,
              reasonText: input.reasonText,
              resolution: input.resolution,
              closureCode: input.closureCode,
              // Shown the open work and confirmed it (REQ-INC-095).
              confirmOpenWork: openWork !== null,
            });
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
          problem.clear();
          act.reset();
        }}
        onOk={() => {
          if (choosing !== null && group !== null) run(choosing, group);
        }}
        destroyOnHidden
      >
        <FormProblem problem={problem} />
        <GroupPicker
          value={group}
          onChange={setGroup}
          testId="inc-start-group"
          ariaLabel={t('work_item.field.group_id')}
        />
      </Modal>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={fieldName}
        opened={incidentView(tried?.opened)}
        latest={incidentView(item)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
          setAsking(null);
          setChoosing(null);
          setOpenWork(null);
          act.reset();
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) {
            run(tried.pending, tried.groupId, conflict.latestVersion ?? item.version);
          }
          setTried(undefined);
        }}
      />
    </>
  );
  return { actions, dialogs };
}
