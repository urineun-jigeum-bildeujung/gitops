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

{{/*
mTLS 활성화 시 Deployment/Rollout에 공통으로 주입하는 env — 한 곳에서만 관리해서
deployment.yaml/rollout.yaml 둘 다 수정하는 실수(하나만 고치고 하나는 빠뜨리는 것)를
방지한다.

- SERVER_PORT를 8443(mTLS 전용)으로 바꾸고, 기존 service.targetPort(8080)는
  MANAGEMENT_SERVER_PORT로 돌려서 헬스체크/Prometheus 스크랩은 그대로 평문 유지.
- SPRING_SSL_BUNDLE_PEM_* 는 certificate.yaml이 만든 Secret을 파일로 마운트한 경로를 가리킴.
*/}}
{{- define "generic-service.mtlsEnv" -}}
{{- if .Values.mtls.enabled }}
- name: INTERNAL_MTLS_ENABLED
  value: "true"
- name: SERVER_PORT
  value: "8443"
- name: MANAGEMENT_SERVER_PORT
  value: {{ .Values.service.targetPort | quote }}
- name: SERVER_SSL_ENABLED
  value: "true"
- name: SERVER_SSL_CLIENT_AUTH
  value: "need"
- name: SERVER_SSL_BUNDLE
  value: "internal-mtls"
- name: SPRING_SSL_BUNDLE_PEM_INTERNAL_MTLS_KEYSTORE_CERTIFICATE
  value: "file:/etc/mtls/tls.crt"
- name: SPRING_SSL_BUNDLE_PEM_INTERNAL_MTLS_KEYSTORE_PRIVATE_KEY
  value: "file:/etc/mtls/tls.key"
- name: SPRING_SSL_BUNDLE_PEM_INTERNAL_MTLS_TRUSTSTORE_CERTIFICATE
  value: "file:/etc/mtls/ca.crt"
{{- end }}
{{- end -}}
