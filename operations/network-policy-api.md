# 내부 NetworkPolicy — API・DB・Redis・Kafka・관측성

## 범위와 남아 있는 제한

서비스 전용 Namespace 8개(백엔드 7개와 web)에 기본 Ingress/Egress 차단을 적용하고,
정상 서비스 Pod에 아래 예외를 허용한다. Namespace와 Pod 라벨을 함께 검사하며,
규칙의 포트는 목적지 Pod의 실제 포트다. DB/Redis/관측성의 알려진 Pod에는 Ingress만 제한한다.
Kafka는 Strimzi가 생성하는 리스너 정책 자체를 좁힌다. 플랫폼 Egress, ArgoCD, Jenkins,
kube-system, Operator 등 전체 클러스터의 기본 차단은 이번 범위가 아니다.

**외부 Egress allowlist는 아직 완료되지 않았다.** 서비스 Pod의 공인 IPv4 목적지는
모든 포트를 임시 허용한다. RFC1918, CGNAT, 링크로컬, 루프백 등의 주소는 제외하여
이 예외로 내부 차단을 우회하지 못하게 한다. OAuth, Toss, 주소 API, S3/CloudFront가
이 단계에서 새로 차단되지 않도록 유지한다. 이후 외부 목적지 제한은 별도 설계·검증한다.
공인 ALB/외부 프록시를 통한 간접 호출 및 hostNetwork/노드 트래픽까지 막는 최종 경계는 아니다.

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
mTLS/SASL 설정, 서비스 환경변수, 이미지 태그, Terraform은 변경하지 않는다.
standard 모드에서는 신규 Pod의 정책 반영 전 잠시 default-allow 구간이 있을 수 있다.

## PR 및 배포 순서

1. gitops PR을 먼저 main에 머지한다. 기본 차트 enabled=false이지만 **플랫폼 DB/Redis/Kafka/
   관측성 정책은 이 머지부터 활성화된다.** 현재 애플리케이션 라벨의 정상 경로를 미리 포함했다.
2. 플랫폼 정상 상태를 확인하고 gitops-value PR을 머지해 서비스 8개의 정책을 활성화한다.
3. ArgoCD 자동 동기화 후 서비스 정책 16개(서비스 허용 8+Namespace 기본 차단 8),
   DB 1개, Redis 대체 정책 1개, 관측성 7개 및 Strimzi 생성 정책을 확인한다.
4. 허용/차단, 로그/메트릭/트레이스, S3 SDK 자격 증명 및 업로드/태그 변경을 검증한다.
5. 성공 확인 후 외부 목적지 Egress 제어 단계로 진행한다.

로컬에서는 두 저장소를 같은 부모 디렉터리에 두고 gitops에서 task validate를 실행한다.
테스트는 Helm 렌더링/YAML/정적 허용 규칙 검증이며 실제 CNI 집행 검증을 대신하지 않는다.
배포 전 기준: auth/order Prometheus 대상은 HTTP/TLS 불일치로 DOWN,
member는 DB 초기화/Pod 기동 문제로 DOWN이었다. 정책으로 새로 발생한 장애와 구분한다.
Gateway의 실제 호출은 배포 후 별도로 확인한다. 이번 작업에서 클러스터에 직접 적용하지 않는다.

## 롤백

서비스 문제는 gitops-value의 해당 networkPolicy.enabled=false로 되돌리는 PR을 머지한다.
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
