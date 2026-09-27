#!/usr/bin/env bash
# Jenkins가 기동 전에 요구하는 Kubernetes Secret을 보존적으로 준비한다.

set -Eeuo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
GH_BIN="${GH_BIN:-gh}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"
AWS_BIN="${AWS_BIN:-aws}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
JENKINS_AUDIT_AWS_ACCOUNT_ID="${JENKINS_AUDIT_AWS_ACCOUNT_ID:-297165773875}"
JENKINS_AUDIT_AWS_SECRET_NAME="${JENKINS_AUDIT_AWS_SECRET_NAME:-petflow/jenkins/security-audit-password}"
KUBE_CONTEXT="${KUBE_CONTEXT:-petflow-dev}"
JENKINS_NAMESPACE="${JENKINS_NAMESPACE:-jenkins}"
SCOPE="all"
TEMP_DIR=""
GIT_USERNAME=""
GIT_TOKEN=""
ADMIN_USERNAME=""
ADMIN_PASSWORD=""
AUDIT_PASSWORD=""

log() {
  printf '[jenkins-credentials] %s\n' "$*"
}

fail() {
  printf '[jenkins-credentials] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: bootstrap-jenkins-credentials.sh [--context CONTEXT] [--namespace NAMESPACE] [--scope all|admin|git|audit]

Existing valid Secrets are preserved. A Secret that exists with a missing or empty
required key is not overwritten; the command fails so credentials are not rotated.
The audit password is retained in AWS Secrets Manager across cluster rebuilds.
EOF
}

cleanup() {
  if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
    rm -f -- \
      "${TEMP_DIR}/jenkins-admin-user" \
      "${TEMP_DIR}/jenkins-admin-password" \
      "${TEMP_DIR}/git-username" \
      "${TEMP_DIR}/git-token" \
      "${TEMP_DIR}/audit-password"
    rmdir -- "${TEMP_DIR}" 2>/dev/null || true
  fi
  GIT_TOKEN=""
  ADMIN_PASSWORD=""
  AUDIT_PASSWORD=""
}
trap cleanup EXIT

while (($# > 0)); do
  case "$1" in
    --context)
      (($# >= 2)) || fail '--context 값이 필요합니다.'
      KUBE_CONTEXT="$2"
      shift 2
      ;;
    --namespace)
      (($# >= 2)) || fail '--namespace 값이 필요합니다.'
      JENKINS_NAMESPACE="$2"
      shift 2
      ;;
    --scope)
      (($# >= 2)) || fail '--scope 값이 필요합니다.'
      SCOPE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "알 수 없는 인자: $1"
      ;;
  esac
done

case "${SCOPE}" in
  all|admin|git|audit) ;;
  *) fail "--scope는 all, admin, git, audit 중 하나여야 합니다: ${SCOPE}" ;;
esac

[[ -n "${KUBE_CONTEXT}" ]] || fail 'Kubernetes context가 비어 있습니다.'
[[ -n "${JENKINS_NAMESPACE}" ]] || fail 'Jenkins Namespace가 비어 있습니다.'
command -v "${KUBECTL_BIN}" >/dev/null 2>&1 || fail "kubectl 명령을 찾을 수 없습니다: ${KUBECTL_BIN}"

kctl() {
  "${KUBECTL_BIN}" --context "${KUBE_CONTEXT}" "$@"
}

secret_exists() {
  local secret_name="$1"
  local error_output

  if error_output="$(kctl --namespace "${JENKINS_NAMESPACE}" get secret "${secret_name}" -o name 2>&1)"; then
    return 0
  fi
  if [[ "${error_output}" == *"NotFound"* || "${error_output}" == *"not found"* ]]; then
    return 1
  fi

  fail "${JENKINS_NAMESPACE}/${secret_name} 조회에 실패했습니다. context·접근 권한·API 연결을 확인하세요."
}

validate_secret() {
  local secret_name="$1"
  shift
  local key_name encoded

  for key_name in "$@"; do
    if ! encoded="$(kctl --namespace "${JENKINS_NAMESPACE}" get secret "${secret_name}" \
      -o "go-template={{index .data \"${key_name}\"}}" 2>/dev/null)"; then
      fail "${JENKINS_NAMESPACE}/${secret_name}의 필수 키를 조회하지 못했습니다."
    fi
    [[ -n "${encoded}" ]] \
      || fail "${JENKINS_NAMESPACE}/${secret_name}의 필수 키가 없거나 비어 있습니다: ${key_name} (기존 Secret은 덮어쓰지 않음)"
  done

  log "${JENKINS_NAMESPACE}/${secret_name} 필수 키 검증 완료 (값 비공개)"
}

write_private_file() {
  local path="$1"
  local value="$2"

  (umask 077 && printf '%s' "${value}" >"${path}")
}

prepare_temp_dir() {
  if [[ -z "${TEMP_DIR}" ]]; then
    TEMP_DIR="$(mktemp -d)"
    chmod 700 "${TEMP_DIR}"
  fi
}

if ! kctl get --raw=/readyz >/dev/null 2>&1; then
  fail "Kubernetes context에 접근할 수 없습니다: ${KUBE_CONTEXT}"
fi
log "대상 확인: context=${KUBE_CONTEXT}, namespace=${JENKINS_NAMESPACE}, scope=${SCOPE}"

admin_missing=false
git_missing=false
audit_missing=false

if [[ "${SCOPE}" == all || "${SCOPE}" == admin ]]; then
  if secret_exists jenkins-admin-credentials; then
    validate_secret jenkins-admin-credentials jenkins-admin-user jenkins-admin-password
    log 'jenkins-admin-credentials 이미 유효함 — 기존 값 유지'
  else
    admin_missing=true
  fi
fi

if [[ "${SCOPE}" == all || "${SCOPE}" == git ]]; then
  if secret_exists jenkins-git-credentials; then
    validate_secret jenkins-git-credentials git-username git-token
    log 'jenkins-git-credentials 이미 유효함 — 기존 값 유지'
  else
    git_missing=true
  fi
fi

if [[ "${SCOPE}" == all || "${SCOPE}" == audit ]]; then
  if secret_exists jenkins-audit-credentials; then
    validate_secret jenkins-audit-credentials audit-password
    log 'jenkins-audit-credentials 이미 유효함 — 저장된 값과 일치 여부 확인 예정'
  else
    audit_missing=true
  fi
fi

# 변경 전에 모든 외부 입력을 먼저 확인한다. gh auth login을 자동 실행하지 않는다.
if [[ "${git_missing}" == true ]]; then
  command -v "${GH_BIN}" >/dev/null 2>&1 || fail "Git credential 생성에 gh 명령이 필요합니다: ${GH_BIN}"
  "${GH_BIN}" auth status >/dev/null 2>&1 \
    || fail "jenkins-git-credentials가 없고 GitHub CLI 인증도 없습니다. gh auth login을 별도로 완료한 뒤 재실행하세요."

  [[ "$("${GH_BIN}" api repos/urineun-jigeum-bildeujung/sever --jq '.permissions.pull')" == true ]] \
    || fail '현재 GitHub 인증에는 sever 저장소 읽기 권한이 없습니다.'
  [[ "$("${GH_BIN}" api repos/urineun-jigeum-bildeujung/gitops-value --jq '.permissions.push')" == true ]] \
    || fail '현재 GitHub 인증에는 gitops-value 저장소 쓰기 권한이 없습니다.'

  GIT_USERNAME="$("${GH_BIN}" api user --jq .login)"
  GIT_TOKEN="$("${GH_BIN}" auth token)"
  [[ -n "${GIT_USERNAME}" ]] || fail 'GitHub 사용자명이 비어 있습니다.'
  [[ -n "${GIT_TOKEN}" ]] || fail 'GitHub 토큰이 비어 있습니다.'
  log 'GitHub 저장소 읽기/쓰기 권한과 credential 입력 확인 완료 (값 비공개)'
fi

if [[ "${admin_missing}" == true ]]; then
  command -v "${OPENSSL_BIN}" >/dev/null 2>&1 || fail "관리자 비밀번호 생성에 openssl이 필요합니다: ${OPENSSL_BIN}"
  ADMIN_USERNAME='admin'
  ADMIN_PASSWORD="$("${OPENSSL_BIN}" rand -hex 24)"
  ADMIN_PASSWORD="${ADMIN_PASSWORD:0:24}"
  [[ -n "${ADMIN_PASSWORD}" ]] || fail 'Jenkins 관리자 비밀번호 생성에 실패했습니다.'
fi

if [[ "${SCOPE}" == all || "${SCOPE}" == audit ]]; then
  command -v "${AWS_BIN}" >/dev/null 2>&1 || fail "보안팀 비밀번호 복원에 AWS CLI가 필요합니다: ${AWS_BIN}"
  aws_account="$("${AWS_BIN}" sts get-caller-identity --query Account --output text 2>/dev/null)" \
    || fail 'AWS 계정 확인에 실패했습니다.'
  [[ "${aws_account}" == "${JENKINS_AUDIT_AWS_ACCOUNT_ID}" ]] \
    || fail "AWS 계정이 예상값과 다릅니다: ${aws_account}"
  if aws_result="$("${AWS_BIN}" secretsmanager get-secret-value \
    --region "${AWS_REGION}" --secret-id "${JENKINS_AUDIT_AWS_SECRET_NAME}" \
    --query SecretString --output text 2>&1)"; then
    AUDIT_PASSWORD="${aws_result}"
    [[ -n "${AUDIT_PASSWORD}" && "${AUDIT_PASSWORD}" != None ]] \
      || fail "Secrets Manager ${JENKINS_AUDIT_AWS_SECRET_NAME}의 SecretString이 비어 있습니다."
  elif [[ "${aws_result}" == *ResourceNotFoundException* ]]; then
    [[ "${audit_missing}" == true ]] \
      || fail "기존 Jenkins audit Secret이 있는데 AWS 보존 Secret이 없습니다. 자동 재발급하지 않습니다: ${JENKINS_AUDIT_AWS_SECRET_NAME}"
    command -v "${OPENSSL_BIN}" >/dev/null 2>&1 || fail "보안팀 비밀번호 생성에 openssl이 필요합니다: ${OPENSSL_BIN}"
    AUDIT_PASSWORD="$("${OPENSSL_BIN}" rand -hex 24)"
    [[ -n "${AUDIT_PASSWORD}" ]] || fail '보안팀 비밀번호 생성에 실패했습니다.'
    prepare_temp_dir
    write_private_file "${TEMP_DIR}/audit-password" "${AUDIT_PASSWORD}"
    "${AWS_BIN}" secretsmanager create-secret \
      --region "${AWS_REGION}" --name "${JENKINS_AUDIT_AWS_SECRET_NAME}" \
      --secret-string "file://${TEMP_DIR}/audit-password" --query ARN --output text >/dev/null \
      || fail "Secrets Manager ${JENKINS_AUDIT_AWS_SECRET_NAME} 생성에 실패했습니다. 비밀번호는 출력하지 않았습니다."
    log "Secrets Manager ${JENKINS_AUDIT_AWS_SECRET_NAME} 최초 생성 완료 (값 비공개)"
  else
    fail "Secrets Manager ${JENKINS_AUDIT_AWS_SECRET_NAME} 조회에 실패했습니다. AWS 자격증명과 GetSecretValue 권한을 확인하세요."
  fi

  if [[ "${audit_missing}" == false ]]; then
    command -v base64 >/dev/null 2>&1 || fail '기존 보안팀 Secret 검증에 base64가 필요합니다.'
    audit_encoded="$(kctl --namespace "${JENKINS_NAMESPACE}" get secret jenkins-audit-credentials \
      -o 'go-template={{index .data "audit-password"}}')"
    audit_existing="$(printf '%s' "${audit_encoded}" | base64 --decode)" \
      || fail '기존 보안팀 Secret 값을 디코딩하지 못했습니다.'
    [[ "${audit_existing}" == "${AUDIT_PASSWORD}" ]] \
      || fail '기존 Jenkins audit Secret과 AWS 보존 Secret의 값이 다릅니다. 자동 교체하지 않습니다.'
    audit_existing=""
    audit_encoded=""
  fi
fi

if [[ "${admin_missing}" == true || "${git_missing}" == true || "${audit_missing}" == true ]]; then
  if ! kctl get namespace "${JENKINS_NAMESPACE}" >/dev/null 2>&1; then
    kctl create namespace "${JENKINS_NAMESPACE}"
  fi
fi

if [[ "${admin_missing}" == true ]]; then
  prepare_temp_dir
  write_private_file "${TEMP_DIR}/jenkins-admin-user" "${ADMIN_USERNAME}"
  write_private_file "${TEMP_DIR}/jenkins-admin-password" "${ADMIN_PASSWORD}"
  kctl --namespace "${JENKINS_NAMESPACE}" create secret generic jenkins-admin-credentials \
    --from-file=jenkins-admin-user="${TEMP_DIR}/jenkins-admin-user" \
    --from-file=jenkins-admin-password="${TEMP_DIR}/jenkins-admin-password"
  ADMIN_PASSWORD=""
  log 'jenkins-admin-credentials 누락분 생성 완료'
  validate_secret jenkins-admin-credentials jenkins-admin-user jenkins-admin-password
fi

if [[ "${git_missing}" == true ]]; then
  prepare_temp_dir
  write_private_file "${TEMP_DIR}/git-username" "${GIT_USERNAME}"
  write_private_file "${TEMP_DIR}/git-token" "${GIT_TOKEN}"
  kctl --namespace "${JENKINS_NAMESPACE}" create secret generic jenkins-git-credentials \
    --from-file=git-username="${TEMP_DIR}/git-username" \
    --from-file=git-token="${TEMP_DIR}/git-token"
  GIT_TOKEN=""
  log 'jenkins-git-credentials 누락분 생성 완료'
  validate_secret jenkins-git-credentials git-username git-token
fi

if [[ "${audit_missing}" == true ]]; then
  prepare_temp_dir
  write_private_file "${TEMP_DIR}/audit-password" "${AUDIT_PASSWORD}"
  kctl --namespace "${JENKINS_NAMESPACE}" create secret generic jenkins-audit-credentials \
    --from-file=audit-password="${TEMP_DIR}/audit-password"
  AUDIT_PASSWORD=""
  log 'jenkins-audit-credentials 누락분 생성 완료 (AWS 보존값 사용)'
  validate_secret jenkins-audit-credentials audit-password
fi

log 'Jenkins 필수 Secret 준비 완료'
