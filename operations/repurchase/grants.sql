-- 관리자 계정으로 실행한다. ai_dev와 repurchase_db가 먼저 존재해야 한다.
-- AI 팀이 ai_dev로 생성한 스키마/테이블에는 같은 계정으로 적재할 수 있다.
GRANT CONNECT, CREATE ON DATABASE repurchase_db TO ai_dev;
