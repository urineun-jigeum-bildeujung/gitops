# 타임딜 알림 스케줄러 실패 / 소요시간 증가

> 이 항목은 아직 Alertmanager 알림이 연결되어 있지 않습니다. "백엔드" 대시보드를 보고
> 판단해야 합니다.

## 증상
- "백엔드" 대시보드(`petflow-backend`) → "타임딜 알림 스케줄러" 로우 →
  **"스케줄러 실행 성공/실패 건수 (10분 누적)"** 패널에 `outcome != SUCCESS` 막대가
  나타남.
- **"스케줄러 소요시간 (평균 / 최대)"** 패널의 평균 또는 최대값이 평소보다 크게
  증가 — 특히 최대값이 스케줄 실행 주기에 근접하거나 넘으면, 다음 실행과 겹쳐서
  [fcm-send-failure.md](fcm-send-failure.md)의 중복 발송으로 이어질 수 있음.

## 확인 순서

1. **실패 건수 확인**:
   ```
   sum(increase(tasks_scheduled_execution_seconds_count{namespace="notification-service", code_function="checkTimeDeals", outcome!="SUCCESS"}[10m])) by (outcome)
   ```
2. **소요시간이 실행 주기에 근접/초과하는지 확인** — 근접/초과하면 겹침 실행 가능성
   있음, FCM 중복 발송 카운트(`fcm_send_duplicate_total`)도 같이 확인.
3. **실패 시 예외 로그 확인** — `TimeDealNotificationScheduler` 및
   `TimeDealNotificationPersistenceService` 로그에서 실패 단계 구분
   (DB 조회 실패 / FCM 발송 단계 실패).
4. **처리 대상 급증 여부 확인** — 최근 등록된 타임딜 건수가 급증했는지 확인
   (처리 대상 자체가 많아져서 소요시간이 늘어난 것인지).

## 완화

- **처리 대상 급증이 원인**: 배치 크기 조정 또는 병렬 처리 도입 검토.
- **특정 단계(DB/FCM)에서 반복 실패**: 해당 단계 재시도 로직 유무 확인, 없으면
  추가 검토.
- **실행 시간이 주기를 넘어 겹침 발생**: 스케줄 주기 조정 또는 실행 중복 방지용
  락(예: `ShedLock`) 적용 검토(현재 없음).

## 에스컬레이션
- 자체 알림 없음 — 대시보드를 주기적으로 확인해야 함.
- 원인이 불명확하거나 반복되면 notification-service 담당자 호출.
