import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { act } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useNotify, ToastProvider } from "./Toast"
import { useSave } from "../../lib/save"

/**
 * A write with no visible outcome is the failure mode this layer exists to
 * prevent, so the tests are about *what the operator sees*, not about whether
 * the request was made.
 */

afterEach(cleanup)

function Harness() {
  const notify = useNotify()
  return (
    <div>
      <button onClick={() => notify.success("已保存", "机位名称已更新")}>
        ok
      </button>
      <button onClick={() => notify.error("保存失败", "字段无效")}>bad</button>
      <button onClick={() => notify.warning("部分生效")}>warn</button>
    </div>
  )
}

function renderWithToast(ui: React.ReactNode) {
  return render(<ToastProvider>{ui}</ToastProvider>)
}

describe("ToastProvider", () => {
  it("announces a success with its detail", () => {
    renderWithToast(<Harness />)
    act(() => {
      screen.getByRole("button", { name: "ok" }).click()
    })

    expect(screen.getByText("已保存")).toBeTruthy()
    expect(screen.getByText("机位名称已更新")).toBeTruthy()
  })

  it("keeps a failure on screen until it is dismissed", () => {
    // A confirmation that outstays its welcome becomes the thing you stop
    // reading — but only successes are allowed to expire.
    renderWithToast(<Harness />)
    act(() => {
      screen.getByRole("button", { name: "bad" }).click()
    })

    const toast = screen.getByRole("status")
    expect(toast.textContent).toContain("保存失败")
    expect(toast.getAttribute("aria-live")).toBe("assertive")
  })

  it("lets the operator dismiss a toast", () => {
    renderWithToast(<Harness />)
    act(() => {
      screen.getByRole("button", { name: "bad" }).click()
    })

    act(() => {
      screen.getByRole("button", { name: "关闭通知" }).click()
    })

    expect(screen.queryByText("保存失败")).toBeNull()
  })

  it("keeps several results visible at once", () => {
    renderWithToast(<Harness />)
    act(() => {
      screen.getByRole("button", { name: "ok" }).click()
    })
    act(() => {
      screen.getByRole("button", { name: "warn" }).click()
    })

    expect(screen.getByText("已保存")).toBeTruthy()
    expect(screen.getByText("部分生效")).toBeTruthy()
  })
})

function SaveButton({ shouldFail }: { shouldFail: boolean }) {
  const mutation = useSave<{ name: string }>({
    mutationFn: async (variables) => {
      if (shouldFail) throw new Error("字段 name 已被占用")
      return variables
    },
    success: () => ({ title: "已保存" }),
    invalidates: [["cameras", "list", false]],
  })
  return (
    <>
      <button onClick={() => mutation.mutate({ name: "前门" })}>保存</button>
      <span data-testid="status">
        {mutation.isPending ? "saving" : mutation.isError ? "error" : "idle"}
      </span>
    </>
  )
}

function SaveHarness({ shouldFail }: { shouldFail: boolean }) {
  const client = new QueryClient()
  return (
    <QueryClientProvider client={client}>
      <SaveButton shouldFail={shouldFail} />
    </QueryClientProvider>
  )
}

describe("useSave", () => {
  it("announces success", async () => {
    render(
      <ToastProvider>
        <SaveHarness shouldFail={false} />
      </ToastProvider>,
    )

    act(() => {
      screen.getByRole("button", { name: "保存" }).click()
    })

    await waitFor(() => {
      expect(screen.getByText("已保存")).toBeTruthy()
    })
  })

  it("surfaces the failure message instead of failing silently", async () => {
    // The Vue version of this page swallowed the error and simply stopped
    // re-rendering, which is indistinguishable from a save that worked.
    render(
      <ToastProvider>
        <SaveHarness shouldFail={true} />
      </ToastProvider>,
    )

    act(() => {
      screen.getByRole("button", { name: "保存" }).click()
    })

    await waitFor(() => {
      expect(screen.getByText("操作失败")).toBeTruthy()
    })
    expect(screen.getByText(/已被占用/)).toBeTruthy()
    expect(screen.getByTestId("status").textContent).toBe("error")
  })

  it("does not retry a write on its own", async () => {
    const attempt = vi.fn(async () => {
      throw new Error("nope")
    })
    const client = new QueryClient()

    function RetryProbe() {
      useSave({ mutationFn: attempt })
      return null
    }

    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <RetryProbe />
        </ToastProvider>
      </QueryClientProvider>,
    )

    // Retrying a write the operator did not ask to repeat is how a
    // half-applied change gets applied twice.
    expect(attempt).not.toHaveBeenCalled()
  })
})
