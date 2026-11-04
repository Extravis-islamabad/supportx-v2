import { act, render, waitFor } from '@testing-library/react';
import { App } from 'antd';
import { useEffect } from 'react';
import { describe, expect, it } from 'vitest';

import { useAppearance } from './appearance';
import { AppearanceProvider } from './AppearanceProvider';

// UI pass 2 polish (agreed with lane B): a message starts below the 56 px header, so it never
// covers the header's search field, and moves down as the header grows with the text size.

function Toast({ scale }: { scale: number }) {
  const { message } = App.useApp();
  const { setTextScale } = useAppearance();
  useEffect(() => {
    setTextScale(scale);
  }, [scale, setTextScale]);
  return (
    <button type="button" onClick={() => void message.info('Saved')}>
      show
    </button>
  );
}

async function topOfMessage(scale: number): Promise<string> {
  const view = render(
    <AppearanceProvider>
      <Toast scale={scale} />
    </AppearanceProvider>,
  );
  act(() => {
    view.getByRole('button', { name: 'show' }).click();
  });
  const holder = await waitFor(() => {
    const found = document.querySelector<HTMLElement>('.ant-message');
    if (found === null) throw new Error('no message shown yet');
    return found;
  });
  const top = holder.style.top;
  view.unmount();
  document.querySelectorAll('.ant-message').forEach((node) => {
    node.remove();
  });
  return top;
}

describe('messages sit below the header', () => {
  it('at the default text size', async () => {
    expect(await topOfMessage(100)).toBe('64px');
  });

  it('lower when the text, and so the header, is larger', async () => {
    expect(await topOfMessage(150)).toBe('92px');
  });
});
