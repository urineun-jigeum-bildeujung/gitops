# HighLatencyP99 — p99 지연시간 1초 초과

## 증상
- 알림: `{service} p99 지연시간 1초 초과`
- 대시보드: [서비스 Golden Signals](.) — "지연시간 (Latency)" 패널

## 확인 순서

1. **평소 대비 트래픽이 급증했는지** — Golden Signals 대시보드 "초당 요청 수(RPS)" 패널에서 확인. 트래픽 급증이면 포화도(CPU/메모리) 문제일 가능성 높음 → 2번으로.
2. **CPU/메모리 포화 여부 확인** (같은 대시보드 "포화도" 패널, 또는 직접 쿼리)
   ```promql
   sum(rate(container_cpu_usage_seconds_total{namespace="<서비스명>", container!="", container!="POD"}[5m]))
     / sum(kube_pod_container_resource_limits{namespace="<서비스명>", resource="cpu"})
   ```
   90% 넘으면 CPU throttling으로 인한 지연 — `HighCPUUsage` 알림도 같이 왔을 가능성 높음.
3. **DB 쿼리가 느려졌는지 확인** — [JVM/런타임 대시보드](.)의 "DB 커넥션 풀" 패널에서 활성 커넥션이 최대치에 가까운지 확인. 가까우면 커넥션 대기 시간이 응답시간에 그대로 더해짐.
4. **어떤 엔드포인트가 느린지 특정**
   ```promql
   histogram_quantile(0.99, sum(rate(http_server_requests_seconds_bucket{service="<서비스명>"}[5m])) by (le, uri))
   ```

## 완화

- **트래픽 급증 + 리소스 부족**: HPA(있다면) 확인, 없으면 replica 수동 증설
  ```bash
  kubectl scale deployment <서비스명> -n <서비스명> --replicas=<N>
  ```
- **DB 커넥션 풀 고갈**: `hikaricp-pool-exhausted.md` 런북 참고
- **특정 쿼리/로직이 원인**: 코드 수준 문제 — 서비스 담당자에게 전달, 필요시 해당 기능만 임시 우회(feature flag 등)

## 에스컬레이션
- p99가 계속 악화되며 사용자 이탈(주문/결제 실패 등)로 이어질 조짐이 있으면 즉시 서비스 담당자 호출.
