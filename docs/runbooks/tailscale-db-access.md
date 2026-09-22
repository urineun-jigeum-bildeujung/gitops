# Tailscale DB 접근 설정

이 구성은 `DBeaver -> Tailnet 주소:5432 -> Tailscale proxy Pod -> petflow-db primary:5432` 경로를 만든다. 인터넷 공개 LoadBalancer는 만들지 않는다.

## 1. Tailnet 정책에 태그 소유권 추가

Tailscale 관리자 콘솔의 **Access controls**에서 현재 JSON 정책 파일의 **최상위 객체**에 추가한다. 이 내용은 GitOps 저장소 파일에 넣는 값이 아니다.

기존 정책에 `tagOwners`가 없다면 다음처럼 추가한다.

```json
{
  "tagOwners": {
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  }
}
```

이미 `tagOwners`가 있다면 블록을 중복 생성하지 말고 기존 객체 안에 두 항목만 합친다.

```json
{
  "tagOwners": {
    "tag:existing": ["autogroup:admin"],
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  }
}
```

정책의 `grants` 또는 `acls`에도 AI 팀 사용자/그룹이 `tag:k8s`의 TCP 5432에 접근할 수 있는 규칙이 필요하다. 기존 정책 형식과 실제 AI 팀 그룹명이 저장소에 없으므로 콘솔에서 기존 형식에 맞춰 추가한다. 다른 포트나 다른 출발자는 허용하지 않는다.

## 2. Operator OAuth Client 생성

Tailscale 관리자 콘솔의 **Trust credentials**에서 OAuth Client를 만들고 다음 쓰기 권한을 `tag:k8s-operator` 태그로 제한한다.

- `General/Services`: Write
- `Devices/Core`: Write
- `Keys/Auth Keys`: Write

Client ID와 Client Secret은 Git에 커밋하지 않는다.

## 3. AWS Secrets Manager에 저장

이름은 정확히 `petflow/tailscale/kubernetes-operator-oauth`, JSON 키는 정확히 `client_id`와 `client_secret`을 사용한다.

```json
{
  "client_id": "Tailscale OAuth Client ID",
  "client_secret": "Tailscale OAuth Client Secret"
}
```

AWS 콘솔에서 생성하는 것을 권장한다. 기존 시크릿을 갱신할 때도 두 JSON 키 이름을 유지한다.

## 4. GitOps 반영 순서와 확인

Argo CD sync wave는 다음 순서를 강제한다.

1. `namespaces`(-9): `tailscale` 네임스페이스
2. `external-secrets-config`(3): `tailscale/operator-oauth`
3. `tailscale-operator`(4): Operator와 CRD
4. `tailscale-db-access`(5): DB ProxyClass와 Tailnet Service

AWS 시크릿을 먼저 생성한 다음 GitOps 변경을 병합한다. 확인 명령은 모두 읽기 전용이다.

```bash
kubectl get externalsecret -n tailscale tailscale-operator-oauth
kubectl get deployment,pod -n tailscale
kubectl get proxyclass petflow-dev-db
kubectl get service -n database petflow-db-tailnet
kubectl get statefulset,pod -n tailscale -l app.kubernetes.io/instance=petflow-dev-db
```

`petflow-db-tailnet`의 `EXTERNAL-IP` 또는 MagicDNS 이름이 채워지면 DBeaver의 Host에 그 주소, Port에 `5432`를 입력한다. DB명/계정/비밀번호는 기존 PostgreSQL 값을 그대로 사용한다.

## 장애 시 안전한 중단

접근만 즉시 막으려면 Tailnet의 5432 접근 규칙을 제거한다. GitOps에서 완전히 제거할 때는 `tailscale-db-access` Application을 먼저 제거하고 Operator는 마지막에 제거한다. 기존 EC2 subnet router는 이 구성과 별개이므로 변경하거나 삭제하지 않는다.
