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
자동 확장 모드. 기존 autoscaling.enabled 사용자는 동작을 유지하되 신규 선언은
mode를 명시해서 HPA와 KEDA가 동시에 같은 워크로드를 제어하지 못하게 한다.
*/}}
{{- define "generic-service.autoscalingMode" -}}
{{- $mode := default "" .Values.autoscaling.mode -}}
{{- if eq $mode "" -}}
{{- if .Values.autoscaling.enabled -}}hpa{{- else -}}disabled{{- end -}}
{{- else if or (eq $mode "disabled") (eq $mode "hpa") (eq $mode "keda") -}}
{{- $mode -}}
{{- else -}}
{{- fail "autoscaling.mode must be one of: disabled, hpa, keda" -}}
{{- end -}}
{{- end -}}

{{- define "generic-service.scaleTargetApiVersion" -}}
{{- if or .Values.canary.enabled .Values.blueGreen.enabled -}}argoproj.io/v1alpha1{{- else -}}apps/v1{{- end -}}
{{- end -}}

{{- define "generic-service.scaleTargetKind" -}}
{{- if or .Values.canary.enabled .Values.blueGreen.enabled -}}Rollout{{- else -}}Deployment{{- end -}}
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
{{- if .Values.mtls.server.enabled }}
- name: SERVER_PORT
  value: "8443"
- name: MANAGEMENT_SERVER_PORT
  value: {{ .Values.service.targetPort | quote }}
- name: SERVER_SSL_ENABLED
  value: "true"
# management.server.ssl이 명시적으로 안 꺼져 있으면 server.ssl.enabled=true를
# 그대로 물려받아서, 포트를 8080으로 분리해놨어도 관리 포트(actuator/prometheus
# 포함)까지 TLS를 요구해버린다 — Prometheus는 평문 HTTP로 스크랩하는데 앱이
# "This combination of host and port requires TLS." 400을 계속 뱉어서 모든
# ServiceDown/TargetDown 알림이 실제로는 이게 원인이었다(2026-09-29 실제
# 파드에 port-forward로 재현·확인). 명시적으로 false를 줘서 관리 포트만 평문 유지.
- name: MANAGEMENT_SERVER_SSL_ENABLED
  value: "false"
- name: SERVER_SSL_CLIENT_AUTH
  value: "need"
- name: SERVER_SSL_BUNDLE
  value: "internalmtls"
{{- end }}
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

{{/*
JVM 힙/Metaspace 상한을 명시하는 공통 env. 모든 서비스에 무조건 주입한다(mTLS/egress처럼
조건부 아님).

기존엔 베이스 이미지 기본값(-XX:MaxRAMPercentage=75.0, Metaspace 무제한)에 그대로 맡겨져
있었는데, 실측(2026-09-29, Prometheus jvm_memory_used/max_bytes) 결과 7개 서비스 전부:
- 힙 실사용량은 76~197Mi인데 상한(75%)은 371~384Mi로 잡혀 있어서, 안 쓰는 힙 공간이
  200Mi 넘게 낭비되고 있었음 — 이 공간을 Metaspace/스레드/네이티브 메모리가 못 씀.
- Metaspace 실사용량은 132~147Mi인데 상한이 아예 없어서(-1) 계속 커질 수 있는 구조.
그 결과 order-service는 실제로 512Mi 컨테이너 한도에서 3회 OOMKilled(gitops#108).

컨테이너 memory limit은 512Mi→768Mi로 같이 올렸다(gitops-value 레포 별도 PR).
그 기준으로 힙 상한 384Mi(768Mi의 50%, 실사용 최대 197Mi 대비 여유 있음),
MaxMetaspaceSize=200m(실사용 최대치 147Mi보다 크게, 무제한으로는 안 커지게).

**-XX:MaxRAMPercentage 대신 -Xmx를 직접 쓴다** — 처음엔 MaxRAMPercentage=50.0으로
했었는데, 배포 후 실측해보니 안 먹히고 있었다(gitops#110). 컨테이너 이미지
ENTRYPOINT 자체에 -XX:MaxRAMPercentage=75.0이 하드코딩되어 있어서, JDK_JAVA_OPTIONS로
넣은 값이 커맨드라인 앞에 붙고 이미지 쪽 값이 뒤에 오는 구조라 JVM이 "나중에 나온
값"인 75.0을 채택해버렸다(같은 -XX 플래그 중복 시 나중 값이 이김). -Xmx는 이미지가
쓰는 -XX:MaxRAMPercentage와 다른 플래그라 "나중 값이 이긴다" 경쟁 자체가 없고,
JVM 에르고노믹스 상 -Xmx가 명시되면 MaxRAMPercentage 기반 계산 자체가 아예
스킵되므로 순서 무관하게 확실히 적용된다(컨테이너 안에서
`java -Xmx256m -XX:MaxRAMPercentage=75.0 -XX:+PrintFlagsFinal`로 직접 검증,
MaxHeapSize={command line} 소스로 -Xmx 값이 이기는 것 확인). Metaspace는 이미지
쪽에 경쟁하는 플래그가 없어서 애초부터 정상 적용되고 있었음.

기존 externalEgressEnv가 JAVA_TOOL_OPTIONS를 프록시 설정용으로 이미 쓰고 있어서(java
런타임), 같은 이름의 env를 여기서 또 선언하면 K8s가 나중 값으로 덮어써서 프록시 설정이
날아간다. JDK_JAVA_OPTIONS는 JDK 9+에서 지원하는 별도 환경변수로, JAVA_TOOL_OPTIONS와
독립적으로 같이 적용되므로 충돌 없이 추가할 수 있다.

mtls.enabled로 게이팅한다 — 위 실측은 mTLS 활성화된 7개 Java(Spring Boot) 서비스만
대상으로 했고, 이 값이 web(node)/nutrition/recommendation처럼 실측 안 한 다른 런타임
서비스한테도 맞는지는 확인 안 됐음. 이 서비스들은 mtls.enabled=false라서 자동으로
제외된다.
*/}}
{{- define "generic-service.jvmMemoryEnv" -}}
{{- if .Values.mtls.enabled }}
- name: JDK_JAVA_OPTIONS
  value: "-Xmx384m -XX:MaxMetaspaceSize=200m"
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
- name: HTTP_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: HTTPS_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: NO_PROXY
  value: "localhost,127.0.0.1,::1,.svc,.svc.cluster.local,169.254.170.23"
{{- else if eq .Values.externalEgress.runtime "python" }}
# requests/urllib3/boto3는 플래그 없이도 HTTP_PROXY/HTTPS_PROXY를 기본으로 읽는다
# (Node의 NODE_OPTIONS=--use-env-proxy 같은 opt-in 플래그가 필요 없음).
- name: HTTP_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: HTTPS_PROXY
  value: {{ printf "http://%s:3128" $proxyHost | quote }}
- name: NO_PROXY
  value: "localhost,127.0.0.1,::1,.svc,.svc.cluster.local,169.254.170.23"
{{- else }}
{{- fail "externalEgress.runtime must be java, node, or python" }}
{{- end }}
{{- end }}
{{- end -}}
