import { Button, Tooltip, type ButtonProps } from 'antd';

import { useLabel } from '../appearance';
import { useLicence } from './context';

/**
 * A button that changes data. In read-only mode it is disabled with an explanation; the server
 * would refuse the change anyway (403 read_only_mode), so this only saves the user a failed try.
 */
export function WriteButton(props: ButtonProps) {
  const t = useLabel();
  const { writable } = useLicence();
  if (writable) return <Button {...props} />;
  return (
    <Tooltip title={t('licence.read_only_action')}>
      {/* A disabled button fires no pointer events; the span carries the tooltip. */}
      <span style={{ display: 'inline-block' }} tabIndex={0} data-testid="read-only-action">
        <Button {...props} disabled style={{ ...props.style, pointerEvents: 'none' }} />
      </span>
    </Tooltip>
  );
}
