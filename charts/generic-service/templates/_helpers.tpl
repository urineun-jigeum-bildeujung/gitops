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

번들 이름은 "internalmtls"(하이픈 없음)로 고정한다 — spring.ssl.bundle.pem.<이름>은
Map<String,...> 동적 키라, 환경변수(SystemEnvironmentPropertySource)가 "_"를 "."로
변환할 때 "internal-mtls"의 하이픈이 두 단계 경로("internal" + "mtls")로 잘못
쪼개져서 NoSuchSslBundleException이 남(2026-09-18 실제 Pod 크래시로 발견). 고정된
스키마 프로퍼티(예: context-path)는 relaxed binding이 하이픈을 복원해주지만, 맵의
동적 키는 그 복원이 안 되는 Spring Boot의 알려진 한계라 아예 구분자 없는 이름으로 우회.
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
  value: "internalmtls"
- name: SPRING_SSL_BUNDLE_PEM_INTERNALMTLS_KEYSTORE_CERTIFICATE
  value: "file:/etc/mtls/tls.crt"
- name: SPRING_SSL_BUNDLE_PEM_INTERNALMTLS_KEYSTORE_PRIVATE_KEY
  value: "file:/etc/mtls/tls.key"
- name: SPRING_SSL_BUNDLE_PEM_INTERNALMTLS_TRUSTSTORE_CERTIFICATE
  value: "file:/etc/mtls/ca.crt"
{{- end }}
{{- end -}}

{{/*
Kafka SASL/SCRAM-SHA-512 활성화 시 주입하는 공통 env.
platform/91-external-secrets-config가 kafka 네임스페이스의 KafkaUser 자격증명을
같은 이름(kafka-credentials)의 로컬 Secret으로 미리 복사해뒀다고 가정한다 - Secret
이름/키가 여기와 정확히 일치해야 함. 트러스트스토어(ca.crt)는 kafka-clients가
PEM 포맷을 파일 경로로 직접 지원해서(ssl.truststore.type=PEM) 별도 변환 불필요.

이 env를 실제로 읽어서 Kafka Producer/Consumer 설정에 반영하는 건 각 서비스의
KafkaProducerConfig/KafkaConsumerConfig(sever 레포) 코드 몫 - 여기선 배선만 한다.
*/}}
{{- define "generic-service.kafkaSaslEnv" -}}
{{- if .Values.kafka.sasl.enabled }}
- name: SPRING_KAFKA_SECURITY_PROTOCOL
  value: "SASL_SSL"
- name: SPRING_KAFKA_PROPERTIES_SASL_MECHANISM
  value: "SCRAM-SHA-512"
- name: SPRING_KAFKA_PROPERTIES_SASL_JAAS_CONFIG
  valueFrom:
    secretKeyRef:
      name: kafka-credentials
      key: SPRING_KAFKA_PROPERTIES_SASL_JAAS_CONFIG
- name: SPRING_KAFKA_SSL_TRUST_STORE_LOCATION
  value: "/etc/kafka-tls/ca.crt"
- name: SPRING_KAFKA_SSL_TRUST_STORE_TYPE
  value: "PEM"
{{- end }}
{{- end -}}

{{- define "generic-service.externalEgressEnv" -}}
{{- if .Values.externalEgress.enabled }}
{{- $proxyHost := printf "%s-egress.%s.svc.cluster.local" (include "generic-service.name" .) .Release.Namespace }}
{{- if eq .Values.externalEgress.runtime "java" }}
- name: JAVA_TOOL_OPTIONS
  value: {{ printf "-Dhttp.proxyHost=%s -Dhttp.proxyPort=3128 -Dhttps.proxyHost=%s -Dhttps.proxyPort=3128 -Dhttp.nonProxyHosts=localhost|127.*|[::1]|*.svc|*.svc.cluster.local|169.254.170.23" $proxyHost $proxyHost | quote }}
{{- else if eq .Values.externalEgress.runtime "node" }}
- name: NODE_OPTIONS
  value: "--use-env-proxy"
- name: NODE_USE_ENV_PROXY
  value: "1"
- name: HTTP_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: HTTPS_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: NO_PROXY
  value: "localhost,127.0.0.1,::1,.svc,.svc.cluster.local,169.254.170.23"
{{- else }}
{{- fail "externalEgress.runtime must be java or node" }}
{{- end }}
{{- end }}
{{- end -}}
