import type { ModalProps } from 'antd';

import { WriteButton } from '@supportx/ui';

/**
 * A dialog's footer whose confirm button is a WriteButton (D-155): while it cannot be used it
 * says why on hover and focus, never a silent grey button. The cancel button stays the dialog's
 * own (its `cancelText` and `onCancel`).
 */
export function okFooter({
  okText,
  onOk,
  loading = false,
  whyDisabled,
  danger = false,
  cancel = true,
  testId,
}: {
  okText: string;
  onOk: () => void;
  loading?: boolean;
  /** Set while the button cannot be used: the reason, already translated. */
  whyDisabled?: string;
  danger?: boolean;
  /** Show the dialog's cancel button (default true). */
  cancel?: boolean;
  testId?: string;
}): ModalProps['footer'] {
  return (_, { CancelBtn }) => (
    <>
      {cancel && <CancelBtn />}
      <WriteButton
        type="primary"
        danger={danger}
        loading={loading}
        disabled={whyDisabled !== undefined}
        whyDisabled={whyDisabled}
        onClick={onOk}
        data-testid={testId}
      >
        {okText}
      </WriteButton>
    </>
  );
}
