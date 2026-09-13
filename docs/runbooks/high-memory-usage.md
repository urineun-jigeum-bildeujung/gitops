# HighMemoryUsage — 메모리 사용률 limit 대비 90% 초과

## 증상
- 알림: `{namespace}/{pod} 메모리 사용률 90% 초과`
- 방치하면 `OOMKilled`로 이어져 `pod-crash-looping.md` 상황이 됨 — 이 알림은 그 전 단계에서 미리 잡는 용도

## 확인 순서

1. **추세 확인** — Grafana [JVM/런타임 대시보드](.)에서 힙 사용량이 서서히 계속 오르기만 하는지(메모리 누수 의심) 아니면 트래픽에 비례해서 오르내리는지 확인.
   ```promql
   sum(jvm_memory_used_bytes{area="heap", service="<서비스명>"})
   ```
2. **JVM 힙 vs 컨테이너 전체 메모리 구분** — `container_memory_working_set_bytes`는 힙+메타스페이스+스레드 스택+Direct Buffer 등 전체를 포함. 힙은 안 늘었는데 컨테이너 메모리만 늘면 Non-heap(메타스페이스, 네이티브 메모리) 문제일 수 있음.
3. **최근 배포 이후 시작된 문제인지** — 새 코드에 캐시/리스트에 계속 쌓기만 하고 안 비우는 로직이 들어갔을 가능성.

## 완화

- **일시적 트래픽 급증이 원인**: 자연 해소 기다리거나 replica 증설로 개별 파드 부하 분산
- **점진적 누수 패턴**: 근본 수정 전까지 임시로 `kubectl rollout restart`로 주기적 재시작(임시방편일 뿐, 반드시 원인 조사 필요)
- **limit 자체가 너무 타이트**: 실제 필요 메모리 대비 여유가 없었던 거라면 `charts/generic-service` values의 `resources.limits.memory` 상향 검토 (단, 이건 증상 회피지 원인 해결 아님)

## 에스컬레이션
- 짧은 시간 안에 OOMKilled까지 갈 것 같으면(추세선상 임박) 서비스 담당자에게 즉시 공유.
