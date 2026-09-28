#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY="${JENKINS_IMAGE_REPOSITORY:-297165773875.dkr.ecr.ap-northeast-2.amazonaws.com/petflow/jenkins-controller}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
VCS_REF="${VCS_REF:-$(git -C "${SCRIPT_DIR}" rev-parse HEAD)}"
IMAGE_TAG="${IMAGE_TAG:-2.568.3-jdk21-${VCS_REF:0:12}}"
BUILD_DATE="${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
IMAGE="${REPOSITORY}:${IMAGE_TAG}"

for command_name in aws docker git; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    printf '[jenkins-image] ERROR: %s 명령이 필요합니다.\n' "${command_name}" >&2
    exit 1
  }
done

aws ecr describe-repositories \
  --region "${AWS_REGION}" \
  --repository-names petflow/jenkins-controller >/dev/null

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"

docker build \
  --build-arg "VCS_REF=${VCS_REF}" \
  --build-arg "BUILD_DATE=${BUILD_DATE}" \
  --tag "${IMAGE}" \
  "${SCRIPT_DIR}"

docker run --rm --entrypoint sh "${IMAGE}" -c '
  set -eu
  test -s /usr/share/jenkins/ref/plugins.lock.txt
  test -s /usr/share/jenkins/ref/plugins/configuration-as-code.jpi
  test -s /usr/share/jenkins/ref/plugins/job-dsl.jpi
  test -s /usr/share/jenkins/ref/plugins/kubernetes.jpi
  test -s /usr/share/jenkins/ref/plugins/github-branch-source.jpi
'

docker run --rm \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.74.0 image \
  --severity CRITICAL --exit-code 1 --ignore-unfixed "${IMAGE}"

docker push "${IMAGE}"
docker image inspect "${IMAGE}" --format '{{index .RepoDigests 0}}'

