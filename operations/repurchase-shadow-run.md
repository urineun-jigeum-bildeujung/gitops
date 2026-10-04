# 재구매 수동 SHADOW Job

이 디렉터리의 검증/재시도 Job은 수동 실행용이다. DSN, 실행 ConfigMap 및 대기
SHADOW Job은 platform에서 자동 생성한다. 정기 CronJob은 생성하지 않는다.

## 모델 접근 검증

`repurchase-model-access-check.yaml`은 `generic-service` Pod Identity와 S3 프록시로
고정 버전의 `manifest.json`, `model.json`을 각각 다운로드한다. AWS 공식 CLI 이미지의
`aws` 명령만 사용하고, 추가 패키지를 인터넷에서 설치하지 않는다.

두 initContainer가 같은 `emptyDir`에 파일을 저장한다. 배치 컨테이너는
`/models/xgboost_aft`로 읽기 전용 마운트하며 manifest SHA-256, 모델 SHA-256,
artifact ID 및 기존 배치 코드의 `load_model_artifact` 검증을 수행한다.
검증 Job에는 DB 자격증명을 전달하지 않으며 예측 결과를 쓰지 않는다.

```bash
kubectl --context petflow-dev apply -f operations/repurchase-model-access-check.yaml
kubectl --context petflow-dev logs -n repurchase job/repurchase-model-access-check -c batch
```

고정 모델 ID:
`ec25eb1bcd8f24ce36a2397c1544cb087cb970af532365de7f8ec900aeb4b7fb`

## 실제 SHADOW 실행 전 준비

`platform/60-cnpg-cluster/manifests/repurchase-shadow-run.yaml`은 GitOps가
**suspend: true**로 생성한다. 다운로드 이후
모델 검증 initContainer가 성공해야 예측 컨테이너가 시작된다.

현재 고정 ECR 이미지로 모델 로딩과 실제 SHADOW 실행을 검증했다. 이미지가
달라지면 검증 Job도 같은 이미지로 다시 확인한다. 실행 인자는 현재 AI 코드의
`shadow-run` 계약을 따른다.

DSN Secret은 `platform/91-external-secrets-config/manifests/app-bindings-repurchase-shadow.yaml`
의 ExternalSecret이 기존 Secrets Manager `petflow/repurchase/db` 자격증명으로 생성한다.
사용자명/비밀번호를 URL 인코딩하고, 세 DB의 rw 주소 및 TLS 연결을 지정한다.
비밀번호와 완성된 DSN은 Git에 기록하지 않는다. 원천 SELECT 및 결과 쓰기 권한은
별도로 검증해야 한다.

실행 ConfigMap은 `platform/60-cnpg-cluster/manifests/repurchase-shadow-run-config.yaml`에서
관리하며 이번에 AI 팀이 확정한 시각과 ID가 들어 있다. 다음 실행에서 값을 바꾸기
전에는 실행 이미지·관측 컷·실행 ID를 다시 합의한다.

| 리소스 | 필요한 키 | 용도 |
| --- | --- | --- |
| Secret `repurchase-shadow-dsns` | `REPURCHASE_ORDER_DATABASE_DSN` | order_db 입력 읽기 |
| 위 Secret | `REPURCHASE_MEMBER_DATABASE_DSN` | member_db 입력 읽기 |
| 위 Secret | `REPURCHASE_RESULT_DATABASE_DSN` | repurchase_db SHADOW 결과 쓰기 |
| ConfigMap `repurchase-shadow-run-config` | `REPURCHASE_AS_OF` | 시간대를 포함하는 고정 관측 컷 |
| 위 ConfigMap | `REPURCHASE_CREATED_AT` | 재시도에도 같은 배치 생성 시각 |
| 위 ConfigMap | `REPURCHASE_PUBLICATION_ID` | 재시도에도 같은 실행 ID |

입력 DB는 `petflow-db-rw.database.svc.cluster.local` 또는 `petflow-db-ro`를 사용할
수 있다. 결과 DB는 rw 주소를 사용하며, DB 계정의 SELECT 및 결과 테이블 권한은
개발자와 확인한다. 코드가 공개 발행 대신 SHADOW 쓰기를 수행하더라도 실제 DB
변경이므로 실행 설정을 합의한 뒤 시작한다. 관측 시각과 실행 ID를 임의로 정하지 않는다.

준비가 끝나면 다음 명령으로 단 한 번 재개한다.

Application은 이 Job의 `/spec/suspend`를 비교·동기화에서 제외하므로 수동 중지
해제를 selfHeal로 되돌리지 않는다. Job의 의도적인 대기가 전체 Application의
건강 상태를 낮추지 않도록 이 Job만 건강 집계에서 제외한다. Job의 실제 상태와
로그는 직접 확인한다. GitOps 관리 Job에는 TTL을 설정하지 않는다.

```bash
kubectl --context petflow-dev patch job repurchase-shadow-run -n repurchase \
  --type=merge -p '{"spec":{"suspend":false}}'
```

이미 실행을 시작한 Job의 Pod template은 수정하지 못한다. 다른 이미지나 실행
설정으로 재실행할 때는 새 Job 이름을 사용하고 실행 ID의 재시도 규칙을 확인한다.
모델 파일은 Job별 `emptyDir`이므로 검증 Job의 파일이 다음 Job으로 전달되지는 않는다.
실제 SHADOW Job의 initContainer가 같은 고정 S3 경로에서 다시 다운로드한다.

## 검증 결과

2026-10-04 수동 실행 ID `shadow-eks-20261003T110300Z-ec25eb1b-v1`로
SHADOW 결과 50,517건을 저장했다. 별도 재시도 Job에서도 `inserted=false`를
확인했고 결과 50,517건 및 배치 1건이 유지되었다. 재시도 파일
`operations/repurchase-shadow-run-retry.yaml`은 자동 동기화 대상이 아니다.
