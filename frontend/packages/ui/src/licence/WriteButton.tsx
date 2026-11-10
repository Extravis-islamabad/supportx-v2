import { Button, Tooltip, type ButtonProps } from 'antd';

import { useLabel } from '../appearance';
import { useLicence } from './context';

export type WriteButtonProps = ButtonProps & {
  /**
   * Why it is disabled, already translated (D-155: every disabled button says why). Shown as
   * its tooltip, on a wrapper that takes focus, so a keyboard reaches the reason too.
   */
  whyDisabled?: string;
};

/**
 * A button that changes data. In read-only mode it is disabled with an explanation; the server
 * would refuse the change anyway (403 read_only_mode), so this only saves the user a failed try.
 * Disabled for any other reason, it says that reason (`whyDisabled`).
 */
export function WriteButton({ whyDisabled, ...props }: WriteButtonProps) {
  const t = useLabel();
  const { writable } = useLicence();
  const disabled = props.disabled === true;
  const why = !writable ? t('licence.read_only_action') : disabled ? whyDisabled : undefined;
  if (why === undefined) return <Button {...props} />;
  return (
    <Tooltip title={why}>
      {/* A disabled button fires no pointer events; the span carries the tooltip. */}
      <span
        style={{ display: 'inline-block' }}
        tabIndex={0}
        data-testid={writable ? 'disabled-why' : 'read-only-action'}
      >
        <Button {...props} disabled style={{ ...props.style, pointerEvents: 'none' }} />
      </span>
    </Tooltip>
  );
}
