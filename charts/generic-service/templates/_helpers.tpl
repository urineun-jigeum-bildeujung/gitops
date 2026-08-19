{{/*
공통 라벨 정의 — Deployment/Rollout/Service/NetworkPolicy가 전부 이 헬퍼로만 라벨을 만들게 해서
셀렉터 불일치(라벨 오타로 NetworkPolicy가 무효화되는 등)를 원천 방지하기 위한 용도.
*/}}
{{- define "generic-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "generic-service.labels" -}}
app.kubernetes.io/name: {{ include "generic-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "generic-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "generic-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
