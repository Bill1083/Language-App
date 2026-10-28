import { Logo } from "@/components/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl"
      />
      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Logo className="[&_svg]:size-10 [&_span]:text-2xl" />
        </div>
        {children}
        <p className="mt-8 text-center text-xs text-muted-foreground">
          <span lang="fr">Bonjour</span> · <span lang="it">Ciao</span> · <span lang="ja">こんにちは</span>
        </p>
      </div>
    </div>
  );
}
