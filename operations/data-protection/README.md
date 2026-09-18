# CNPG 데이터 복원 검증

이 경로는 Argo CD 자동 동기화 대상이 아니다. 운영 `database/petflow-db`는 변경하지 않고
S3 `cnpg/` 백업에서 `database/petflow-db-restore`를 별도로 생성해 복원 가능 여부를 확인한다.

현재 백업 archive는 `cnpg/petflow-db-7686679137262796820/`이다. 운영 Cluster의
plugin `serverName`과 복원 manifest의 `externalClusters` plugin `serverName`을 일치시킨다.
`initdb`로 운영 DB를 재생성하면 PostgreSQL `status.systemID`를 확인하고 두 manifest의
`serverName`을 `petflow-db-<새 systemID>`로 변경한다. 기존 archive는 보존한다.
이전 DB의 백업을 복원할 때는 해당 archive의 `serverName`을 사용한다.

`Expected empty archive` 오류가 발생하면 서로 다른 DB가 archive를 공유하는지 확인한다.
기존 S3 WAL을 삭제하거나 `cnpg.io/skipEmptyWalArchiveCheck`로 검사를 우회하지 않는다.

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
