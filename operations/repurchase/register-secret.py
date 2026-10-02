"""기존 ai_dev 비밀번호를 숨김 입력으로 Secrets Manager에 등록한다.

비밀번호는 파일, 명령행 인자, 출력에 기록하지 않는다. DB 비밀번호는 변경하지 않는다.
"""
import getpass
import json
import subprocess
import sys

BASE = ["aws", "--profile", "petflow-terraform-ujibil1", "--region", "ap-northeast-2", "secretsmanager"]
NAME = "petflow/repurchase/db"

def main():
    if not sys.stdin.isatty():
        raise SystemExit("비밀번호를 숨김 입력할 수 있는 터미널에서 실행하세요.")
    existing = subprocess.run(BASE + ["describe-secret", "--secret-id", NAME],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if existing.returncode and "ResourceNotFoundException" not in existing.stderr:
        raise SystemExit(existing.stderr)
    password = getpass.getpass("기존 ai_dev 비밀번호: ")
    if not password:
        raise SystemExit("빈 비밀번호는 등록하지 않습니다.")
    if password != getpass.getpass("비밀번호 확인: "):
        raise SystemExit("입력한 비밀번호가 일치하지 않습니다.")
    operation = (["put-secret-value", "--secret-id", NAME] if existing.returncode == 0
                 else ["create-secret", "--name", NAME])
    result = subprocess.run(BASE + operation + ["--secret-string", "file:///dev/stdin"],
                            input=json.dumps({"username": "ai_dev", "password": password}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise SystemExit(result.stderr)
    print("petflow/repurchase/db 등록 완료. DB 비밀번호는 변경하지 않았습니다.")

if __name__ == "__main__":
    main()
