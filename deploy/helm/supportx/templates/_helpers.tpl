{{/* Names: every object is "<release>-<component>" (release "supportx" -> "supportx-api"). */}}
{{- define "supportx.name" -}}
{{- printf "%s-%s" .root.Release.Name .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "supportx.labels" -}}
app.kubernetes.io/name: supportx
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: supportx
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
{{- end -}}

{{- define "supportx.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Fail early on settings every profile needs. */}}
{{- define "supportx.validate" -}}
{{- /* The dev-only quick sign-in (D-151) is for the local Compose stack: never in a cluster. */}}
{{- if hasKey .Values "devQuickSignIn" }}
{{- fail "devQuickSignIn is the local dev stack's quick sign-in (D-151): it is never set in the chart" }}
{{- end }}
{{- range $name := list "SUPPORTX_DEV_QUICK_SIGN_IN" "SUPPORTX_SHOWCASE_PASSWORD" "SUPPORTX_SHOWCASE_TOTP_KEY" }}
{{- if hasKey $.Values.app.extraEnv $name }}
{{- fail (printf "%s is for the local dev stack only (D-151): never set it in the chart" $name) }}
{{- end }}
{{- end }}
{{- if and .Values.valkeyHa.enabled .Values.valkey.enabled }}
{{- fail "valkeyHa (HA, ADR-038) replaces the bundled valkey chart: set valkey.enabled=false" }}
{{- end }}
{{- if and (gt (int .Values.centrifugo.replicas) 1) (not .Values.valkeyHa.enabled) }}
{{- fail "centrifugo.replicas above 1 needs the Valkey engine: turn on valkeyHa (values-ha.yaml)" }}
{{- end }}
{{- if not .Values.publicUrl -}}
{{- fail "publicUrl is required (the browser's origin, e.g. https://supportx.example.com)" -}}
{{- end -}}
{{- if not (regexMatch "^https?://[^/]+$" .Values.publicUrl) -}}
{{- fail "publicUrl must be scheme://host[:port] with no path or trailing slash" -}}
{{- end -}}
{{- if not (has .Values.routing.mode (list "gateway" "ingress" "none")) -}}
{{- fail "routing.mode must be gateway, ingress or none" -}}
{{- end -}}
{{- if not (has .Values.postgresql.mode (list "cnpg" "external")) -}}
{{- fail "postgresql.mode must be cnpg or external" -}}
{{- end -}}
{{- end -}}

{{/* Image reference for our own images: registry override, tag or digest. */}}
{{- define "supportx.image" -}}
{{- $img := index .root.Values.images .name -}}
{{- $repo := $img.repository -}}
{{- if .root.Values.images.registry -}}
{{- $repo = printf "%s/%s" .root.Values.images.registry (regexReplaceAll "^[^/]+\\.[^/]+/" $repo "") -}}
{{- end -}}
{{- if $img.digest -}}
{{- printf "%s@%s" $repo $img.digest -}}
{{- else -}}
{{- printf "%s:%s" $repo (default .root.Chart.AppVersion $img.tag) -}}
{{- end -}}
{{- end -}}

{{/* Third-party image with the registry override applied. */}}
{{- define "supportx.thirdPartyImage" -}}
{{- if .root.Values.images.registry -}}
{{- printf "%s/%s" .root.Values.images.registry (regexReplaceAll "^[^/]+\\.[^/]+/" .image "") -}}
{{- else -}}
{{- .image -}}
{{- end -}}
{{- end -}}

{{- define "supportx.pullSecrets" -}}
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{/* Database hosts (CNPG services or external). */}}
{{- define "supportx.dbHost" -}}
{{- if eq .Values.postgresql.mode "cnpg" -}}
{{- printf "%s-pg-rw" .Release.Name -}}
{{- else -}}
{{- required "postgresql.external.host is required" .Values.postgresql.external.host -}}
{{- end -}}
{{- end -}}

{{- define "supportx.dbPoolerHost" -}}
{{- if eq .Values.postgresql.mode "cnpg" -}}
{{- printf "%s-pg-pooler" .Release.Name -}}
{{- else -}}
{{- default .Values.postgresql.external.host .Values.postgresql.external.poolerHost -}}
{{- end -}}
{{- end -}}

{{- define "supportx.dbPort" -}}
{{- if eq .Values.postgresql.mode "cnpg" -}}5432{{- else -}}{{ .Values.postgresql.external.port }}{{- end -}}
{{- end -}}

{{/* The migrate Job of this revision: pods of this revision wait for it (tooling/wait_for_job). */}}
{{- define "supportx.migrateJob" -}}
{{- printf "%s-migrate-%d" .Release.Name (int .Release.Revision) -}}
{{- end -}}

{{/* Restricted Pod Security Standard for our own pods. */}}
{{- define "supportx.podSecurityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .Values.podSecurity.runAsUser }}
  runAsGroup: {{ .Values.podSecurity.runAsUser }}
  fsGroup: {{ .Values.podSecurity.fsGroup }}
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "supportx.containerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end -}}

{{/* Secret-backed environment: role passwords first, so URLs below can use $(VAR). */}}
{{- define "supportx.secretEnv" -}}
- name: SUPPORTX_SECRET_APP_DB_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: app-db-password}}
- name: SUPPORTX_SECRET_VALKEY_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: valkey-password}}
- name: SUPPORTX_SECRET_NATS_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: nats-password}}
- name: SUPPORTX_DATABASE_URL
  value: "postgresql://supportx_app:$(SUPPORTX_SECRET_APP_DB_PASSWORD)@{{ include "supportx.dbPoolerHost" . }}:{{ include "supportx.dbPort" . }}/{{ .Values.postgresql.database }}"
- name: SUPPORTX_VALKEY_URL
  value: "valkey://:$(SUPPORTX_SECRET_VALKEY_PASSWORD)@{{ .Release.Name }}-valkey:6379/0"
- name: SUPPORTX_NATS_URL
  value: "nats://supportx:$(SUPPORTX_SECRET_NATS_PASSWORD)@{{ .Release.Name }}-nats:4222"
- name: SUPPORTX_SESSION_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: session-secret}}
{{- include "supportx.sessionKeysEnv" . }}
- name: SUPPORTX_OIDC_CONSOLE_CLIENT_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: oidc-console-secret}}
- name: SUPPORTX_OIDC_PORTAL_CLIENT_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: oidc-portal-secret}}
- name: SUPPORTX_KEYCLOAK_IDENTITY_CLIENT_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: keycloak-identity-secret}}
- name: SUPPORTX_MULTI_TENANT
  value: {{ .Values.multiTenant | quote }}
{{- if .Values.mail.smtpHost }}
- {name: SUPPORTX_MAIL_SMTP_HOST, value: {{ .Values.mail.smtpHost | quote }}}
- {name: SUPPORTX_MAIL_SMTP_PORT, value: {{ .Values.mail.smtpPort | quote }}}
- {name: SUPPORTX_MAIL_SMTP_SECURITY, value: {{ .Values.mail.smtpSecurity | quote }}}
- {name: SUPPORTX_MAIL_SMTP_USERNAME, value: {{ .Values.mail.smtpUsername | quote }}}
- {name: SUPPORTX_MAIL_FROM_ADDRESS, value: {{ .Values.mail.fromAddress | quote }}}
- {name: SUPPORTX_MAIL_FROM_NAME, value: {{ .Values.mail.fromName | quote }}}
- name: SUPPORTX_MAIL_SMTP_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: mail-smtp-password, optional: true}}
{{- end }}
- name: SUPPORTX_CENTRIFUGO_API_KEY
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: centrifugo-api-key}}
- name: SUPPORTX_CENTRIFUGO_TOKEN_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: centrifugo-token-secret}}
- name: SUPPORTX_OBJECT_STORAGE_ACCESS_KEY
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: s3-access-key}}
- name: SUPPORTX_OBJECT_STORAGE_SECRET_KEY
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: s3-secret-key}}
{{- end -}}

{{/* Sign-in key ring (D-162, ADR-048): each listed secret from the app Secret as its own
variable, then SUPPORTX_SESSION_KEYS as JSON naming them with $(VAR), so no secret is ever in
the chart's values or rendered manifests. Nothing when `secrets.sessionKeys` is empty. */}}
{{- define "supportx.sessionKeysEnv" -}}
{{- $root := . -}}
{{- $entries := list -}}
{{- range $i, $k := .Values.secrets.sessionKeys }}
{{- if not (regexMatch "^[a-z0-9_-]{1,32}$" (toString $k.id)) }}
{{- fail (printf "secrets.sessionKeys[%d].id must be 1 to 32 of a-z, 0-9, '_' and '-'" $i) }}
{{- end }}
{{- if $k.key }}
- name: SUPPORTX_SECRET_SESSION_KEY_{{ $i }}
  valueFrom: {secretKeyRef: {name: {{ $root.Values.secrets.app }}, key: {{ $k.key }}}}
{{- $entries = append $entries (printf "{\"id\":\"%s\",\"secret\":\"$(SUPPORTX_SECRET_SESSION_KEY_%d)\"}" $k.id $i) }}
{{- else if eq (toString $k.id) "legacy" }}
{{- $entries = append $entries "{\"id\":\"legacy\"}" }}
{{- else }}
{{- fail (printf "secrets.sessionKeys[%d] needs `key` (only legacy may leave it out)" $i) }}
{{- end }}
{{- end }}
{{- if $entries }}
- name: SUPPORTX_SESSION_KEYS
  value: {{ printf "[%s]" (join "," $entries) | quote }}
{{- end }}
{{- end -}}

{{/* Files key ring (WP-022, ADR-028): the API (uploads) and the consumers worker (scanning) only.
Optional: an installation without it answers 503 files_not_configured, never stores plaintext. */}}
{{- define "supportx.filesEnv" -}}
- name: SUPPORTX_FILES_KEYS
  valueFrom: {secretKeyRef: {name: {{ .Values.secrets.app }}, key: files-keys, optional: true}}
{{- end -}}

{{/* Common pod parts for the API and workers. */}}
{{- define "supportx.backendEnvFrom" -}}
envFrom:
  - configMapRef:
      name: {{ .Release.Name }}-env
{{- end -}}

{{- define "supportx.waitForMigrate" -}}
- name: wait-for-migrate
  image: {{ include "supportx.image" (dict "root" . "name" "backend") }}
  imagePullPolicy: {{ .Values.images.backend.pullPolicy }}
  command: ["python", "-m", "tooling.wait_for_job"]
  env:
    - name: SUPPORTX_MIGRATE_JOB
      value: {{ include "supportx.migrateJob" . }}
    - name: SUPPORTX_WAIT_TIMEOUT_SECONDS
      value: {{ .Values.migrate.waitTimeoutSeconds | quote }}
    - name: POD_NAMESPACE
      valueFrom: {fieldRef: {fieldPath: metadata.namespace}}
  {{- include "supportx.containerSecurityContext" . | nindent 2 }}
  resources:
    requests: {cpu: 10m, memory: 64Mi}
    limits: {cpu: 200m, memory: 128Mi}
{{- end -}}

{{- define "supportx.metricsAnnotations" -}}
{{- if not (include "supportx.podMonitorsEnabled" .) }}
prometheus.io/scrape: "true"
prometheus.io/port: "9464"
prometheus.io/path: /metrics
{{- end }}
{{- end -}}

{{- define "supportx.podMonitorsEnabled" -}}
{{- $mode := toString .Values.metrics.podMonitors -}}
{{- if or (eq $mode "true") (and (eq $mode "auto") (.Capabilities.APIVersions.Has "monitoring.coreos.com/v1/PodMonitor")) -}}
true
{{- end -}}
{{- end -}}

{{/* Checksum of the settings so pods restart when they change, plus podAnnotations. */}}
{{- define "supportx.configChecksum" -}}
checksum/env: {{ include (print $.Template.BasePath "/configmap-env.yaml") . | sha256sum }}
{{- with .Values.podAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
High availability (WP-014b): copies of one component spread over nodes. Nothing when `ha.enabled`
is off, so a single-node install schedules as before. "hard" never puts two copies on one node
(a node lost takes at most one); "soft" prefers not to, for small test clusters.
*/}}
{{- define "supportx.scheduling" -}}
{{- if .root.Values.ha.enabled }}
affinity:
  podAntiAffinity:
    {{- if eq .root.Values.ha.antiAffinity "hard" }}
    requiredDuringSchedulingIgnoredDuringExecution:
      - topologyKey: kubernetes.io/hostname
        labelSelector:
          matchLabels:
            {{- include "supportx.selector" . | nindent 12 }}
    {{- else }}
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels:
              {{- include "supportx.selector" . | nindent 14 }}
    {{- end }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "supportx.selector" . | nindent 8 }}
{{- end }}
{{- end -}}

{{/* Temporal's frontend: the configured address, else this release's bundled one, else empty. */}}
{{- define "supportx.temporalAddress" -}}
{{- if .Values.temporal.address -}}
{{- .Values.temporal.address -}}
{{- else if .Values.temporal.bundled.enabled -}}
{{- printf "%s-temporal-frontend:7233" .Release.Name -}}
{{- end -}}
{{- end -}}

{{/* The bundled Temporal's schema Job of this revision (the server waits for it). */}}
{{- define "supportx.temporalSchemaJob" -}}
{{- printf "%s-temporal-schema-%d" .Release.Name (int .Release.Revision) -}}
{{- end -}}
