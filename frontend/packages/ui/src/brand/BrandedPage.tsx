import { Flex } from 'antd';
import type { ReactNode } from 'react';

import { BrandLogo } from './BrandLogo';

/**
 * The logo above a full-page message shown outside the app frame (sign-in problems, session
 * errors, crashes): the user still sees whose product this is.
 */
export function BrandedPage({ children }: { children: ReactNode }) {
  return (
    <Flex vertical align="center" style={{ paddingTop: 48 }}>
      <BrandLogo height={40} />
      {children}
    </Flex>
  );
}
