# PodCrashLooping — 15분 내 3회 초과 재시작

## 증상
- 알림: `{namespace}/{pod} 반복 재시작`
- `kubectl get pods`에서 `CrashLoopBackOff` 또는 `RESTARTS` 카운트가 계속 오름

## 확인 순서

1. **재시작 전 마지막 로그 확인** (재시작 후엔 이전 로그가 사라지므로 `--previous` 필수)
   ```bash
   kubectl logs -n <네임스페이스> <파드명> --previous --tail=200
   ```
2. **종료 코드/사유 확인**
   ```bash
   kubectl describe pod -n <네임스페이스> <파드명>
   ```
   `Last State` 섹션의 `Exit Code`, `Reason` 확인:
   - `OOMKilled` → 메모리 부족, `high-memory-usage.md` 런북 + limit 상향 검토
   - `Error` (0이 아닌 종료 코드) → 애플리케이션 시작 실패, 로그의 스택트레이스 확인
   - `Completed`인데 반복 재시작 → livenessProbe 설정 오류 의심
3. **최근 배포/설정 변경 여부**
   ```bash
   argocd app history <네임스페이스>
   ```
   방금 배포 직후 시작된 문제면 애플리케이션 시작 자체가 실패하는 것(설정값 오류, DB 마이그레이션 실패 등).
4. **의존 리소스(DB/Secret) 확인** — 시작 시점에 필요한 Secret/ConfigMap이 없거나 DB 연결이 안 되면 부트스트랩 단계에서 계속 죽음.
   ```bash
   kubectl get secret,configmap -n <네임스페이스>
   ```

## 완화

- **방금 배포가 원인**: `argocd app rollback <네임스페이스>`로 이전 버전 복귀
- **OOMKilled**: `charts/generic-service` values의 `resources.limits.memory` 상향 후 재배포
- **의존 리소스 누락**: 해당 Secret/ConfigMap 먼저 생성/복구 후 파드 재시작

## 에스컬레이션
- 롤백해도 계속 CrashLoop이면 인프라(노드/스토리지) 문제일 수 있음 — 인프라 담당자 호출.
