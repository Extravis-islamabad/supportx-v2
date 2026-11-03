#!/bin/sh
# Configure slapd for dc=example,dc=org with the admin password the test passes, load the
# people, then run in the foreground.
set -eu
: "${LDAP_ADMIN_PASSWORD:?the test passes it}"
debconf-set-selections <<SEL
slapd slapd/password1 password ${LDAP_ADMIN_PASSWORD}
slapd slapd/password2 password ${LDAP_ADMIN_PASSWORD}
slapd slapd/domain string example.org
slapd shared/organization string Example
slapd slapd/no_configuration boolean false
slapd slapd/purge_database boolean true
slapd slapd/move_old_database boolean true
SEL
dpkg-reconfigure -f noninteractive slapd >/dev/null 2>&1
slapd -h "ldap:///" -u openldap -g openldap
for _ in $(seq 1 50); do
  ldapsearch -x -H ldap://localhost -b dc=example,dc=org -s base >/dev/null 2>&1 && break
  sleep 0.2
done
ldapadd -x -H ldap://localhost -D cn=admin,dc=example,dc=org -w "${LDAP_ADMIN_PASSWORD}" \
  -f /opt/sx/seed.ldif >/dev/null
kill "$(cat /var/run/slapd/slapd.pid)"
sleep 1
exec slapd -d 0 -h "ldap:///" -u openldap -g openldap
