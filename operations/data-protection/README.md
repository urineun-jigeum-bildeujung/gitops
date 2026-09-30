# CNPG 데이터 복원 검증

이 경로는 Argo CD 자동 동기화 대상이 아니다. 운영 `database/petflow-db`는 변경하지 않고
S3 `cnpg/` 백업에서 `database/petflow-db-restore`를 별도로 생성해 복원 가능 여부를 확인한다.

적용 전 `petflow-db`의 최신 `Backup`이 `completed`인지 확인한다. 복원 Cluster는 Infra의
`database/petflow-db-restore` Pod Identity와 GitOps의 `gp3-cnpg` StorageClass를 사용한다.

```bash
kubectl --context petflow-dev -n database get backup
kubectl --context petflow-dev apply -f operations/data-protection/petflow-db-restore.yaml
kubectl --context petflow-dev -n database wait \
  --for=condition=Ready --timeout=30m cluster/petflow-db-restore
```

업무 데이터 또는 사전에 기록한 marker를 복원 Cluster에서 조회해 일치 여부를 확인한다.
검증 후에는 복원 Cluster만 삭제한다.

```bash
kubectl --context petflow-dev -n database delete cluster petflow-db-restore --wait=true
kubectl --context petflow-dev -n database get pvc \
  -l cnpg.io/cluster=petflow-db-restore
```

운영 `petflow-db`, `petflow-db-backups` ObjectStore, `cnpg/` S3 객체는 삭제하지 않는다.

## CNPG · Redis 장바구니 · Kafka 통합 복원

통합 유지보수 실행과 복원은 인접 infra 저장소의
`docs/stateful-backup-restore.md`를 따른다. `stateful-qualification.example.json`은
격리 복원 검증 결과를 기록하는 예시이며 실제 성공 증거가 아니다. 2026-10-01 KST에
CNPG S3/WAL·EBS, Redis cart 및 Kafka의 실제 격리 복원 시험을 완료했다. 결과와 범위는
infra의 `docs/backup-restore-measurement-20261001.md`를 참조한다. 구성요소별 시험이며
동일 실행의 통합 manifest 및 전체 destroy/apply qualification은 아직 완료하지 않았다.
검증 보고서는 참고용 기록이며 실행 전제조건이 아니다. `./tdestroy.sh`는 별도 로컬
보고서 지정 없이 서비스 중단·백업을 수행하며 백업 검증이 실패하면 삭제를 중단한다.

`task bootstrap:root-app`은 `database/stateful-recovery`의 ready 상태와 CNPG/Redis/Kafka
준비 상태를 확인한다. 정상 부트스트랩은 infra의 데이터 복원 및 검증 이후에 수행한다.
