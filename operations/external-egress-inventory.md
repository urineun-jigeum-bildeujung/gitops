# 외부 Egress 호출 목록

2026-09-18 로컬 checkout의 코드, 배포 설정, 업로드 계약과 기능 문서를 교차 확인한 목록이다.
정책 적용이나 운영 트래픽 관찰은 수행하지 않았다. 애플리케이션이 구현한 호출과
기능을 활성화했을 때 필요한 목적지와 예정된 연결을 정리하며, 운영 호출 성공을 의미하지 않는다.
`구현`은 호출 코드가 있다는 뜻이고, `예정`은 계약/인프라에 근거가 있으나 호출 구현이
아직 없다는 뜻이다. 목적지가 미정인 기능은 도메인 허용 대상으로 확정하지 않는다.

| 저장소 | 브랜치 | 확인한 커밋 |
| --- | --- | --- |
| gitops | main | 5a264c1 |
| gitops-value | feat/networkpolicy | a4e09d4 |
| sever | dev | 4a642dd |
| web | dev | d3ea7be |

## 서비스 Pod의 외부 허용 목록

| 출발 서비스 | 도메인 | 포트 | 상태 | 용도와 호출 경로 |
| --- | --- | --- | --- | --- |
| auth-service | kauth.kakao.com | TCP 443 | 구현 | POST /oauth/token, OAuth 토큰 교환 |
| auth-service | kapi.kakao.com | TCP 443 | 구현 | GET /v2/user/me, 사용자 정보 |
| auth-service | www.googleapis.com | TCP 443 | 구현 | /oauth2/v4/token, /oauth2/v3/userinfo; Spring Google 기본 provider |
| payment-service | api.tosspayments.com | TCP 443 | 구현 | POST /v1/payments/confirm, /v1/payments/{paymentKey}/cancel |
| web | business.juso.go.kr | TCP 443 | 구현 | /addrlink/addrLinkApi.do; Next.js 서버 Route Handler가 주소 검색 |
| member-service | petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com | TCP 443 | 예정 | profiles/ 업로드 계약: 객체 존재/크기 확인, 태그 조회 및 confirmed 태그 변경 |
| review-service | petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com | TCP 443 | 예정 | reviews/ 업로드 계약: 객체 존재/크기 확인, 태그 조회 및 confirmed 태그 변경 |
| order-service | petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com | TCP 443 | 예정 | orders/ 업로드 계약: 객체 존재/크기 확인, 태그 조회 및 confirmed 태그 변경 |
| web | image.leechs.shop | TCP 443 | 예정·조건부 | 업로드 이미지 CDN; Next.js 서버 이미지 최적화를 사용할 때 Pod 연결 필요 |
| product-service | 확인된 외부 목적지 없음 | — | 미정 | 상품 이미지 업로드 담당 서비스/계약 미정; 임의 S3 권한을 추가하지 않음 |
| notification-service | 푸시 제공자 도메인 미정 | — | 미정 | 알림 UI의 푸시 안내는 있으나 제공자·발송 구현·담당 서버 경로 미확정 |

각 서비스에는 해당 행의 확정된 목적지만 허용한다. 예정된 S3 목적지도 정책 설계에
포함하며 구현 전에 endpoint 설정과 대조한다. 모든 서비스에 공통 외부 도메인 목록을
허용하지 않는다. 현재 코드에서 사업 기능상 인터넷 TCP 80 또는 UDP가 필요한 경로는
확인하지 못했다. CoreDNS의 TCP/UDP 53과 기존 내부 통신은 별도로 유지한다.

## 근거와 설정 상태

- 카카오 주소는 [auth dev values](../../gitops-value/values/dev/services/auth-service/values.yaml)의
  `SPRING_SECURITY_OAUTH2_CLIENT_PROVIDER_KAKAO_*` 설정과
  [CustomOAuth2UserService](../../sever/services/auth-service/src/main/java/com/golajugaenyang/auth/security/CustomOAuth2UserService.java)의
  `DefaultOAuth2UserService` 호출에서 확인했다.
- Google provider 주소는 저장소에 직접 적혀 있지 않다. `registration.google`이 Spring의
  `CommonOAuth2Provider.GOOGLE` 기본값을 사용한다. [Spring Security 7.1.0 소스](https://raw.githubusercontent.com/spring-projects/spring-security/7.1.0/config/src/main/java/org/springframework/security/config/oauth2/client/CommonOAuth2Provider.java)에서
  token/userinfo/JWK의 호스트는 모두 `www.googleapis.com`이다. 현재 scope는 `email`이며
  `openid`가 없어 OIDC ID token/JWK 처리를 현재 호출로 단정하지 않는다. JWK 처리를
  활성화해도 동일 호스트의 `/oauth2/v3/certs`이므로 도메인 허용 목록은 같다.
  현재 issuer discovery override는 확인되지 않았다.
- OAuth client-id/secret은 dev values에 placeholder가 남아 있다. 정상 로그인 트래픽을
  확인한 목록이 아니라 OAuth 연결을 활성화할 때 필요한 코드상의 허용 목록이다.
- 토스 호스트는 [payment dev values](../../gitops-value/values/dev/services/payment-service/values.yaml)의
  `TOSS_PAYMENTS_BASE_URL`, [ExternalClientConfig](../../sever/services/payment-service/src/main/java/com/golajugaenyang/payment/config/ExternalClientConfig.java),
  [TossPaymentApiClient](../../sever/services/payment-service/src/main/java/com/golajugaenyang/payment/adapter/out/external/toss/client/TossPaymentApiClient.java)에서 확인했다.
- 주소 API는 [web Route Handler](../../web/src/app/api/juso/route.ts)가 호출한다.
  member-service의 외부 예외로 넣으면 안 된다. `JUSO_CONFM_KEY`가 없으면 외부 요청 전에
  오류를 반환한다. 현재 gitops/dev values에는 이 키의 주입이 확인되지 않았다.
- 백엔드 전체의 main 코드와 Gradle 의존성에는 아직 S3 SDK, presigner,
  S3 객체 업로드/조회/태그 호출 구현이 없다. 다만 [이미지 업로드 계약](../../infra/docs/image-uploads.md)과
  [Terraform workload 설정](../../infra/terraform/environments/dev/main.tf)은 member의 `profiles/`,
  review의 `reviews/`를 명시하므로 두 서비스의 S3 연결을 **예정된 허용 대상**으로 포함한다.
- 계약상 presigned PUT은 브라우저가 S3에 직접 보내지만, 백엔드는 `HeadObject`,
  `GetObjectTagging`, `PutObjectTagging`으로 업로드 확인 및 상태 변경을 해야 한다.
  presign 생성 자체와 이 API 호출을 구분한다. 기존 `169.254.170.23:80` Pod Identity
  자격 증명 예외는 인터넷 도메인과 별도로 유지한다.
- 표의 S3 주소는 문서의 DEV 버킷/리전과 [AWS regional virtual-host endpoint 형식](https://docs.aws.amazon.com/AmazonS3/latest/userguide/VirtualHosting.html)을
  조합한 예정 목적지다. 실제 배포의 Terraform `image_upload_config` 출력 및 SDK endpoint
  설정으로 확인한다. path-style을 선택하면 `s3.ap-northeast-2.amazonaws.com` 등으로
  호스트가 달라질 수 있으므로 선택 시 목록을 갱신한다. AWS 전체 wildcard를 허용하지 않는다.
  두 서비스의 버킷 호스트는 같으며 prefix 제한은 [서비스별 IAM](../../infra/terraform/modules/workload-iam/image-uploads.tf)이 담당한다.
- CDN은 [Terraform](../../infra/terraform/environments/dev/main.tf)의 `image.${var.domain_name}`과
  [S3 module 출력](../../infra/terraform/modules/s3/outputs.tf)의 `uploads_cdn_base_url`을 기준으로 한다.
  `leechs.shop` 환경에서는 **image.leechs.shop**이다. 업로드 문서에 남아 있는 CloudFront
  기본 도메인 설명보다 실제 `image_upload_config.file_base_url` 출력을 우선한다.

## 목적지가 아직 정해지지 않은 기능

| 기능 | 확인한 근거 | 목록에서의 처리 |
| --- | --- | --- |
| 재입고/알림 푸시 | [재입고 알림 문서](../../web/src/views/restock-alarm/README.md)와 UI의 기기 푸시 안내; 현재 API는 mock | 푸시 제공자, 호출 주체 및 SDK/프로토콜 확정 후 목적지 추가. Firebase 등 특정 업체를 추정해 허용하지 않음 |
| 휴대폰 SMS 인증 | [휴대폰 인증 문서](../../web/src/views/verify-phone/README.md): PM 결정으로 MVP 목업 | 실제 SMS 연결은 보류 상태. 예정된 확정 목적지 없음 |
| 상품/반려동물 이미지 연결 | [온보딩 문서](../../web/src/views/onboarding/README.md): 업로드 엔드포인트 부재, #226 | member/review 계약의 범위와 연결할 API를 확인. product-service 자체 업로드 권한/외부 호출은 별도 확정 필요 |

알림 목록 조회나 내부 Kafka 이벤트만으로 외부 발송 연결이 생기는 것은 아니다.
미정 기능에는 인터넷 전체 허용 예외를 유지할 근거가 없다.

## 브라우저 호출 및 빌드 호출

| 대상 | 실제 출발 위치 | 서비스 Pod 외부 허용 여부 |
| --- | --- | --- |
| kauth.kakao.com/oauth/authorize | 로그인 redirect를 따라가는 브라우저 | auth의 token 교환과 같은 호스트지만 authorize 자체는 서버 호출 아님 |
| accounts.google.com/o/oauth2/v2/auth | 로그인 redirect를 따라가는 브라우저 | 현재 auth Pod 허용 목록에서 제외 |
| 토스 결제 SDK가 불러오는 UI/결제창 | 브라우저 | web Pod 허용 목록에서 제외; 브라우저 도메인 전체는 별도 HAR/CSP 조사 필요 |
| leechs.shop/auth/callback 및 OAuth callback | 브라우저가 우리 서비스로 접속 | 외부 Egress 예외 아님 |
| 사용자 이미지 `<img>` | 브라우저 | 서버 fetch와 구분 |
| 예정된 presigned PUT: petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com | 브라우저 | PUT 자체는 Pod 호출 아님; member/review/order의 확인·태그 API는 위 표처럼 별도 필요 |
| 예정된 CDN 이미지 조회: image.leechs.shop | 브라우저 또는 Next.js 이미지 최적화 서버 | 브라우저 직접 조회는 Pod 예외 아님; 서버 최적화 사용 시 web Pod 예외 필요 |
| Google Fonts | Next.js 빌드 작업 | web 런타임 예외 아님 |

근거는 [OAuth 시작 URL](../../web/src/views/login/config/oauth.ts),
[토스 Client Component](../../web/src/views/checkout/ui/toss-payment-widget.tsx),
[avatar img](../../web/src/shared/ui/avatar-uploader/avatar-uploader.tsx),
[폰트 설정](../../web/src/app/layout.tsx)이다. `next/font/google`은 빌드 시 다운로드한
폰트를 자체 제공한다. [Next.js 공식 설명](https://nextjs.org/docs/app/getting-started/fonts).

[Next 이미지 설정](../../web/next.config.ts)의 `remotePatterns`는 현재 `http://localhost`만
허용한다. S3/CloudFront 또는 `image.leechs.shop`에 대한 서버 이미지 최적화 호출은 현재
허용되어 있지 않다. 예정된 이미지 연결을 구현할 때 계약의 CDN 호스트를 설정에 추가하고,
서버 최적화 사용 여부를 확인한다. 임의의 S3/CloudFront 전체 도메인을 허용하지 않는다.
프론트의 [결제 승인 함수](../../web/src/views/checkout/api/payment.ts)는 아직 mock 응답이며,
백엔드 토스 승인 호출이 프론트와 끝까지 연결됐다고 간주하지 않는다.

## 플랫폼 및 CI는 별도 범위

gitops를 함께 확인한 결과 아래 트래픽은 존재하지만 서비스 8개의 공통 외부 허용
목록에 넣지 않는다. 플랫폼 전체를 격리할 때 출발 Pod별로 별도 조사·검증한다.

| 출발 구성 요소 | 설정에서 확인한 외부 대상/기능 | 근거 |
| --- | --- | --- |
| PostgreSQL Barman sidecar | S3 petflow-dev-db-backups 버킷, cnpg prefix | platform/60-cnpg-cluster/manifests/petflow-db.yaml |
| External Secrets Operator | ap-northeast-2 Secrets Manager | platform/91-external-secrets-config/manifests/cluster-secret-store.yaml |
| Argo CD repo-server | GitHub gitops/gitops-value 및 platform application.yaml의 Helm repository URL | bootstrap, applications/appset.yaml, platform/*/application.yaml |
| Jenkins 및 빌드 agent | GitHub checkout/push, release 다운로드, Gradle/Maven, npm, 이미지 registry/ECR, Trivy DB | sever/Jenkinsfile, web/Jenkinsfile, Dockerfile, Gradle 및 npm 설정 |
| AWS 플랫폼 controllers/Pod Identity agent | 기능별 AWS API | chart/SDK 기본값과 운영 호출을 추가 확인해야 함 |

Helm repository URL과 Docker `image.repository`는 애플리케이션 런타임 HTTP 호출이 아니다.
이미지 pull은 보통 노드가 수행하며, Jenkins의 image build/push는 빌드 Pod 트래픽이다.
SDK endpoint 선택, 다운로드 redirect, registry 인증/CDN과 chart 기본값의 간접 호출까지
정적으로 모두 확정한 것은 아니다. 플랫폼 전체 차단에는 이 표만으로 부족하다.

## 적용 전 확인할 차이

최신 소스 checkout과 배포 이미지 버전은 다르다. web 소스는 `d3ea7be`지만 dev values의
이미지 태그는 `bc68d33bc9633b9fcc94f9985d9421f449ab4564`다. 백엔드도 서비스별로
서로 다른 과거 SHA 태그를 사용한다. git pull만으로 실행 중인 이미지가 최신 소스가
되지는 않는다. 실제 이미지의 호출이나 주입된 환경변수가 이 목록과 다른지 배포 전에
확인해야 한다.

이번 파일 변경에서 서비스 8개의 직접 공인 IPv4 전체 허용 예외를 제거했다.
확정된 목적지와 예정된 S3/CDN은 `externalEgress.allowedDomains`에 서비스별로 반영했다.
전용 프록시 5개에만 공인 IPv4 TCP 443 접근을 허용하고 CONNECT 호스트명을 검사한다.
푸시/SMS 제공자 미정 기능에는 새 외부 예외를 추가하지 않았다.
설정/제약/배포 순서는 [NetworkPolicy 설명](network-policy-api.md)을 참고한다.
저장소 파일 변경만 완료한 상태이며 운영 CNI 집행/기능 테스트를 완료했다는 의미는 아니다.
