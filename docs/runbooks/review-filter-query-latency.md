# 리뷰 필터 조회 메인쿼리 vs 후속 호출 처리시간 괴리

> 이 항목은 아직 Alertmanager 알림이 연결되어 있지 않습니다. "백엔드" 대시보드를 보고
> 판단해야 하며, 증상이 심해지면 `HighErrorRate`/`HighLatencyP99` 알림으로 간접적으로
> 먼저 감지될 수 있습니다.

## 증상
- "백엔드" 대시보드(`petflow-backend`) → "리뷰 필터 조회" 로우 → **"필터조회 메인쿼리
  vs 후속 호출 평균시간"** 패널에서 두 선 중 하나가 눈에 띄게 벌어짐.
- **메인쿼리**(`ReviewJpaRepository.findRecentReviewIdsWithImageByProductId`)가 느려짐
  → 필터 조건/정렬 방식 또는 인덱스 문제.
- **후속 호출**(이미지/질문/추천수 조회 — `ReviewImageJpaRepository`,
  `ReviewQuestionJpaRepository`, `ReviewRecommendJpaRepository` 합산)이 느려짐 →
  아래 3개 레포지토리 중 어디가 원인인지 쪼개서 봐야 함.

## 확인 순서

1. **후속 호출 쪽이 원인이면 레포지토리별로 쪼개서 확인**:
   ```
   sum(rate(spring_data_repository_invocations_seconds_sum{namespace="review-service", repository=~"ReviewImageJpaRepository|ReviewQuestionJpaRepository|ReviewRecommendJpaRepository"}[$__rate_interval])) by (repository, method)
   /
   sum(rate(spring_data_repository_invocations_seconds_count{namespace="review-service", repository=~"ReviewImageJpaRepository|ReviewQuestionJpaRepository|ReviewRecommendJpaRepository"}[$__rate_interval])) by (repository, method)
   ```
   Grafana Explore에서 위 쿼리를 직접 실행하면 범인 레포지토리를 특정할 수 있음.
2. **이미지/리뷰 개수가 많은 상품에 요청이 몰리는지 확인** — 특정 상품 ID 조회가
   반복되면 N+1 유사 패턴(리뷰당 이미지 여러 건 조회) 의심.
3. **필터조회 p95/p99, 5xx 에러율 패널 동시 확인** — 여기서도 같이 튀면
   `HighLatencyP99`/`HighErrorRate` 알림으로 먼저 감지됐을 것.
4. **메인쿼리 쪽이 원인이면** — 필터 파라미터 조합(정렬/카테고리 등)별로 실행계획
   차이가 있는지 Postgres `EXPLAIN ANALYZE`로 확인.

## 완화

- 특정 후속 호출 레포지토리가 느리면 해당 쿼리/인덱스 우선 점검.
- 이미지 개수가 많은 상품에서 후속 호출이 느려지는 패턴이면 페이지네이션 또는
  이미지 조회 lazy loading 방식 검토.
- 메인쿼리가 원인이면 인덱스 추가 또는 정렬 조건 최적화 검토.

## 에스컬레이션
- 자체 알림 없음 — p95/5xx 에러율 패널을 통해 간접적으로 감지됨.
- 원인이 불명확하거나 재현이 안 되면 review-service 담당자 호출.
