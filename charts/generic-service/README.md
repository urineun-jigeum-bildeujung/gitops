# generic-service autoscaling

`autoscaling.mode`는 한 워크로드에 하나의 컨트롤러만 연결한다.

- `disabled`: `replicaCount`를 Deployment/Rollout에 기록한다.
- `hpa`: 차트가 CPU HPA를 만들며 `replicas`를 렌더링하지 않는다.
- `keda`: 차트가 CPU와 선택적 Kafka trigger를 가진 `ScaledObject`를 만들며
  `replicas`를 렌더링하지 않는다. Kafka 사용 시 같은 Namespace의 Secret에
  `username`, `password`, `ca.crt` 키가 있어야 한다.

이전 `autoscaling.enabled: true`는 `mode: hpa`로 계속 해석되지만 신규 values는
반드시 `mode`를 명시한다. `podDisruptionBudget`는 `minAvailable`과
`maxUnavailable` 중 하나만 설정한다.

KEDA의 Kafka `lagThreshold`는 처리시간과 유입량을 실측한 뒤 조정해야 한다. Kafka
partition 수보다 많은 consumer replica는 같은 consumer group의 병렬 처리량을 늘리지
못한다. CPU trigger와 HTTP 처리 용량 확장은 별도로 동작할 수 있다.
