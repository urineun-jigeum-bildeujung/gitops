# ServiceDown — 서비스가 2분 이상 응답 없음

## 증상
- 알림: `{service} 다운`
- `up{service="<서비스명>"} == 0` — Prometheus가 `/actuator/prometheus` 스크레이프 자체에 실패

## 확인 순서

1. **파드가 떠 있는지부터 확인**
   ```bash
   kubectl get pods -n <서비스명>
   ```
   - 파드가 아예 없음 → ArgoCD sync 실패 가능성, `argocd app get <서비스명>` 확인
   - `CrashLoopBackOff` → `pod-crash-looping.md` 런북으로
   - `Pending` → 노드 리소스 부족 가능성, `kubectl describe pod`로 Events 확인
   - `Running`인데 up=0 → 2번으로
2. **Running인데 스크레이프가 안 되는 경우** — 앱은 떠 있는데 `/actuator/prometheus`가 응답 안 하는 상황. `deploy/<서비스명>`은 auth-service/payment-service처럼 Argo Rollout(blueGreen/canary)을 쓰는 서비스에선 못 찾으니, 라벨 셀렉터로 파드를 직접 지정한다.
   ```bash
   POD=$(kubectl get pod -n <서비스명> -l app.kubernetes.io/name=generic-service -o jsonpath='{.items[0].metadata.name}')
   kubectl exec -n <서비스명> "$POD" -- curl -sv localhost:8080/actuator/prometheus 2>&1 | tail -20
   ```
   - **응답이 `HTTP 400`이고 본문이 `"This combination of host and port requires TLS."`면 mTLS 관리포트 SSL 상속 문제다(2026-09-29 auth-service 등 다수 서비스에서 실제 재현)** — mTLS 활성화 서비스는 `management.server.ssl.enabled`를 명시적으로 안 꺼두면 `server.ssl.enabled=true`(메인 8443 포트용)를 그대로 물려받아서, Prometheus가 평문으로 스크레이프하는 8080 관리 포트까지 TLS를 요구해버림. `charts/generic-service`의 `generic-service.mtlsEnv`(`_helpers.tpl`)에 `MANAGEMENT_SERVER_SSL_ENABLED: "false"`가 있는지 확인 — 이미 있는데도 재현되면 차트가 아니라 다른 원인이니 계속 조사. (gitops#106에서 최초 발견/수정)
   - 그 외의 실패면 앱 내부 데드락/행(hang) 의심 → 로그 확인, 필요시 파드 재시작
   ```bash
   kubectl rollout restart deployment <서비스명> -n <서비스명>   # Deployment인 경우
   kubectl argo rollouts restart generic-service -n <서비스명>  # Rollout(blueGreen/canary)인 경우
   ```
3. **ServiceMonitor/네트워크 문제인지 확인** (앱은 정상인데 Prometheus만 못 붙는 경우)
   ```bash
   kubectl get servicemonitor -n <서비스명>
   ```
   Prometheus Targets 페이지(`kubectl port-forward svc/kube-prometheus-stack-prometheus 9090 -n observability`)에서 해당 타겟 상태/에러 메시지 확인.

## 완화

- 재시작으로 복구되면 일단 정상화, 이후 왜 죽었는지(OOM, 데드락 등) 로그로 원인 추적
- ArgoCD sync 실패가 원인이면 매니페스트/values 오류 수정 후 재sync

## 에스컬레이션
- 재시작해도 즉시 다시 다운되면(반복) 바로 서비스 담당자 호출 — 코드 레벨 버그일 가능성 높음.
