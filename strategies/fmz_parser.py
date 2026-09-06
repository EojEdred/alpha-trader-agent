"""
FMZ Quant strategy markdown parser.

Parses the fmzquant/strategies submodule markdown files and extracts:
- Name, Author, Description, Strategy Arguments, Source language/code
- Detail URL, Last Modified
- Normalized slug and Python identifier

Usage:
    from strategies.fmz_parser import FMZParser
    parser = FMZParser()
    catalog = parser.build_catalog()
    parser.save_catalog(catalog)
"""

import json
import re
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
try:
    from loguru import logger
except ImportError:
    import logging as logger


DEFAULT_FMZ_DIR = Path(__file__).parent / "fmzquant"
DEFAULT_CATALOG_PATH = Path(__file__).parent / "fmz_catalog.json"


@dataclass
class FMZStrategy:
    """Parsed FMZ strategy metadata."""

    slug: str
    name: str
    author: str
    description: str
    arguments: List[Dict[str, Any]]
    source_language: Optional[str]
    source_code: Optional[str]
    detail_url: Optional[str]
    last_modified: Optional[str]
    file_path: str
    file_size: int
    python_identifier: str
    source_hash: Optional[str]
    parse_status: str  # "ok", "no_source", "pinescript_only", "unparseable"
    parse_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FMZParser:
    """Parse FMZ Quant strategy markdown files."""

    def __init__(self, fmz_dir: Optional[Path] = None):
        self.fmz_dir = Path(fmz_dir) if fmz_dir else DEFAULT_FMZ_DIR

    def _to_identifier(self, text: str, slug: str, existing: Optional[set] = None) -> str:
        """Convert a strategy name to a unique valid Python class/identifier."""
        # Keep only ASCII alphanumeric; collapse everything else to underscore.
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text)
        cleaned = cleaned.strip("_")
        if not cleaned:
            cleaned = "strategy"
        if len(cleaned) > 80:
            cleaned = cleaned[:80].rsplit("_", 1)[0] or cleaned[:80]
        base = "fmz_" + cleaned.lower()
        base = re.sub(r"_+", "_", base).strip("_")
        identifier = base
        counter = 1
        existing = existing or set()
        while identifier in existing:
            suffix = hashlib.md5((slug + str(counter)).encode()).hexdigest()[:4]
            identifier = f"{base}_{suffix}"
            counter += 1
        return identifier

    def _to_slug(self, filename: str) -> str:
        """Convert markdown filename to a URL-friendly slug."""
        name = Path(filename).stem
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", name)
        slug = slug.strip("-").lower()
        if not slug:
            slug = "strategy"
        if len(slug) > 120:
            slug = slug[:120].rsplit("-", 1)[0] or slug[:120]
        return slug

    def _detect_description(self, text: str) -> str:
        """Extract description text after the > Description marker."""
        # FMZ docs use a description block followed by other > markers.
        # Match content between `> Strategy Description` and the next `>` marker at line start.
        match = re.search(
            r">\s*Strategy\s*Description\s*\n+(.+?)(?=\n>\s*[A-Za-z]|\n>\s*Source|\n```|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            desc = match.group(1).strip()
            # Collapse whitespace but keep paragraph breaks light.
            desc = re.sub(r"\n\s*\n+", "\n\n", desc)
            desc = re.sub(r"[ \t]+", " ", desc)
            # Truncate very long descriptions.
            if len(desc) > 2000:
                desc = desc[:1997] + "..."
            return desc
        return ""

    def _detect_arguments(self, text: str) -> List[Dict[str, Any]]:
        """Parse the Strategy Arguments markdown table."""
        args = []
        # Look for a table after the > Strategy Arguments marker.
        match = re.search(
            r">\s*Strategy\s*Arguments\s*\n+\s*\|(.+?)\|\s*\n\s*\|[-:\s|]+\|\s*\n((?:\s*\|.+?\|\s*\n)+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return args

        header_line = match.group(1)
        rows_text = match.group(2)
        headers = [h.strip().lower() for h in header_line.split("|") if h.strip()]
        if not headers:
            return args

        for row in rows_text.strip().split("\n"):
            row = row.strip()
            if not row.startswith("|"):
                continue
            cells = [c.strip() for c in row.split("|")]
            # Remove leading/trailing empty cells produced by the outer pipes.
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            arg = {}
            for idx, header in enumerate(headers):
                value = cells[idx] if idx < len(cells) else ""
                if header == "default":
                    arg["default"] = self._coerce_default(value)
                else:
                    arg[header] = value
            if "argument" in arg and arg["argument"]:
                args.append(arg)
        return args

    def _coerce_default(self, value: str) -> Any:
        """Try to coerce a default argument string to bool/int/float/str."""
        value = value.strip()
        if value.lower() in ("true", "yes", "on"):
            return True
        if value.lower() in ("false", "no", "off"):
            return False
        if value == "":
            return ""
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _detect_source(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Detect source language and extract code block content."""
        # Match `> Source (language)` followed by a fenced code block.
        match = re.search(
            r">\s*Source\s*\(?\s*(\w+)\s*\)?\s*\n+```\s*\w*\n(.*?)```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            lang = match.group(1).strip().lower()
            code = match.group(2).strip()
            return lang, code
        return None, None

    def _detect_detail_url(self, text: str) -> Optional[str]:
        match = re.search(r">\s*Detail\s*\n+\s*(https?://\S+)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _detect_last_modified(self, text: str) -> Optional[str]:
        match = re.search(
            r">\s*Last\s*Modified\s*\n+\s*(\d{4}-\d{2}-\d{2}[\s\d:\-]*)",
            text,
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    def _detect_name(self, text: str) -> Optional[str]:
        match = re.search(r">\s*Name\s*\n+\s*(.+?)(?=\n\s*>|\Z)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _detect_author(self, text: str) -> Optional[str]:
        match = re.search(r">\s*Author\s*\n+\s*(.+?)(?=\n\s*>|\Z)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def parse_file(self, path: Path, existing_identifiers: Optional[set] = None) -> FMZStrategy:
        """Parse a single FMZ markdown file."""
        slug = self._to_slug(path.name)
        existing = existing_identifiers or set()
        identifier = self._to_identifier(self._to_slug(path.name), slug, existing)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return FMZStrategy(
                slug=slug,
                name=path.stem,
                author="",
                description="",
                arguments=[],
                source_language=None,
                source_code=None,
                detail_url=None,
                last_modified=None,
                file_path=str(path),
                file_size=path.stat().st_size if path.exists() else 0,
                python_identifier=identifier,
                source_hash=None,
                parse_status="unparseable",
                parse_error=str(e),
            )

        name = self._detect_name(text) or path.stem
        identifier = self._to_identifier(name, slug, existing)
        author = self._detect_author(text) or ""
        description = self._detect_description(text) or ""
        arguments = self._detect_arguments(text)
        detail_url = self._detect_detail_url(text)
        last_modified = self._detect_last_modified(text)
        lang, code = self._detect_source(text)

        if lang is None:
            parse_status = "no_source"
        elif lang in ("pinescript", "pine script", "pine"):
            parse_status = "pinescript_only"
        elif lang not in ("javascript", "python"):
            parse_status = "unsupported_language"
        else:
            parse_status = "ok"

        source_hash = hashlib.sha256((code or "").encode()).hexdigest()[:16] if code else None

        return FMZStrategy(
            slug=slug,
            name=name,
            author=author,
            description=description,
            arguments=arguments,
            source_language=lang,
            source_code=code,
            detail_url=detail_url,
            last_modified=last_modified,
            file_path=str(path),
            file_size=len(text.encode("utf-8")),
            python_identifier=identifier,
            source_hash=source_hash,
            parse_status=parse_status,
        )

    def build_catalog(self) -> List[FMZStrategy]:
        """Parse all markdown files in the fmzquant submodule."""
        if not self.fmz_dir.exists():
            raise FileNotFoundError(f"FMZ strategies directory not found: {self.fmz_dir}")

        md_files = sorted(self.fmz_dir.glob("*.md"))
        logger.info(f"Found {len(md_files)} markdown files in {self.fmz_dir}")

        catalog = []
        existing_identifiers: set = set()
        for idx, path in enumerate(md_files):
            if idx % 500 == 0 and idx > 0:
                logger.info(f"Parsed {idx}/{len(md_files)} FMZ strategies...")
            try:
                entry = self.parse_file(path, existing_identifiers)
                existing_identifiers.add(entry.python_identifier)
                catalog.append(entry)
            except Exception as e:
                logger.error(f"Failed to parse {path}: {e}")
                slug = self._to_slug(path.name)
                identifier = self._to_identifier(path.stem, slug, existing_identifiers)
                existing_identifiers.add(identifier)
                catalog.append(
                    FMZStrategy(
                        slug=slug,
                        name=path.stem,
                        author="",
                        description="",
                        arguments=[],
                        source_language=None,
                        source_code=None,
                        detail_url=None,
                        last_modified=None,
                        file_path=str(path),
                        file_size=path.stat().st_size if path.exists() else 0,
                        python_identifier=identifier,
                        source_hash=None,
                        parse_status="unparseable",
                        parse_error=str(e),
                    )
                )
        return catalog

    def save_catalog(
        self,
        catalog: List[FMZStrategy],
        path: Optional[Path] = None,
    ) -> Path:
        """Save catalog to JSON."""
        path = Path(path) if path else DEFAULT_CATALOG_PATH
        data = [item.to_dict() for item in catalog]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Saved FMZ catalog with {len(catalog)} entries to {path}")
        return path

    def load_catalog(self, path: Optional[Path] = None) -> List[FMZStrategy]:
        """Load catalog from JSON."""
        path = Path(path) if path else DEFAULT_CATALOG_PATH
        data = json.loads(path.read_text(encoding="utf-8"))
        return [FMZStrategy(**item) for item in data]


def main():
    parser = FMZParser()
    catalog = parser.build_catalog()
    parser.save_catalog(catalog)

    status_counts: Dict[str, int] = {}
    for item in catalog:
        status_counts[item.parse_status] = status_counts.get(item.parse_status, 0) + 1
    logger.info(f"Parse status summary: {status_counts}")


if __name__ == "__main__":
    main()
