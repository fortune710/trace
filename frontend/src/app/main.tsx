import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AnalyticsErrorBoundary } from '../components/analytics/analytics-error-boundary.tsx'
import { AnalyticsProvider } from '../components/analytics/analytics-provider.tsx'
import { SessionBoundary } from '../components/auth/session-boundary.tsx'
import { Toaster } from '../components/ui/toast.tsx'
import { TooltipProvider } from '../components/ui/tooltip.tsx'
import { DesktopOAuthBootstrap } from '../hooks/use-desktop-oauth.ts'
import { initAnalytics } from '@/lib/analytics'

initAnalytics()

const queryClient = new QueryClient()
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <BrowserRouter>
        <AnalyticsErrorBoundary>
          <AnalyticsProvider>
            <SessionBoundary>
              <Toaster />
              <DesktopOAuthBootstrap />
              <App />
            </SessionBoundary>
          </AnalyticsProvider>
        </AnalyticsErrorBoundary>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>,
)
