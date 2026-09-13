# HighCPUUsage — CPU 사용률 limit 대비 90% 초과 (10분 이상)

## 증상
- 알림: `{namespace}/{pod} CPU 사용률 90% 초과`
- CPU는 limit을 넘기면 OOMKilled처럼 파드가 죽진 않고 대신 **throttling**(강제로 느려짐) 발생 → 보통 `HighLatencyP99` 알림과 같이 옴

## 확인 순서

1. **트래픽 증가가 원인인지 확인** — Golden Signals 대시보드의 "초당 요청 수(RPS)"와 시간대를 겹쳐보기.
2. **특정 요청/로직이 CPU를 많이 쓰는지** — 최근 배포에 무거운 연산(예: 반복문 안에서 비효율적 쿼리, 이미지 처리 등)이 추가됐는지 코드 변경 이력 확인.
3. **GC가 CPU를 많이 먹는지** — [JVM/런타임 대시보드](.)의 "GC 정지 시간" 패널 확인. GC가 잦으면 힙이 너무 작게 잡혀서 CPU를 갉아먹는 것일 수 있음(`high-memory-usage.md`와 연계해서 볼 것).

## 완화

- **트래픽 증가**: replica 증설로 분산
  ```bash
  kubectl scale deployment <서비스명> -n <서비스명> --replicas=<N>
  ```
- **특정 로직이 원인**: 코드 수정 필요 — 서비스 담당자 전달
- **limit이 너무 타이트**: `charts/generic-service` values의 `resources.limits.cpu` 상향 검토 (노드 여유 자원 먼저 확인 — DEV 노드가 c7i-flex.large 2대라 여유가 많지 않음)

## 에스컬레이션
- CPU throttling이 지속되며 지연시간이 계속 악화되면 서비스 담당자 + 인프라 담당자 동시 확인 필요.
