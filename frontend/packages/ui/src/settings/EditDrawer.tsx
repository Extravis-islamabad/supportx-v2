import { App, Button, Drawer, Flex, Grid, Modal, Tooltip } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE } from '../density';

interface EditSurfaceProps {
  open: boolean;
  /** "Add site" / "Edit Dubai office": the title only. */
  title: string;
  /** The primary button's text: Save, Add, Create… */
  okText?: string;
  saving?: boolean;
  /** Disabled only when nothing could be saved yet; validation runs on save. */
  okDisabled?: boolean;
  /** Why the primary is disabled, already translated: its tooltip (no unexplained disabled). */
  okWhyNot?: string;
  onCancel: () => void;
  onOk: () => void;
  /** Delete / Deactivate: start side of the footer, red; the caller confirms. */
  destructive?: ReactNode;
  /** Drawer only: actions in its header, such as a "…" menu of account actions (lane B, PEO-03). */
  extra?: ReactNode;
  /** Drawer only: 960 px for wide content such as a permission table (lane B, PEO-06/07). */
  wide?: boolean;
  /** Unsaved input: Cancel and closing ask "Discard changes?" first (lane A's review). */
  dirty?: boolean;
  children: ReactNode;
  testId?: string;
}

/** Cancel or close: straight away, or after "Discard changes?" when there is unsaved input. */
function useGuardedCancel(dirty: boolean | undefined, onCancel: () => void): () => void {
  const t = useLabel();
  const { modal } = App.useApp();
  return () => {
    if (dirty !== true) {
      onCancel();
      return;
    }
    modal.confirm({
      title: t('settings.discard_title'),
      content: t('settings.discard_body'),
      okText: t('settings.discard'),
      okButtonProps: { danger: true },
      cancelText: t('settings.keep_editing'),
      onOk: onCancel,
    });
  };
}

/** The footer of every add/edit surface: the destructive action apart, then Cancel, then primary. */
function Footer({
  okText,
  saving,
  okDisabled,
  okWhyNot,
  onCancel,
  onOk,
  destructive,
}: Omit<EditSurfaceProps, 'open' | 'title' | 'children' | 'testId' | 'extra' | 'wide' | 'dirty'>) {
  const t = useLabel();
  return (
    <Flex justify="space-between" align="center" gap={SPACE.xs}>
      <div>{destructive}</div>
      {/* Cancel before the primary, both on the end side; RTL mirrors (QA6S-SHELL-06). */}
      <Flex gap={SPACE.xs}>
        <Button onClick={onCancel} disabled={saving} data-testid="edit-cancel">
          {t('actions.cancel')}
        </Button>
        <Tooltip title={okDisabled === true ? okWhyNot : undefined}>
          {/* A wrapper keeps the tooltip on a disabled button, and its reason reachable. */}
          <span
            tabIndex={okDisabled === true && okWhyNot !== undefined ? 0 : undefined}
            aria-label={
              okDisabled === true && okWhyNot !== undefined
                ? `${okText ?? t('actions.save')}: ${okWhyNot}`
                : undefined
            }
          >
            <Button
              type="primary"
              onClick={onOk}
              loading={saving}
              disabled={okDisabled}
              data-testid="edit-ok"
            >
              {okText ?? t('actions.save')}
            </Button>
          </span>
        </Tooltip>
      </Flex>
    </Flex>
  );
}

/**
 * The one drawer for longer add/edit forms (QA6S-SHELL-06): 640 px, full screen on phones, a
 * sticky footer with Cancel left of the primary. Five or more fields; fewer use `EditDialog`.
 */
export function EditDrawer({
  open,
  title,
  children,
  testId,
  extra,
  wide = false,
  dirty,
  ...footer
}: EditSurfaceProps) {
  const phone = Grid.useBreakpoint().sm === false;
  const cancel = useGuardedCancel(dirty, footer.onCancel);
  return (
    <Drawer
      open={open}
      title={title}
      extra={extra}
      width={phone ? '100%' : wide ? 960 : 640}
      onClose={cancel}
      destroyOnHidden
      footer={<Footer {...footer} onCancel={cancel} />}
      data-testid={testId}
    >
      {children}
    </Drawer>
  );
}

/** The one dialog for short add/edit forms, four fields at most (QA6S-SHELL-06): 520 px. */
export function EditDialog({
  open,
  title,
  children,
  testId,
  dirty,
  ...footer
}: Omit<EditSurfaceProps, 'extra' | 'wide'>) {
  const cancel = useGuardedCancel(dirty, footer.onCancel);
  return (
    <Modal
      open={open}
      title={title}
      width={520}
      onCancel={cancel}
      destroyOnHidden
      footer={<Footer {...footer} onCancel={cancel} />}
      data-testid={testId}
    >
      {children}
    </Modal>
  );
}
