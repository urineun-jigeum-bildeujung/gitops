# gitops
골라주개냥 CI/CD + GitOps 관련 Repo

## 구조

```
bootstrap/
  root-app.yaml               App-of-apps 최상위 — 클러스터에 최초 apply할 파일 하나
  apps.yaml                   root-app이 만드는 자식 Application 3개 (projects/platform/applications)
projects/
  services-project.yaml       우리 서비스 전용 AppProject
  platform-project.yaml       addon 전용 AppProject
platform/
  00-cert-manager/             인증서 자동 발급 (Istio 대신 채택)
  05-namespaces/, 05-rbac/     네임스페이스, RBAC
  05-storageclass/             gp3 기본 StorageClass (EKS 기본 gp2는 구식 드라이버라 K8s 1.27+에서 동작 안 함)
  10-ingress-nginx/            클러스터 진입점
  30-kube-prometheus-stack/, 30-loki/, 30-tempo/    관찰성 3종
  40-cnpg-operator/, 40-keda/, 40-external-secrets-operator/, 40-kafka-operator/,
  40-trivy-operator/                     오퍼레이터 5종 (trivy-operator는 이미지 취약점 스캔)
  40-redis/                    타임딜 동시성 락/카운터용 Redis (오퍼레이터 없이 chart 직접 배포)
  40-jenkins/                  CI 서버 (오퍼레이터 없이 chart 직접 배포, Kubernetes plugin으로 동적 agent)
  50-kafka-cluster/            실제 Kafka 브로커 클러스터(KRaft 모드) + 토픽 7종
  91-external-secrets-config/  ESO의 "어디서 뭘 가져올지" 설정 (ClusterSecretStore 등) — 미완성, ServiceAccount 확정 필요
  root.yaml                    platform 레이어 App-of-apps root
applications/
  appset.yaml                  서비스용 ApplicationSet — values 레포를 스캔해서 서비스 Application 자동 생성
charts/generic-service/        서비스 전체가 공유하는 공용 Helm 차트 (canary 지원, Argo Rollouts 연동)
docs/
  branching-strategy.md        브랜치 전략, PR 규칙
```

폴더 이름의 숫자(`00-`, `05-`, `30-`...)는 사람이 읽을 때 배포 순서를 한눈에 알 수 있게 하는 표시일 뿐이고,
실제 순서는 각 `application.yaml`의 `sync-wave` annotation이 강제한다.

addon들은 별도 래퍼 Chart.yaml 없이 ArgoCD Application의 `source.chart` 필드로 외부 Helm 차트를 직접 참조한다.

## 시작하기 (클러스터에 처음 반영하거나, 재구축 후)

```bash
aws eks update-kubeconfig --name petflow-eks --region ap-northeast-2
task bootstrap
```

Kafka 토픽(KafkaTopic)은 서비스/이벤트 목록이 아직 초안이라 미포함 — 확정되면
`platform/50-kafka-cluster/manifests/`에 추가 예정.
`task bootstrap`이 ArgoCD 설치부터 `root-app.yaml` apply까지 한 번에 처리한다 (`task bootstrap:argocd`,
`task bootstrap:root-app`으로 개별 실행도 가능). DEV 환경은 destroy/apply를 반복하는 설계라, 재구축할
때마다 이 명령 하나만 다시 실행하면 된다.

커밋 전 검증은 `task validate` (Helm 차트 렌더링 + 전체 YAML 문법 검사).

## 남은 것 / 알아둘 것

- **values(서비스별 이미지 태그·리소스 값)는 별도 레포로 분리 예정** — 이 레포는 차트/구조만 담당.
  서비스 목록은 확정됐지만(auth/member/product/order/payment/review/notification) values 레포 자체가
  아직 없어서 `applications/appset.yaml`의 repoURL은 TODO 상태 — 서비스 실제 배포는 이게 생겨야 시작됨.
- addon 버전은 전부 실제 조회해서 고정함(`targetRevision`). 단, kafka-operator(Strimzi)는 최신이 아니라
  로컬 Kafka(3.9.0) 호환 버전(0.45.2)으로 의도적으로 낮춰서 고정 — 최신 버전은 Kafka 4.x만 지원.
- Kafka 토픽(`platform/50-kafka-cluster/manifests/topic.yaml`)은 백엔드 기획 문서 기준으로 7종 작성됨.
  백엔드가 아직 코드(공통 이벤트 모듈)로 구현 전이라 이름이 바뀌면 같이 수정 필요.
- Redis 이미지는 `bitnamilegacy/redis` 저장소를 명시해서 씀 — Bitnami가 최신 버전 외 과거 태그를
  무료 저장소(`docker.io/bitnami/*`)에서 내려서, 지정 안 하면 ImagePullBackOff 남.

