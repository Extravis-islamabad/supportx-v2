import { Alert, App, Button, Card, Modal, Radio, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useAccessSettings,
  useSaveAccessSettings,
  type TechnicianScope,
} from '@supportx/api-client';
import { reportError, useAccess, useLabel } from '@supportx/ui';

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

function useSave(onDone?: () => void) {
  const t = useLabel();
  const { message } = App.useApp();
  const save = useSaveAccessSettings();
  return {
    pending: save.isPending,
    run: (scope: TechnicianScope, version: number) => {
      save.mutate(
        { scope, version },
        {
          onSuccess: () => {
            void message.success(t('common.saved'));
            onDone?.();
          },
          onError: (error) => {
            if (error instanceof ApiError && error.isConflict) {
              void message.warning(t('settings.changed_elsewhere'));
              return;
            }
            reportError(error);
          },
        },
      );
    },
  };
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
  const save = useSave(() => {
    setOpen(false);
  });
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
        }}
        destroyOnHidden
        data-testid="technician-scope-question"
      >
        <Space direction="vertical" size="middle">
          <Typography.Paragraph>{t('access_settings.explain')}</Typography.Paragraph>
          <Choices value={scope} onChange={setScope} />
        </Space>
      </Modal>
    </>
  );
}

/** Admin › Roles: change the answer later. Applies to every technician at once. */
export function TechnicianVisibilityCard() {
  const t = useLabel();
  const { can } = useAccess();
  const settings = useAccessSettings(can('roles.manage'));
  const [draft, setDraft] = useState<{ scope: TechnicianScope; base: number } | null>(null);
  const save = useSave(() => {
    setDraft(null);
  });
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
            setDraft({ scope, base: draft?.base ?? saved.version });
          }}
        />
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
    </Card>
  );
}
