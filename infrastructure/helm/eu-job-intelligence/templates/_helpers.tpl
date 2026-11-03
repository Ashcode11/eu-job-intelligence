{{- define "eujobs.fullname" -}}{{ .Release.Name | trunc 40 | trimSuffix "-" }}{{- end -}}

{{- define "eujobs.labels" -}}
app.kubernetes.io/name: eu-job-intelligence
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "eujobs.selector" -}}
app.kubernetes.io/name: eu-job-intelligence
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "eujobs.secretName" -}}
{{- default (printf "%s-secrets" (include "eujobs.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "eujobs.pythonImage" -}}
{{ .Values.image.python.repository }}:{{ .Values.image.python.tag }}
{{- end -}}

{{/* Environment shared by every Python container. */}}
{{- define "eujobs.pythonEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "eujobs.fullname" . }}-config
env:
  - name: DATABASE_URL
    valueFrom: { secretKeyRef: { name: {{ include "eujobs.secretName" . }}, key: DATABASE_URL } }
  - name: REDIS_URL
    valueFrom: { secretKeyRef: { name: {{ include "eujobs.secretName" . }}, key: REDIS_URL } }
  - name: API_KEYS
    valueFrom: { secretKeyRef: { name: {{ include "eujobs.secretName" . }}, key: API_KEYS } }
  - name: ADZUNA_APP_ID
    valueFrom: { secretKeyRef: { name: {{ include "eujobs.secretName" . }}, key: ADZUNA_APP_ID, optional: true } }
  - name: ADZUNA_APP_KEY
    valueFrom: { secretKeyRef: { name: {{ include "eujobs.secretName" . }}, key: ADZUNA_APP_KEY, optional: true } }
{{- end -}}

{{/* initContainer: wait for the database (and the migrated schema). */}}
{{- define "eujobs.waitForDb" -}}
- name: wait-for-db
  image: {{ include "eujobs.pythonImage" . }}
  imagePullPolicy: {{ .Values.image.python.pullPolicy }}
  command: ["python", "-m", "scripts.wait_for_db", "--migrations", "--timeout", "600"]
  {{- include "eujobs.pythonEnv" . | nindent 2 }}
  resources:
    requests: { cpu: 10m, memory: 64Mi }
    limits: { cpu: 250m, memory: 192Mi }
  securityContext:
    allowPrivilegeEscalation: false
{{- end -}}

{{- define "eujobs.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 999
  runAsGroup: 999
  fsGroup: 999
{{- end -}}
