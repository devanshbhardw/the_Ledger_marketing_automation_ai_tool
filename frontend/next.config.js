const path = require('path');

const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    // OAuth login/callback hit the backend directly (same forwarding idea as
    // app/api/ga/[...path]/route.ts, but as a rewrite so provider redirects
    // land on the frontend origin registered in the OAuth apps).
    return [
      {
        source: '/oauth/:path*',
        destination: `${BACKEND}/oauth/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
