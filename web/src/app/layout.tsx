import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { AuthProvider } from "@/components/auth-provider";
import { PreferencesProvider } from "@/components/preferences-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Pantry Hub",
  description: "Firebase-backed pantry, shopping, and kitchen analytics dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" data-theme="dark" suppressHydrationWarning>
      <body className="min-h-full flex flex-col bg-gray-950 text-gray-100">
        <PreferencesProvider>
          <AuthProvider>
            <AppShell>{children}</AppShell>
          </AuthProvider>
        </PreferencesProvider>
      </body>
    </html>
  );
}
