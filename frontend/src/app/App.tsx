import { Navigate, Route, Routes } from "react-router-dom"

import { AccountPage } from "@/app/auth/account-page"
import {
  CallbackPage,
  ForgotPasswordPage,
  ResetPasswordPage,
  SignInPage,
  SignUpPage,
  VerifyEmailPage,
} from "@/app/auth/pages"
import { AuthenticatedOnly, GuestOnly } from "@/app/auth/route-guards"
import { AgentsPage } from "@/app/agents/agents-page"
import { AgentDetailsPage } from "@/app/agents/agent-details-page"
import { IntegrationsPage } from "@/app/integrations/integrations-page"
import { ProjectDetailsPage } from "@/app/projects/project-details-page"
import { ProjectsPage } from "@/app/projects/projects-page"
import { ReviewDetailsPage } from "@/app/reviews/review-details-page"
import {
  ApiKeysPage,
  LegacyCredentialsRedirect,
  SettingsIndexRedirect,
} from "@/app/settings/api-keys-page"
import { WorkspacePage } from "@/app/workspace/workspace-page"

function App() {
  return (
    <Routes>
      <Route element={<GuestOnly />}>
        <Route
          path="/sign-in"
          element={<SignInPage />}
        />
        <Route
          path="/sign-up"
          element={<SignUpPage />}
        />
        <Route
          path="/forgot-password"
          element={<ForgotPasswordPage />}
        />
        <Route
          path="/reset-password"
          element={<ResetPasswordPage />}
        />
        <Route
          path="/auth/verify"
          element={<VerifyEmailPage />}
        />
        <Route
          path="/auth/callback"
          element={<CallbackPage />}
        />
      </Route>
      <Route element={<AuthenticatedOnly />}>
        <Route
          path="/account"
          element={<AccountPage />}
        />
        <Route
          path="/projects"
          element={<ProjectsPage />}
        />
        <Route
          path="/projects/:projectId"
          element={<ProjectDetailsPage />}
        />
        <Route
          path="/reviews/:reviewId"
          element={<ReviewDetailsPage />}
        />
        <Route
          path="/agents"
          element={<AgentsPage />}
        />
        <Route
          path="/agents/:agentId"
          element={<AgentDetailsPage />}
        />
        <Route
          path="/integrations"
          element={<IntegrationsPage />}
        />
        <Route
          path="/settings"
          element={<SettingsIndexRedirect />}
        />
        <Route
          path="/settings/api-keys"
          element={<ApiKeysPage />}
        />
        <Route
          path="/settings/credentials"
          element={<LegacyCredentialsRedirect />}
        />
        <Route
          path="/learn-more"
          element={<WorkspacePage section="Learn More" />}
        />
      </Route>
      <Route
        path="*"
        element={<Navigate to="/account" replace />}
      />
    </Routes>
  )
}

export default App
