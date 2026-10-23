import { Navigate, Route, Routes } from 'react-router-dom'

import { AccountPage } from '@/auth/account-page'
import { CallbackPage, ForgotPasswordPage, ResetPasswordPage, SignInPage, SignUpPage, VerifyEmailPage } from '@/auth/pages'
import { AuthenticatedOnly, GuestOnly } from '@/auth/route-guards'

function App() {
  return <Routes><Route element={<GuestOnly />}><Route path="/sign-in" element={<SignInPage />} /><Route path="/sign-up" element={<SignUpPage />} /><Route path="/forgot-password" element={<ForgotPasswordPage />} /><Route path="/reset-password" element={<ResetPasswordPage />} /><Route path="/auth/verify" element={<VerifyEmailPage />} /><Route path="/auth/callback" element={<CallbackPage />} /></Route><Route element={<AuthenticatedOnly />}><Route path="/account" element={<AccountPage />} /></Route><Route path="*" element={<Navigate to="/account" replace />} /></Routes>
}

export default App
