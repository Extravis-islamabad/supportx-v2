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
      { path: 'requests', handle: { titleKey: 'nav.my_requests' }, lazy: comingSoon },
      { path: 'catalog', handle: { titleKey: 'nav.catalog' }, lazy: comingSoon },
      { path: '*', handle: { titleKey: 'shell.not_found' }, lazy: comingSoon },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
