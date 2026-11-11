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
        // WP-049a s2: the asset list, vendors and one asset.
        path: 'assets',
        handle: { section: 'assets' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/assets/AssetsPage')).AssetsPage,
            }),
          },
          {
            path: 'vendors',
            lazy: async () => ({
              Component: (await import('./pages/assets/VendorsPage')).VendorsPage,
            }),
          },
          {
            // WP-049a s5 (REQ-AST-030, 031): the loan register.
            path: 'loans',
            lazy: async () => ({
              Component: (await import('./pages/assets/LoansPage')).LoansPage,
            }),
          },
          {
            // WP-049b s1 (REQ-AST-033, 034): consumable stock, its lots and ledger.
            path: 'consumables',
            lazy: async () => ({
              Component: (await import('./pages/assets/ConsumablesPage')).ConsumablesPage,
            }),
          },
          {
            path: 'consumables/:id',
            lazy: async () => ({
              Component: (await import('./pages/assets/ConsumablePage')).ConsumablePage,
            }),
          },
          {
            // WP-049a s4 (REQ-AST-028): static and dynamic groups.
            path: 'groups',
            lazy: async () => ({
              Component: (await import('./pages/assets/GroupsPage')).GroupsPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({ Component: (await import('./pages/assets/AssetPage')).AssetPage }),
          },
        ],
      },
      {
        // The change screens (WP-045d D19, taken forward): the list, a new change, the record.
        path: 'changes',
        handle: { section: 'changes' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/changes/ChangesPage')).ChangesPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/changes/NewChangePage')).NewChangePage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/changes/ChangePage')).ChangePage,
            }),
          },
        ],
      },
      {
        // WP-058a s6: releases on the stage engine (ADR-041).
        path: 'releases',
        handle: { section: 'releases' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/releases/ReleasesPage')).ReleasesPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/releases/NewReleasePage')).NewReleasePage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/releases/ReleasePage')).ReleasePage,
            }),
          },
        ],
      },
      {
        // WP-044a s5: problems (the list, creating one, the record).
        path: 'problems',
        handle: { section: 'problems' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/problems/ProblemsPage')).ProblemsPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/problems/NewProblemPage')).NewProblemPage,
            }),
          },
          {
            path: 'known-errors',
            lazy: async () => ({
              Component: (await import('./pages/problems/KnownErrors')).KnownErrorsPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/problems/ProblemPage')).ProblemPage,
            }),
          },
        ],
      },
      {
        path: 'requests',
        handle: { section: 'requests' },
        children: [
          {
            // WP-030 s3: an approval from an e-mail link (the token is in the URL fragment).
            path: 'approval-link',
            lazy: async () => ({
              Component: (await import('./pages/requests/ActionLinkPage')).ActionLinkPage,
            }),
          },
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/requests/RequestsPage')).RequestsPage,
            }),
          },
          {
            path: 'new',
            lazy: async () => ({
              Component: (await import('./pages/requests/NewRequestPage')).NewRequestPage,
            }),
          },
          {
            path: ':id',
            lazy: async () => ({
              Component: (await import('./pages/requests/RequestPage')).RequestPage,
            }),
          },
        ],
      },
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
        path: 'knowledge',
        handle: { section: 'knowledge' },
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (await import('./pages/knowledge/KnowledgePage')).KnowledgePage,
            }),
          },
          {
            path: 'approvals',
            lazy: async () => ({
              Component: (await import('./pages/knowledge/ApprovalInboxPage')).ApprovalInboxPage,
            }),
          },
          {
            path: 'articles/new',
            lazy: async () => ({
              Component: (await import('./pages/knowledge/ArticleEditorPage')).NewArticlePage,
            }),
          },
          {
            path: 'articles/:id',
            lazy: async () => ({
              Component: (await import('./pages/knowledge/ArticlePage')).ArticlePage,
            }),
          },
          {
            path: 'articles/:id/edit/:lang',
            lazy: async () => ({
              Component: (await import('./pages/knowledge/ArticleEditorPage')).ArticleEditorPage,
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
          {
            index: true,
            lazy: async () => ({ Component: (await import('./pages/admin/SetupHome')).SetupHome }),
          },
          {
            path: 'instance',
            lazy: async () => ({
              Component: (await import('./pages/admin/InstanceSettingsPage')).InstanceSettingsPage,
            }),
          },
          {
            path: 'licence',
            lazy: async () => ({
              Component: (await import('./pages/admin/LicencePage')).LicencePage,
            }),
          },
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
            path: 'requests',
            lazy: async () => ({
              Component: (await import('./pages/admin/requests/RequestSettingsPage'))
                .RequestSettingsPage,
            }),
          },
          {
            // WP-032 D8: every portal setting on one page (REQ-PRT-031).
            path: 'portal',
            lazy: async () => ({
              Component: (await import('./pages/admin/portal/PortalSettingsPage'))
                .PortalSettingsPage,
            }),
          },
          {
            // WP-031: the service catalog's administration (plan D4).
            path: 'catalog',
            lazy: async () => ({
              Component: (await import('./pages/admin/catalog/CatalogAdminPage')).CatalogAdminPage,
            }),
          },
          {
            path: 'catalog/items/:id',
            lazy: async () => ({
              Component: (await import('./pages/admin/catalog/CatalogItemPage')).CatalogItemPage,
            }),
          },
          {
            path: 'assets',
            lazy: async () => ({
              Component: (await import('./pages/admin/assets/AssetCatalogPage')).AssetCatalogPage,
            }),
          },
          {
            // Visual workflows (WP-048b S4): the list (template C) and the designer.
            path: 'workflows',
            lazy: async () => ({
              Component: (await import('./pages/admin/workflows/WorkflowsPage')).WorkflowsPage,
            }),
          },
          {
            path: 'workflows/:workflowId',
            lazy: async () => ({
              Component: (await import('./pages/admin/workflows/DesignerPage')).DesignerPage,
            }),
          },
          {
            path: 'automation/:section?',
            lazy: async () => ({
              Component: (await import('./pages/admin/automation/AutomationPage')).AutomationPage,
            }),
          },
          {
            // The change screens' S4: change advisory boards (template E).
            path: 'change-boards',
            lazy: async () => ({
              Component: (await import('./pages/admin/changes/ChangeBoardsPage')).ChangeBoardsPage,
            }),
          },
          {
            path: 'sla/:section?',
            lazy: async () => ({
              Component: (await import('./pages/admin/sla/SlaPage')).SlaPage,
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
            path: 'ai',
            lazy: async () => ({
              Component: (await import('./pages/admin/AiSettingsPage')).AiSettingsPage,
            }),
          },
          {
            path: 'api-keys',
            lazy: async () => ({
              Component: (await import('./pages/admin/ApiKeysPage')).ApiKeysPage,
            }),
          },
          {
            path: 'notifications',
            lazy: async () => ({
              Component: (await import('./pages/admin/notifications/NotificationRulesPage'))
                .NotificationRulesPage,
            }),
          },
          {
            path: 'mail',
            lazy: async () => ({
              Component: (await import('./pages/admin/mail/MailPage')).MailPage,
            }),
          },
          {
            path: 'integrations',
            lazy: async () => ({
              Component: (await import('./pages/admin/integrations/IntegrationsPage'))
                .IntegrationsPage,
            }),
          },
          {
            path: 'integrations/directories',
            lazy: async () => ({
              Component: (await import('./pages/admin/integrations/DirectoriesPage'))
                .DirectoriesPage,
            }),
          },
          {
            path: 'knowledge',
            lazy: async () => ({
              Component: (await import('./pages/admin/knowledge/KnowledgeSettingsPage'))
                .KnowledgeSettingsPage,
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
