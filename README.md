# gitops
골라주개냥 CI/CD + GitOps 관련 Repo

## 구조 (뼈대 단계, 2026-08-19 개정 — Troika 팀 실제 레포 패턴 참고해서 재구성)

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
  10-ingress-nginx/            클러스터 진입점
  30-kube-prometheus-stack/, 30-loki/, 30-tempo/    관찰성 3종
  40-cnpg-operator/, 40-keda/, 40-external-secrets-operator/   오퍼레이터 3종
  91-external-secrets-config/  ESO의 "어디서 뭘 가져올지" 설정 (ClusterSecretStore 등)
  kafka/                       보류 (백엔드 확인 대기)
  root.yaml                    platform 레이어 App-of-apps root
applications/
  appset.yaml                  서비스용 ApplicationSet — values 레포를 스캔해서 서비스 Application 자동 생성
charts/generic-service/        서비스 전체가 공유하는 공용 Helm 차트 (canary 지원, Argo Rollouts 연동)
```

폴더 이름의 숫자(`00-`, `05-`, `30-`...)는 사람이 읽을 때 배포 순서를 한눈에 알 수 있게 하는 표시일 뿐이고,
실제 순서는 각 `application.yaml`의 `sync-wave` annotation이 강제한다.

addon들은 별도 래퍼 Chart.yaml 없이 ArgoCD Application의 `source.chart` 필드로 외부 Helm 차트를 직접 참조한다.

**values(서비스별 이미지 태그·리소스 값)는 별도 레포로 분리 예정** — 이 레포는 차트/구조만 담당.
서비스 목록이 아직 확정 전이라 `applications/appset.yaml`의 values 레포 URL은 TODO 상태.

각 addon의 버전(`x.x.x`)과 Kafka 포함 여부는 아직 미확정 — 실제 적용 전 확인 필요.

