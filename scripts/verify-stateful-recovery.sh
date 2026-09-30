#!/usr/bin/env bash
# infra/tapply.sh가 세 데이터 저장소를 검증하기 전 서비스 자동 배포를 차단한다.
set -Eeuo pipefail
phase="$(kubectl -n database get configmap stateful-recovery -o jsonpath='{.data.phase}')"
[[ "${phase}" == ready ]] || {
  echo '[bootstrap] CNPG/장바구니/Kafka 복원이 완료되지 않았습니다. infra/tapply.sh로 먼저 검증하세요.' >&2
  exit 1
}
kubectl -n database wait --for=condition=Ready cluster/petflow-db --timeout=30s
kubectl -n kafka wait --for=condition=Ready kafka/pet-subscription-kafka --timeout=30s
ready="$(kubectl -n redis get statefulset redis-master -o jsonpath='{.status.readyReplicas}')"
[[ "${ready}" == 1 ]] || { echo '[bootstrap] Redis가 Ready가 아닙니다.' >&2; exit 1; }
