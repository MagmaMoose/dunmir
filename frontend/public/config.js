// Default runtime config stub.
// - Local dev & Cloudflare Pages: this file is served as-is (empty config),
//   so the app falls back to VITE_API_BASE or the built-in default.
// - Docker: docker-entrypoint.sh overwrites this with the value of API_BASE.
window.__CONFIG__ = window.__CONFIG__ || {};
