"""Markdown note parser for VaultMCP.

Extracts front matter, headings with line ranges, tags, and links.
Fault-tolerant: invalid front matter records an error but preserves note indexing.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import hashlib
import yaml
from typing import Any

TAG_INLINE_REGEX = re.compile(r"(?:^|[^\w#])#([a-zA-Z0-9_\-\/]+)(?=[^\w#]|$)")
WIKILINK_REGEX = re.compile(r"\[\[([^\|\]\n]+)(?:\|[^\]\n]+)?\]\]")
MDLINK_REGEX = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+\.md(?:#[^)\n]*)?)\)")
HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class ParsedSection:
    ordinal: int
    heading: str
    level: int
    line_start: int
    line_end: int
    body: str


@dataclass
class ParsedLink:
    target_text: str
    kind: str  # 'wiki' or 'markdown'
    line: int
    context: str


@dataclass
class ParsedTag:
    name: str
    source: str  # 'front_matter' or 'inline'


@dataclass
class ParsedNote:
    path: str
    title: str
    folder: str
    front_matter: dict[str, Any]
    size_bytes: int
    content_hash: str
    modified_at: str
    parse_error: str | None
    sections: list[ParsedSection] = field(default_factory=list)
    tags: list[ParsedTag] = field(default_factory=list)
    links: list[ParsedLink] = field(default_factory=list)


def parse_markdown(
    rel_path: str,
    content: str,
    modified_at: str,
    size_bytes: int | None = None,
) -> ParsedNote:
    """Parses a markdown string into a ParsedNote structure."""
    if size_bytes is None:
        size_bytes = len(content.encode("utf-8"))

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    folder = ""
    if "/" in rel_path:
        folder = rel_path.rsplit("/", 1)[0]

    lines = content.splitlines(keepends=False)
    total_lines = len(lines)

    # 1. Front Matter extraction
    front_matter: dict[str, Any] = {}
    parse_error: str | None = None
    body_start_line = 1

    if lines and lines[0].strip() == "---":
        closing_idx = -1
        for i in range(1, total_lines):
            if lines[i].strip() == "---":
                closing_idx = i
                break

        if closing_idx != -1:
            fm_text = "\n".join(lines[1:closing_idx])
            try:
                loaded = yaml.safe_load(fm_text)
                if isinstance(loaded, dict):
                    front_matter = loaded
                elif loaded is not None:
                    parse_error = "Front matter YAML is not a dictionary"
            except Exception as e:
                parse_error = f"YAML parse error: {str(e)}"
            body_start_line = closing_idx + 2
        else:
            parse_error = "Unclosed front matter delimiter '---'"

    # 2. Title extraction
    title = ""
    if isinstance(front_matter.get("title"), str) and front_matter["title"].strip():
        title = front_matter["title"].strip()

    # 3. Tags extraction
    tag_set: dict[str, str] = {}  # name -> source

    # From front matter
    fm_tags = front_matter.get("tags") or front_matter.get("tag")
    if isinstance(fm_tags, list):
        for t in fm_tags:
            if isinstance(t, str):
                cleaned = t.lstrip("#").strip().lower()
                if cleaned:
                    tag_set[cleaned] = "front_matter"
    elif isinstance(fm_tags, str):
        cleaned = fm_tags.lstrip("#").strip().lower()
        if cleaned:
            tag_set[cleaned] = "front_matter"

    # 4. Sections & Line scan
    sections: list[ParsedSection] = []
    links: list[ParsedLink] = []

    current_ordinal = 0
    current_heading = ""
    current_level = 0
    current_start = 1
    current_body_lines: list[str] = []

    first_h1_text = ""

    for line_idx, line in enumerate(lines, start=1):
        if line_idx < body_start_line:
            continue

        # Extract inline tags (only in body lines, not in front matter)
        for match in TAG_INLINE_REGEX.finditer(line):
            tag_name = match.group(1).lower()
            # Exclude purely numeric hex-like sequences or common false positives
            if not re.match(r"^[0-9a-fA-F]{3,6}$", tag_name):
                if tag_name not in tag_set:
                    tag_set[tag_name] = "inline"

        # Extract wiki links
        for match in WIKILINK_REGEX.finditer(line):
            target = match.group(1).strip()
            links.append(ParsedLink(target_text=target, kind="wiki", line=line_idx, context=line.strip()))

        # Extract markdown links (internal .md)
        for match in MDLINK_REGEX.finditer(line):
            target = match.group(2).strip()
            links.append(ParsedLink(target_text=target, kind="markdown", line=line_idx, context=line.strip()))

        # Heading detection
        h_match = HEADING_REGEX.match(line)
        if h_match:
            level = len(h_match.group(1))
            heading_text = h_match.group(2).strip()

            if level == 1 and not first_h1_text:
                first_h1_text = heading_text

            # Finalize previous section if it has non-whitespace content
            body_str = "\n".join(current_body_lines).strip()
            if body_str:
                end_line = max(current_start, line_idx - 1)
                sections.append(
                    ParsedSection(
                        ordinal=current_ordinal,
                        heading=current_heading,
                        level=current_level,
                        line_start=current_start,
                        line_end=end_line,
                        body=body_str,
                    )
                )
                current_ordinal += 1

            current_heading = heading_text
            current_level = level
            current_start = line_idx
            current_body_lines = [line]
        else:
            if not current_body_lines and not line.strip():
                # Don't start intro section with empty blank lines
                current_start = line_idx + 1
            else:
                current_body_lines.append(line)

    # Finalize remaining section
    body_str = "\n".join(current_body_lines).strip()
    if body_str:
        end_line = max(current_start, total_lines)
        sections.append(
            ParsedSection(
                ordinal=current_ordinal,
                heading=current_heading,
                level=current_level,
                line_start=current_start,
                line_end=end_line,
                body=body_str,
            )
        )

    # Determine fallback title if not in front matter
    if not title:
        if first_h1_text:
            title = first_h1_text
        else:
            # File name without extension
            stem = Path(rel_path).stem
            title = stem

    tags_list = [ParsedTag(name=name, source=src) for name, src in tag_set.items()]

    return ParsedNote(
        path=rel_path,
        title=title,
        folder=folder,
        front_matter=front_matter,
        size_bytes=size_bytes,
        content_hash=content_hash,
        modified_at=modified_at,
        parse_error=parse_error,
        sections=sections,
        tags=tags_list,
        links=links,
    )
