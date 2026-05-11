# =============================================================
# Lumora website - production-ready
# =============================================================
# nginx + our HTML + a custom nginx config that proxies API
# calls to the in-cluster API service.
# =============================================================
FROM nginx:alpine

# Replace nginx's default config with ours (the one that proxies /api/*)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static site files
COPY index.html /usr/share/nginx/html/index.html
COPY images/    /usr/share/nginx/html/images/

EXPOSE 80
