# 내부 NetworkPolicy — API・DB・Redis・Kafka・관측성

## 범위와 남아 있는 제한

서비스 전용 Namespace 8개(백엔드 7개와 web)에 기본 Ingress/Egress 차단을 적용하고,
정상 서비스 Pod에 아래 예외를 허용한다. Namespace와 Pod 라벨을 함께 검사하며,
규칙의 포트는 목적지 Pod의 실제 포트다. DB/Redis/관측성의 알려진 Pod에는 Ingress만 제한한다.
Kafka는 Strimzi가 생성하는 리스너 정책 자체를 좁힌다. 플랫폼 Egress, ArgoCD, Jenkins,
kube-system, Operator 등 전체 클러스터의 기본 차단은 이번 범위가 아니다.

외부 Egress는 서비스별 HTTPS CONNECT 프록시를 거치도록 구성한다. 애플리케이션 Pod의
공인 IPv4 전체 허용 예외를 제거하고, 자기 Namespace의 전용 프록시 Pod TCP 3128만
추가 허용한다. 프록시의 수신 정책은 같은 서비스의 정확한 Pod 라벨만 허용한다.
프록시는 CoreDNS와 공인 IPv4 TCP 443만 접근할 수 있으며, Squid가 서비스별 정확한
CONNECT 호스트명을 검사한다. 공인 IPv4 전체 예외가 남는 곳은 전용 프록시뿐이다.

| 서비스 | 프록시가 허용하는 도메인 |
| --- | --- |
| auth | kauth.kakao.com, kapi.kakao.com, www.googleapis.com |
| payment | api.tosspayments.com |
| member / review | petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com |
| web | business.juso.go.kr, image.leechs.shop |
| product / order / notification | 프록시 및 직접 인터넷 예외 없음 |

member/review S3와 web CDN은 예정된 연결도 포함한 목록이다. S3 prefix는 IAM으로
분리한다. 푸시/SMS 제공자 미정 기능에는 외부 예외를 추가하지 않는다.
근거와 구현 상태는 [외부 연결 목록](external-egress-inventory.md)을 참고한다.

프록시는 서비스별 2개 replica로 배포되며 자격 증명/ServiceAccount token을 받지 않는다.
이미지는 로컬 검증한 Ubuntu Squid digest로 고정한다. CA 추가나 TLS 복호화는 하지 않으며,
클라이언트가 원격 인증서를 검증한다. 이 구성은 CONNECT 요청의 목적지 호스트명을 검사한다.
TLS 내부 SNI/HTTP Host, URL 경로, 업로드 내용을 검사하지 않는다. 허용된 외부 서비스의
악용이나 같은 목적지의 domain fronting까지 차단하는 L7 통제는 별도 범위다.
공인 ALB/내부 서비스가 대신 호출하는 간접 경로 및 hostNetwork/노드 트래픽도 별도 경계다.

Java는 JAVA_TOOL_OPTIONS의 HTTP/HTTPS proxy system property를 사용한다. 현재 auth의
기본 OAuth HTTP client와 payment의 JDK HttpClient에 적용되며, 내부 *.svc.cluster.local,
*.svc, localhost와 169.254.170.23은 직접 연결한다. 추후 HTTP client/SDK를 바꾸면서
기본 ProxySelector/system property를 무시하면 해당 client에 프록시를 직접 설정해야 한다.
직접 인터넷 fallback은 정책으로 차단되므로 이런 변경은 연결 실패로 나타난다.
Node는 NODE_OPTIONS=--use-env-proxy와 HTTP_PROXY/HTTPS_PROXY/NO_PROXY를 주입한다.
Node >=22.21.0이 필요하다. 구버전은 지원하지 않는 flag로 기동 실패하므로 배포 전에
실제 web 이미지의 Node 버전을 확인하고 필요하면 재빌드한다.
새 기능의 S3 SDK는 리전/버킷 endpoint와 proxy/bypass 설정을 함께 검증한다.
프록시 설정 변수는 차트가 관리하며 values.env에 중복 선언하면 렌더링 실패한다.

## 허용 경로

| 경로 | 목적지 Pod 포트 |
| --- | --- |
| 예정 Gateway → 백엔드 7개 | auth/member/order: 8443, 나머지: 8080 |
| auth ↔ member | 8443 |
| order → product | 8080 |
| payment → order | 8443 |
| auth/member/product/order/payment/review → PostgreSQL primary | 5432 |
| auth/order → Redis master | 6379 |
| product/order/payment → Kafka broker | 9092, 9093 |
| 서비스 8개 → CoreDNS | TCP/UDP 53 |
| 백엔드 7개 → Tempo | 4318 |
| member/review → Pod Identity 자격 증명 엔드포인트 | 169.254.170.23:80 |
| Public ALB → web / Alloy Faro | 3000 / 12347 |
| web → 예정 Gateway | 8080 |
| Prometheus → 백엔드 / DB / Alloy / Loki 계열 | 8080 / 9187 / 12345 / 3100·8080·3500 |
| Alloy → Loki gateway / Tempo | 8080 / 4317 |
| Grafana → Prometheus / Loki gateway / Tempo | 9090 / 8080 / 3200 |
| Argo Rollouts → Prometheus | 9090 |
| Internal ALB → Grafana / Prometheus | 3000 / 9090 |
| DB → 같은 CNPG cluster, CNPG Operator/Plugin → DB | 5432, 8000 |

notification의 현재 dev values에는 DB 접속 설정이 없어 DB 예외를 추가하지 않았다.
해당 서비스에 DB 기능을 연결할 때 DB 수신 및 notification Egress를 함께 갱신한다.
Redis 내부 peer, Loki gateway→single-binary, canary와 메트릭 경로도 유지한다.
Alloy는 hostPath 로그를 읽으므로 애플리케이션 Pod에 별도의 로그 수신 포트를 열지 않는다.
플랫폼 Egress는 그대로여서 Alloy의 Kubernetes API 접근, DB 백업/S3 호출도 변경하지 않는다.

Gateway는 아직 미배포다. Namespace api-gateway, name generic-service,
instance dev-api-gateway를 예정 식별자로 가정한다. 배포 시 라벨/포트가 달라지거나
Gateway 자체의 Egress를 격리한다면 대응 정책이 필요하다.
서비스 라벨은 name generic-service, instance dev-<service>이다.
order→product, payment→order URL/mTLS 구현은 담당자의 별도 수정이 필요하다.
네트워크 허용이 HTTP/TLS/인증 설정까지 정상화하는 것은 아니다.

## 실제 Service/CNI 확인 사항

2026-09-18 조회한 VPC CNI는 v1.22.4-eksbuild.3이며 standard 모드다.
AWS CNI의 Service ClusterIP 해석을 고려해 Egress peer 라벨을 실제 Service selector와
맞췄다. DB는 cluster+primary, Redis는 name+instance+master,
Kafka bootstrap은 cluster+kind+name+broker-role, API/Tempo/CoreDNS는 실제 selector를 사용한다.
ClusterIP 경유 API/DB/Redis/Kafka와 Pod IP 경유를 배포 후 각각 확인해야 한다.

Public ALB는 10.0.0.0/24, 10.0.1.0/24, Internal ALB는 10.0.4.0/22, 10.0.8.0/22를
출발지 예외로 사용한다. ALB는 Pod selector로 식별할 수 없으며 이 예외는 ALB만을
식별하는 규칙이 아니다. 같은 서브넷의 주소도 포함하므로 기존 ALB/노드 Security Group
경계와 함께 사용한다. VPC/서브넷/ALB 배치 변경 시 반드시 갱신한다.

NetworkPolicy 권한은 합집합이다. Redis 기본 broad 정책은 enabled=false로 제거하고,
동일 Helm release의 extraDeploy에서 제한된 정책을 생성한다. Kafka의 두 리스너에
networkPolicyPeers를 설정해 기존 9092/9093 전체 허용을 없앤다.
mTLS/SASL 설정, 이미지 태그, Terraform은 변경하지 않는다. 외부 호출 서비스에만 프록시 환경변수를 추가한다.
standard 모드에서는 신규 Pod의 정책 반영 전 잠시 default-allow 구간이 있을 수 있다.

## PR 및 배포 순서

1. 로컬에서 두 저장소를 같은 부모 디렉터리에 두고 gitops에서 task validate를 실행한다.
   실제 web 이미지의 Node >=22.21.0 여부와 Java client의 proxy/bypass 동작을 확인한다.
2. gitops 차트 변경을 먼저 main에 머지한다. externalEgress의 기본값은 false이므로
   기존 values의 동작은 유지한다. gitops-value만 먼저 머지하면 인터넷 예외는 제거되지만
   구차트에는 프록시가 없어 외부 호출이 실패한다.
3. gitops-value를 머지한다. proxy 정책/ConfigMap/Service wave -4, proxy Deployment -3,
   앱 허용 정책 -2, Namespace 기본 차단 -1, 앱 workload 0 순서로 동기화한다.
   앱의 프록시 env 변경으로 앱 Pod가 교체된다. 프록시가 준비되지 않으면 다음 wave를 기다린다.
4. 서비스 정책 21개(앱 허용 8+Namespace 기본 차단 8+프록시 정책 5)와 프록시 5개
   Deployment/10개 Pod를 확인한다. 기존 DB/Redis/Kafka/관측성 정책도 유지되는지 확인한다.
5. 실제 CNI에서 내부 API/DB/Redis/Kafka/DNS/Tempo 및 Pod Identity 통신을 검증한다.
   자기 프록시의 허용 도메인 연결, 다른 도메인/다른 서비스 프록시/IP-literal/잘못된 포트
   차단, 앱 Pod의 직접 공인 IP:443 차단을 검사한다. OAuth/Toss/Juso 키를 정상 주입한
   기능 테스트도 필요하다. 예정된 S3/이미지 API 구현 시 업로드 확인/태그 변경/CDN을 검증한다.

테스트는 Helm 렌더링/YAML/정적 허용 규칙 검증이며 실제 CNI 집행 검증을 대신하지 않는다.
로컬 Docker에서 비루트/read-only Squid 설정 파싱, 허용 Google 연결 및 다른 도메인/IP/
HTTP/포트 차단을 확인했다. Java 기본 JDK HttpClient/URLConnection 및 Node 기본 fetch의 프록시 연결과 차단을 검증했다.
배포 전 기존 장애와 정책으로 새로 발생한 장애를 구분한다. 이번 작업은 저장소 파일 수정이며
클러스터에는 직접 적용하지 않는다.

## 리소스 중복 검수

`task validate`에 `validate:resource-duplicates`를 포함한다. YAML 중복 키, 동일한
API group/종류/Namespace/이름의 리소스, 환경변수 이름, 컨테이너·Service 포트,
컨테이너·볼륨 이름과 마운트 경로, 동일한 NetworkPolicy 규칙/peer/port,
프록시 허용 도메인의 중복을 검사한다. Namespace가 다르거나 서로 다른 workload 모드의
리소스는 별도로 구분한다.

2026-09-18 검수에서 YAML 75개, 서비스 기본/카나리/블루그린 렌더링 24개,
기본 배포 및 저장소 선언 리소스 200개의 중복 오류가 없었다. Node의 중복된 활성화
설정은 NODE_OPTIONS만 남겼다. Namespace 기본 차단과 앱/프록시 허용 정책의
selector 중첩, 서비스별 프록시 5개와 각 2 replica는 필요한 구성으로 유지한다.

검수 대상은 로컬 저장소 선언, 플랫폼 Helm inline values의 extraDeploy,
서비스 차트 렌더링 결과다. operations의 수동 복원 예시는 별도 배포이므로 운영 리소스와
합쳐 비교하지 않는다. 원격 플랫폼 Helm chart의 전체 생성 결과, Operator가 생성한
리소스 및 실행 중인 클러스터의 중복/정책 합집합은 이 정적 검사만으로 확인하지 않는다.

## 롤백

외부 호출 문제는 해당 서비스의 이번 values 변경(인터넷 예외 제거 및 externalEgress 설정)을 함께
되돌린다. externalEgress.enabled=false만 설정하면 직접 인터넷은 계속 차단된다.
전체 서비스 정책을 해제하려면 externalEgress.enabled=false와 networkPolicy.enabled=false를
함께 설정한다. externalEgress는 Namespace 기본 차단과 앱 정책을 필수로 요구한다.
이렇게 해야 서비스 허용 정책과 Namespace 기본 차단이 **둘 다** 제거된다.
Namespace 기본 차단만 남긴 채 서비스 허용 정책만 삭제하면 서비스가 차단된다.

플랫폼 문제는 gitops의 해당 변경을 되돌린다. DB 정책 파일 제거,
관측성 application/정책 제거, Redis 기본 networkPolicy 재활성화+extraDeploy 정책 제거,
Kafka networkPolicyPeers 제거가 대상이다. 서비스 enabled=false만으로 플랫폼 정책은
해제되지 않는다. ArgoCD prune/reconcile 결과를 확인하며 긴급 클러스터 변경은 별도 승인 후 진행한다.

## 참고

- Kubernetes NetworkPolicy: https://kubernetes.io/docs/concepts/services-networking/network-policies/
- AWS CNI Service selector 제약: https://github.com/aws/amazon-network-policy-controller-k8s#considerations
- Strimzi 0.45.2 listener networkPolicyPeers: https://strimzi.io/docs/operators/0.45.2/configuring
- CNPG Operator/DB 포트: https://cloudnative-pg.io/docs/devel/networking/

- [Squid ACL 공식 문서](https://www.squid-cache.org/Doc/config/acl/)
- [Ubuntu Squid 이미지](https://hub.docker.com/r/ubuntu/squid)
- [Java 기본 ProxySelector](https://docs.oracle.com/en/java/javase/21/docs/api/java.net.http/java/net/http/HttpClient.Builder.html)
- [Node 22.21.0 proxy 옵션](https://nodejs.org/download/release/v22.21.0/docs/api/cli.html#--use-env-proxy)
