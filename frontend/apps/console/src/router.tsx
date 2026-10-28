import { createBrowserRouter, type RouteObject } from 'react-router';

import { ConsoleLayout } from './ConsoleLayout';
import { SECTION_KEYS } from './nav';
import { Loading } from './pages/Loading';
import { RouteError } from './pages/RouteError';

/**
 * Every page is its own lazily loaded chunk (route-level code splitting), so the first load only
 * fetches the shell. The dev-only components page is not even part of a production build:
 * `import.meta.env.DEV` is false there and the bundler drops the branch.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <ConsoleLayout />,
    errorElement: <RouteError />,
    hydrateFallbackElement: <Loading />,
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import('./pages/HomePage')).HomePage }),
      },
      ...SECTION_KEYS.map((key) => ({
        path: key,
        handle: { section: key },
        lazy: async () => ({ Component: (await import('./pages/SectionPage')).SectionPage }),
      })),
      {
        path: 'incidents',
        handle: { section: 'incidents' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/incidents/IncidentsPage')).IncidentsPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/incidents/NewIncidentPage')).NewIncidentPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/incidents/IncidentPage')).IncidentPage,
            }),
          },
        ],
      },
      {
        path: 'dashboards',
        handle: { section: 'dashboards' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/dashboards/DashboardsPage')).DashboardsPage,
            }),
          },
          {
            path: ':ref',
            lazy: async () => ({
              Component: (await import('./pages/dashboards/DashboardsPage')).DashboardsPage,
            }),
          },
        ],
      },
      {
        path: 'reports',
        handle: { section: 'reports' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/reports/ReportsHomePage')).ReportsHomePage,
            }),
          },
          {
            path: 'builtin/:code',
            lazy: async () => ({
              Component: (await import('./pages/reports/ReportPage')).ReportPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/reports/ReportPage')).ReportPage,
            }),
          },
        ],
      },
      {
        path: 'announcements',
        handle: { section: 'announcements' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/announcements/AnnouncementsPage'))
                .AnnouncementsPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/announcements/NewAnnouncementPage'))
                .NewAnnouncementPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/announcements/AnnouncementPage')).AnnouncementPage,
            }),
          },
        ],
      },
      {
        path: 'admin',
        handle: { section: 'admin' },
        lazy: async () => ({ Component: (await import('./pages/admin/AdminLayout')).AdminLayout }),
        children: [
          { index: true, element: null },
          {
            path: 'users',
            lazy: async () => ({ Component: (await import('./pages/admin/UsersPage')).UsersPage }),
          },
          {
            path: 'organization/:section?',
            lazy: async () => ({
              Component: (await import('./pages/admin/organization/OrganizationPage'))
                .OrganizationPage,
            }),
          },
          {
            path: 'roles',
            lazy: async () => ({ Component: (await import('./pages/admin/RolesPage')).RolesPage }),
          },
          {
            path: 'audit',
            lazy: async () => ({
              Component: (await import('./pages/admin/audit/AuditPage')).AuditPage,
            }),
          },
          {
            path: 'incidents/:section?',
            lazy: async () => ({
              Component: (await import('./pages/admin/incidents/IncidentSettingsPage'))
                .IncidentSettingsPage,
            }),
          },
          {
            path: 'automation/:section?',
            lazy: async () => ({
              Component: (await import('./pages/admin/automation/AutomationPage')).AutomationPage,
            }),
          },
          {
            path: 'files',
            lazy: async () => ({
              Component: (await import('./pages/admin/files/FilesPage')).FilesPage,
            }),
          },
          {
            path: 'branding',
            lazy: async () => ({
              Component: (await import('./pages/admin/branding/BrandingPage')).BrandingPage,
            }),
          },
          {
            path: 'security',
            lazy: async () => ({
              Component: (await import('./pages/admin/security/SecurityPage')).SecurityPage,
            }),
          },
          {
            path: 'notifications',
            lazy: async () => ({
              Component: (await import('./pages/admin/notifications/NotificationRulesPage'))
                .NotificationRulesPage,
            }),
          },
        ],
      },
      {
        path: 'profile',
        lazy: async () => ({ Component: (await import('./pages/ProfilePage')).ProfilePage }),
      },
      ...(import.meta.env.DEV
        ? [
            {
              path: 'dev/components',
              lazy: async () => ({
                Component: (await import('./pages/DevComponentsPage')).DevComponentsPage,
              }),
            },
          ]
        : []),
      {
        path: '*',
        lazy: async () => ({ Component: (await import('./pages/NotFoundPage')).NotFoundPage }),
      },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
