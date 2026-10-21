"""极简 Markdown → HTML 渲染（辨证报告用）。

零依赖、离线可用（局域网约束下不能 vendor 失败就裸奔）。
支持：#/##/### 标题、**粗体**、- 无序列表、1. 有序列表、| 表格 |、
`行内代码`、段落。先整体 HTML 转义，渲染器产出的标签是白名单内的。
"""
from __future__ import annotations

import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    return text


def render(md: str) -> str:
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        # 表格：连续 | 开头行，第二行是分隔行
        if line.lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in block]
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            if rows:
                head, body = rows[0], rows[1:]
                out.append("<table><thead><tr>"
                           + "".join(f"<th>{_inline(html.escape(c))}</th>" for c in head)
                           + "</tr></thead><tbody>"
                           + "".join("<tr>" + "".join(
                               f"<td>{_inline(html.escape(c))}</td>" for c in r)
                               + "</tr>" for r in body)
                           + "</tbody></table>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = min(len(m.group(1)) + 2, 6)  # # → h3 … #### → h6（页内层级）
            out.append(f"<h{level}>{_inline(html.escape(m.group(2)))}</h{level}>")
            i += 1
            continue
        if re.match(r"^\s*(---+|\*\*\*+)\s*$", line):
            out.append('<hr style="border:none; border-top:1px solid var(--line); margin:14px 0;">')
            i += 1
            continue
        if line.lstrip().startswith(">"):
            # 引用块：连续 > 行合并
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(re.sub(r"^\s*>\s?", "", lines[i].rstrip()))
                i += 1
            inner = " ".join(b for b in block if b)
            out.append(f'<blockquote style="margin:10px 0; padding:8px 14px; '
                       f'border-left:4px solid var(--cinnabar); '
                       f'background:var(--card-sunken); border-radius:8px;">'
                       f'{_inline(html.escape(inner))}</blockquote>')
            continue
        if re.match(r"^[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].rstrip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].rstrip()))
                i += 1
            out.append("<ul>" + "".join(
                f"<li>{_inline(html.escape(t))}</li>" for t in items) + "</ul>")
            continue
        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].rstrip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].rstrip()))
                i += 1
            out.append("<ol>" + "".join(
                f"<li>{_inline(html.escape(t))}</li>" for t in items) + "</ol>")
            continue
        out.append(f"<p>{_inline(html.escape(line))}</p>")
        i += 1
    return "\n".join(out)
