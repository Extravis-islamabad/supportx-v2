import { Spin } from 'antd';
import { createBrowserRouter, type RouteObject } from 'react-router';

import { PortalLayout } from './PortalLayout';

const comingSoon = async () => ({
  Component: (await import('./pages/ComingSoonPage')).ComingSoonPage,
});

/** Lazy, route-level chunks as in the console. */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <PortalLayout />,
    hydrateFallbackElement: <Spin />,
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import('./pages/HomePage')).HomePage }),
      },
      {
        path: 'account',
        handle: { titleKey: 'nav.profile' },
        lazy: async () => ({ Component: (await import('./pages/AccountPage')).AccountPage }),
      },
      { path: 'requests', handle: { titleKey: 'nav.my_requests' }, lazy: comingSoon },
      { path: 'catalog', handle: { titleKey: 'nav.catalog' }, lazy: comingSoon },
      { path: '*', handle: { titleKey: 'shell.not_found' }, lazy: comingSoon },
    ],
  },
];

/** Routes are relative to where the portal is served: `/` in dev, `/portal/` when deployed. */
export const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';

export function createRouter() {
  return createBrowserRouter(routes, { basename: BASENAME });
}
