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
   ```promql
   jvm_memory_used_bytes{area="nonheap", id="Metaspace", namespace="<네임스페이스>"}
   jvm_memory_max_bytes{area="nonheap", id="Metaspace", namespace="<네임스페이스>"}
   ```
   **Metaspace가 실사용량은 크지 않은데 max가 `-1`(무제한)로 나오면, 힙/컨테이너 여유가 없어서 컨테이너 전체 메모리를 압박하는 구조적 원인일 수 있다(2026-09-29 order-service 3회 OOMKilled의 실제 원인 — gitops#109/#111 참고)**: `charts/generic-service`가 베이스 이미지 기본값(`-XX:MaxRAMPercentage=75.0`, Metaspace 무제한)에 그대로 맡기면 힙 상한이 실사용량보다 훨씬 크게 잡혀서 Metaspace/네이티브 메모리가 쓸 공간이 부족해짐. 실제 적용된 JVM 플래그를 직접 확인:
   ```bash
   POD=$(kubectl get pod -n <서비스명> -l app.kubernetes.io/name=generic-service -o jsonpath='{.items[0].metadata.name}')
   kubectl exec -n <서비스명> "$POD" -- sh -c 'cat /proc/1/cmdline | tr "\0" " "'
   ```
   `-Xmx`/`-XX:MaxMetaspaceSize`가 안 보이면 `generic-service.jvmMemoryEnv`(`_helpers.tpl`)가 이 서비스에 적용 안 되고 있는 것(현재 `mtls.enabled`로 게이팅됨). **`-XX:MaxRAMPercentage`로 값을 넣으면 이미지 ENTRYPOINT에 이미 박혀있는 `-XX:MaxRAMPercentage=75.0`한테 밀려서(같은 플래그 중복 시 나중 값이 이김) 무시된다 — 반드시 `-Xmx`(절대값)로 지정해야 순서 무관하게 확실히 적용된다.**
3. **최근 배포 이후 시작된 문제인지** — 새 코드에 캐시/리스트에 계속 쌓기만 하고 안 비우는 로직이 들어갔을 가능성.

## 완화

- **일시적 트래픽 급증이 원인**: 자연 해소 기다리거나 replica 증설로 개별 파드 부하 분산
- **점진적 누수 패턴**: 근본 수정 전까지 임시로 `kubectl rollout restart`로 주기적 재시작(임시방편일 뿐, 반드시 원인 조사 필요)
- **limit 자체가 너무 타이트**: 실제 필요 메모리 대비 여유가 없었던 거라면 `charts/generic-service` values의 `resources.limits.memory` 상향 검토 (단, 이건 증상 회피지 원인 해결 아님)
- **힙 상한 과다 + Metaspace 무제한(2번 항목 패턴)**: `_helpers.tpl`의 `generic-service.jvmMemoryEnv`에서 `-Xmx`/`-XX:MaxMetaspaceSize` 값을 실측 기반으로 조정. limit 상향과 반드시 같이 검토 — 힙/Metaspace 상한 합이 limit에 거의 다 차면 CodeHeap/스레드/네이티브 메모리 쓸 공간이 없어 여전히 OOM 가능(gitops#111에서 이 계산으로 값 재조정한 이력 참고).

## 에스컬레이션
- 짧은 시간 안에 OOMKilled까지 갈 것 같으면(추세선상 임박) 서비스 담당자에게 즉시 공유.
