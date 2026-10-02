# 재구매 결과 DB

- Cluster: database/petflow-db
- Database: repurchase_db (owner: app)
- AI/배치 계정: 기존 수동 생성 ai_dev
- 배치 Namespace: repurchase
- Secret: repurchase/db-credentials (DB_USER, DB_PASSWORD)
- Host: petflow-db-rw.database.svc.cluster.local:5432

## 적용 순서

1. namespaces.yaml의 repurchase Namespace를 적용한다.
2. petflow-db.yaml의 repurchase-db Database를 적용하고 status.applied=true를 확인한다.
3. petflow-db Application의 PostSync Job이 app 계정으로 ai_dev에 CONNECT/CREATE를 부여한다.
   grants.sql은 수동 복구 시 같은 권한을 부여하는 참고 SQL이다.
4. 터미널에서 `python3 register-secret.py`로 기존 ai_dev 비밀번호를 등록한다.
5. app-bindings-repurchase.yaml 및 DB ingress/배치 egress 정책을 적용한다.
6. ExternalSecret SecretSynced/Ready 및 실제 비밀번호 접속을 확인한다.
7. AI 팀이 ai_dev로 repurchase 스키마 및 결과 테이블을 생성한 후 CronJob을 활성화한다.

복원된 클러스터의 SQL GRANT는 물리 백업에 포함된다. 백업 없는 신규 구축에서는
수동 생성 ai_dev를 먼저 준비해야 한다. 동기화 후 PostSync Job이 권한을 다시 부여한다.
CNPG Database 리소스 자체는 이 GRANT를 실행하지 않는다.

DB 수신과 배치 송신은 app.kubernetes.io/name=generic-service,
app.kubernetes.io/instance=dev-repurchase 라벨을 사용한다.
신규 배치는 현재 DNS/DB 연결만 허용한다. 추가 데이터 소스는 필요에 따라 허용한다.
배치 이미지/명령/스케줄은 미확정이므로 실행 워크로드는 생성하지 않는다.
