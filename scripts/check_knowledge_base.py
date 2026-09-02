#!/usr/bin/env python3
"""Run local consistency checks for the Markdown knowledge base."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references" / "README.md"
IGNORED_DIRS = {".git", ".agents", ".codex", "private", "__pycache__"}
SOURCE_CODE_RE = re.compile(
    r"\b(?:CN|WHO|NHS|ACOG|RCOG|MAYO|FDA|COCHRANE|ZJ|HZ|WHZJU)-[A-Z]+-\d{3}\b"
)
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
REVIEW_RE = re.compile(r"^- 最近复核：(\d{4}-\d{2}-\d{2})$", re.MULTILINE)
DYNAMIC_RE = re.compile(
    r"政策|政务|医保|生育保险|津贴|补贴|劳动|产假|护理假|育儿假|"
    r"生育登记|建小卡|社区|医院|院区|预约|入院|户籍|出生医学证明|联办"
)


def markdown_files() -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        base = Path(directory)
        files.extend(base / name for name in filenames if name.endswith(".md"))
    return sorted(files)


def parse_date(value: str, label: str, errors: list[str]) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{label}: 无效日期 {value}")
        return None


def without_fenced_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def source_sections(reference_text: str) -> tuple[dict[str, str], set[str]]:
    active_text, stopped_text = reference_text.split("## 已停用来源", 1)
    active: dict[str, str] = {}
    matches = list(
        re.finditer(r"^###\s+([A-Z][A-Z0-9-]+)[：:].*$", active_text, re.MULTILINE)
    )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(active_text)
        active[match.group(1)] = active_text[match.start() : end]
    stopped = set(SOURCE_CODE_RE.findall(stopped_text.split("## 来源编号规则", 1)[0]))
    return active, stopped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", help="以 YYYY-MM-DD 覆盖当前日期，便于复核到期测试")
    args = parser.parse_args()
    errors: list[str] = []
    today = parse_date(args.today, "--today", errors) if args.today else date.today()
    if today is None:
        return 2

    files = markdown_files()
    file_set = {path.resolve() for path in files}
    incoming = {path.resolve(): 0 for path in files}
    used_sources: set[str] = set()

    for path in files:
        text = path.read_text(encoding="utf-8")
        checked_text = without_fenced_code(text)
        relative = path.relative_to(ROOT)
        h1_count = len(re.findall(r"^#(?!#)\s+", checked_text, re.MULTILINE))
        if h1_count != 1:
            errors.append(f"{relative}: 一级标题数量应为 1，实际为 {h1_count}")

        if re.search(r"\b\d{17}[\dXx]\b|\b1[3-9]\d{9}\b", checked_text):
            errors.append(f"{relative}: 疑似包含身份证号或手机号")

        if "20-24 周" in checked_text:
            errors.append(f"{relative}: 使用了不完整的中期超声窗口，应核对 20～24+6 周")

        if path != REFERENCES:
            used_sources.update(SOURCE_CODE_RE.findall(checked_text))

        if "## 内容依据与复核" in checked_text:
            if "- 采用来源：" not in checked_text:
                errors.append(f"{relative}: 缺少采用来源")
            review_matches = REVIEW_RE.findall(checked_text)
            if len(review_matches) != 1:
                errors.append(f"{relative}: 最近复核日期数量应为 1")
            else:
                reviewed = parse_date(review_matches[0], str(relative), errors)
                if reviewed:
                    max_age = 90 if DYNAMIC_RE.search(checked_text) else 365
                    age = (today - reviewed).days
                    if age < 0:
                        errors.append(f"{relative}: 最近复核日期晚于检查日期")
                    elif age >= max_age:
                        errors.append(f"{relative}: 已超过 {max_age} 天复核周期")

        for raw_target in LINK_RE.findall(checked_text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = unquote(target.split("#", 1)[0])
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            if not resolved.exists():
                errors.append(f"{relative}: 内部链接不存在 -> {raw_target}")
            elif resolved in incoming:
                incoming[resolved] += 1

    reference_text = REFERENCES.read_text(encoding="utf-8")
    active_sources, stopped_sources = source_sections(reference_text)
    undefined = used_sources - set(active_sources)
    for code in sorted(undefined):
        status = "已停用" if code in stopped_sources else "未定义"
        errors.append(f"来源编号 {code} {status}，但正文仍在引用")
    for code in sorted(set(active_sources) - used_sources):
        errors.append(f"来源编号 {code} 已登记但正文未引用")

    for code, section in active_sources.items():
        if "- 适用范围：" not in section:
            errors.append(f"来源编号 {code}: 缺少适用范围")
        matches = REVIEW_RE.findall(section)
        if len(matches) != 1:
            errors.append(f"来源编号 {code}: 最近复核日期数量应为 1")
            continue
        reviewed = parse_date(matches[0], f"来源编号 {code}", errors)
        if reviewed:
            max_age = 90 if DYNAMIC_RE.search(section) else 365
            age = (today - reviewed).days
            if age < 0:
                errors.append(f"来源编号 {code}: 最近复核日期晚于检查日期")
            elif age >= max_age:
                errors.append(f"来源编号 {code}: 已超过 {max_age} 天复核周期")

    exempt_orphans = {ROOT / "AGENTS.md", ROOT / "README.md"}
    for path, count in incoming.items():
        if count == 0 and path not in {item.resolve() for item in exempt_orphans}:
            errors.append(f"{path.relative_to(ROOT)}: 没有其他 Markdown 页面链接到此页")

    if errors:
        print(f"知识库检查失败，共 {len(errors)} 项：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"知识库检查通过：{len(files)} 个 Markdown 文件，"
        f"{len(active_sources)} 个有效来源编号。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
