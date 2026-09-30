# FrontendOrderApiFailureSustained — 주문 흐름(장바구니/주문/결제) API 실패율 급증

## 증상
- 알림: `web 주문 흐름(장바구니/주문/결제) API 실패율 급증`
- 브라우저에서 잰(Faro `faro.tracing.fetch`) `/api/v1/{carts,orders,payments}` 호출 실패율(4xx/5xx 또는 네트워크 에러)이 30% 초과, 5분 이상 지속
- **critical** — 프론트엔드팀이 "사용자가 재시도하지 않고 나가는 구간이라 늦게 알수록 놓치는 사용자가 쌓인다"고 명시한 흐름

## 확인 순서

1. **실패 상세 확인** (Grafana "프론트엔드 (web)" 대시보드 → "API 응답 상태 코드별 건수" 패널에서 어떤 상태코드가 많은지 먼저 확인)
   ```logql
   {service_name=~"petflow-web|unknown_service"} |= "app_name=petflow-web" |= "faro.tracing.fetch" |= "carts" or "orders" or "payments"
   ```
2. **상태코드 0(네트워크 에러)인지 4xx/5xx인지 구분** — 원인이 완전히 다름:
   - **0 (네트워크 에러/CORS 차단/타임아웃)**: 게이트웨이/네트워크 경로 문제 가능성. `api-gateway` 네임스페이스 상태, NetworkPolicy 확인.
   - **5xx**: 백엔드(order-service/payment-service 등) 문제 — `high-error-rate.md`, `service-down.md` 런북과 함께 백엔드 쪽도 확인.
   - **4xx**: 프론트가 잘못된 요청을 보내고 있거나(스키마 불일치), 정당한 사용자 입력 오류가 몰린 것일 수 있음 — 실제 요청/응답 바디는 민감정보 마스킹 때문에 로그에 없으므로, 재현 필요.
3. **백엔드 쪽 골든시그널 알림과 겹치는지 확인** — `HighErrorRate`/`ServiceDown`/`HikariCPConnectionPoolExhausted`가 같은 시간대에 order-service/payment-service/member-service에서도 떴으면 원인은 백엔드에 있고 이 알림은 그 증상이 브라우저까지 전파된 것.
4. **결제 흐름이면 PG(토스) 테스트 연동 이슈인지 확인** — 결제는 실결제가 아니라 PG 테스트 연동(`test_sk_...`/`test_gck_...` 키 세트)이라, 두 키가 세트로 안 맞으면 결제 승인 자체가 실패할 수 있음.

## 완화

- **백엔드가 원인**: 해당 백엔드 런북(`service-down.md`, `high-error-rate.md`, `hikaricp-pool-exhausted.md`)으로 넘어가서 처리
- **게이트웨이/네트워크 문제**: `api-gateway` NetworkPolicy, mTLS 설정 확인 (사례: gitops#106 mTLS 관리포트 SSL 상속 버그)
- **프론트 요청 스키마 문제**: 최근 배포 이력 확인 후 롤백 검토, 코드 수정 필요시 프론트엔드 담당자 전달

## 에스컬레이션
- 임계값(30%)은 2026-09-30 dev 환경(목데이터 섞인 테스트 트래픽) 실측 기준 잠정치임 — 그 시점 평균 실패율이 이미 21%였을 만큼 dev 환경 자체가 노이즈가 많으니, 실사용자 트래픽이 생기면 프론트엔드팀과 반드시 재조정 필요(`platform/30-loki/manifests/frontend-alert-rules.yaml` 참고).
- critical 알림이라 5분 지속되면 바로 백엔드/프론트엔드/인프라 담당자 동시 호출.
