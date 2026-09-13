# PodNotReady — 5분 이상 Ready 상태 아님

## 증상
- 알림: `{namespace}/{pod} Not Ready 지속`
- `kubectl get pods`에서 `READY` 컬럼이 `0/1`로 계속 남아있음 (재시작은 안 하지만 트래픽을 못 받는 상태)

## 확인 순서

1. **readinessProbe 실패 사유 확인**
   ```bash
   kubectl describe pod -n <네임스페이스> <파드명>
   ```
   `Events` 섹션에서 `Readiness probe failed` 메시지와 실패 원인(타임아웃/커넥션 거부 등) 확인.
2. **앱이 시작은 됐는지 로그 확인**
   ```bash
   kubectl logs -n <네임스페이스> <파드명> --tail=100
   ```
   Spring Boot 기동 로그에서 "Started XxxApplication"이 안 찍혔으면 초기화 중 어딘가에서 멈춘 것 — DB 연결 대기, 외부 API 호출 대기 등.
3. **DB/외부 의존성 응답 확인** — 부트스트랩 시점에 필요한 리소스가 늦게 뜨는 경우(예: CNPG Postgres가 아직 준비 안 됨) 흔히 발생.
4. **health 엔드포인트 직접 호출**
   ```bash
   kubectl exec -n <네임스페이스> <파드명> -- curl -sf localhost:8080/actuator/health
   ```

## 완화

- 의존 리소스가 늦게 뜬 경우: 의존 리소스 정상화되면 자동으로 Ready 전환됨(추가 조치 불필요)
- 계속 실패하면 readinessProbe의 `initialDelaySeconds`/`timeoutSeconds`가 너무 빡빡한 건 아닌지 차트 values 확인
- 근본 원인(DB 연결 실패 등)이 있으면 그 리소스부터 복구

## 에스컬레이션
- 여러 파드가 동시에 Not Ready면 공유 의존성(DB, 공통 Secret) 문제일 가능성 높음 — 인프라 담당자 호출.
