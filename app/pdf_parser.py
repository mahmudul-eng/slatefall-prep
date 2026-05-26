import re
import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, Optional

# Map of section number -> title (matches the dossier Table of Contents)
SECTION_TITLES = {
    1: "Identity, Background, and Public Status",
    2: "Powers, Abilities, and Documented Limits",
    3: "Origin and Key Historical Events",
    4: "Equipment, Gear, and Specialized Technology",
    5: "Operational Tactics and Combat Doctrine",
    6: "Allies, Networks, and Known Affiliations",
    7: "Adversaries and Documented Threats",
    8: "Known Bases, Safehouses, and Operational Territory",
    9: "Case Files: Documented Engagements and Incidents",
    10: "Glossary, Codenames, and Reference Tables",
}

# Regex patterns to detect section headings in extracted text
# Matches "Section 1.", "Section 2." etc. at the start of a line
PDF_PATH = Path(__file__).parent.parent / "data" / "SLATEFALL_DOSSIER.pdf"

SECTION_HEADING_RE = re.compile(
    r"^Section\s+(\d+)\.\s+(.+)$", re.IGNORECASE | re.MULTILINE
)


def extract_full_text(pdf_path: str | Path) -> str:
    """Extract all text from the PDF, page by page."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages)


def split_into_sections(full_text: str) -> Dict[int, str]:
    """
    Split the full PDF text into a dict keyed by section number (1-10).
    Each value is the raw text content of that section.
    """
    matches = list(SECTION_HEADING_RE.finditer(full_text))

    if not matches:
        raise ValueError(
            "No section headings found in PDF text. "
            "Check that the PDF is machine-readable."
        )

    sections: Dict[int, str] = {}
    for i, match in enumerate(matches):
        sec_num = int(match.group(1))
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        sections[sec_num] = full_text[start:end].strip()

    return sections


def get_section_text(pdf_path: str | Path, section_id: int) -> str:
    """Return the text of a single section by its number (1-10)."""
    full_text = extract_full_text(pdf_path)
    sections = split_into_sections(full_text)
    if section_id not in sections:
        available = sorted(sections.keys())
        raise ValueError(
            f"Section {section_id} not found. Available sections: {available}"
        )
    return sections[section_id]


def get_sections(pdf_path: str | Path, section_ids: list[int]) -> Dict[int, str]:
    """Return a dict of {section_id: text} for all requested sections."""
    full_text = extract_full_text(pdf_path)
    sections = split_into_sections(full_text)

    result = {}
    for sid in section_ids:
        if sid not in sections:
            available = sorted(sections.keys())
            raise ValueError(
                f"Section {sid} not found. Available: {available}"
            )
        result[sid] = sections[sid]
    return result


def list_sections(pdf_path: str | Path) -> Dict[int, str]:
    """Return all section numbers and titles available in the PDF."""
    full_text = extract_full_text(pdf_path)
    sections = split_into_sections(full_text)
    return {sid: SECTION_TITLES.get(sid, f"Section {sid}") for sid in sorted(sections)}
