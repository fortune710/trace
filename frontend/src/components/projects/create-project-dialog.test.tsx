// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CreateProjectDialog } from "@/components/projects/create-project-dialog"
import { useLocalFolderPicker } from "@/hooks/use-local-folder-picker"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { LocalProjectCreationError } from "@/lib/desktop-projects"

vi.mock("@/hooks/use-runtime-environment", () => ({
  useRuntimeEnvironment: vi.fn(),
}))

vi.mock("@/hooks/use-local-folder-picker", () => ({
  useLocalFolderPicker: vi.fn(),
}))

const mockedLocalMutate = vi.hoisted(() => vi.fn())

vi.mock("@/hooks/use-debounce", () => ({
  useDebounce: (value: string) => value,
}))

vi.mock("@/hooks/use-project-feedback", () => ({
  projectCreatedToast: {},
  projectErrorCopy: vi.fn(),
  useProjectErrorToast: vi.fn(),
}))

vi.mock("@/hooks/use-projects", () => ({
  useBranches: vi.fn(() => ({
    data: undefined,
    error: null,
    isLoading: false,
    isFetchingNextPage: false,
    isError: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
  })),
  useRepositories: vi.fn(() => ({
    data: undefined,
    error: null,
    isLoading: false,
    isFetchingNextPage: false,
    isError: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
  })),
  useCreateProject: vi.fn(() => ({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
  })),
  useCreateLocalProject: vi.fn(() => ({
    mutate: mockedLocalMutate,
    reset: vi.fn(),
    isPending: false,
    error: null,
  })),
}))

vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const mockedRuntime = vi.mocked(useRuntimeEnvironment)
const mockedFolderPicker = vi.mocked(useLocalFolderPicker)

function renderDialog(onOpenChange = vi.fn()) {
  return render(
    <MemoryRouter>
      <CreateProjectDialog open onOpenChange={onOpenChange} />
    </MemoryRouter>,
  )
}

describe("CreateProjectDialog local folder source", () => {
  const selectFolder = vi.fn()
  const clearSelection = vi.fn()
  const commitSelection = vi.fn()

  beforeEach(() => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    mockedFolderPicker.mockReturnValue({
      selection: null,
      isSelecting: false,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })
    selectFolder.mockReset()
    clearSelection.mockReset()
    commitSelection.mockReset()
    mockedLocalMutate.mockReset()
    selectFolder.mockResolvedValue(null)
    clearSelection.mockResolvedValue(undefined)
  })

  afterEach(() => {
    cleanup()
  })

  it("hides the local source in the browser", () => {
    mockedRuntime.mockReturnValue({ kind: "web", isTauri: false, isWeb: true })

    renderDialog()

    expect(screen.queryByRole("button", { name: /local folder/i })).toBeNull()
  })

  it("shows and invokes the local source picker in Tauri", () => {
    renderDialog()

    fireEvent.click(screen.getByRole("button", { name: /local folder/i }))

    expect(selectFolder).toHaveBeenCalledOnce()
  })

  it("keeps the source-page subtitle generic and path-free", () => {
    mockedFolderPicker.mockReturnValue({
      selection: {
        sourceId: "source-a",
        displayName: "Trace project",
        availability: "available",
        lastValidatedAt: "2026-10-16T00:00:00.000Z",
      },
      isSelecting: false,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()

    expect(screen.getByText("Choose a folder on this device")).toBeTruthy()
    expect(screen.queryByText(/Users\/example/)).toBeNull()
  })

  it("disables the picker while selection is in progress", () => {
    mockedFolderPicker.mockReturnValue({
      selection: null,
      isSelecting: true,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()

    expect(screen.getByRole("button", { name: /local folder/i }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByText("Choosing folder…")).toBeTruthy()
  })

  it("shows a safe retryable picker error", () => {
    mockedFolderPicker.mockReturnValue({
      selection: null,
      isSelecting: false,
      error: { code: "permission_denied", message: "Trace does not have permission to read that folder." },
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()

    expect(screen.getByRole("alert").textContent).toContain("permission")
    expect(screen.getByRole("alert").textContent).not.toContain("/")
  })

  it("skips repository selection and defaults step three to the folder name", async () => {
    selectFolder.mockResolvedValue({
      sourceId: "source-a",
      displayName: "Trace project",
      availability: "available",
      lastValidatedAt: "2026-10-16T00:00:00.000Z",
    })

    renderDialog()
    fireEvent.click(screen.getByRole("button", { name: /local folder/i }))

    await waitFor(() => expect((screen.getByLabelText("Project name") as HTMLInputElement).value).toBe("Trace project"))
    expect(screen.queryByText("Choose a repository")).toBeNull()
    expect(screen.queryByText("Selected commit")).toBeNull()
    expect(screen.getByText("Local folder")).toBeTruthy()
  })

  it("does not show the folder name on the source page", () => {
    mockedFolderPicker.mockReturnValue({
      selection: {
        sourceId: "source-a",
        displayName: "Trace project",
        availability: "available",
        lastValidatedAt: "2026-10-16T00:00:00.000Z",
      },
      isSelecting: false,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()

    expect(screen.getAllByText("Choose a folder on this device")).toHaveLength(1)
    expect(screen.queryByText("Trace project")).toBeNull()
  })

  it("creates a local project with the opaque source ID and no backend fields", async () => {
    const selection = {
      sourceId: "source-a",
      displayName: "Trace project",
      availability: "available",
      lastValidatedAt: "2026-10-16T00:00:00.000Z",
    } as const
    selectFolder.mockResolvedValue(selection)
    mockedFolderPicker.mockReturnValue({
      selection,
      isSelecting: false,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()
    fireEvent.click(screen.getByRole("button", { name: /local folder/i }))
    await waitFor(() => expect((screen.getByLabelText("Project name") as HTMLInputElement).value).toBe("Trace project"))
    fireEvent.click(screen.getByRole("button", { name: "Create project" }))

    expect(mockedLocalMutate).toHaveBeenCalledWith(
      { name: "Trace project", category: "business", sourceId: "source-a" },
      expect.any(Object),
    )
    expect(mockedLocalMutate.mock.calls[0][0]).not.toHaveProperty("repositoryId")
    expect(mockedLocalMutate.mock.calls[0][0]).not.toHaveProperty("branchName")
  })

  it("clears the provisional selection when the dialog is cancelled", () => {
    renderDialog()

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

    expect(clearSelection).toHaveBeenCalledOnce()
  })

  it("retains the selected folder when creation reports a duplicate", async () => {
    const selection = {
      sourceId: "source-a",
      displayName: "Trace project",
      availability: "available",
      lastValidatedAt: "2026-10-16T00:00:00.000Z",
    } as const
    selectFolder.mockResolvedValue(selection)
    mockedFolderPicker.mockReturnValue({
      selection,
      isSelecting: false,
      error: null,
      selectFolder,
      clearSelection,
      commitSelection,
    })

    renderDialog()
    fireEvent.click(screen.getByRole("button", { name: /local folder/i }))
    await waitFor(() => expect((screen.getByLabelText("Project name") as HTMLInputElement).value).toBe("Trace project"))
    fireEvent.click(screen.getByRole("button", { name: "Create project" }))

    const options = mockedLocalMutate.mock.calls[0][1] as { onError: (error: unknown) => void }
    options.onError(new LocalProjectCreationError("already_exists"))

    expect(clearSelection).not.toHaveBeenCalled()
  })
})
