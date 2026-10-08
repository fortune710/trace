import { useNavigate } from 'react-router-dom'
import { AuthShell } from '@/auth/layout'
import { useLogout, useSession } from '@/auth/session'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
export function AccountPage() { const navigate = useNavigate(); const session = useSession(); const logout = useLogout(); return <AuthShell><p className="text-sm text-muted-foreground">Signed in</p><h1 className="mt-2 text-2xl font-medium tracking-tight">Your account is ready.</h1><p className="mt-3 text-sm text-muted-foreground">Session confirmed for <span className="font-mono text-foreground">{session.data?.user_id}</span>.</p><Button className="mt-8 w-full" disabled={logout.isPending} onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/sign-in', { replace: true }) })}>{logout.isPending ? <Spinner /> : null}Sign out</Button></AuthShell> }
