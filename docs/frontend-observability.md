# 프론트엔드(web) 관측성 운영 문서

## 1. 전체 그림

프론트엔드는 서버(SSR)와 브라우저(클라이언트) 두 축을 다르게 계측한다.

| 축 | 계측 방식 | 수집 경로 | 데이터소스 |
|---|---|---|---|
| **SSR 서버(Next.js/Node)** | prom-client 기본 메트릭 | Prometheus가 `web` 네임스페이스 직접 스크레이프 | Prometheus |
| **브라우저(클라이언트)** | Grafana Faro SDK | 브라우저 → Alloy(수집기) → Loki/Tempo | Loki(로그) / Tempo(트레이스) |

## 2. 브라우저 계측 (Grafana Faro RUM)

### 프론트 코드 (web 레포)

- `src/instrumentation-client.ts` — Next.js가 인식하는 진입점. `window.load` 이후에만 Faro를 동적 import해서 초기화한다(Faro+OpenTelemetry gzip 71KB, 첫 화면 로딩과 경쟁하지 않도록).
- `src/shared/lib/observability/faro.ts` — 실제 초기화:
  ```ts
  initializeFaro({
    url: FARO_CONFIG.url,
    apiKey: FARO_CONFIG.apiKey,
    app: { name: "petflow-web", environment: process.env.NODE_ENV },
    instrumentations: [...getWebInstrumentations(), new TracingInstrumentation()],
  });
  ```
  - `getWebInstrumentations()`: 에러, 콘솔, 웹바이탈(측정치), 세션, 화면 이벤트 — Faro 기본 세트 전부 수집.
  - `TracingInstrumentation`: fetch/XHR에 `traceparent` 헤더 주입 → 같은 origin(`/api/v1/...`) 호출만 백엔드 트레이스와 연결됨. Toss/Firebase 등 외부 origin은 CORS가 `traceparent`를 허용하지 않아 연결되지 않음(의도된 제약).
- `src/shared/lib/report-error.ts` — 콘솔에 찍기 전 1차 필터. `ApiError`는 `status`/`errorCode`만, 일반 `Error`는 `error.name`만 기록하고 `.message`/`problem.detail` 등 원문은 기록하지 않는다.
- 로컬 개발환경에서는 Faro URL/키를 비워둔다(localhost origin이면 수집기가 preflight를 400으로 거부하기 때문).

### 수집기 (gitops, Alloy)

`platform/30-alloy/application.yaml`의 `faro.receiver "app"` 블록이 포트 12347로 브라우저 데이터를 직접 수신한다.

- 공개 경로: `https://leechs.shop/collect` (⚠️ 임시 도메인, 추후 변경 가능)
- 인증: `FARO_API_KEY` — AWS Secrets Manager(`petflow/observability/faro-collector-api-key`) → ExternalSecret `faro-collector`(`platform/91-external-secrets-config/manifests/app-bindings-alloy.yaml`) → K8s Secret `faro-collector`. 2026-09-30 기준 라이브로 정상 동작 확인됨(`SecretSynced=True`, Alloy 파드 전부 정상).
- 로그 → `loki.process "faro_redact"` → Loki
- 트레이스 → `otelcol.processor.attributes "faro_redact"` → Tempo

### 개인정보 마스킹 (2차 방어선)

프론트 코드(`report-error.ts`)가 1차로 거르고, **Alloy가 최종 마스킹**을 한다(실제 방어선은 여기). 정규식으로 다음을 가린다:

- URL: `auth/callback`, `payment/done`, `signup`, `mypage/address/search` 뒤 쿼리스트링 전체
- 헤더: `authorization`, `idempotency-key`, `x-api-key`
- 값(JSON/logfmt 둘 다 커버): `accessToken`, `refreshToken`, `code`, `paymentKey`, `customerKey`, `tossOrderId`, `receiver`, `phone`, `address`, `detail`, `zipCode`, `deliveryNote`, `nickname`

Faro SDK 자체는 필터링하지 않으며, 수집기(Alloy)가 가려준다는 것이 전제다.

## 3. 대시보드 — "프론트엔드 (web)" (`petflow-frontend-web`)

### SSR 서버 로우 (Prometheus, `namespace="web"`)

메모리(RSS), 힙 사용량, 이벤트루프 지연, CPU 사용량, GC 시간 비율, 파드 재시작 수 — Node.js 프로세스 자체 상태만 본다.

> "SSR 요청량/렌더시간" 패널은 만들 수 없다 — `web`의 `/metrics`가 prom-client 기본 메트릭만 노출하고 HTTP 요청 카운터/히스토그램이 없기 때문(코드에 미들웨어 추가 필요, gitops 쪽 설정만으론 불가능).

### 브라우저(Faro RUM) 로우 (Loki)

- Core Web Vitals p75: LCP / FCP / INP / TTFB / CLS
- 세션 수, API 실패율(%), API 응답지연 p75, API 총 호출 수
- API 응답 상태코드별 건수 (상태코드 0 = 네트워크 에러/CORS 차단/타임아웃)
- 이벤트 종류별 발생량(event/measurement/exception/log), 예외 발생 수, 최근 예외 로그(50줄, 마스킹된 상태로 표시)

## 4. 알림 2종 (Loki Ruler 기반 — 백엔드 8개와 다른 구조)

백엔드 8개는 Prometheus `PrometheusRule` CRD 기반인데, 이 2개는 브라우저 로그(Loki) 기반이라 **Loki 자체 Ruler**를 사용한다(`platform/30-loki/application.yaml`의 `rulerConfig` → Alertmanager로 직접 전송).

| 알림 | 조건 | 심각도 | 비고 |
|---|---|---|---|
| **FrontendJsErrorSpike** | 최근 10분간 JS 예외(`kind=exception`) 10건 초과, 5분 지속 | warning | 평소 10분당 1~2건 기준 |
| **FrontendOrderApiFailureSustained** | `/api/v1/{carts,orders,payments}` 호출 실패율(4xx/5xx/네트워크에러) 30% 초과, 5분 지속 | **critical** | "재시도 없이 이탈하는 구간이라 탐지가 늦으면 이탈자가 더 늘어난다"는 프론트팀 요청 사유 |

> ⚠️ **두 임계값 모두 dev 환경 잠정치다**(2026-09-30 실측: JS 예외 평균 1.6/10분, 주문 API 실패율 평균 21%). 실사용자 트래픽이 생기면 프론트팀과 재협의해서 조정해야 한다.

## 5. Discord 라우팅

2026-09-30에 인프라 채널에서 분리 완료됨:

```
알림 발생 → alertname으로 분기
├─ 백엔드 8개(HighErrorRate 등)              → discord-infra 채널
└─ 프론트엔드 2개(JsErrorSpike/OrderApiFailure) → discord-frontend 채널
```

두 receiver 모두 메시지 포맷은 동일(상태/요약/설명/발생시각(KST)/대응방법 링크), 웹훅 시크릿만 다르다.

## 6. 런북

- [`frontend-js-error-spike.md`](runbooks/frontend-js-error-spike.md): 최근 예외 로그 확인 → 배포 직후 여부 확인(`argocd app rollback dev-web`로 롤백 가능) → hydration 실패(`Hydration failed`, `Minified React error #418/#423` 등)인지 일반 JS 에러인지 구분
- [`frontend-order-api-failure.md`](runbooks/frontend-order-api-failure.md): 상태코드별 원인 분기 — **0(네트워크/CORS/타임아웃)**은 게이트웨이·네트워크 문제, **5xx**는 백엔드 문제(`high-error-rate.md` 등과 교차 확인), **4xx**는 프론트 요청 스키마 문제 또는 결제 테스트 키 불일치 의심

## 7. 알려진 제약사항

- 임계값 2개(JS 예외 10건/10분, 주문 API 실패율 30%)는 dev 환경 잠정치 — 실트래픽 기준으로 재조정 필요.
- Faro 수집 엔드포인트 도메인(`leechs.shop`)은 임시이며 추후 변경될 수 있다.
- SSR 요청량/렌더시간 지표는 `web`의 코드 변경(HTTP 미들웨어 계측 추가) 없이는 대시보드에 추가할 수 없다.
