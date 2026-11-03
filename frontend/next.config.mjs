/** @type {import('next').NextConfig} */
// The browser talks to the API through /backend/* on the same origin, so no CORS is needed.
// The API key is entered by the user and sent by the browser; the frontend holds no secret.
const backend = process.env.BACKEND_INTERNAL_URL || "http://localhost:8081";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${backend}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
