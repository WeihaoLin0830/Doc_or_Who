/** @type {import('next').NextConfig} */
const nextConfig = {
    // Proxy API requests to the FastAPI backend during development
    async rewrites() {
        const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        return [
            {
                source: "/api/:path*",
                destination: `${backendUrl}/api/:path*`,
            },
        ];
    },
};

export default nextConfig;
