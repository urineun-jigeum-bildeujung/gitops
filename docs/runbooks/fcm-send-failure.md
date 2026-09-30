# FCM 발송 실패 / 중복 발송 감지

> 이 항목은 아직 "백엔드" 대시보드에 전용 패널이 없고(코드 계측만 되어 있음),
> Alertmanager 알림도 연결되어 있지 않습니다. 확인하려면 아래 PromQL을 Grafana
> Explore에서 직접 실행해야 합니다.

## 증상
- 타임딜 알림 발송 실패율 증가: `fcm_send_total{result="failure"}` 증가
  (`FcmPushSender` 발송 시도 실패)
- 중복 발송 감지 증가: `fcm_send_duplicate_total` 증가
  (`TimeDealNotificationPersistenceService.tryMarkAsSent`가 이미 발송된 건에 대해
  false를 반환 — 발송 자체가 실패한 게 아니라 중복 방지 로직이 정상 작동해서
  발송을 막은 신호일 수도 있음. 다만 계속 오르면 스케줄러가 같은 대상을 반복
  처리하고 있다는 뜻이라 원인 파악 필요)

## 확인 순서

1. **발송 실패율 확인**:
   ```
   sum(rate(fcm_send_total{namespace="notification-service", result="failure"}[$__rate_interval]))
   /
   sum(rate(fcm_send_total{namespace="notification-service"}[$__rate_interval])) * 100
   ```
2. **실패가 전체적인지 특정 타임딜/상품에 몰리는지 확인** — 전체적으로 실패율이
   오르면 FCM 서버 장애 또는 Firebase 서비스 계정 자격증명 만료 의심.
3. **`FcmPushSender` 로그 확인** — 실패 시 로그가 남게 되어 있음. 에러 메시지로
   원인 구분(invalid/만료된 토큰 vs quota exceeded vs 자격증명 문제).
4. **중복 발송 카운트가 계속 오르는 경우** — [scheduler-duration-anomaly.md](scheduler-duration-anomaly.md)의
   "스케줄러 소요시간" 패널과 대조. 이전 스케줄러 실행이 끝나기 전에 다음 실행이
   시작되는 경우(실행 주기보다 소요시간이 길어짐) 같은 대상을 중복 처리할 수 있음.

## 완화

- **FCM 자격증명/쿼터 문제**: Firebase 콘솔에서 서비스 계정 키 상태 확인, 필요시 갱신.
- **특정 토큰 invalid 에러 다수**: 만료된 디바이스 토큰을 정리하는 로직이 현재 없음
  — 반복적으로 발생하면 백로그로 등록 검토.
- **스케줄러 실행 시간 초과로 인한 중복 발송**: 스케줄 주기 조정 또는 분산 락 적용
  검토(현재 별도 락 없음).

## 에스컬레이션
- 대시보드 패널/알림 둘 다 없어서 위 PromQL을 직접 실행해서 확인해야 함.
- 원인이 불명확하거나 재현이 안 되면 notification-service 담당자 호출.
