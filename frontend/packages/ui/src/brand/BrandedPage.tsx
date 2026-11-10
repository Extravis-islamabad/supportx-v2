import { Flex, theme } from 'antd';
import type { ReactNode } from 'react';

import { BrandLogo } from './BrandLogo';

/**
 * The logo above a full-page message shown outside the app frame (sign-in problems, session
 * errors, crashes): the user still sees whose product this is.
 */
export function BrandedPage({ children }: { children: ReactNode }) {
  const { token } = theme.useToken();
  // The page's own background, filling the window (QA10-P2-02): outside the app frame nothing else
  // paints one, so a dark theme put a dark card on the browser's white page and the white-text
  // logo vanished.
  return (
    <div
      style={{ position: 'fixed', inset: 0, overflowY: 'auto', background: token.colorBgLayout }}
    >
      <Flex vertical align="center" style={{ paddingTop: 48, paddingBottom: 48 }}>
        <BrandLogo height={40} />
        {children}
      </Flex>
    </div>
  );
}
