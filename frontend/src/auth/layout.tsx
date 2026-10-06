import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
export function AuthShell({ children }: { children: ReactNode }) { return <main className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-4 py-10 text-foreground"><div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-[radial-gradient(ellipse_at_top,rgba(0,117,255,0.16),transparent_64%)]" /><section className="relative w-full max-w-md rounded-xl border border-border bg-card p-6 sm:p-8"><Link className="font-mono text-sm tracking-tight text-foreground" to="/account">trace</Link><Separator className="my-6" />{children}</section></main> }
export function AuthLoading() { return <AuthShell><Skeleton className="h-8 w-48" /><Skeleton className="mt-4 h-20 w-full" /></AuthShell> }
export function RequestError({ error }: { error: unknown }) { return <p className="mt-3 text-sm text-destructive" role="alert">{error instanceof Error ? error.message : 'Unable to complete the request.'}</p> }
