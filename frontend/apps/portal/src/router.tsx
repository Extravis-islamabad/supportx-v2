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
      {
        path: 'requests',
        handle: { titleKey: 'nav.my_requests' },
        lazy: async () => ({
          Component: (await import('./pages/requests/RequestsPage')).RequestsPage,
        }),
      },
      {
        path: 'requests/new',
        handle: { titleKey: 'portal.report.title' },
        lazy: async () => ({
          Component: (await import('./pages/requests/ReportPage')).ReportPage,
        }),
      },
      {
        // WP-030 s3: approve or reject from an e-mail link (the token is in the URL fragment).
        path: 'requests/approval-link',
        handle: { titleKey: 'portal.approvals.title' },
        lazy: async () => ({
          Component: (await import('./pages/approvals/ApprovalLinkPage')).ApprovalLinkPage,
        }),
      },
      {
        path: 'approvals',
        handle: { titleKey: 'portal.approvals.title' },
        lazy: async () => ({
          Component: (await import('./pages/approvals/ApprovalsPage')).ApprovalsPage,
        }),
      },
      {
        path: 'requests/:id',
        handle: { titleKey: 'nav.my_requests' },
        lazy: async () => ({
          Component: (await import('./pages/requests/RequestPage')).RequestPage,
        }),
      },
      {
        path: 'service-requests',
        handle: { titleKey: 'portal.service_requests.title' },
        lazy: async () => ({
          Component: (await import('./pages/service-requests/ServiceRequestsPage'))
            .ServiceRequestsPage,
        }),
      },
      {
        path: 'service-requests/:id',
        handle: { titleKey: 'portal.service_requests.title' },
        lazy: async () => ({
          Component: (await import('./pages/service-requests/ServiceRequestPage'))
            .ServiceRequestPage,
        }),
      },
      {
        // WP-031: the catalog for requesters, and one item's request form.
        path: 'catalog',
        handle: { titleKey: 'nav.catalog' },
        lazy: async () => ({
          Component: (await import('./pages/catalog/CatalogPage')).CatalogPage,
        }),
      },
      {
        path: 'catalog/items/:id',
        handle: { titleKey: 'nav.catalog' },
        lazy: async () => ({
          Component: (await import('./pages/catalog/CatalogItemPage')).CatalogItemPage,
        }),
      },
      {
        // WP-032 D2: one search box for everything (REQ-PRT-003).
        path: 'search',
        handle: { titleKey: 'portal.search.title' },
        lazy: async () => ({ Component: (await import('./pages/SearchPage')).SearchPage }),
      },
      { path: '*', handle: { titleKey: 'shell.not_found' }, lazy: comingSoon },
    ],
  },
];

/** Routes are relative to where the portal is served: `/` in dev, `/portal/` when deployed. */
export const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';

export function createRouter() {
  return createBrowserRouter(routes, { basename: BASENAME });
}
