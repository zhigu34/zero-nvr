import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderOptions, type RenderResult } from "@testing-library/react"

import { ToastProvider } from "./components/ui/Toast"

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
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
    renderOptions,
  )

  return { ...result, client }
}
