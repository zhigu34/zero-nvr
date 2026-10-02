import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderOptions, type RenderResult } from "@testing-library/react"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router"

import { ToastProvider } from "./components/ui/Toast"
import { ConfirmProvider } from "./components/ui/Confirm"

/**
 * The same wrapper the app uses around every route, so a component tested in
 * isolation sees the providers it will actually have at runtime.
 *
 * This is not optional convenience: `useSave` and `useNotify` both throw
 * outside their providers, and a page that renders fine in the app while its
 * test crashes is worse than no test at all.
 */
export interface ProviderOptions extends RenderOptions {
  /** Supply a pre-seeded client, e.g. one with `setQueryData` already called. */
  client?: QueryClient
}

export function renderWithProviders(
  ui: React.ReactElement,
  options: ProviderOptions = {},
): RenderResult & { client: QueryClient } {
  const { client: provided, ...renderOptions } = options
  const client =
    provided ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

  const result = render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ConfirmProvider>{ui}</ConfirmProvider>
      </ToastProvider>
    </QueryClientProvider>,
    renderOptions,
  )

  return { ...result, client }
}

/**
 * The same, plus a minimal in-memory router.
 *
 * Needed by any page that navigates — `useNavigate` throws without a router
 * context rather than degrading. The real route tree is deliberately not
 * reused here: it carries auth guards, so a page test would have to fake a
 * signed-in session to get past a redirect that has nothing to do with what
 * it is testing. A two-route tree renders the page and nothing else.
 */
export function renderWithRouter(
  ui: React.ReactElement,
  options: ProviderOptions & { path?: string } = {},
): RenderResult & { client: QueryClient } {
  const { client: provided, path = "/", ...rest } = options
  const client =
    provided ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })

  const rootRoute = createRootRoute({ component: () => ui })
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => ui,
  })
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })

  const result = render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ConfirmProvider>
          <RouterProvider router={router} />
        </ConfirmProvider>
      </ToastProvider>
    </QueryClientProvider>,
    rest,
  )

  return { ...result, client }
}
