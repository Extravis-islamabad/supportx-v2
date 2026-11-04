#!/bin/sh
# Build slapd's configuration and data as the openldap user, from the admin password the test
# passes (stored only as its hash), then run in the foreground on port 1389.
set -eu
: "${LDAP_ADMIN_PASSWORD:?the test passes it}"
STATE=/opt/sx/state
mkdir -p "$STATE/slapd.d" "$STATE/data" "$STATE/run"
hash=$(slappasswd -s "$LDAP_ADMIN_PASSWORD")
cat > "$STATE/config.ldif" <<LDIF
dn: cn=config
objectClass: olcGlobal
cn: config
olcPidFile: $STATE/run/slapd.pid

dn: cn=module{0},cn=config
objectClass: olcModuleList
cn: module{0}
olcModulePath: /usr/lib/ldap
olcModuleLoad: back_mdb

dn: cn=schema,cn=config
objectClass: olcSchemaConfig
cn: schema

include: file:///etc/ldap/schema/core.ldif
include: file:///etc/ldap/schema/cosine.ldif
include: file:///etc/ldap/schema/nis.ldif
include: file:///etc/ldap/schema/inetorgperson.ldif

dn: olcDatabase={-1}frontend,cn=config
objectClass: olcDatabaseConfig
objectClass: olcFrontendConfig
olcDatabase: {-1}frontend

dn: olcDatabase={0}config,cn=config
objectClass: olcDatabaseConfig
olcDatabase: {0}config
olcAccess: {0}to * by * none

dn: olcDatabase={1}mdb,cn=config
objectClass: olcDatabaseConfig
objectClass: olcMdbConfig
olcDatabase: {1}mdb
olcDbDirectory: $STATE/data
olcSuffix: dc=example,dc=org
olcRootDN: cn=admin,dc=example,dc=org
olcRootPW: $hash
olcAccess: {0}to * by self write by anonymous auth by * read
LDIF
slapadd -n 0 -F "$STATE/slapd.d" -l "$STATE/config.ldif" >/dev/null
slapadd -n 1 -F "$STATE/slapd.d" -l /opt/sx/seed.ldif >/dev/null
exec slapd -d 0 -h "ldap://:1389/" -F "$STATE/slapd.d"
