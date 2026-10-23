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
            path: 'roles',
            lazy: async () => ({ Component: (await import('./pages/admin/RolesPage')).RolesPage }),
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
