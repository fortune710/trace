import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { Toaster } from '../components/ui/toast.tsx'
import { TooltipProvider } from '../components/ui/tooltip.tsx'
import { DesktopProjectBootstrap } from '../components/desktop-project-bootstrap.tsx'
import { DesktopOAuthBootstrap } from '../hooks/use-desktop-oauth.ts'
import { SessionBoundary } from '../components/auth/session-boundary.tsx'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <DesktopProjectBootstrap />
    <TooltipProvider>
      <BrowserRouter>
        <DesktopOAuthBootstrap />
        <Toaster />
        <SessionBoundary>
          <App />
        </SessionBoundary>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>,
)
