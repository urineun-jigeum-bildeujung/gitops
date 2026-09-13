# HighErrorRate — 5xx 에러율 5% 초과

## 증상
- 알림: `{service} 5xx 에러율 5% 초과`
- 대시보드: [서비스 Golden Signals](.) — "에러율 (Errors)" 패널에서 해당 서비스 확인

## 확인 순서

1. **어느 URI에서 나는지 확인** (Grafana "에러/가용성" 대시보드 → "URI별 5xx 발생 건수" 패널)
   ```promql
   sum(increase(http_server_requests_seconds_count{service="<서비스명>", status=~"5.."}[10m])) by (uri, status)
   ```
2. **최근 배포 여부 확인** — ArgoCD에서 방금 sync된 게 있는지
   ```bash
   argocd app get <서비스명> --show-operation
   ```
   방금 배포 직후라면 롤백을 우선 고려 (아래 "완화" 참고).
3. **파드 로그 확인**
   ```bash
   kubectl logs -n <서비스명> -l app.kubernetes.io/name=<서비스명> --tail=200 --since=15m
   ```
   스택트레이스에서 어떤 예외(`AppException`, DB 커넥션 오류, NPE 등)인지 확인.
4. **의존 서비스/DB 상태 확인** — 이 서비스가 호출하는 DB(CNPG Postgres)나 외부 API가 죽어있는지.

## 완화

- **방금 배포가 원인**이면: ArgoCD에서 이전 revision으로 롤백
  ```bash
  argocd app rollback <서비스명>
  ```
- **DB/의존성 문제**면: 해당 컴포넌트 복구가 우선 (이 런북 범위 밖 — 해당 컴포넌트 런북 참고)
- **특정 엔드포인트만 문제**면: 코드 수정 필요 — 임시로 해당 라우트만 문제 있다고 판단되면 트래픽 영향 범위를 관찰하며 원인 서비스 담당자에게 에스컬레이션

## 에스컬레이션
- 5분 내로 원인 파악이 안 되고 에러율이 계속 오르면 서비스 담당자 + 인프라 담당자 동시 호출.
