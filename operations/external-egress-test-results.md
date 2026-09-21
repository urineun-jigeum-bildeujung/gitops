# 외부 Egress 실클러스터 검증 결과

검사 시각 2026-09-18T19:38:28+09:00.

대상 context는 petflow-dev다. 서비스 Pod 자체에 임시 curl 컨테이너를 붙여 같은 Pod IP의 정책을 검사했다. 앱 라벨을 복제한 별도 테스트 Pod는 생성하지 않았다.

gitops 차트는 5c38078, gitops-value Egress 변경은 PR #42의 7f66267에 포함되어 있다. payment에는 후속 hotfix #43 eb436f1이 반영됐다. Egress 프록시 5개 Deployment의 Pod 10개가 Ready였다.

## 결론

네트워크 및 Node 검사 55/55 통과. 실제 Java 검사 3개 중 새 auth preview와 현재 payment Pod는 통과했지만 기존 auth active Pod는 실패했다. auth는 블루그린 Paused 상태로 active=7884cb587c, preview=7f4fbfcc8이다. 기존 active에는 JAVA_TOOL_OPTIONS가 없어 외부 연결이 HttpConnectTimeoutException으로 실패했다. 새 정책은 기존 Pod에도 즉시 적용되므로 rollout 승인 전에도 기존 Pod의 직접 외부 호출이 차단된다. 배포 전환 순서에서 미리 처리해야 했던 문제다.

auth 서비스 전환/promote, 이미지 변경, NetworkPolicy 변경은 이번 테스트에서 수행하지 않았다. 새 auth preview의 네트워크 검증이 통과했다는 사실은 실제 OAuth 로그인/내부 mTLS 기능 전체 검증을 대신하지 않는다.

## 서비스별 결과

| 서비스 | 검사 수 | 통과 수 | 검사 Pod |
| --- | --- | --- | --- |
| auth-service | 11 | 11 | generic-service-7884cb587c-cjdf9 |
| member-service | 9 | 9 | generic-service-7ccd6b9686-qglxt |
| notification-service | 1 | 1 | generic-service-67d74f6f7b-wtj4f |
| order-service | 4 | 4 | generic-service-5985f7c77f-5nhs9 |
| payment-service | 9 | 9 | generic-service-7f477d7b48-l9m7r |
| product-service | 3 | 3 | generic-service-645449595f-9prl5 |
| review-service | 9 | 9 | generic-service-86d54cdf66-jqpxz |
| web | 9 | 9 | generic-service-dccbbb6cc-k59zn |

## 검사 범위

- 서비스 8개의 직접 공인 인터넷 HTTPS 차단. DNS 해석 후 연결 타임아웃을 확인했다.
- 서비스별 프록시 경유 목적지 8건(서로 다른 도메인 7개) 연결. S3는 member/review 각각 검사했다.
- 프록시에서 다른 도메인, IP-literal, 8443 포트 및 평문 HTTP 차단.
- 다른 서비스의 프록시 접근 차단.
- 지정된 DB 6개 서비스, Redis 2개 서비스, Kafka 3개 서비스 및 Pod Identity 2개 서비스의 TCP 연결 유지.
- web 실제 Node v22.23.2 기본 fetch의 주소 API 연결 및 금지 도메인 403 차단.

TCP 검사에서는 접속 성공 후 프로토콜 메시지를 보내지 않아 대기 타임아웃이 발생한다. remote_ip와 time_connect로 TCP 접속 성공 여부를 판별했다. DB 인증/쿼리, Kafka 인증/메시지 발행, Pod Identity 자격 증명 획득을 검증한 것은 아니다.

허용 S3/CDN 루트는 CONNECT=200 이후 원격 HTTP=403이었다. 미인증/객체 경로 없는 요청의 원격 거절이며 프록시의 CONNECT=403 차단과 구분했다. 실제 업로드·HeadObject·태그 변경 및 CDN 객체 조회는 미검증이다.

auth preview의 평문 HTTP 관리 포트 검사(`127.0.0.1:8080/actuator/health`)는 HTTP 400과 "This combination of host and port requires TLS."를 반환했다. HTTPS/TLS가 필요한 포트로 확인했으며 Egress 차단으로 인한 타임아웃과 구분한다. 인증서를 이용한 관리 포트 health 기능 검증은 수행하지 않았다.

## 실제 Java 결과

| 서비스 | Pod | 프록시 설정 | 결과 |
| --- | --- | --- | --- |
| auth-service | generic-service-7f4fbfcc8-mzvjm | 있음 | 통과 |
| auth-service | generic-service-7884cb587c-cjdf9 | 없음 | PROXY=MISSING; ALLOW_FAILED=HttpConnectTimeoutException |
| payment-service | generic-service-7f477d7b48-l9m7r | 있음 | 통과 |

Java 검사 클래스는 앱 컨테이너의 임시 경로에 복사해 현재 환경변수로 실행한 후 삭제했다. 임시 curl 검사 컨테이너 프로세스는 종료했다. 최초 restricted profile 검사는 이미지의 비수치 curl_user 때문에 기동되지 않아 baseline profile의 실제 비루트 이미지로 다시 검사했다. 기동하지 못한 ephemeral container 명세는 Pod 교체 전까지 남으며 앱 Pod를 정리 목적으로 재시작하지 않았다.

WAL 백업/스키마 오류, OAuth 로그인과 결제 거래 전체 및 운영 트래픽의 성공률은 이번 네트워크 검사로 정상화됐다고 판단하지 않는다.
