# Jenkins Controller Image

PetFlow Jenkins controller의 core/JDK와 전체 플러그인 버전을 고정한 이미지다.
클러스터의 새 PVC에서 Jenkins를 시작할 때 외부 plugin mirror를 조회하지 않도록
`platform/40-jenkins/application.yaml`은 이 이미지의 digest와
`controller.installPlugins: false`를 함께 사용한다.

## 고정 기준

- Jenkins: `2.568.3`
- JDK: `21`
- Base image digest: `sha256:c1e4c349365f6d16d88595b2c5f7e8ff39b8ae1d061f62420bac193b4b9616d0`
- Plugin source: `plugins.lock.txt`
- Registry: `297165773875.dkr.ecr.ap-northeast-2.amazonaws.com/petflow/jenkins-controller`
- Verified image: `2.568.3-jdk21-69893891df2f@sha256:c203ea5e76b203df61ccb7dcf204dd259d61b6950b73f374621b63604e0f8f91`
- Security baseline: Debian 보안 패키지 적용, 불필요한 controller `git-lfs` 제거, Trivy 0.74.0 CRITICAL 0

`plugins.lock.txt`는 2026-09-28 정상 DEV Jenkins에서 활성화된 플러그인 ID와
전이 의존성을 포함한 전체 버전 목록이다(2026-09-29에 `lockable-resources` 추가,
기존 81개는 버전 변경 없음 — jenkins-plugin-cli로 재해석 후 diff 확인). 플러그인을
변경할 때는 테스트 Jenkins에서 JCasC·Job DSL·Kubernetes agent를 검증한 뒤 lock
파일과 image digest를 함께 갱신한다. 이번 변경은 별도 테스트 Jenkins 없이 로컬에서
이미지 빌드·필수 플러그인 파일 존재·Trivy CRITICAL 스캔(0건)까지만 확인했고,
JCasC/Kubernetes agent 동작은 merge 후 ArgoCD가 실제 DEV Jenkins를 재기동시킬 때
확인한다.

## 빌드

```bash
AWS_PROFILE=petflow-terraform-ujibil2 \
  ./images/jenkins-controller/build-and-push.sh
```

스크립트는 ECR Repository가 이미 Terraform으로 준비돼 있어야 실행된다. 이미지에는
credential, token, Secret, JENKINS_HOME 데이터를 넣지 않는다. 빌드가 끝나면 출력된
digest를 `platform/40-jenkins/application.yaml`에 반영한다.

## Rollback

직전 정상 image reference로 GitOps 값을 되돌린다. Jenkins core와 plugin 데이터 형식이
바뀌는 업그레이드에서는 image rollback만으로 복구된다고 가정하지 말고 PVC snapshot과
plugin 호환성을 먼저 확인한다. 이 초기 버전은 기존 정상 인스턴스와 같은 core와 plugin
버전을 사용하므로 데이터 형식 변경을 포함하지 않는다.

