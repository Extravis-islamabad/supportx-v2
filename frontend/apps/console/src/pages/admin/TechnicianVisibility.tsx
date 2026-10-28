import { Alert, App, Button, Card, Modal, Radio, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  useAccessSettings,
  useSaveAccessSettings,
  type AccessSettings,
  type TechnicianScope,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  useAccess,
  useConflict,
  useFormProblem,
  useLabel,
  type ConflictDialogProps,
} from '@supportx/ui';

const SCOPES: TechnicianScope[] = ['group', 'all'];

function Choices({
  value,
  onChange,
}: {
  value: TechnicianScope;
  onChange: (scope: TechnicianScope) => void;
}) {
  const t = useLabel();
  return (
    <Radio.Group
      value={value}
      onChange={(event) => {
        onChange(event.target.value as TechnicianScope);
      }}
      aria-label={t('access_settings.question')}
      data-testid="technician-scope"
    >
      <Space direction="vertical">
        {SCOPES.map((scope) => (
          <Radio key={scope} value={scope}>
            <Typography.Text strong>{t(`technician_scope.${scope}`)}</Typography.Text>
            <br />
            <Typography.Text type="secondary">
              {t(`technician_scope.${scope}.description`)}
            </Typography.Text>
          </Radio>
        ))}
      </Space>
    </Radio.Group>
  );
}

const answerView = (settings: AccessSettings | undefined) =>
  settings && { technician_scope: settings.technician_scope };

/**
 * `opened`: the settings when the choice began, `latest` the live ones; a save someone else beat (409) opens the shared
 * conflict dialog with both (QA WP-029 BUG-05). "Reload" drops the choice
 * (`onDone`), "Keep my changes" saves it again on their version.
 */
function useSave(
  onDone: () => void,
  opened: AccessSettings | undefined,
  latest: AccessSettings | undefined,
) {
  const t = useLabel();
  const { message } = App.useApp();
  const save = useSaveAccessSettings();
  // A refused save is shown where it was made (QA WP-029 BUG-02): render <FormProblem>.
  const problem = useFormProblem();
  const conflict = useConflict();
  const [stopped, setStopped] = useState<TechnicianScope>();
  const run = (scope: TechnicianScope, version: number) => {
    problem.clear();
    save.mutate(
      { scope, version },
      {
        onSuccess: () => {
          void message.success(t('common.saved'));
          onDone();
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setStopped(scope);
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  const conflictDialog: ConflictDialogProps = {
    open: conflict.open,
    error: conflict.error,
    fieldLabel: () => t('access_settings.title'),
    opened: answerView(opened),
    latest: answerView(latest),
    onReload: () => {
      conflict.clear();
      onDone();
    },
    onKeepMine: () => {
      conflict.clear();
      if (stopped !== undefined) run(stopped, conflict.latestVersion ?? latest?.version ?? 0);
    },
  };
  return { pending: save.isPending, problem, run, conflictDialog };
}

/**
 * The first-run question (D-052, D-073): what the built-in technician role sees. Shown to whoever
 * manages roles as a banner until answered (never a blocking dialog: work goes on meanwhile, and
 * the least-privileged answer "their groups" applies until then). "Choose" opens the question
 * with "their groups" preselected.
 */
export function TechnicianVisibilityQuestion() {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('roles.manage');
  const settings = useAccessSettings(allowed);
  const [scope, setScope] = useState<TechnicianScope>('group');
  const [open, setOpen] = useState(false);
  // The settings when the question was opened, for the conflict dialog.
  const [opened, setOpened] = useState<AccessSettings>();
  const save = useSave(
    () => {
      setOpen(false);
    },
    opened,
    settings.data,
  );
  if (!allowed || settings.data?.answered_at !== null) return null;
  return (
    <>
      <Alert
        type="info"
        showIcon
        data-testid="technician-scope-banner"
        message={t('access_settings.question')}
        description={t('access_settings.banner')}
        action={
          <Button
            type="primary"
            onClick={() => {
              setOpened(settings.data);
              setOpen(true);
            }}
            data-testid="technician-scope-choose"
          >
            {t('access_settings.choose')}
          </Button>
        }
      />
      <Modal
        open={open}
        title={t('access_settings.question')}
        okText={t('access_settings.confirm')}
        cancelText={t('actions.cancel')}
        okButtonProps={{ loading: save.pending, 'data-testid': 'technician-scope-save' }}
        onOk={() => {
          save.run(scope, settings.data?.version ?? 0);
        }}
        onCancel={() => {
          setOpen(false);
          save.problem.clear();
        }}
        destroyOnHidden
        data-testid="technician-scope-question"
      >
        <Space direction="vertical" size="middle">
          <FormProblem problem={save.problem} />
          <Typography.Paragraph>{t('access_settings.explain')}</Typography.Paragraph>
          <Choices value={scope} onChange={setScope} />
        </Space>
      </Modal>
      <ConflictDialog {...save.conflictDialog} />
    </>
  );
}

/** Admin › Roles: change the answer later. Applies to every technician at once. */
export function TechnicianVisibilityCard() {
  const t = useLabel();
  const { can } = useAccess();
  const settings = useAccessSettings(can('roles.manage'));
  const [draft, setDraft] = useState<{
    scope: TechnicianScope;
    base: number;
    opened: AccessSettings;
  } | null>(null);
  const save = useSave(
    () => {
      setDraft(null);
    },
    draft?.opened,
    settings.data,
  );
  if (!can('roles.manage') || settings.data === undefined) return null;
  const saved = settings.data;
  const value = draft?.scope ?? saved.technician_scope;
  const stale = draft !== null && draft.base !== saved.version;
  return (
    <Card title={t('access_settings.title')} data-testid="technician-visibility">
      <Space direction="vertical" size="middle">
        <Typography.Paragraph type="secondary">{t('access_settings.explain')}</Typography.Paragraph>
        {stale && <Alert type="warning" showIcon message={t('settings.changed_elsewhere')} />}
        <Choices
          value={value}
          onChange={(scope) => {
            setDraft({
              scope,
              base: draft?.base ?? saved.version,
              opened: draft?.opened ?? saved,
            });
          }}
        />
        <FormProblem problem={save.problem} />
        <Button
          type="primary"
          disabled={draft === null || draft.scope === saved.technician_scope}
          loading={save.pending}
          onClick={() => {
            if (draft !== null) save.run(draft.scope, draft.base);
          }}
          data-testid="technician-visibility-save"
        >
          {t('actions.save')}
        </Button>
      </Space>
      <ConflictDialog {...save.conflictDialog} />
    </Card>
  );
}
