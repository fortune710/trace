import { AppShell } from "@/components/layout/app-shell"

export function WorkspacePage({ section }: { section: string }) {
  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <h1 className="text-xl font-medium tracking-tight">{section}</h1>
      </section>
    </AppShell>
  )
}
