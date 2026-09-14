# Redis / Kafka DEV Platform 운영 계약

기준일: 2026-09-12

이 문서는 Petflow DEV EKS에 배포하는 Redis와 Kafka의 현재 설정, Backend 접속 정보,
검증 절차와 팀별 책임 범위를 정의한다. 두 Platform은 AWS 관리형 서비스가 아니라 이
GitOps 저장소의 Kubernetes Resource로 관리한다.

## 현재 구성

| 항목 | Redis | Kafka |
|---|---|---|
| Namespace | `redis` | `kafka` |
| Version | Redis 7.4.3 / Bitnami Chart 20.13.4 | Kafka 3.9.0 / Strimzi 0.45.2 |
| Architecture | standalone 1대 | KRaft, controller+broker 겸용 1대 |
| 외부 노출 | 없음, ClusterIP | 없음, internal listener |
| Port | 6379 | 9092 |
| Storage | gp3 8Gi PVC | gp3 10Gi PVC |
| 인증 | DEV에서 비활성화 | 내부 plain listener |

DEV에서는 고가용성보다 작은 기본 Capacity와 비용 절감을 우선한다. Redis replication,
Kafka broker 3대와 controller 분리, replication factor 3은 운영 환경 검토 범위다.

Strimzi 공식 호환성 표에서 0.45.2는 Kafka 3.9.0과 Kubernetes 1.25~1.35를 지원하므로
현재 EKS 1.35 구성과 호환된다. 버전 변경 시 [Strimzi 지원 버전 표](https://strimzi.io/downloads/)와
각 Chart의 release note를 다시 확인한다.

## Resource 기준

| Workload | CPU Request / Limit | Memory Request / Limit |
|---|---|---|
| Redis master | 100m / 500m | 256Mi / 512Mi |
| Kafka broker/controller | 250m / 1 | 512Mi / 1Gi |
| Strimzi Cluster Operator | 250m / 1 | 512Mi / 1Gi |

초기 DEV 값이며 `kubectl top`, Prometheus, Pending/OOMKilled, CPU Throttling을 확인해
조정한다. Backend와 Platform이 모두 올라온 뒤 Node Capacity와 함께 다시 측정한다.

## Redis Persistence 정책

Redis는 단순 Cache뿐 아니라 타임딜 Queue, 재고/구매 제어 후보로 사용될 수 있으므로
DEV에서도 Persistence를 켠다.

- `standalone` 1대
- Append Only File(AOF) 활성화
- RDB Snapshot 비활성화
- `gp3`, `ReadWriteOnce`, 8Gi PVC
- Service는 ClusterIP만 사용
- DEV 인증은 비활성화하되 외부 노출 또는 운영 전환 전에 반드시 재검토

PVC와 AOF는 Pod 재시작 시 복구 수단이지만 Redis 자체의 단일 장애점을 제거하지는 않는다.
타임딜 구매의 최종 정합성은 Database/Backend Transaction이 책임져야 한다.

Backend 접속 정보:

```text
host: redis-master.redis.svc.cluster.local
port: 6379
```

Service 이름은 Chart release `redis`와 Bitnami standalone 구성 기준이다. 실제 배포 후
`kubectl get svc -n redis`로 확인한다.

Redis Key, TTL, Lock 알고리즘, Queue 자료구조, AI Cache TTL과 Pub/Sub 사용 여부는
Backend/PM이 확정한다. 현재 Manifest에서 임의로 정하지 않는다.

## Kafka Storage와 접속 정보

Kafka는 Strimzi Operator가 관리하는 단일 `KafkaNodePool`을 사용한다.

- Kafka 3.9.0, Strimzi 0.45.2
- Strimzi Operator는 설치 위치인 `kafka` Namespace만 감시
- KRaft mode
- `dual-role` Node 1대가 controller와 broker 역할 겸용
- 내부 plaintext Listener 9092
- `gp3` 10Gi PVC, `deleteClaim: false`
- Topic/Transaction Replication Factor 1

Backend Bootstrap Server:

```text
pet-subscription-kafka-kafka-bootstrap.kafka.svc:9092
```

DEV 단일 Broker에서는 Broker 장애 동안 Kafka를 사용할 수 없고 replica 1 데이터는 별도
Broker 복제본을 갖지 않는다. 운영 환경으로 전환할 때 Broker 3대, controller 분리,
replication factor 3과 인증/TLS를 함께 검토한다.

## Kafka Topic 계약

Kubernetes `metadata.name`은 lowercase DNS 이름으로 관리하고 실제 Kafka Topic 이름은
`spec.topicName`에 보존한다.

| Kubernetes Resource | Kafka Topic | 현재 Producer | 현재 Consumer | 상태 |
|---|---|---|---|---|
| `review-created` | `ReviewCreated` | review-service | product-service | 우선 검증 대상 |
| `order-paid` | `OrderPaid` | payment-service | order-service | 확인 필요 |
| `order-confirmed` | `OrderConfirmed` | order-service | notification-service | 확인 필요 |
| `order-status-changed` | `OrderStatusChanged` | order-service | notification-service | 확인 필요 |
| `user-signed-up` | `UserSignedUp` | 미정 | 미정 | 확인 필요 |
| `member-withdrawn` | `MemberWithdrawn` | member-service | 미정 | 확인 필요 |
| `restock-detected` | `RestockDetected` | 미정 | 미정 | 확인 필요 |

모든 Topic은 초기값으로 partition 3, replica 1을 사용한다. Producer/Consumer, Event
Payload, Consumer Group, Partition Key, Retention, Retry와 DLQ는 Backend 구현과 함께
확정한다. 합의 전에는 Topic 이름 외 동작 계약으로 간주하지 않는다.

## 배포 후 검증

Argo CD가 `main`을 동기화한 뒤 아래 순서로 확인한다.

Redis:

```bash
kubectl get all,pvc -n redis
kubectl get events -n redis --sort-by=.lastTimestamp
kubectl run redis-check --rm -i --restart=Never -n redis \
  --image=bitnamilegacy/redis:7.4.3-debian-12-r0 \
  -- redis-cli -h redis-master.redis.svc.cluster.local -p 6379 ping
```

정상 기준은 Redis Pod `Running`, PVC `Bound`, Service 6379 생성과 `PONG` 응답이다.

Kafka:

```bash
kubectl get pods,svc,pvc -n kafka
kubectl get kafka,kafkanodepool,kafkatopic -n kafka
kubectl get events -n kafka --sort-by=.lastTimestamp
kubectl get storageclass gp3
```

정상 기준은 Strimzi Operator와 Broker Pod `Running`, Kafka/KafkaNodePool `Ready`, PVC
`Bound`, Bootstrap Service 9092 생성, KafkaTopic 7개 `Ready`다.

Bootstrap 연결 확인:

```bash
kubectl run kafka-check --rm -i --restart=Never -n kafka \
  --image=quay.io/strimzi/kafka:0.45.2-kafka-3.9.0 \
  -- bin/kafka-topics.sh \
  --bootstrap-server pet-subscription-kafka-kafka-bootstrap.kafka.svc:9092 \
  --list
```

EKS Private API에 접근하는 `kubectl` 명령은 Tailscale이 연결된 Windows/WSL에서 실행한다.

## 역할 경계

Infra 팀:

- Redis/Strimzi/Kafka version과 Architecture
- CPU/Memory Resource, gp3 PVC와 내부 Service
- KafkaNodePool, KafkaTopic Manifest와 Endpoint 문서
- 배포 후 Pod/Service/PVC/Capacity 검증

CloudNative/GitOps 팀:

- Argo CD App-of-Apps 연결과 Sync/Health
- Automated Sync, Self Heal, Prune 운영
- Platform 배포 순서와 Monitoring 연결

Backend 팀:

- Redis Client, Key, TTL, Lock, Queue와 Cache 정책
- Kafka Producer/Consumer, Event DTO와 Consumer Group
- Partition Key, Retention, Retry와 DLQ 정책

Backend 구현 전에는 실제 Producer/Consumer E2E, Redis Queue/Lock, KEDA Queue Scaling과
타임딜 부하 테스트를 완료 조건으로 보지 않는다.
