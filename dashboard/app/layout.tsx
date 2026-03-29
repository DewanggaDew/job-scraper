import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import Link from 'next/link'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Job Scraper Dashboard',
  description: 'Personal job tracking dashboard — Dewangga Dewata Indera',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-50 min-h-screen`}>
        {/* ── Top Navigation ── */}
        <nav className="bg-white border-b border-gray-200 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-14">

              {/* Brand */}
              <Link href="/" className="flex items-center gap-2 font-bold text-gray-900 text-lg hover:text-green-700 transition-colors">
                <span className="text-2xl">🎯</span>
                <span className="hidden sm:inline">Job Scraper</span>
              </Link>

              {/* Nav links */}
              <div className="flex items-center gap-1">
                <NavLink href="/" label="📋 Jobs" />
                <NavLink href="/tracker" label="📊 Tracker" />
              </div>

            </div>
          </div>
        </nav>

        {/* ── Page content ── */}
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </main>

        {/* ── Footer ── */}
        <footer className="mt-12 border-t border-gray-200 bg-white">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 text-center text-xs text-gray-400">
            Job Scraper · Runs on GitHub Actions every 4 hours · Built for Dewangga Dewata Indera
          </div>
        </footer>
      </body>
    </html>
  )
}

function NavLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="px-3 py-2 rounded-md text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
    >
      {label}
    </Link>
  )
}
