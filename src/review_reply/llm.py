"""AI（大規模言語モデル）を呼ぶ部分の約束ごと。

core.py は、次の形のオブジェクトを受け取って使います。

    class LLMClient:
        def complete(self, system: str, user: str) -> str: ...

テストでは、決まった答えを返す偽物（tests/fakes.py の FakeLLM）を渡します。
本物のAI（Azure OpenAI、Microsoft Foundry など）につなぐ実装は、このファイルに
自由に追加してかまいません。APIキーは環境変数から読み、コードに書かないでください。
"""

from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...
