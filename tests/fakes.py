"""テスト用の偽物のAI。決まった答えを順番に返し、受け取ったプロンプトを記録する。"""


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise AssertionError("AIを想定より多く呼んでいます")
        return self.responses.pop(0)
