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

`task bootstrap`은 `helm-values/argocd.yaml`을 포함해 ArgoCD, Jenkins Credential, `root-app.yaml`을 모두 복구한다. Jenkins Git Credential이
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

보안팀 Jenkins 계정 `security-audit`의 비밀번호는 최초 실행 때 AWS Secrets Manager의
`petflow/jenkins/security-audit-password`에 한 번 생성한다. 이후에는 같은 값을
`jenkins/jenkins-audit-credentials` Secret으로 복원하며, 값이 다르면 자동 교체하지 않고
실패한다. 실행 주체는 계정 `297165773875`에서 `sts:GetCallerIdentity`,
`secretsmanager:GetSecretValue` 권한이 필요하다. 최초 생성에는 `secretsmanager:CreateSecret`
권한도 필요하다. Secret 원문은 Git이나 Terraform State에 저장하지 않는다.
보안팀 비밀번호만 복원할 때는 `task bootstrap:jenkins-audit-secret KUBE_CONTEXT=petflow-dev`를 쓴다.
Jenkins 내부 계정과 권한은 `platform/40-jenkins/application.yaml`의 JCasC가 관리한다.
security IAM 사용자는 `jenkins` 네임스페이스의 포트포워딩으로 Jenkins에 연결한 뒤,
`security-audit` 계정으로 로그인한다.

`security-audit`에는 `Overall/Read`, `Overall/SystemRead`, `Job/Read`,
`Job/ExtendedRead`, `Credentials/View`만 부여한다. Jenkins 관리자 권한과
빌드 실행·설정 변경 권한은 부여하지 않는다. 배포 후 해당 계정으로 시스템·Job·Credential
메타데이터를 조회하고, 변경 기능과 Secret/Token 원문 접근이 차단되는지 확인한다.
포트포워딩은 `kubectl --context petflow-dev -n jenkins port-forward svc/jenkins 8080:8080`으로
열고 `http://localhost:8080`에서 로그인할 수 있다.

관리자 Secret은 기존 값이 있으면 유지되지만 클러스터와 함께 삭제된 경우 현재 공식 bootstrap이 새 랜덤
비밀번호를 만든다. 클러스터 세대 사이에 같은 관리자 비밀번호를 복원하는 영구 공급원은 아직 없으며,
필요하면 AWS Secrets Manager 같은 보존 저장소로 옮기는 작업을 별도 범위로 진행한다. 개별 단계는
`task bootstrap:jenkins-admin-secret`, `task bootstrap:jenkins-git-credentials`,
`task bootstrap:jenkins-audit-secret`,
`task bootstrap:argocd`, `task bootstrap:root-app`으로 실행할 수 있다.

Jenkins Controller는 `images/jenkins-controller/plugins.lock.txt`의 고정 플러그인을 포함한 ECR 이미지를 사용한다. `platform/40-jenkins/application.yaml`은 태그와 digest를 함께 고정하고 `controller.installPlugins=false`로 실행하므로 새 PVC에서도 외부 플러그인 mirror를 조회하지 않는다. 이미지 갱신은 `images/jenkins-controller/build-and-push.sh`로 빌드·CRITICAL 취약점 검사·Push한 뒤 검증된 digest를 Application에 반영한다. 빌드 절차와 롤백 기준은 해당 이미지 디렉터리의 README를 따른다.

커밋 전 검증은 `task validate` (Helm 차트 렌더링 + 전체 YAML 문법 검사).

## 기여 방법 (이슈 → 브랜치 → PR)

이 레포는 `blank_issues_enabled: false`라 **이슈 없이는 이슈 자체를 못 만든다** — 반드시
`.github/ISSUE_TEMPLATE/`의 폼 3종(`bug.yml`, `change_request.yml`, `config.yml`) 중 하나로
시작한다. 버그 수정은 `bug.yml`, 새 addon/구조 변경/서비스 온보딩은 `change_request.yml`을 쓴다.

1. 이슈 생성 (제목은 템플릿이 `fix: `/`feat: `를 자동으로 붙여줌)
2. 브랜치 생성 — 강제 규칙은 아니지만 관례상 `fix/<이슈번호>-짧은설명`, `feat/<이슈번호>-짧은설명`
   (예: `fix/109-jvm-heap-tuning`). 브랜치는 항상 최신 `origin/main`에서 새로 딴다 — 이미
   머지된 브랜치 위에서 새 브랜치를 파면 add/add 충돌이 남(직접 겪음).
3. 커밋 → `task validate`로 로컬 검증 → push → PR (`.github/pull_request_template.md` 양식)
4. PR 본문에 `Closes #<이슈번호>`를 넣어 머지 시 이슈가 자동으로 닫히게 한다.
5. **Squash merge**로 병합 — `main`의 커밋 히스토리는 항상 깔끔하게 유지.

승인 인원 0명(현재 인프라 담당자 단독 운영), CODEOWNERS 미사용 — 팀원이 합류하면
`docs/branching-strategy.md`부터 재검토한다.

## 배포 반영 확인 및 트러블슈팅

`main`에 머지되면 ArgoCD가 자동 동기화하지만(`selfHeal: true`), **자동 폴링 주기를 기다리지
않고 즉시 확인하려면** 관련 Application을 hard refresh 한다.

```bash
kubectl patch application <app-name> -n argocd --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'

# 동기화 상태/리비전 확인
kubectl get application <app-name> -n argocd \
  -o jsonpath='{.status.sync.status} health={.status.health.status} rev={.status.sync.revisions}{"\n"}'
```

- root Application(`app-platform`, `platform-root`)과 실제 바뀐 리소스를 담당하는 자식
  Application(예: 서비스면 `dev-<서비스명>`, addon이면 `platform/*`의 Application 이름)을
  **둘 다** refresh해야 한다 — root만 새로고침하면 자식이 안 따라오는 경우가 있다.
- **ArgoCD가 관리하는 리소스는 `kubectl apply`/`kubectl patch`로 직접 손대지 않는다** —
  `selfHeal: true`라 몇 초 안에 git 상태로 되돌려버린다. 라이브로 뭔가 테스트해야 하면
  `kubectl apply --dry-run=server`(스키마 검증만) 정도만 쓰고, 실제 동작 확인은 반드시
  커밋 → 머지 → sync 경로로 한다.
- `.status.sync.revisions`는 소스가 여러 개인 Application(예: 서비스 Application은
  `charts/generic-service` + `gitops-value` 두 소스)이면 배열로 나온다 — 둘 다 원하는 커밋
  SHA와 일치하는지 확인한다.

## Argo Rollouts — 블루그린/카나리 승격·재시작

`blueGreen.enabled`(예: auth-service)는 `autoPromotionEnabled: false`라 새 버전이 healthy해도
**수동 승인 없이는 트래픽이 안 넘어간다.**

```bash
# 새 ReplicaSet이 준비됐는지 먼저 확인
kubectl get rollout <name> -n <서비스명> \
  -o jsonpath='{.status.currentPodHash} updated={.status.updatedReplicas} ready={.status.readyReplicas}{"\n"}'

# 확인됐으면 승격 (kubectl-argo-rollouts 플러그인 필요)
kubectl argo rollouts promote <name> -n <서비스명>

# 문제가 있어 되돌려야 하면
kubectl argo rollouts abort <name> -n <서비스명>
```

`canary.enabled`(예: payment-service)는 `steps`에 `pause: {duration: 60}`처럼 **시간 기반
pause만 있으면 자동으로 다음 단계로 넘어간다** — 수동 개입 불필요. `pause: {}`(duration 없음)
스텝이 있으면 그 지점은 blueGreen과 마찬가지로 수동 promote가 필요하다. 현재 `steps` 설정은
`gitops-value`의 각 서비스 `values.yaml` `canary.steps`에서 확인한다.

Deployment 기반 서비스(canary/blueGreen 둘 다 꺼져 있는 서비스)는 일반 롤링 업데이트라
별도 승인 없이 자동으로 끝까지 진행된다.

```bash
# 새 이미지로 강제 재시작(설정 값 변경 없이)
kubectl rollout restart deployment <name> -n <서비스명>          # Deployment
kubectl argo rollouts restart <name> -n <서비스명>                # Rollout
```

## 모니터링 및 알림

- **Grafana**: `https://grafana.leechs.shop` (인터넷 공개, 로그인 필수). Golden Signals/JVM/에러
  대시보드는 `platform/30-kube-prometheus-stack/manifests`의 ConfigMap을 sidecar가 자동 로드.
- **Prometheus**: 클러스터 내부 전용, `kubectl port-forward svc/kube-prometheus-stack-prometheus
  9090:9090 -n observability`로 접근.
- **Alertmanager**: 골든시그널 알림 8종(`HighErrorRate`, `HighLatencyP99`, `ServiceDown`,
  `PodCrashLooping`, `PodNotReady`, `HighMemoryUsage`, `HighCPUUsage`,
  `HikariCPConnectionPoolExhausted`, 정의는 `platform/30-kube-prometheus-stack/manifests/alert-rules.yaml`)만
  Discord로 라우팅된다(`manifests/alertmanager-config-discord.yaml`, `AlertmanagerConfig` CRD).
  kube-prometheus-stack이 기본 제공하는 수십 개 알림은 대상이 아니다 — 새 알림 규칙을
  추가하면 Discord로 보내기 위해 그 `AlertmanagerConfig`의 `matchers` 정규식에도 추가해야 한다.
- **알림이 울리면**: 메시지에 딸려오는 `runbook_url`을 따라가면 `docs/runbooks/`의 대응
  문서로 바로 이동한다. 각 런북은 확인 순서, 흔한 원인(실제 겪었던 사고 기준), 완화 방법,
  에스컬레이션 기준을 담고 있다.
- **EKS 관리형 컨트롤플레인 관련 알림**(`KubeControllerManagerDown` 등)은 구조적으로 절대
  해소되지 않아 `defaultRules.rules`에서 꺼져 있다 — 새로 이런 알림이 보이면 EKS가 노출 안
  하는 컴포넌트인지부터 의심한다.

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

### Argo CD·Jenkins Tailscale 관리 접근

`helm-values/argocd.yaml`과 `platform/40-jenkins/application.yaml`은 `petflow-dev-management`
IngressGroup의 Internal ALB 하나를 공유한다. Argo CD는 HTTPS backend와 `/healthz`, Jenkins는
HTTP backend와 `/login`을 사용한다. 둘 다 Terraform이 만드는 `petflow-dev-management-alb`
frontend SG를 이름으로 참조하고 Controller가 backend SG 규칙을 관리한다.

| 서비스 | 주소 | 접근 조건 |
|---|---|---|
| Argo CD | `https://argocd.leechs.shop` | Tailscale 연결 |
| Jenkins | `https://jenkins.leechs.shop` | Tailscale 연결 |

Public Web/Gateway 그룹과 ingress-nginx 설정은 이 구성으로 변경하지 않는다. Route53 Alias와
frontend SG는 Infra 저장소가 관리한다.

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
