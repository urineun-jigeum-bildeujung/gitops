<!--
PR 제목 컨벤션: 유형: 설명
예시: feat: kafka 토픽 정의 추가, fix: cronjob 리소스 requests 누락 수정
-->

## 변경 내용

<!-- 이 PR이 무엇을 바꾸는지 요약 (어떤 addon/서비스/차트인지) -->


## 변경 범위

<!-- 해당하는 것에 표시 -->
- [ ] platform addon (`platform/*`)
- [ ] 서비스 차트 (`charts/generic-service`)
- [ ] ArgoCD 구조 (`bootstrap/`, `applications/`, `projects/`)
- [ ] 문서 (`docs/`)

## 검증

<!-- task validate / helm lint / helm template 결과를 확인했는지 -->
- [ ] `task validate` 통과 확인
- [ ] (차트 변경 시) `helm template`으로 렌더링 결과 직접 확인

## 클러스터 반영 영향

<!--
이 레포는 main에 merge되는 즉시 ArgoCD가 자동 반영합니다(docs/branching-strategy.md 참고).
merge 시 실제로 어떤 리소스가 새로 생기거나 바뀌는지, 기존 서비스에 영향이 있는지 적어주세요.
-->


## To Reviewers

<!-- 리뷰어에게 특별히 봐달라고 요청하고 싶은 부분 -->
