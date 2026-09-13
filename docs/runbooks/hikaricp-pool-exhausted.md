# HikariCPConnectionPoolExhausted — DB 커넥션 풀 고갈

## 증상
- 알림: `{service} DB 커넥션 풀 고갈`
- `hikaricp_connections_active >= hikaricp_connections_max`가 5분 이상 지속
- 사용자 입장에서는 요청이 DB 커넥션을 못 받아서 응답이 느려지거나(`HighLatencyP99`) 타임아웃/에러(`HighErrorRate`)로 나타남

## 확인 순서

1. **커넥션을 오래 붙잡고 있는 쿼리가 있는지 확인** — 느린 쿼리나 트랜잭션이 안 끝나고 있으면 커넥션이 반환이 안 됨.
   ```sql
   -- Postgres에 직접 접속해서
   SELECT pid, now() - query_start AS duration, state, query
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY duration DESC
   LIMIT 20;
   ```
2. **트래픽이 갑자기 늘어서 풀 자체가 부족해진 건지** — Golden Signals 대시보드 RPS와 시간대 비교.
3. **커넥션 누수 의심** — 코드에서 트랜잭션/커넥션을 명시적으로 닫지 않는 경로가 있는지(예: 예외 발생 시 finally 없이 종료). 배포 이력과 대조해서 최근에 추가된 코드인지 확인.

## 완화

- **느린 쿼리가 원인**: 해당 쿼리 강제 종료 고려(운영 중인 트랜잭션 kill은 신중하게)
  ```sql
  SELECT pg_terminate_backend(<pid>);
  ```
- **풀 크기 자체가 부족**: `application.yml`의 `spring.datasource.hikari.maximum-pool-size` 상향 검토 — 단, DB 쪽 `max_connections` 여유도 같이 확인해야 함(서비스별로 늘리면 DB 전체 커넥션 수 합계가 한도를 넘을 수 있음)
- **누수 의심**: 임시로 파드 재시작하면 풀은 초기화되지만 근본 원인 아님 — 반드시 코드 조사 필요

## 에스컬레이션
- 여러 서비스에서 동시에 발생하면 DB 자체의 `max_connections` 한도 문제일 수 있음 — DB 담당/인프라 담당자 호출.
