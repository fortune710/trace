import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { Toaster } from './components/ui/toast.tsx'
import { TooltipProvider } from './components/ui/tooltip.tsx'

const queryClient = new QueryClient()
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <BrowserRouter>
        <Toaster />
        <App />
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>,
)
