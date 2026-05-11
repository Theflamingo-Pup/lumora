# =============================================================
# Lumora website - Step 1
# This Dockerfile packages the static site into a container.
# =============================================================

# FROM = "start from this base image"
# nginx:alpine is a tiny (~25MB) web server. We didn't have to
# install nginx ourselves - someone already built this image
# and put it on Docker Hub (the public image registry).
FROM nginx:alpine

# COPY = "copy files from my project into the image"
# Left side  = path on YOUR computer (relative to this Dockerfile)
# Right side = path INSIDE the image
# /usr/share/nginx/html is where nginx looks for files to serve.
COPY index.html /usr/share/nginx/html/index.html
COPY images/    /usr/share/nginx/html/images/

# EXPOSE = "this container will listen on port 80"
# This is documentation only - it doesn't actually open the port.
# The real port opening happens at "docker run" time with -p.
EXPOSE 80

# No CMD needed - the nginx base image already knows how to start nginx.
