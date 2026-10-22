// @supportx/api-client: typed access to the SupportX API (architecture.md §9.2).
// Types come from schema.ts, generated from the backend's OpenAPI contract (`make openapi`, D-022).
// The TanStack Query hooks for business resources are added in WP-010.
export {
  API_BASE,
  ApiError,
  apiFetch,
  apiGet,
  apiPost,
  CSRF_HEADER,
  loginUrl,
  setCsrfToken,
  type App,
  type ProblemDetail,
} from './http';
export type { components, paths } from './schema';
export {
  fetchMe,
  SESSION_QUERY_KEY,
  useLogout,
  useSession,
  type MeResponse,
  type SessionTenant,
  type SessionUser,
} from './session';
