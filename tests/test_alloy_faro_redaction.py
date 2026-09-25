import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "platform/30-alloy/application.yaml"

# Alloy 문자열 리터럴(따옴표 안, 백슬래시 이스케이프)에서 값을 꺼내는 정규식
LITERAL = r'"((?:[^"\\]|\\.)*)"'


def unescape(literal):
    return re.sub(r'\\(["\\])', r"\1", literal)


def faro_redact_block():
    app = yaml.safe_load(APP.read_text())
    values = yaml.safe_load(app["spec"]["source"]["helm"]["values"])
    config = values["collectors"]["alloy"]["extraConfig"]
    start = config.index('loki.process "faro_redact"')
    depth = 0
    for i in range(config.index("{", start), len(config)):
        depth += config[i] == "{"
        depth -= config[i] == "}"
        if depth == 0:
            return config[start:i + 1]


def replace_rules():
    block = faro_redact_block()
    pattern = rf"stage\.replace \{{\s*expression = {LITERAL}\s*replace\s*= {LITERAL}\s*\}}"
    return [(unescape(e), unescape(r)) for e, r in re.findall(pattern, block)]


def redact(line, rules):
    # stage.replace는 정규식에서 괄호로 묶은 부분만 replace 값으로 바꾸고 나머지는 그대로 둔다.
    # 실제 Alloy(v1.19.2)에 넣어 확인한 동작이다. ${1} 같은 표기는 해석되지 않는다.
    for expression, replace in rules:
        pattern = re.compile(expression)

        def swap(m, replace=replace):
            if m.group(1) is None:
                return m.group(0)
            offset = m.start(0)
            return m.group(0)[:m.start(1) - offset] + replace + m.group(0)[m.end(1) - offset:]

        line = pattern.sub(swap, line)
    return line


# (입력, 실제 Alloy가 낸 결과). 값은 모두 가짜다.
CASES = [
    (
        r'timestamp="2026-09-25 09:00:00 +0000 UTC" kind=log message="x" context_refreshToken=FAKE-TOKEN-1 '
        r'context_phone="010-0000-0000" context_note=hello app_name=case-1 '
        r"page_url=https://leechs.shop/auth/callback?code=FAKECODE&state=abc browser_mobile=false",
        r'timestamp="2026-09-25 09:00:00 +0000 UTC" kind=log message="x" context_refreshToken=[REDACTED] '
        r'context_phone=[REDACTED] context_note=hello app_name=case-1 '
        r"page_url=https://leechs.shop/auth/callback?[REDACTED] browser_mobile=false",
    ),
    (
        r'kind=event name=click context_note=hello app_name=case-2 page_url=https://leechs.shop/products?page=2',
        r'kind=event name=click context_note=hello app_name=case-2 page_url=https://leechs.shop/products?page=2',
    ),
    (
        r"kind=event app_name=case-3 page_url=https://x/signup?nickname=FAKENICK&a=1 "
        r"referrer=https://x/payment/done?paymentKey=FAKEPK&orderId=9 z=1",
        r"kind=event app_name=case-3 page_url=https://x/signup?[REDACTED] "
        r"referrer=https://x/payment/done?[REDACTED] z=1",
    ),
    (
        r'{"authorization":"Bearer FAKEAUTH","idempotency-key":"FAKEKEY","code":"FAKEC","note":"keep","app_name":"case-4"}',
        r'{"authorization":"[REDACTED]","idempotency-key":"[REDACTED]","code":"[REDACTED]","note":"keep","app_name":"case-4"}',
    ),
    (
        r"kind=event event_data_server.address=leechs.shop app_name=case-5 status=200",
        r"kind=event event_data_server.address=leechs.shop app_name=case-5 status=200",
    ),
    (
        r'kind=log value="a \"b\" c" context_nickname="홍 길동" app_name=case-6 tail=keep',
        r'kind=log value="a \"b\" c" context_nickname=[REDACTED] app_name=case-6 tail=keep',
    ),
    (
        r'kind=event app_name=case-7 page_url="https://leechs.shop/mypage/address/search?query=FAKE%20ADDR&_rsc=1abc"',
        r'kind=event app_name=case-7 page_url="https://leechs.shop/mypage/address/search?[REDACTED]"',
    ),
    (
        r'kind=exception status=400 code=PAYMENT_FAIL value="boom" app_name=case-8',
        r'kind=exception status=400 code=PAYMENT_FAIL value="boom" app_name=case-8',
    ),
]


class FaroRedactionTest(unittest.TestCase):

    def test_rules_are_found(self):
        self.assertEqual(len(replace_rules()), 4)

    def test_replace_never_uses_group_references(self):
        # Alloy는 replace 안의 ${1}을 해석하지 않고 글자 그대로 찍는다. 이 표기가 들어가면
        # 로그가 망가지고 가릴 값은 그대로 남는다(2026-09-25 실제로 발생).
        for expression, replace in replace_rules():
            self.assertNotIn("${", replace, expression)
            self.assertNotIn("$1", replace, expression)

    def test_each_rule_captures_only_the_value_to_hide(self):
        for expression, _ in replace_rules():
            self.assertEqual(re.compile(expression).groups, 1, expression)

    def test_redaction_matches_what_real_alloy_produced(self):
        rules = replace_rules()
        for source, expected in CASES:
            self.assertEqual(redact(source, rules), expected, source)

    def test_service_name_label_is_lifted_from_app_name(self):
        block = faro_redact_block()
        self.assertRegex(block, r'stage\.logfmt \{\s*mapping = \{ app_name = "" \}\s*\}')
        self.assertRegex(block, r'stage\.labels \{\s*values = \{ service_name = "app_name" \}\s*\}')


if __name__ == "__main__":
    unittest.main()
