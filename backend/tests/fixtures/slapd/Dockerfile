# Test-only OpenLDAP server for the AD/LDAP federation test (WP-040, D-130). Debian's slapd
# (OpenLDAP Public Licence) on debian-slim pinned by digest. Never shipped, never pushed: the
# test builds it locally. It runs as the unprivileged openldap user on port 1389; its admin
# password comes from the test at run time, so the image holds no secret.
FROM debian:12-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils \
    && rm -rf /var/lib/apt/lists/* /etc/ldap/slapd.d/* /var/lib/ldap/* \
    && mkdir -p /opt/sx/state \
    && chown openldap:openldap /opt/sx/state
COPY start.sh seed.ldif /opt/sx/
USER openldap
EXPOSE 1389
HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
    CMD ldapsearch -x -H ldap://localhost:1389 -b "" -s base >/dev/null 2>&1 || exit 1
ENTRYPOINT ["/bin/sh", "/opt/sx/start.sh"]
