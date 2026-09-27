#!/usr/bin/env bash
# Redis 기본/서비스/감사 계정 비밀번호를 AWS Secrets Manager에 최초 1회만 생성한다.

set -Eeuo pipefail

AWS_BIN="${AWS_BIN:-aws}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
REDIS_SECRET_NAME="${REDIS_SECRET_NAME:-petflow/redis/credentials}"
EXPECTED_AWS_ACCOUNT_ID="${EXPECTED_AWS_ACCOUNT_ID:-297165773875}"

fail() {
  printf '[redis-credentials] ERROR: %s\n' "$*" >&2
  exit 1
}

command -v "${AWS_BIN}" >/dev/null 2>&1 || fail 'aws CLI가 필요합니다.'
command -v "${OPENSSL_BIN}" >/dev/null 2>&1 || fail 'openssl이 필요합니다.'
command -v python3 >/dev/null 2>&1 || fail 'python3가 필요합니다.'

account_id="$("${AWS_BIN}" sts get-caller-identity --query Account --output text)" \
  || fail 'AWS 계정을 확인하지 못했습니다.'
[[ "${account_id}" == "${EXPECTED_AWS_ACCOUNT_ID}" ]] \
  || fail "예상한 AWS 계정이 아닙니다: ${account_id}"

temp_dir="$(mktemp -d)"
chmod 700 "${temp_dir}"
cleanup() {
  rm -f -- "${temp_dir}/credentials.json" "${temp_dir}/aws-error"
  rmdir -- "${temp_dir}" 2>/dev/null || true
}
trap cleanup EXIT

if "${AWS_BIN}" secretsmanager get-secret-value \
  --region "${AWS_REGION}" --secret-id "${REDIS_SECRET_NAME}" \
  --query SecretString --output text >"${temp_dir}/credentials.json" 2>"${temp_dir}/aws-error"; then
  python3 - "${temp_dir}/credentials.json" <<'PY' \
    || fail '기존 Redis Secret의 필수 값이 없거나 형식이 잘못되었습니다. 자동 교체하지 않습니다.'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    credentials = json.load(source)
for key in ("default-password", "app-password", "audit-password"):
    if not re.fullmatch(r"[0-9a-f]{64}", credentials.get(key, "")):
        raise SystemExit(1)
if len({credentials[key] for key in ("default-password", "app-password", "audit-password")}) != 3:
    raise SystemExit(1)
PY
  printf '[redis-credentials] 기존 Secrets Manager 값 검증 완료 (값 유지·비공개)\n'
elif [[ "$(<"${temp_dir}/aws-error")" == *ResourceNotFoundException* ]]; then
  default_password="$("${OPENSSL_BIN}" rand -hex 32)"
  app_password="$("${OPENSSL_BIN}" rand -hex 32)"
  audit_password="$("${OPENSSL_BIN}" rand -hex 32)"
  (umask 077 && printf '{"default-password":"%s","app-password":"%s","audit-password":"%s"}' \
    "${default_password}" "${app_password}" "${audit_password}" >"${temp_dir}/credentials.json")
  "${AWS_BIN}" secretsmanager create-secret \
    --region "${AWS_REGION}" --name "${REDIS_SECRET_NAME}" \
    --secret-string "file://${temp_dir}/credentials.json" \
    --query ARN --output text >/dev/null \
    || fail 'Redis Secret 생성에 실패했습니다.'
  printf '[redis-credentials] Secrets Manager 최초 생성 완료 (값 비공개)\n'
else
  fail 'Secrets Manager 조회에 실패했습니다. AWS 인증·권한·리전을 확인하세요.'
fi
