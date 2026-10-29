{{- define "incident-triage-agent.name" -}}
incident-triage-agent
{{- end }}

{{- define "incident-triage-agent.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "incident-triage-agent.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "incident-triage-agent.labels" -}}
app.kubernetes.io/name: {{ include "incident-triage-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
