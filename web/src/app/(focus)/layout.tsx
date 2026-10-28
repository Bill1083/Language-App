import { AuthGuard } from "@/components/auth-guard";

/** Full-screen, distraction-free screens: lessons, conversations, reviews, onboarding. */
export default function FocusLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard requireLanguage={false}>{children}</AuthGuard>;
}
