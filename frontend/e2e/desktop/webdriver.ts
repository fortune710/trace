import { mkdir, writeFile } from "node:fs/promises"
import path from "node:path"

const elementKey = "element-6066-11e4-a52e-4f735466cecf"

type WebDriverElement = Record<string, string>

function elementId(element: WebDriverElement) {
  return element[elementKey] ?? element.ELEMENT
}

export class WebDriverClient {
  private sessionId: string | null = null

  constructor(private readonly baseUrl: string) {}

  private async request<T>(requestPath: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${requestPath}`, init)
    const payload = await response.json() as { value?: T; message?: string; error?: string }

    if (!response.ok || payload.error) {
      throw new Error(payload.message ?? payload.error ?? `WebDriver request failed: ${response.status}`)
    }

    return payload.value as T
  }

  async start(applicationPath: string) {
    const value = await this.request<{ sessionId?: string; capabilities?: { browserName?: string } }>("/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        capabilities: {
          alwaysMatch: {
            browserName: "",
            "tauri:options": { application: applicationPath },
          },
        },
      }),
    })

    this.sessionId = value.sessionId ?? null
    if (!this.sessionId) {
      throw new Error("Tauri WebDriver did not return a session ID")
    }
  }

  private sessionPath(suffix: string) {
    if (!this.sessionId) throw new Error("WebDriver session is not started")
    return `/session/${this.sessionId}${suffix}`
  }

  async navigate(url: string) {
    await this.request(this.sessionPath("/url"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    })
  }

  async currentUrl() {
    return this.request<string>(this.sessionPath("/url"))
  }

  async find(using: "css selector" | "xpath", value: string) {
    return this.request<WebDriverElement>(this.sessionPath("/element"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ using, value }),
    })
  }

  async has(using: "css selector" | "xpath", value: string) {
    try {
      await this.find(using, value)
      return true
    } catch {
      return false
    }
  }

  async click(using: "css selector" | "xpath", value: string) {
    const element = await this.find(using, value)
    await this.request(this.sessionPath(`/element/${elementId(element)}/click`), { method: "POST" })
  }

  async type(using: "css selector" | "xpath", value: string, text: string) {
    const element = await this.find(using, value)
    await this.request(this.sessionPath(`/element/${elementId(element)}/value`), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, value: [...text] }),
    })
  }

  async text(using: "css selector" | "xpath", value: string) {
    const element = await this.find(using, value)
    return this.request<string>(this.sessionPath(`/element/${elementId(element)}/text`))
  }

  async execute<T>(script: string, args: unknown[] = []) {
    return this.request<T>(this.sessionPath("/execute/sync"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ script, args }),
    })
  }

  async screenshot(directory: string, name: string) {
    const screenshot = await this.request<string>(this.sessionPath("/screenshot"))
    await mkdir(directory, { recursive: true })
    await writeFile(path.join(directory, name), Buffer.from(screenshot, "base64"))
  }

  async waitFor<T>(operation: () => Promise<T>, predicate: (value: T) => boolean, timeoutMilliseconds = 30_000) {
    const deadline = Date.now() + timeoutMilliseconds
    let lastError: unknown

    while (Date.now() < deadline) {
      try {
        const value = await operation()
        if (predicate(value)) return value
      } catch (error) {
        lastError = error
      }
      await new Promise((resolve) => setTimeout(resolve, 200))
    }

    throw new Error(`WebDriver condition timed out${lastError ? `: ${String(lastError)}` : ""}`)
  }

  async waitForElement(using: "css selector" | "xpath", value: string) {
    return this.waitFor(() => this.find(using, value), () => true)
  }

  async waitForText(using: "css selector" | "xpath", value: string, expectedText: string) {
    return this.waitFor(() => this.text(using, value), (text) => text.includes(expectedText))
  }

  async close() {
    if (!this.sessionId) return
    await this.request(this.sessionPath(""), { method: "DELETE" }).catch(() => undefined)
    this.sessionId = null
  }
}
