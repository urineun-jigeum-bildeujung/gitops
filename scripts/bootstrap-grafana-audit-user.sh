#!/usr/bin/env bash
# Create or restore the security-audit Grafana account with a stable password.

set -Eeuo pipefail

AWS_BIN="${AWS_BIN:-aws}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
CURL_BIN="${CURL_BIN:-curl}"
JQ_BIN="${JQ_BIN:-jq}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
EXPECTED_AWS_ACCOUNT_ID="${GRAFANA_AUDIT_AWS_ACCOUNT_ID:-297165773875}"
AWS_SECRET_NAME="${GRAFANA_AUDIT_AWS_SECRET_NAME:-petflow/grafana/security-audit-password}"
KUBE_CONTEXT="${KUBE_CONTEXT:-petflow-dev}"
NAMESPACE="${GRAFANA_NAMESPACE:-observability}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-kube-prometheus-stack-grafana}"
GRAFANA_ADMIN_SECRET_NAME="${GRAFANA_ADMIN_SECRET_NAME:-grafana-admin-credentials}"
LOGIN="security-audit"
LOCAL_PORT="${GRAFANA_BOOTSTRAP_LOCAL_PORT:-13000}"
TEMP_DIR=""
PORT_FORWARD_PID=""
AUDIT_PASSWORD=""
ADMIN_PASSWORD=""

log() { printf '[grafana-audit] %s\n' "$*"; }
fail() { printf '[grafana-audit] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ -n "${PORT_FORWARD_PID}" ]]; then
    kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    wait "${PORT_FORWARD_PID}" 2>/dev/null || true
  fi
  if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
    rm -rf -- "${TEMP_DIR}"
  fi
  AUDIT_PASSWORD=""
  ADMIN_PASSWORD=""
}
trap cleanup EXIT

for command_name in "${AWS_BIN}" "${KUBECTL_BIN}" "${CURL_BIN}" "${JQ_BIN}" "${OPENSSL_BIN}" base64; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "${command_name} 명령이 필요합니다."
done

TEMP_DIR="$(mktemp -d)"
chmod 700 "${TEMP_DIR}"

account_id="$("${AWS_BIN}" sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || fail 'AWS 계정 확인에 실패했습니다.'
[[ "${account_id}" == "${EXPECTED_AWS_ACCOUNT_ID}" ]] \
  || fail "AWS 계정이 예상값과 다릅니다: ${account_id}"

if secret_result="$("${AWS_BIN}" secretsmanager get-secret-value --region "${AWS_REGION}" \
  --secret-id "${AWS_SECRET_NAME}" --query SecretString --output text 2>&1)"; then
  AUDIT_PASSWORD="${secret_result}"
  [[ -n "${AUDIT_PASSWORD}" && "${AUDIT_PASSWORD}" != None ]] \
    || fail "Secrets Manager ${AWS_SECRET_NAME}의 SecretString이 비어 있습니다."
elif [[ "${secret_result}" == *ResourceNotFoundException* ]]; then
  AUDIT_PASSWORD="$("${OPENSSL_BIN}" rand -hex 24)"
  [[ -n "${AUDIT_PASSWORD}" ]] || fail '보안팀 Grafana 비밀번호 생성에 실패했습니다.'
  (umask 077 && printf '%s' "${AUDIT_PASSWORD}" >"${TEMP_DIR}/audit-password")
  "${AWS_BIN}" secretsmanager create-secret --region "${AWS_REGION}" \
    --name "${AWS_SECRET_NAME}" --secret-string "file://${TEMP_DIR}/audit-password" \
    --query ARN --output text >/dev/null \
    || fail "Secrets Manager ${AWS_SECRET_NAME} 생성에 실패했습니다."
  log "Secrets Manager ${AWS_SECRET_NAME} 최초 생성 완료 (값 비공개)"
else
  fail "Secrets Manager ${AWS_SECRET_NAME} 조회에 실패했습니다. AWS 권한을 확인하세요."
fi
[[ "${AUDIT_PASSWORD}" != *$'\n'* && "${AUDIT_PASSWORD}" != *$'\r'* ]] \
  || fail '저장된 Grafana 비밀번호에 지원하지 않는 개행 문자가 있습니다.'

admin_user_b64="$("${KUBECTL_BIN}" --context "${KUBE_CONTEXT}" -n "${NAMESPACE}" \
  get secret "${GRAFANA_ADMIN_SECRET_NAME}" -o 'go-template={{index .data "admin-user"}}' 2>/dev/null)" \
  || fail 'Grafana 관리자 Kubernetes Secret을 조회하지 못했습니다.'
admin_password_b64="$("${KUBECTL_BIN}" --context "${KUBE_CONTEXT}" -n "${NAMESPACE}" \
  get secret "${GRAFANA_ADMIN_SECRET_NAME}" -o 'go-template={{index .data "admin-password"}}' 2>/dev/null)" \
  || fail 'Grafana 관리자 Kubernetes Secret의 비밀번호를 조회하지 못했습니다.'
[[ -n "${admin_user_b64}" && -n "${admin_password_b64}" ]] \
  || fail 'Grafana 관리자 Secret에 필요한 값이 없습니다.'
ADMIN_USER="$(printf '%s' "${admin_user_b64}" | base64 --decode)" \
  || fail 'Grafana 관리자 사용자 디코딩에 실패했습니다.'
ADMIN_PASSWORD="$(printf '%s' "${admin_password_b64}" | base64 --decode)" \
  || fail 'Grafana 관리자 비밀번호 디코딩에 실패했습니다.'
unset admin_user_b64 admin_password_b64
[[ -n "${ADMIN_USER}" && -n "${ADMIN_PASSWORD}" ]] \
  || fail 'Grafana 관리자 Secret 값이 비어 있습니다.'
[[ "${ADMIN_USER}" != *$'\n'* && "${ADMIN_PASSWORD}" != *$'\n'* ]] \
  || fail 'Grafana 관리자 Secret에 개행 문자가 포함되어 있습니다.'

# Write credentials to a private curl config instead of exposing them in process arguments.
escape_curl_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "${value}"
}
printf 'user = "%s:%s"\n' "$(escape_curl_value "${ADMIN_USER}")" \
  "$(escape_curl_value "${ADMIN_PASSWORD}")" >"${TEMP_DIR}/curl.conf"
chmod 600 "${TEMP_DIR}/curl.conf"

"${KUBECTL_BIN}" --context "${KUBE_CONTEXT}" -n "${NAMESPACE}" \
  port-forward --address 127.0.0.1 "service/${GRAFANA_SERVICE}" "${LOCAL_PORT}:80" \
  >"${TEMP_DIR}/port-forward.log" 2>&1 &
PORT_FORWARD_PID=$!

ready=false
for _ in $(seq 1 60); do
  if ! kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
    cat "${TEMP_DIR}/port-forward.log" >&2
    fail 'Grafana Service port-forward가 시작되지 않았습니다.'
  fi
  if "${CURL_BIN}" --silent --show-error --fail --max-time 3 \
    "http://127.0.0.1:${LOCAL_PORT}/api/health" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[[ "${ready}" == true ]] || fail 'Grafana API가 준비되지 않았습니다.'

api_request() {
  local method="$1" path="$2" body_file="${3:-}"
  local args=(--silent --show-error --max-time 20 --config "${TEMP_DIR}/curl.conf" \
    --request "${method}" --output "${TEMP_DIR}/response.json" --write-out '%{http_code}')
  if [[ -n "${body_file}" ]]; then
    args+=(--header 'Content-Type: application/json' --data-binary "@${body_file}")
  fi
  "${CURL_BIN}" "${args[@]}" "http://127.0.0.1:${LOCAL_PORT}${path}"
}

lookup_code="$(api_request GET "/api/users/lookup?loginOrEmail=${LOGIN}")" \
  || fail 'Grafana 계정 조회 API 호출이 실패했습니다.'
if [[ "${lookup_code}" == 200 ]]; then
  user_id="$("${JQ_BIN}" -r '.id // empty' "${TEMP_DIR}/response.json")"
  [[ "${user_id}" =~ ^[1-9][0-9]*$ ]] || fail 'Grafana 계정 조회 결과에 유효한 사용자 ID가 없습니다.'
elif [[ "${lookup_code}" == 404 ]]; then
  "${JQ_BIN}" -n --arg name 'Security Audit' --arg email 'security-audit@petflow.invalid' \
    --arg login "${LOGIN}" --arg password "${AUDIT_PASSWORD}" \
    '{name:$name,email:$email,login:$login,password:$password,OrgId:1}' \
    >"${TEMP_DIR}/create-user.json"
  create_code="$(api_request POST /api/admin/users "${TEMP_DIR}/create-user.json")" \
    || fail 'Grafana 사용자 생성 API 호출이 실패했습니다.'
  [[ "${create_code}" == 200 ]] \
    || fail "Grafana security-audit 생성에 실패했습니다 (HTTP ${create_code})."
  user_id="$("${JQ_BIN}" -r '.id // empty' "${TEMP_DIR}/response.json")"
  [[ "${user_id}" =~ ^[1-9][0-9]*$ ]] || fail 'Grafana 사용자 생성 결과에 유효한 ID가 없습니다.'
  log 'Grafana security-audit 사용자 최초 생성 완료'
else
  fail "Grafana 계정 조회 실패 (HTTP ${lookup_code})."
fi

org_users_code="$(api_request GET /api/org/users/lookup)" \
  || fail 'Grafana 조직 사용자 조회 API 호출이 실패했습니다.'
[[ "${org_users_code}" == 200 ]] || fail "Grafana 조직 사용자 조회 실패 (HTTP ${org_users_code})."
org_user_id="$("${JQ_BIN}" -r --arg login "${LOGIN}" \
  '[.[] | select(.login == $login) | .userId] | first // empty' "${TEMP_DIR}/response.json")"
if [[ -z "${org_user_id}" ]]; then
  "${JQ_BIN}" -n --arg login "${LOGIN}" '{role:"Editor",loginOrEmail:$login}' \
    >"${TEMP_DIR}/add-org-user.json"
  add_org_code="$(api_request POST /api/org/users "${TEMP_DIR}/add-org-user.json")" \
    || fail 'Grafana 조직에 계정 추가 API 호출이 실패했습니다.'
  [[ "${add_org_code}" == 200 ]] || fail "Grafana 조직에 계정 추가 실패 (HTTP ${add_org_code})."
  org_user_id="$("${JQ_BIN}" -r '.userId // empty' "${TEMP_DIR}/response.json")"
fi
[[ "${org_user_id}" == "${user_id}" ]] \
  || fail 'Grafana 기본 조직에서 security-audit 사용자 ID가 일치하지 않습니다.'

# Keep Secrets Manager authoritative, including after an ephemeral Grafana database reset.
"${JQ_BIN}" -n --arg password "${AUDIT_PASSWORD}" '{password:$password}' \
  >"${TEMP_DIR}/password.json"
password_code="$(api_request PUT "/api/admin/users/${user_id}/password" "${TEMP_DIR}/password.json")" \
  || fail 'Grafana 사용자 비밀번호 동기화 API 호출이 실패했습니다.'
[[ "${password_code}" == 200 ]] || fail "Grafana 비밀번호 동기화 실패 (HTTP ${password_code})."

"${JQ_BIN}" -n '{role:"Editor"}' >"${TEMP_DIR}/role.json"
role_code="$(api_request PATCH "/api/org/users/${user_id}" "${TEMP_DIR}/role.json")" \
  || fail 'Grafana Editor 역할 설정 API 호출이 실패했습니다.'
[[ "${role_code}" == 200 ]] || fail "Grafana Editor 역할 설정 실패 (HTTP ${role_code})."

"${JQ_BIN}" -n '{isGrafanaAdmin:false}' >"${TEMP_DIR}/server-admin.json"
admin_role_code="$(api_request PUT "/api/admin/users/${user_id}/permissions" "${TEMP_DIR}/server-admin.json")" \
  || fail 'Grafana 전역 관리자 권한 확인 API 호출이 실패했습니다.'
[[ "${admin_role_code}" == 200 ]] \
  || fail "Grafana 전역 관리자 권한 제외 설정 실패 (HTTP ${admin_role_code})."

log "계정 보장 완료: login=${LOGIN}, orgRole=Editor, grafanaAdmin=false (비밀번호 값 비공개)"
