export type AnalyticsEventMap = {
  // Auth / onboarding
  auth_sign_in_submitted: { method: "password" | "oauth" }
  auth_sign_in_succeeded: { method: "password" | "oauth"; provider?: "github" | "google" }
  auth_sign_in_failed: { method: "password" | "oauth"; provider?: "github" | "google"; error_code?: string }
  auth_sign_up_submitted: { method: "password" }
  auth_sign_up_succeeded: { method: "password" }
  auth_sign_up_failed: { method: "password"; error_code?: string }
  auth_password_recovery_submitted: Record<string, never>
  auth_password_recovery_succeeded: Record<string, never>
  auth_password_reset_submitted: Record<string, never>
  auth_password_reset_succeeded: Record<string, never>
  auth_email_verify_submitted: Record<string, never>
  auth_email_verify_succeeded: Record<string, never>
  auth_oauth_started: { provider: "github" | "google"; surface: "web" | "desktop" }
  auth_logout_clicked: Record<string, never>
  auth_session_expired_shown: Record<string, never>

  // Navigation / product shell
  navigation_sidebar_clicked: { destination: string }
  landing_cta_clicked: { cta: string }

  // Projects / repos
  project_create_submitted: { source: "github" | "local"; category: string }
  project_create_succeeded: { source: "github" | "local"; category: string }
  project_create_failed: { source: "github" | "local"; error_code?: string }
  project_opened: { project_id: string; source: "github" | "local" }
  project_issue_tracking_updated: { project_id: string; provider_count: number }

  // Reviews
  review_create_submitted: { project_id: string; source: "github" | "local"; agent_count: number }
  review_create_succeeded: { project_id: string; review_id?: string; source: "github" | "local"; agent_count: number }
  review_create_failed: { project_id: string; source: "github" | "local"; error_code?: string }
  review_opened: { review_id: string; status?: string }

  // Findings / remediations
  finding_opened: { finding_id: string; review_id: string; severity?: string; status?: string }
  finding_status_updated: { finding_id: string; status: string }
  finding_pr_create_submitted: { finding_id: string }
  finding_pr_create_succeeded: { finding_id: string }
  finding_pr_create_failed: { finding_id: string; error_code?: string }
  finding_local_remediation_applied: { finding_id: string; outcome: "succeeded" | "failed" }
  finding_issue_create_submitted: { finding_id: string; provider: string }
  finding_issue_create_succeeded: { finding_id: string; provider: string }
  finding_issue_create_failed: { finding_id: string; provider: string; error_code?: string }

  // Agents / skills
  agent_create_submitted: { review_category: string; model_provider: string }
  agent_create_succeeded: { agent_id?: string; review_category: string; model_provider: string }
  agent_create_failed: { review_category?: string; model_provider?: string; error_code?: string }
  agent_opened: { agent_id: string }
  agent_updated: { agent_id: string; fields: string[] }
  agent_disabled: { agent_id: string }
  agent_avatar_uploaded: { agent_id: string }
  agent_avatar_deleted: { agent_id: string }
  agent_skills_picker_opened: { agent_id: string }
  agent_skill_attach_submitted: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
  }
  agent_skill_attach_succeeded: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
  }
  agent_skill_attach_failed: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
    error_code?: string
  }
  agent_skill_detach_submitted: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
  }
  agent_skill_detach_succeeded: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
  }
  agent_skill_detach_failed: {
    agent_id: string
    skill_id: string
    provider: "skills.sh"
    error_code?: string
  }

  // Settings / credentials
  settings_api_key_saved: { provider: string; action: "create" | "rotate" }
  settings_api_key_save_failed: { provider: string; action: "create" | "rotate"; error_code?: string }
  settings_automatic_prs_toggled: { enabled: boolean }

  // Integrations
  integration_connect_started: { provider: "github" | "gitlab" | "linear" }
  integration_connect_failed: { provider: "github" | "gitlab" | "linear"; error_code?: string }

  // Notifications
  notification_opened: { notification_id: string }
  notification_mark_read: { scope: "one" | "all" }
}

export type AnalyticsEventName = keyof AnalyticsEventMap

export type AnalyticsEventProperties<T extends AnalyticsEventName> = AnalyticsEventMap[T]
