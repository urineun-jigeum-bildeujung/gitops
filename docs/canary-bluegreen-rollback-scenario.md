# 카나리·블루그린 배포 시연 + 롤백 시나리오

> **상태: 실행 완료 (2026-09-18)** — payment-service(카나리)/auth-service(블루그린) 둘 다 정상 승급 + 롤백 시나리오를 실제 클러스터에서 시연했다. 아래 설계 내용에 이어 각 섹션 끝에 **실행 결과**를 추가했다.

## 왜 이 두 서비스를 골랐는가

카나리와 블루그린은 존재 이유가 다르고, 그래서 적용 대상도 달라야 한다.

- **카나리 → payment-service**: 신버전 배포가 잘못됐을 때 피해가 **되돌릴 수 없는 성격**(이미 결제된 돈, 중복 결제, 정산 오류)인 서비스에 적용한다. 트래픽 일부에만 먼저 노출해서 문제를 조기에 잡고 나머지 트래픽은 안전하게 지키는 것이 목적. 실제 결제 시스템을 운영하는 회사들이 결제 관련 배포에 가장 먼저, 가장 보수적으로 카나리를 적용하는 것과 같은 이유다.
- **블루그린 → auth-service**: 반대로, **트래픽이 신구 버전으로 나뉘어 있는 상태 자체가 위험한** 서비스에 적용한다. 로그인/인증에 카나리를 쓰면 어떤 사용자는 구버전 토큰 형식으로, 어떤 사용자는 신버전 형식으로 세션이 생겨서 이후 요청이 다른 버전 서버로 튈 때 토큰 검증이 안 맞아 갑자기 로그아웃되는 사고로 이어질 수 있다. 그래서 인증 계열은 "전체를 한 번에 전환 + 문제 생기면 즉시 전체 되돌림" 방식이 자연스럽다.

## 사전 준비 (실행 전 반드시 필요)

1. **Argo Rollouts 컨트롤러 배포** — `rollouts.argoproj.io`, `analysistemplates.argoproj.io` 등 CRD가 클러스터에 없음(2026-09-16 확인). `charts/generic-service`의 `rollout.yaml`/`analysistemplate.yaml`은 이 컨트롤러가 있어야 실제로 동작한다. Alloy와 같은 패턴으로 `platform/*` 아래 새 Application 추가 필요.
2. **AnalysisTemplate의 라벨 버그 수정** — `charts/generic-service/templates/analysistemplate.yaml`의 PromQL이 `service="<서비스명>"`으로 필터링하는데, 이 라벨은 7개 서비스 전부 `"generic-service"`로 동일(2026-09-15 대시보드/알림에서 발견한 것과 같은 원인 — ServiceMonitor relabeling이 k8s Service 오브젝트 이름을 그대로 붙임). 지금 이대로면 카나리 버전만이 아니라 **클러스터 전체 서비스의 에러율**을 보게 되어 자동 판단이 무의미해짐. `namespace` 라벨 기준으로 교체 필요.
3. **시연 대상 서비스의 replicaCount 임시 상향** — 기본값 1개로는 "10%"를 설정해도 실제로는 반반(50%)이 되는 식으로 단계별 비율이 의미 없어짐. 최소 5~10개로 잠깐 늘려야 눈에 보이는 단계적 전환이 됨.
4. **지속적인 트래픽 발생** — k6 등으로 대상 서비스에 요청을 미리 흘려둬야 Grafana에서 전환 과정이 실제로 보이고, AnalysisTemplate도 판단할 데이터가 생김("부하 먼저, 배포는 나중" — DropMong 프로젝트에서 얻은 교훈).

## A. 카나리 롤백 시나리오 — payment-service

### 설정
```yaml
canary:
  enabled: true
  analysis:
    enabled: true
  steps:
    - setWeight: 20
    - pause: { duration: 60 }
    - setWeight: 50
    - pause: { duration: 60 }
    - setWeight: 100
```

### 정상 시나리오 (비교 기준)
1. 정상적인 신버전 이미지로 태그 변경 → ArgoCD sync → Rollout 시작
2. 20% → 60초 대기 → AnalysisTemplate이 에러율 정상 확인 → 50% → 60초 대기 → 100% 완전 전환
3. 구버전 ReplicaSet 자동 스케일다운

### 롤백 시나리오 (핵심 산출물)
1. **일부러 에러를 내는 버전**을 배포한다 (예: 결제 요청 처리 로직에서 의도적으로 500을 반환하도록 임시 코드 삽입, 또는 잘못된 환경변수로 하위 의존성 연결을 끊음).
2. Rollout이 20%로 신버전을 승급시키기 시작.
3. AnalysisTemplate이 1분 간격으로 에러율을 쿼리:
   ```promql
   sum(rate(http_server_requests_seconds_count{namespace="payment-service",status=~"5.."}[5m]))
   /
   sum(rate(http_server_requests_seconds_count{namespace="payment-service"}[5m]))
   ```
4. 에러율이 5%(`successCondition: result[0] <= 0.05`)를 초과하면 `failureLimit: 3`회 연속 실패 후 **Argo Rollouts가 자동으로 진행을 중단**.
5. 확인 명령:
   ```bash
   kubectl argo rollouts get rollout payment-service -n payment-service --watch
   ```
   `Degraded` 상태로 전환되고, 신버전 트래픽 비중이 더 이상 올라가지 않음을 확인.
6. 자동 중단만으로는 트래픽이 20%만큼은 여전히 신버전에 남아있으므로, 완전히 되돌리려면:
   ```bash
   kubectl argo rollouts abort payment-service -n payment-service
   # 또는 이전 정상 revision으로 명시적 되돌림
   kubectl argo rollouts undo payment-service -n payment-service
   ```
7. **결과**: 전체 요청의 80% 이상은 애초에 구버전으로만 처리됐고, 신버전에 노출됐던 20%도 자동 감지 후 짧은 시간 내 되돌아감 — 전체 트래픽을 신버전으로 먼저 밀어넣고 사후에 알아채는 것 대비 피해 범위가 확연히 작음.

### 실행 결과 (2026-09-18)

- **AnalysisTemplate "no data" 버그 발견 및 수정**: 5xx 에러가 0건일 때 `sum(rate(...status=~"5.."))`이 매칭되는 타임시리즈가 아예 없어 Prometheus가 빈 결과를 반환 → AnalysisRun이 `Error`로 실패하는 문제를 발견. `(sum(rate(...5xx...)) or vector(0)) / sum(rate(...total...))`로 수정해 정상 배포도 분석을 통과하도록 고침.
- **정상 승급**: 수정 후 20%→50%→100% 정상 승급 확인.
- **롤백 시나리오는 두 가지 장애 주입 방식을 시도**했고, 그 과정에서 중요한 사실을 발견했다:
  1. **1차 — DB 접속 차단**: `SPRING_DATASOURCE_URL`을 존재하지 않는 호스트로 변경. 결과: Hibernate가 부팅 시점에 DB 커넥션을 요구해서 **애플리케이션 자체가 크래시/재시작을 반복**(crash-loop). crash-loop는 커넥션 자체가 거부되는 것이라 HTTP 레벨 5xx로 잡히지 않고, AnalysisTemplate이 에러율 0%로 오판해서 깨진 버전이 그대로 100%까지 승급되는 사고가 발생했다.
  2. **2차 — 강제 HTTP 503 코드 주입**: `/actuator/health`가 DB와 무관하게 무조건 503을 반환하는 임시 `HealthIndicator`를 추가. 앱은 정상 기동하고 503도 실제로 확인했으나, **부팅에 약 60초가 걸려** AnalysisTemplate의 측정 주기와 타이밍이 어긋나면서(부팅 완료 전까지는 stable만 트래픽을 받아 에러율 0%로 집계) 이번에도 자동 감지가 승급을 막지 못했다.
  3. 두 경우 모두 **수동 `kubectl argo rollouts abort`로 즉시 롤백은 성공**했다 — 깨진 리비전이 0개로 스케일다운되고 stable 버전으로 완전 복귀됨을 확인.

```
$ kubectl argo rollouts abort generic-service -n payment-service
rollout 'generic-service' aborted
```
```
Events:
  Normal   ScalingReplicaSet   Scaled up ReplicaSet generic-service-5759869f7 (revision 2, stable) from 2 to 4
  Warning  RolloutAborted      Rollout aborted update to revision 3
  Normal   ScalingReplicaSet   Scaled down ReplicaSet generic-service-7c6858d777 (revision 3, canary) from 2 to 0
```

**결론 / 후속 과제**: 자동 감지가 완전히 신뢰 가능하려면 (a) AnalysisTemplate의 측정 간격·시작 지연을 애플리케이션 부팅 시간보다 여유 있게 잡거나, (b) `startupProbe`로 부팅 완료 전에는 트래픽 자체가 가지 않게 막는 보완이 필요하다. 이번 시연에서는 수동 개입(`abort`)으로 **롤백 메커니즘 자체**(문제 발견 시 트래픽을 안전하게 되돌리는 동작)는 확실히 검증했다.

## B. 블루그린 롤백 시나리오 — auth-service

### 설정
```yaml
blueGreen:
  enabled: true
  autoPromotionEnabled: false
  scaleDownDelaySeconds: 30
```

### 흐름
1. 신버전 배포 → 기존 트래픽을 받는 `auth-service`(activeService)는 그대로 구버전을 가리킴. 신버전은 `auth-service-preview`라는 별도 Service로만 접근 가능한 상태로 100% 기동.
2. **사용자 트래픽에 영향 없이** preview 서비스를 직접 호출해서 검증:
   ```bash
   kubectl port-forward svc/auth-service-preview -n auth-service 8081:80
   curl http://localhost:8081/actuator/health
   ```
3. 검증 결과에 따라 갈림:
   - **문제 없음** → `kubectl argo rollouts promote auth-service -n auth-service` → activeService의 selector가 즉시 신버전으로 전환, 구버전은 `scaleDownDelaySeconds`(30초) 뒤 스케일다운.
   - **문제 있음(롤백 시나리오)** → promote를 아예 하지 않고 그대로 폐기:
     ```bash
     kubectl argo rollouts abort auth-service -n auth-service
     ```
4. **결과**: promote를 안 하는 한 activeService는 신버전이 존재하는 동안에도 계속 구버전만 가리키고 있었으므로, **실사용자는 단 한 건의 요청도 신버전으로 처리된 적이 없음** — 카나리처럼 "일부는 이미 신버전으로 처리됐다"는 부분적 영향 자체가 존재하지 않는 것이 블루그린 롤백의 핵심 장점.

### 실행 결과 (2026-09-18)

- **mTLS 환경에서는 `curl`로 preview를 직접 검증할 수 없음을 확인**: auth-service는 `mtls.enabled: true`라 8080/8443 포트 전부 클라이언트 인증서를 요구한다. 클라이언트 인증서 없는 plain curl은 TLS 핸드셰이크 단계에서 거부됨(`000`) — 실제로는 preview 파드 자체의 애플리케이션 로그(`Started AuthServiceApplication`)와 k8s readiness 상태(`ready:1/1`)로 정상 기동을 검증했다.
- **Promote 시나리오**: preview 정상 기동 확인 후 promote 실행, 신버전이 즉시 active/stable로 전환됨을 확인.

```
$ kubectl argo rollouts promote generic-service -n auth-service
rollout 'generic-service' promoted
```
```
Status:          ✔ Healthy
Images:          ...auth-service:xxx (active, stable)
```

- **Abort(롤백) 시나리오**: 별도로 새 리비전을 트리거한 뒤 promote 없이 즉시 abort.

```
$ kubectl argo rollouts abort generic-service -n auth-service
rollout 'generic-service' aborted
```
```
Status:          ✖ Degraded
Message:         RolloutAborted: Rollout aborted update to revision 3
Images:          ...auth-service:xxx (active, stable)   ← 이전 검증된 버전 그대로 유지
```

- **결과**: active는 abort 시점까지 한 번도 신버전을 가리킨 적이 없어, 설계대로 실사용자 영향 없이 배포 시도만 취소됨을 실제로 확인했다.

## 실행 중 겪은 환경 이슈 (참고)

시연 자체와는 별개로, 진행 도중 클러스터 인프라 문제를 겪고 해결했다 — 재현 가능성이 있어 기록해둔다.

- **워커 노드 1대 kubelet 다운**: EC2 인스턴스 자체는 정상(AWS 헬스체크 통과)인데 kubelet만 응답 불능 상태가 되어 해당 노드의 모든 파드(ArgoCD server, Kafka 브로커, Jenkins 등 포함)가 `Terminating`에 걸림. 인스턴스를 종료해 관리형 노드그룹(ASG)이 자동으로 새 노드를 띄우도록 유도해 복구.
- **CPU/파드 수 한도**: 시연을 위해 일시적으로 늘린 replicaCount가 겹치면서 클러스터 CPU/노드당 파드 수(29개) 한도에 몰려 Kafka 브로커 등 필수 컴포넌트가 스케줄 자체가 안 되는 상황 발생. replicaCount를 낮춰 해소. **cluster-autoscaler가 클러스터에 실제로는 배포되어 있지 않다는 것도 이 과정에서 확인됨** — ASG 태그만 있고 자동 확장은 동작하지 않는 상태.
- **CI 파이프라인과의 경합**: 장애 대응 중 수동으로 되돌린 배포 태그를, 마침 그 시점에 뒤늦게 완료된 Jenkins 빌드의 자동 GitOps 커밋이 다시 덮어쓴 사례가 있었다. 진행 중인 배포를 긴급히 수동 조정할 때는 관련 CI 빌드가 대기 중인지 함께 확인할 필요가 있다.

## 산출물로 남길 것

- [x] `kubectl argo rollouts get rollout ...` 진행 과정 터미널 캡처 (정상 승급 1회, 롤백 1회 — 카나리/블루그린 각각) — 위 각 섹션의 실행 결과 참고
- [ ] Grafana Golden Signals 대시보드에서 배포 시점 전후 에러율/트래픽 그래프 스크린샷
- [x] 실제 소요 시간/발견한 이슈 기록 — 위 실행 결과 및 환경 이슈 섹션 참고
- [ ] 이 문서에 위 캡처 대신/추가로 실제 스크린샷 첨부해서 최종본으로 갱신
