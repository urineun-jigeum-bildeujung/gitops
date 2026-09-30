# 재고차감 API 응답시간 vs DB(재고이동기록) 처리시간 괴리

> 이 항목은 아직 Alertmanager 알림이 연결되어 있지 않습니다. "백엔드" 대시보드를 보고
> 판단해야 하며, 증상이 심해지면 `HighErrorRate`/`HighLatencyP99` 알림으로 간접적으로
> 먼저 감지될 수 있습니다.

## 증상
- "백엔드" 대시보드(`petflow-backend`) → "재고 차감" 로우 → **"재고차감 평균 응답시간
  vs DB(재고이동 기록) 평균시간"** 패널에서 두 선의 간격이 평소보다 벌어짐.
- API 전체 평균(`재고차감 API 전체 평균`)만 오르고 DB 평균(`DB(재고이동 기록) 평균`)은
  그대로 → DB 외 구간(HikariCP 커넥션 획득 대기, GC, 네트워크 등)이 원인.
- 두 선이 같이 오름 → `StockMovementJpaRepository.insertIfAbsent`(재고 이동 기록 저장
  쿼리) 자체가 느려진 것.
- 참고: 재고차감은 원자적 UPDATE 방식이라 "DB row lock 대기 시간" 자체는 현재 지표로
  볼 수 없음(HikariCP 커넥션 풀 대기와는 다른 개념).

## 확인 순서

1. **두 선이 벌어지는 패턴부터 구분** — 위 증상 항목 참고.
2. **HikariCP 패널(같은 대시보드 하단 "DB 커넥션 풀" 로우) 확인** — `product-service`의
   활성 커넥션이 최대치에 근접했는지. 근접했다면 [hikaricp-pool-exhausted.md](hikaricp-pool-exhausted.md)
   절차로 넘어갈 것.
3. **DB 평균 자체가 오른 경우** — Postgres에 직접 접속해서 느린 쿼리/락 대기 확인:
   ```sql
   SELECT pid, now() - query_start AS duration, state, query
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY duration DESC
   LIMIT 20;
   ```
4. **동시성/락 경합 의심** — 타임딜 등 특정 상품에 재고차감 요청이 몰리고 있는지
   확인(같은 상품 ID로 짧은 시간에 대량 호출). Golden Signals 대시보드에서 해당 시간대
   `product-service` RPS와 비교.
5. **최근 배포 이력 대조** — 스키마 변경이나 재고이동기록 테이블 관련 코드 변경이
   최근에 있었는지 확인.

## 완화

- **API 평균만 오르고 DB 평균 정상**: HikariCP 풀 크기/GC 문제로 보고
  [hikaricp-pool-exhausted.md](hikaricp-pool-exhausted.md) 절차 진행.
- **DB 평균 자체 상승**: 느린 쿼리 종료 검토, 재고이동기록 테이블 인덱스 점검.
- **특정 상품에 요청 집중(락 경합 의심)**: 해당 상품 재고차감 요청 큐잉/배치 처리 도입
  검토(단기적으로는 관찰만 하고 근본 대응은 별도 설계 필요).

## 에스컬레이션
- 이 패널은 원인 진단용이며 자체 알림은 없음 — 재고차감 5xx 에러율/p99가 같이
  튀면 그게 먼저 Discord로 알림이 감. 원인이 불명확하거나 재현이 안 되면
  product-service 담당자 호출.
