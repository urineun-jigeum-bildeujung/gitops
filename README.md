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
  05-storageclass/             공용 gp3 + 자동 EBS Backup 태그가 있는 CNPG 전용 gp3-cnpg
  10-ingress-nginx/            클러스터 진입점
  10-aws-load-balancer-controller/  alb Ingress를 AWS ALB/NLB로 연결 (EKS Pod Identity 사용)
  30-kube-prometheus-stack/, 30-loki/, 30-tempo/    관찰성 3종
  40-cnpg-operator/, 40-keda/, 40-external-secrets-operator/, 40-kafka-operator/,
  40-trivy-operator/                     오퍼레이터 5종 (trivy-operator는 이미지 취약점 스캔)
  40-redis/                    타임딜 동시성 락/카운터용 Redis (standalone, AOF, gp3 PVC)
  40-jenkins/                  CI 서버 (오퍼레이터 없이 chart 직접 배포, Kubernetes plugin으로 동적 agent)
  50-kafka-cluster/            Kafka 3.9.0 단일 KRaft 브로커 + gp3 PVC + 토픽 7종
  91-external-secrets-config/  ESO의 "어디서 뭘 가져올지" 설정 (ClusterSecretStore 등) — 미완성, ServiceAccount 확정 필요
  root.yaml                    platform 레이어 App-of-apps root
applications/
  appset.yaml                  서비스용 ApplicationSet — values 레포를 스캔해서 서비스 Application 자동 생성
charts/generic-service/        서비스 전체가 공유하는 공용 Helm 차트 (canary 지원, Argo Rollouts 연동)
docs/
  branching-strategy.md        브랜치 전략, PR 규칙
  redis-kafka-platform.md      Redis/Kafka 설정 계약, Endpoint, 검증 및 역할 경계
operations/
  data-protection/             Argo CD 비대상 CNPG 온디맨드 복원 검증 Manifest/Runbook
```

폴더 이름의 숫자(`00-`, `05-`, `30-`...)는 사람이 읽을 때 배포 순서를 한눈에 알 수 있게 하는 표시일 뿐이고,
각 `application.yaml`의 `sync-wave` annotation은 같은 동기화 범위에서 순서를 조정한다. 서로 다른 상위
Application/ApplicationSet 사이의 전역 순서는 보장하지 않으므로 복구 스크립트가 핵심 컴포넌트의 준비 상태를 별도로 확인한다.

addon들은 별도 래퍼 Chart.yaml 없이 ArgoCD Application의 `source.chart` 필드로 외부 Helm 차트를 직접 참조한다.

## 시작하기 (클러스터에 처음 반영하거나, 재구축 후)

```bash
aws eks update-kubeconfig --name petflow-eks --region ap-northeast-2
task bootstrap
```

`task bootstrap`은 ArgoCD, Jenkins Credential, `root-app.yaml`을 모두 복구한다. Jenkins Git Credential이
없을 때는 로그인된 GitHub CLI와 `sever` 읽기·`gitops-value` 쓰기 권한이 필요하다. 유효한 Secret이 이미
있으면 GitHub CLI 인증 없이도 기존 값을 유지한다. Controller/ALB 같은 클러스터 핵심 경로만 복구할 때는
GitHub 인증에 의존하지 않는 다음 명령을 사용한다.

```bash
task bootstrap:core
```

Jenkins Credential만 별도로 복구하려면 다음 명령을 실행한다. 모든 Kubernetes 호출은 지정한 context와
`jenkins` Namespace를 사용한다. 기존 Secret은 필수 키가 모두 유효할 때 보존하며, 키가 없거나 빈 기존
Secret은 자동으로 덮어쓰지 않고 실패한다. Git Secret이 누락됐는데 GitHub 인증·권한이 없을 때도
`gh auth login`을 자동 실행하지 않고 실패한다.

```bash
task bootstrap:credentials KUBE_CONTEXT=petflow-dev
```

관리자 Secret은 기존 값이 있으면 유지되지만 클러스터와 함께 삭제된 경우 현재 공식 bootstrap이 새 랜덤
비밀번호를 만든다. 클러스터 세대 사이에 같은 관리자 비밀번호를 복원하는 영구 공급원은 아직 없으며,
필요하면 AWS Secrets Manager 같은 보존 저장소로 옮기는 작업을 별도 범위로 진행한다. 개별 단계는
`task bootstrap:jenkins-admin-secret`, `task bootstrap:jenkins-git-credentials`,
`task bootstrap:argocd`, `task bootstrap:root-app`으로 실행할 수 있다.

커밋 전 검증은 `task validate` (Helm 차트 렌더링 + 전체 YAML 문법 검사).

## AWS Load Balancer Controller

`platform/10-aws-load-balancer-controller/application.yaml`이 공식 AWS EKS Helm Chart를 직접 참조한다.
`platform/root.yaml`이 이 Application을 자동 탐색하므로 `task bootstrap:core` 이후 ArgoCD가 Controller를
설치하고, `ingressClassName: alb`인 Web Ingress를 감지해 `petflow-dev-public` ALB를 생성한다.

- GitOps 관리: Helm Release, Controller Deployment/Pod/Service, ServiceAccount, CRD와 Webhook
- Infra 관리: IAM Role/Policy, EKS Pod Identity Association, Subnet Tag와 Network 조건
- Pod Identity 계약: `kube-system/aws-load-balancer-controller` (IRSA annotation 사용 안 함)
- 고정 설정: Chart `3.5.0`, Cluster `petflow-eks`, Region `ap-northeast-2`
- VPC 탐색: `Project=petflow`, `Environment=dev`, `Name=petflow-vpc` 공통 태그 사용 (VPC ID 고정 안 함)
- Webhook TLS: 선행 배포되는 cert-manager(sync-wave `-10`)가 인증서 발급·갱신
- 배포 힌트: Controller sync-wave `-5`, 서비스 Application sync-wave `10`

Sync Wave만으로 전체 Application의 절대 순서를 보장하지 않는다. `trestore.sh`가 Controller
`Synced/Healthy`, Deployment Available, Certificate Ready와 Webhook Endpoint를 확인한 뒤 ALB 검증으로 진행한다.

```bash
kubectl get application aws-load-balancer-controller -n argocd
kubectl get deployment,pod,service -n kube-system \
  -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl get certificate,issuer -n kube-system
kubectl get endpoints aws-load-balancer-webhook-service -n kube-system
kubectl get crd | grep elbv2.k8s.aws
kubectl get ingress -A -o wide
```

정상 기준은 Application `Synced/Healthy`, Controller Pod `Running/Ready`, Web Ingress `ADDRESS`에
ALB DNS가 표시되는 상태다. `ingress-nginx`는 `ingressClassName: nginx`만 담당하므로 두 Controller는
서로 대체하지 않고 함께 운영한다.

### Grafana 공개·Prometheus 비공개 접근

`platform/30-kube-prometheus-stack/manifests/ingress-grafana-public.yaml`은 Grafana를 기존
`petflow-public` IngressGroup에 합류시켜 Web과 같은 Public ALB를 재사용한다. 별도
`load-balancer-name`은 지정하지 않으며, `/api/health`를 Target Health Check로 사용한다.

| 서비스 | 접근 정책 | 주소 |
|---|---|---|
| Grafana | 인터넷 공개, HTTPS·로그인 필수 | `https://grafana.leechs.shop` |
| Prometheus | Ingress·외부 DNS 없음, ClusterIP 전용 | `kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090` |

Grafana의 익명 접근과 사용자 임의 가입은 Helm values에서 차단한다. 관리자 인증정보는
Chart가 관리하는 Kubernetes Secret을 사용하며 Git에 값을 저장하지 않는다. Prometheus UI가
필요한 운영자는 Tailscale 연결 후 포트포워딩을 사용한다.

```bash
kubectl --context petflow-dev -n observability get ingress grafana-public -o wide
kubectl --context petflow-dev -n observability port-forward \
  svc/kube-prometheus-stack-prometheus 9090:9090
```

## 남은 것 / 알아둘 것

- 서비스별 이미지 태그·리소스 값은 별도 `gitops-value` 레포에서 관리한다. 이 레포는 공용 차트와
  Platform/Application 구조를 담당하며 `applications/appset.yaml`이 values 디렉터리를 스캔한다.
- addon 버전은 전부 실제 조회해서 고정함(`targetRevision`). 단, kafka-operator(Strimzi)는 최신이 아니라
  로컬 Kafka(3.9.0) 호환 버전(0.45.2)으로 의도적으로 낮춰서 고정 — 최신 버전은 Kafka 4.x만 지원.
- Kafka 토픽(`platform/50-kafka-cluster/manifests/topic.yaml`)은 백엔드 기획 문서 기준으로 7종 작성됐다.
  Kubernetes Resource 이름은 lowercase이고 실제 Topic 이름은 `spec.topicName`으로 보존한다. 이벤트
  Payload, Producer/Consumer, Consumer Group, Retry/DLQ는 Backend 합의 후 확정한다.
- Redis 이미지는 `bitnamilegacy/redis` 저장소를 명시해서 씀 — Bitnami가 최신 버전 외 과거 태그를
  무료 저장소(`docker.io/bitnami/*`)에서 내려서, 지정 안 하면 ImagePullBackOff 남.
