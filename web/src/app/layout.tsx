import type { Metadata } from "next";
import Link from "next/link";
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
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-gray-950 text-gray-100">
        <header className="sticky top-0 z-50 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
          <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <Link href="/" className="text-sm font-bold text-emerald-400 hover:text-emerald-300">
              Smart Pantry
            </Link>
            <div className="flex items-center gap-2">
              <Link
                href="/"
                className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
              >
                Home
              </Link>
              <Link
                href="/inventory"
                className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
              >
                Inventory
              </Link>
              <Link
                href="/shopping"
                className="rounded px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white"
              >
                Shopping
              </Link>
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
