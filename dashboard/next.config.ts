import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Allow server components to fetch from Supabase directly
  experimental: {
    serverComponentsExternalPackages: [],
  },

  // Environment variables that should be available on the client side
  // (prefixed with NEXT_PUBLIC_) are automatically exposed.
  // Server-only variables are accessed via process.env in Server Components.

  // Strict mode for catching React issues early
  reactStrictMode: true,

  // Image optimisation — allow Supabase storage domain if you store logos there
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '*.supabase.co',
        pathname: '/storage/v1/object/public/**',
      },
    ],
  },
}

export default nextConfig
