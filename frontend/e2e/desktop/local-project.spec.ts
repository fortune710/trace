import assert from "node:assert/strict"
import { createWriteStream } from "node:fs"
import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from "node:child_process"
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"

import { assertPathFree } from "../../src/test/path-redaction"
import { startDesktopTestApi } from "./test-api"
import { WebDriverClient } from "./webdriver"

const frontendDirectory = path.resolve(import.meta.dir, "../..")
const repositoryDirectory = path.resolve(frontendDirectory, "..")

type DesktopDriver = {
  client: WebDriverClient
  process: ChildProcessWithoutNullStreams
  log: ReturnType<typeof createWriteStream>
}

function applicationPath() {
  const targetDirectory = path.join(frontendDirectory, "src-tauri", "target", "debug")

  if (process.platform === "darwin") {
    return path.join(targetDirectory, "bundle", "macos", "Trace.app")
  }

  if (process.platform === "win32") {
    return path.join(targetDirectory, "trace-desktop.exe")
  }

  throw new Error("Desktop E2E is supported only on macOS and Windows")
}

function buildDesktopApplication(apiBaseUrl: string) {
  execFileSync("bun", ["run", "tauri:build", "--", "--debug"], {
    cwd: frontendDirectory,
    env: {
      ...process.env,
      VITE_API_BASE_URL: apiBaseUrl,
    },
    stdio: "inherit",
  })
}

async function startDesktopDriver(
  pickerPath: string,
  testResultsDirectory: string,
  logName: string,
): Promise<DesktopDriver> {
  const driverProcess = spawn("tauri-driver", ["--port", "4444"], {
    cwd: repositoryDirectory,
    env: {
      ...process.env,
      TRACE_E2E_PICKER_PATH: pickerPath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  })
  const driverLog = createWriteStream(path.join(testResultsDirectory, logName))
  driverProcess.stdout.pipe(driverLog)
  driverProcess.stderr.pipe(driverLog)

  const driver = new WebDriverClient("http://127.0.0.1:4444")
  try {
    await driver.waitFor(
      async () => fetch("http://127.0.0.1:4444/status"),
      (status) => status.ok,
    )
    await driver.start(applicationPath())
  } catch (error) {
    driverProcess.kill()
    driverLog.end()
    throw error
  }

  return {
    client: driver,
    process: driverProcess,
    log: driverLog,
  }
}

async function closeDesktopDriver(driver: DesktopDriver) {
  await driver.client.close()
  driver.process.kill()
  driver.log.end()
}

async function withDesktopDriver(
  pickerPath: string,
  scenario: string,
  testResultsDirectory: string,
  callback: (driver: WebDriverClient) => Promise<void>,
) {
  const desktopDriver = await startDesktopDriver(
    pickerPath,
    testResultsDirectory,
    `tauri-driver-${scenario}.log`,
  )

  try {
    await callback(desktopDriver.client)
  } catch (error) {
    await desktopDriver.client
      .screenshot(testResultsDirectory, `desktop-${scenario}-failure.png`)
      .catch(() => undefined)
    throw error
  } finally {
    await closeDesktopDriver(desktopDriver)
  }
}

async function openLocalFolderPicker(driver: WebDriverClient) {
  await driver.waitForText("css selector", "body", "Projects")
  await driver.click("xpath", "//button[contains(normalize-space(.), 'Create project')]")
  await driver.click("xpath", "//button[.//span[normalize-space(.)='Local folder']]")
}

async function closeCreateProjectDialog(driver: WebDriverClient) {
  await driver.click("xpath", "//button[normalize-space(.)='Cancel']")
}

async function run() {
  const api = startDesktopTestApi()
  const fixtureDirectory = await mkdtemp(path.join(os.tmpdir(), "trace-desktop-e2e-"))
  const projectDirectory = path.join(fixtureDirectory, "Local project")
  const missingDirectory = path.join(fixtureDirectory, "Missing project")
  const filePath = path.join(fixtureDirectory, "Not a folder.txt")
  const testResultsDirectory = path.join(frontendDirectory, "test-results")

  await mkdir(projectDirectory)
  await writeFile(path.join(fixtureDirectory, "fixture.txt"), "desktop e2e fixture")
  await writeFile(filePath, "not a directory")
  await mkdir(testResultsDirectory, { recursive: true })

  try {
    buildDesktopApplication(api.baseUrl)

    await withDesktopDriver(
      projectDirectory,
      "local-project-success",
      testResultsDirectory,
      async (driver) => {
        await openLocalFolderPicker(driver)
        await driver.waitForElement("css selector", "#project-name")
        assert.equal(await driver.has("xpath", "//*[normalize-space(.)='Choose a repository']"), false)
        assert.equal(await driver.has("xpath", "//*[normalize-space(.)='Choose branch']"), false)

        await driver.type("css selector", "#project-name", "Desktop E2E project")
        await driver.click("xpath", "//button[@type='submit' and normalize-space(.)='Create project']")
        await driver.waitForText("css selector", "body", "Projects")
        assert.match(await driver.currentUrl(), /\/projects\/local:/)

        api.expireSession()
        await driver.execute("window.dispatchEvent(new Event('focus'))")
        await driver.waitForText("css selector", "body", "Your session has ended")
        await driver.click("xpath", "//button[normalize-space(.)='Go to sign in']")
        await driver.waitForElement("css selector", "#email")
        await driver.type("css selector", "#email", "desktop-e2e@example.test")
        await driver.type("css selector", "#password", "correct-horse-battery-staple")
        await driver.click("xpath", "//button[@type='submit' and normalize-space(.)='Sign in']")
        await driver.waitForText("css selector", "body", "Projects")
      },
    )

    await withDesktopDriver(
      "__cancel__",
      "local-project-cancel",
      testResultsDirectory,
      async (driver) => {
        await openLocalFolderPicker(driver)
        await driver.waitForText("css selector", "body", "Choose a folder on this device")
        assert.equal(await driver.has("css selector", "#project-name"), false)
        await closeCreateProjectDialog(driver)
      },
    )

    await withDesktopDriver(
      missingDirectory,
      "local-project-missing",
      testResultsDirectory,
      async (driver) => {
        await openLocalFolderPicker(driver)
        const body = await driver.waitForText("css selector", "body", "no longer exists")
        assertPathFree(body, [missingDirectory])
        await closeCreateProjectDialog(driver)
      },
    )

    await withDesktopDriver(
      filePath,
      "local-project-file",
      testResultsDirectory,
      async (driver) => {
        await openLocalFolderPicker(driver)
        const body = await driver.waitForText("css selector", "body", "Choose a folder rather than a file")
        assertPathFree(body, [filePath])
        await closeCreateProjectDialog(driver)
      },
    )

    assert.equal(api.projectCreateRequests.length, 0)
    assertPathFree(api.requests)
  } finally {
    api.close()
    await rm(fixtureDirectory, { recursive: true, force: true })
  }
}

await run()
