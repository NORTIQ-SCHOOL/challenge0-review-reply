#!/usr/bin/env python3
"""第0回 企業課題チャレンジの自動採点スクリプト（課題1・課題2で共通）。

応募者の使い方:
    pip install -r requirements-dev.txt
    python grader/grade.py

運営の使い方（応募時の再採点）:
    python grade.py --repo <応募リポジトリ> --tests <公開テスト> <非公開テスト> --json result.json

合格ライン（応募の条件）: 100点満点で 90 点を「超える」こと。
秘密情報が見つかった場合は、点数にかかわらず条件を満たさない扱い。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TITLE = "第0回 企業課題チャレンジ 自動採点"
PASS_THRESHOLD = 90.0
PLACEHOLDER_MARK = "TODO: このREADMEを書き換えてください"
PROVIDED_WORKFLOWS = {"autograde.yml", "autograde.yaml"}

CATEGORY_MAX = {
    "A": ("A. 機能テスト", 70),
    "B": ("B. ドキュメント", 15),
    "C": ("C. 安全性", 10),
    "D": ("D. CI（自動テスト）", 5),
}

SECRET_PATTERNS = [
    ("AWSのアクセスキー", re.compile(r"AKIA" + r"[0-9A-Z]{16}")),
    ("GitHubのトークン", re.compile(r"\bgh[pousr]" + r"_[A-Za-z0-9]{36,}")),
    ("APIキー（sk-で始まるもの）", re.compile(r"\bsk" + r"-[A-Za-z0-9][A-Za-z0-9_\-]{30,}")),
    ("Slackのトークン", re.compile(r"\bxox[baprs]" + r"-[A-Za-z0-9-]{10,}")),
    ("LINEのチャネルアクセストークンらしき値", re.compile(r"(?i)channel_?access_?token\s*[=:]\s*['\"][A-Za-z0-9+/=]{40,}")),
    ("秘密鍵", re.compile("-----BEGIN " + r"(RSA |EC |OPENSSH |DSA )?" + "PRIVATE KEY-----")),
]


@dataclass
class Check:
    category: str
    name: str
    points: float
    max_points: float
    message: str


def find_file(repo: Path, candidates: list[str]) -> Path | None:
    for rel in candidates:
        rel_path = Path(rel)
        parent = repo / rel_path.parent
        if not parent.is_dir():
            continue
        for child in parent.iterdir():
            if child.is_file() and child.name.lower() == rel_path.name.lower():
                return child
    return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore")
    return proc.stdout if proc.returncode == 0 else ""


def is_git_repo(repo: Path) -> bool:
    return git(repo, "rev-parse", "--is-inside-work-tree").strip() == "true"


# ---------------------------------------------------------------- A. 機能テスト


def run_tests(repo: Path, test_paths: list[Path] | None) -> tuple[int, int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        empty_ini = tmp_dir / "pytest.ini"
        empty_ini.write_text("[pytest]\n", encoding="utf-8")
        report = tmp_dir / "report.xml"
        if test_paths:
            workspace = tmp_dir / "workspace"
            workspace.mkdir()
            if (repo / "src").is_dir():
                shutil.copytree(repo / "src", workspace / "src")
            targets = []
            for i, path in enumerate(test_paths):
                dest = workspace / f"tests_{i}"
                if path.is_dir():
                    shutil.copytree(path, dest)
                else:
                    dest.mkdir()
                    shutil.copy(path, dest / path.name)
                targets.append(str(dest))
            rootdir, src_dir = workspace, workspace / "src"
        else:
            targets = [str(repo / "tests")]
            rootdir, src_dir = repo, repo / "src"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
               "-c", str(empty_ini), "--rootdir", str(rootdir),
               f"--junitxml={report}", *targets]
        try:
            proc = subprocess.run(cmd, cwd=rootdir, env=env, capture_output=True, text=True, timeout=300)
            output = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return 0, 0, "テストが5分以内に終わりませんでした（無限ループやリトライの回しすぎがないか確認してください）"
        if not report.exists():
            return 0, 0, output[-3000:]
        root = ET.parse(report).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        total = sum(int(s.get("tests", 0)) for s in suites)
        failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
        skipped = sum(int(s.get("skipped", 0)) for s in suites)
        return max(total - failed - skipped, 0), total, output[-3000:]


def check_tests(repo: Path, test_paths: list[Path] | None) -> list[Check]:
    passed, total, output = run_tests(repo, test_paths)
    max_points = CATEGORY_MAX["A"][1]
    if total == 0:
        return [Check("A", "機能テスト", 0, max_points,
                      "テストを実行できませんでした。src と tests を確認してください。\n" + output[-800:])]
    message = f"{passed}/{total} 本のテストに合格"
    if passed < total:
        message += "。失敗したテストは `python -m pytest -q` で確認できます"
    return [Check("A", "機能テスト", round(max_points * passed / total, 1), max_points, message)]


# ---------------------------------------------------------------- B. ドキュメント


def check_readme(repo: Path) -> Check:
    path = find_file(repo, ["README.md"])
    if not path:
        return Check("B", "README.md", 0, 6, "README.md がありません")
    text = read_text(path)
    if PLACEHOLDER_MARK in text:
        return Check("B", "README.md", 0, 6, "README.md がテンプレートのままです。CHALLENGE.md の「提出物」を見て書き換えてください")
    headings = "\n".join(re.findall(r"^#{1,6}\s*(.+)$", text, flags=re.M)).lower()
    points, missing = 0, []
    for keys, pts, label in (
        (("概要", "overview", "about"), 1, "「概要」"),
        (("使い方", "usage", "セットアップ"), 2, "「使い方」"),
        (("設計", "仕組み", "design", "architecture"), 2, "「設計」"),
        (("制限", "注意", "既知の問題", "limitation"), 1, "「制限・注意点」"),
    ):
        if any(k in headings for k in keys):
            points += pts
        else:
            missing.append(label)
    message = "OK" if not missing else "足りない見出し：" + "、".join(missing)
    return Check("B", "README.md", points, 6, message)


def check_doc(repo: Path, name: str, max_points: float, min_chars: int, hint: str) -> Check:
    path = find_file(repo, [name, f"docs/{name}"])
    if not path:
        return Check("B", name, 0, max_points, f"{name} がありません。{hint}")
    if len(read_text(path).strip()) < min_chars:
        return Check("B", name, max_points / 2, max_points, f"{name} の中身が短すぎます。{hint}")
    return Check("B", name, max_points, max_points, "OK")


# ---------------------------------------------------------------- C. 安全性


def files_to_scan(repo: Path) -> list[Path]:
    if is_git_repo(repo):
        listed = [repo / line for line in git(repo, "ls-files").splitlines() if line]
    else:
        listed = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [p for p in listed if p.is_file() and "grader" not in p.relative_to(repo).parts
            and p.stat().st_size < 1_000_000]


def check_safety(repo: Path) -> list[Check]:
    checks = []
    found = []
    for path in files_to_scan(repo):
        rel = path.relative_to(repo)
        if rel.name == ".env":
            found.append(f"{rel}（.env ファイルそのもの）")
            continue
        text = read_text(path)
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                found.append(f"{rel}（{label}）")
    if found:
        checks.append(Check("C", "秘密情報", 0, 5,
                            "秘密情報らしきものがあります。すぐ削除し、キーは無効化して作り直してください：" + "、".join(found[:5])))
    else:
        checks.append(Check("C", "秘密情報", 5, 5, "OK"))

    gitignore = repo / ".gitignore"
    has_env_rule = gitignore.is_file() and re.search(r"^\s*\.env\s*$", read_text(gitignore), flags=re.M)
    checks.append(Check("C", ".gitignore の .env", 2 if has_env_rule else 0, 2,
                        "OK" if has_env_rule else ".gitignore に .env の行を追加してください"))

    example = repo / ".env.example"
    checks.append(Check("C", ".env.example", 3 if example.is_file() else 0, 3,
                        "OK" if example.is_file() else "必要な環境変数の名前だけを書いた .env.example を置いてください（値は書かない）"))
    return checks


# ---------------------------------------------------------------- D. CI


def check_ci(repo: Path) -> list[Check]:
    folder = repo / ".github" / "workflows"
    files = [] if not folder.is_dir() else [
        p for p in sorted(folder.iterdir())
        if p.suffix.lower() in (".yml", ".yaml") and p.name.lower() not in PROVIDED_WORKFLOWS
    ]
    best, message = 0.0, ".github/workflows/ に、push か pull_request で pytest を実行するワークフローを作ってください"
    for path in files:
        try:
            data = (yaml.safe_load(read_text(path)) if yaml else None) or {}
        except Exception as exc:
            message = f"{path.name} をYAMLとして読めません：{exc}"
            continue
        triggers = data.get("on", data.get(True)) if isinstance(data, dict) else None
        events = {"push", "pull_request"}
        trig_ok = (triggers in events if isinstance(triggers, str)
                   else any(t in events for t in triggers) if isinstance(triggers, (list, dict)) else False)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        test_ok = isinstance(jobs, dict) and any(
            isinstance(step, dict) and "pytest" in str(step.get("run", ""))
            for job in jobs.values() for step in ((job or {}).get("steps") or [])
        )
        score = (2.5 if trig_ok else 0) + (2.5 if test_ok else 0)
        if score > best:
            best = score
            message = f"{path.name}：OK" if score == 5 else f"{path.name}：push か pull_request で動き、pytest を実行するようにしてください"
    return [Check("D", "CIのワークフロー", best, 5, message)]


# ---------------------------------------------------------------- まとめ


def grade(repo: Path, test_paths: list[Path] | None) -> dict:
    checks = (
        check_tests(repo, test_paths)
        + [
            check_readme(repo),
            check_doc(repo, "PROMPTS.md", 4, 100, "使ったAIツールと、主なプロンプトを書いてください"),
            check_doc(repo, "THIRD_PARTY.md", 5, 10, "使ったOSSとライセンスの一覧を書いてください（なければ「なし」）"),
        ]
        + check_safety(repo)
        + check_ci(repo)
    )
    categories = {}
    for key, (label, max_points) in CATEGORY_MAX.items():
        points = round(sum(c.points for c in checks if c.category == key), 1)
        categories[key] = {"label": label, "points": points, "max_points": max_points}
    total = round(sum(c["points"] for c in categories.values()), 1)
    secrets_ok = all(c.points == c.max_points for c in checks if c.name == "秘密情報")
    return {
        "total": total,
        "threshold": PASS_THRESHOLD,
        "secrets_ok": secrets_ok,
        "passed": total > PASS_THRESHOLD and secrets_ok,
        "categories": categories,
        "checks": [asdict(c) for c in checks],
    }


def to_markdown(result: dict) -> str:
    if result["passed"]:
        status = "応募の条件を満たしています"
    elif not result["secrets_ok"]:
        status = "秘密情報が見つかったため、点数にかかわらず応募の条件を満たしません"
    else:
        status = "まだ応募の条件（90点超え）に届いていません"
    lines = [f"# {TITLE}", "", f"**{result['total']} / 100 点**（{status}）", "",
             "| 区分 | 点数 |", "| --- | --- |"]
    for cat in result["categories"].values():
        lines.append(f"| {cat['label']} | {cat['points']} / {cat['max_points']} |")
    todo = [c for c in result["checks"] if c["points"] < c["max_points"]]
    lines += ["", "## 直すところ" if todo else "## すべての項目を満たしています", ""]
    lines += [f"- [{c['category']}] {c['name']}（{c['points']}/{c['max_points']}）：{c['message']}" for c in todo]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--tests", nargs="*", help="運営用：使うテストのフォルダ")
    parser.add_argument("--summary", help="Markdownの結果を書き出すファイル")
    parser.add_argument("--json", help="結果をJSONで書き出すファイル")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    tests = [Path(p).resolve() for p in args.tests] if args.tests else None
    result = grade(repo, tests)
    markdown = to_markdown(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(markdown)
    try:
        print(markdown)
    except BrokenPipeError:
        pass
    return 0 if result["passed"] or args.no_fail else 1


if __name__ == "__main__":
    sys.exit(main())
