# Test-only OpenLDAP server for the AD/LDAP federation test (WP-040, D-130). Debian's slapd
# (OpenLDAP Public Licence) on debian-slim pinned by digest. Never shipped, never pushed: the
# test builds it locally. Its admin password comes from the test at run time, so the image
# holds no secret.
FROM debian:12-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils \
    && rm -rf /var/lib/apt/lists/*
COPY start.sh seed.ldif /opt/sx/
EXPOSE 389
ENTRYPOINT ["/bin/sh", "/opt/sx/start.sh"]
