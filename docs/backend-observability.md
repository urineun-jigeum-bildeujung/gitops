# 백엔드 관측성 운영 문서

## 1. 전체 그림

백엔드 7개 서비스(auth/member/product/order/payment/review/notification-service)는
전부 Prometheus 메트릭(Spring Boot Actuator) 기반으로 계측되고, 대시보드는 목적에 따라
4종으로 분리되어 있다.

| 대시보드 | 범위 | 용도 |
|---|---|---|
| **Golden Signals** (`petflow-golden-signals`) | 서비스 전체(namespace 선택형) | 트래픽/에러율/지연시간/포화도 4대 핵심 지표 |
| **에러 / 가용성** (`petflow-errors-availability`) | 서비스 전체(namespace 선택형) | 지금 뭐가 죽어있는지/반복 재시작하는지 |
| **JVM / 런타임** (`petflow-jvm-runtime`) | 서비스 전체(namespace 선택형) | 힙/GC/스레드/DB 커넥션 풀 등 프로세스 내부 상태 |
| **백엔드** (`petflow-backend`) | product/order/review/notification-service 특정 API·쿼리 | 백엔드팀 요구사항(2026-09-30) 기반 세부 지표 |

> 모든 서비스가 같은 Helm 차트(`charts/generic-service`)를 쓰기 때문에 파드 이름도
> `service` 라벨도 전부 `generic-service`로 동일하다 — 그래서 위 대시보드들은 전부
> 파드 이름이 아니라 **`namespace` 라벨**로 서비스를 구분한다(Golden
> Signals/에러·가용성/JVM 대시보드는 상단 `$namespace` 드롭다운으로 직접 선택 가능).

## 2. Golden Signals 대시보드

- **트래픽**: 초당 요청 수(RPS) — namespace/uri/method별
- **에러율**: 5xx 에러율(%) — namespace별
- **지연시간**: p50/p95/p99 — namespace별
- **포화도**: CPU/메모리 사용률(limit 대비 %) — namespace/pod별

## 3. 에러 / 가용성 대시보드

- **가용성**: 서비스 up/down 상태 타임라인(0=DOWN 빨강, 1=UP 초록)
- **에러 상세**: URI별 5xx 발생 건수
- **파드 안정성**: 1시간 누적 재시작 횟수, Ready 아닌 파드 수

## 4. JVM / 런타임 대시보드

- **힙 메모리**: 힙 사용량 vs 최대치
- **GC**: GC 정지 시간 비율
- **스레드/CPU**: 라이브 스레드 수, 프로세스 CPU 사용률
- **DB 커넥션 풀(HikariCP)**: 활성 커넥션 vs 최대치

## 5. 백엔드 세부 대시보드 (`petflow-backend`)

2026-09-30 백엔드팀(문시원/노여진) 요구사항 조사서 기반으로 신설. 위 3개 범용
대시보드로는 못 보여주는 "uri별·쿼리별" 세부 지표 전용:

- 상품 검색/상세조회 p95·p99·5xx 에러율 (product-service)
- 재고차감 p95·p99·5xx 에러율 + **API 전체 평균 vs DB(재고이동기록) 평균 시간 비교**
- 주문 생성 p95·p99·5xx 에러율 (order-service)
- 리뷰 필터조회 p95·p99·5xx 에러율 + **메인쿼리 vs 후속 호출(이미지/질문/추천수) 평균 시간 비교**
- 타임딜 알림 스케줄러 성공/실패 건수(10분 누적) + 소요시간(평균/최대) (notification-service)
- HikariCP 활성 vs 최대 커넥션 (product/order/review/notification-service)

## 6. 알림 8종 (Golden Signals 기반, Alertmanager `petflow-golden-signals`)

전부 `namespace=~".+-service"` 스코프(7개 서비스 전체 대상), 런북과 1:1로 연동됨.

| 알림 | 조건 | for | 심각도 | 런북 |
|---|---|---|---|---|
| **HighErrorRate** | 5xx 에러율 5% 초과 | 5m | critical | [high-error-rate.md](runbooks/high-error-rate.md) |
| **HighLatencyP99** | p99 지연시간 1초 초과 | 5m | warning | [high-latency-p99.md](runbooks/high-latency-p99.md) |
| **ServiceDown** | Prometheus 스크레이프 무응답 | 2m | critical | [service-down.md](runbooks/service-down.md) |
| **PodCrashLooping** | 15분간 3회 초과 재시작 | 5m | critical | [pod-crash-looping.md](runbooks/pod-crash-looping.md) |
| **PodNotReady** | Not Ready 지속 | 5m | warning | [pod-not-ready.md](runbooks/pod-not-ready.md) |
| **HighMemoryUsage** | 메모리 사용률 limit 대비 90% 초과 | 5m | warning | [high-memory-usage.md](runbooks/high-memory-usage.md) |
| **HighCPUUsage** | CPU 사용률 limit 대비 90% 초과 | 10m | warning | [high-cpu-usage.md](runbooks/high-cpu-usage.md) |
| **HikariCPConnectionPoolExhausted** | 활성 커넥션이 최대치 도달 | 5m | critical | [hikaricp-pool-exhausted.md](runbooks/hikaricp-pool-exhausted.md) |

## 7. Discord 라우팅 — 클라우드 인프라 채널로 연동 완료

8개 알림 전부 **Alertmanager → `discord-infra` receiver → 클라우드 인프라 팀 Discord
채널**로 발송되도록 연동되어 있다(`platform/30-kube-prometheus-stack/manifests/alertmanager-config-discord.yaml`).

- 발송 메시지에 상태(발생/해소)/요약/설명/발생 시각(KST)/**대응 방법(runbook_url)**까지
  전부 포함 — 알림만 보고도 바로 해당 런북으로 이동 가능.
- 같은 알림이 여러 서비스에서 동시에 뜨면 `alertname` 기준으로 그룹핑해서 메시지 1개로
  합침(Discord 웹훅 429 rate limit 방지 목적, 2026-09-30 튜닝).
- 프론트엔드 알림 2종(`FrontendJsErrorSpike`/`FrontendOrderApiFailureSustained`)은
  별도 `discord-frontend` receiver로 분리되어 있어 백엔드 8개와 섞이지 않는다
  (자세한 내용은 [frontend-observability.md](frontend-observability.md) 참고).

## 8. 추가 계측 — 아직 알림 미연동 (런북만 존재)

백엔드팀 요구사항 반영 중 새로 계측했지만, 아직 Alertmanager 알림이 없어서
**대시보드를 보고 사람이 직접 판단해야 하는 항목** 4개:

- [`inventory-deduction-db-latency.md`](runbooks/inventory-deduction-db-latency.md) — 재고차감 API vs DB(재고이동기록) 처리시간 괴리
- [`review-filter-query-latency.md`](runbooks/review-filter-query-latency.md) — 리뷰 필터 메인쿼리 vs 후속 호출 처리시간 괴리
- [`fcm-send-failure.md`](runbooks/fcm-send-failure.md) — FCM 발송 실패율/중복 발송 (코드 계측은 됐지만 대시보드 패널조차 아직 없음, PromQL 직접 실행 필요)
- [`scheduler-duration-anomaly.md`](runbooks/scheduler-duration-anomaly.md) — 타임딜 알림 스케줄러 실패/소요시간 증가

## 9. 알려진 제약사항

- 상품 상세조회의 실제 DB 쿼리 시간은 계측 불가 — product-service가 계측 중인
  레포지토리 메서드에 상세조회 쿼리 자체가 포함되어 있지 않음.
- 재고 차감의 "원자적 UPDATE 대기 시간"(DB row lock 대기)은 현재 지표로 볼 수 없음.
- FCM 발송 성공/실패, 중복 발송 감지는 코드 계측만 있고 대시보드 패널은 아직 없음.
