import { Button, Drawer, Flex, Grid, Modal } from 'antd';
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
  onCancel: () => void;
  onOk: () => void;
  /** Delete / Deactivate: start side of the footer, red; the caller confirms. */
  destructive?: ReactNode;
  children: ReactNode;
  testId?: string;
}

/** The footer of every add/edit surface: the destructive action apart, then Cancel, then primary. */
function Footer({
  okText,
  saving,
  okDisabled,
  onCancel,
  onOk,
  destructive,
}: Omit<EditSurfaceProps, 'open' | 'title' | 'children' | 'testId'>) {
  const t = useLabel();
  return (
    <Flex justify="space-between" align="center" gap={SPACE.xs}>
      <div>{destructive}</div>
      {/* Cancel before the primary, both on the end side; RTL mirrors (QA6S-SHELL-06). */}
      <Flex gap={SPACE.xs}>
        <Button onClick={onCancel} disabled={saving} data-testid="edit-cancel">
          {t('actions.cancel')}
        </Button>
        <Button
          type="primary"
          onClick={onOk}
          loading={saving}
          disabled={okDisabled}
          data-testid="edit-ok"
        >
          {okText ?? t('actions.save')}
        </Button>
      </Flex>
    </Flex>
  );
}

/**
 * The one drawer for longer add/edit forms (QA6S-SHELL-06): 640 px, full screen on phones, a
 * sticky footer with Cancel left of the primary. Five or more fields; fewer use `EditDialog`.
 */
export function EditDrawer({ open, title, children, testId, ...footer }: EditSurfaceProps) {
  const phone = Grid.useBreakpoint().sm === false;
  return (
    <Drawer
      open={open}
      title={title}
      width={phone ? '100%' : 640}
      onClose={footer.onCancel}
      destroyOnHidden
      footer={<Footer {...footer} />}
      data-testid={testId}
    >
      {children}
    </Drawer>
  );
}

/** The one dialog for short add/edit forms, four fields at most (QA6S-SHELL-06): 520 px. */
export function EditDialog({ open, title, children, testId, ...footer }: EditSurfaceProps) {
  return (
    <Modal
      open={open}
      title={title}
      width={520}
      onCancel={footer.onCancel}
      destroyOnHidden
      footer={<Footer {...footer} />}
      data-testid={testId}
    >
      {children}
    </Modal>
  );
}
