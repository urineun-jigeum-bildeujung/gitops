# FrontendJsErrorSpike — web 브라우저 JS 예외 급증

## 증상
- 알림: `web 프론트엔드 JS 예외 급증`
- 최근 10분간 브라우저에서 잡힌 JS 예외(Faro `kind=exception`)가 10건 초과 (평소 10분당 1~2건 수준)
- 백엔드 알림 8개(petflow-golden-signals)와 달리 Prometheus 메트릭이 아니라 **Loki 자체 Ruler**가 Faro 로그를 보고 판단함

## 확인 순서

1. **최근 예외 목록 직접 확인** (Grafana "프론트엔드 (web)" 대시보드 → "최근 예외" 패널, 또는 LogQL)
   ```logql
   {service_name=~"petflow-web|unknown_service"} |= "app_name=petflow-web" |= "kind=exception"
   ```
   같은 스택트레이스/메시지가 반복되는지, 아니면 여러 종류가 섞여 있는지 확인.
2. **최근 배포 직후인지 확인** — Jenkins에서 `web` 파이프라인의 최근 빌드/배포 시각과 알림 발생 시각을 대조. "배포 전 대비 증가"가 프론트엔드팀이 이 알림을 요청한 핵심 이유임.
   ```bash
   argocd app get dev-web --show-operation
   ```
3. **하이드레이션 실패인지 일반 JS 에러인지 구분** — 지금 알림/대시보드는 이 둘을 구분하지 않고 `kind=exception`으로 뭉뚱그림. 예외 메시지에 `Hydration failed`, `Text content does not match`, `Minified React error #418/#423` 등이 보이면 하이드레이션 실패 — 화면은 정상으로 보이는데 버튼/인터랙션이 안 먹는 케이스라 특히 주의.
4. **특정 브라우저/페이지에 몰려있는지** — 최근 예외 로그의 `browser_name`, `page_url` 필드로 특정 환경에서만 나는지 확인.

## 완화

- **방금 배포가 원인**: `argocd app rollback dev-web`으로 이전 버전 복귀 (web은 Deployment라 blueGreen/canary 없이 롤링 롤백)
- **하이드레이션 실패**: 서버(SSR)와 클라이언트(브라우저)가 그리는 HTML이 달라서 발생 — 보통 `Date`/`Math.random()`처럼 렌더링마다 값이 바뀌는 코드, 혹은 브라우저 확장 프로그램이 DOM을 건드리는 경우. 코드 수정 필요, 프론트엔드 담당자 전달.
- **일반 JS 에러**: 스택트레이스 기준으로 프론트엔드 담당자에게 전달.

## 에스컬레이션
- 임계값(10건/10분)은 2026-09-30 dev 환경 실측 기준으로 정한 잠정치임 — 실사용자 트래픽이 생기면 프론트엔드팀과 재조정 필요(`platform/30-loki/manifests/frontend-alert-rules.yaml` 참고).
- 계속 늘어나며 여러 페이지/여러 브라우저에서 동시에 나면 프론트엔드 담당자 즉시 호출.
