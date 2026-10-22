"""Smart intake: turn ONE pasted job posting into the five fields the frozen model was trained on.

    pasted text  ->  parse_posting()  ->  title / company_profile / description / requirements / benefits
                                          ->  create_combined_text (unchanged)  ->  DistilBERT

This is a plain, deterministic, rule-based parser. It does NOT use a language model, an external AI API, or
the DistilBERT model. The same text always gives the same result.

The rules (kept deliberately conservative):

1. A line counts as a section heading only if it is (a) an exact, known heading such as "Requirements",
   "About the Role" or "What You'll Do", and (b) written like a heading: on its own line, optionally followed
   by a colon and text ("Requirements: Python, SQL"), optionally wrapped in markdown (## or **). A heading word
   inside a normal sentence is NOT a heading. A bare heading without a colon must start with a capital letter
   and must not end like a sentence (".", "!", "?"), and bullet lines are never headings.
2. Text under a recognized heading goes to the matching field. Headings that name a field (Requirements,
   Benefits, ...) are removed because the model input adds its own label.
3. Nothing is invented and nothing is thrown away. Text that cannot be placed with confidence is kept in
   DESCRIPTION (see "fallback" below). No text is copied into more than one field.

Fallback (what happens to text that is not in a recognized section):
- Text before the first heading, text under headings like "How to apply" or "Location", the extra lines under a
  "Job Title" heading, and ALL text of a posting that has no headings at all is kept in DESCRIPTION, in the
  original order.
- Sub-headings that are kept for readability stay in the text they belong to: Responsibilities / Duties go to
  DESCRIPTION, and Salary / Compensation / Pay go to BENEFITS, each with their original heading line.
- If the first line of the posting is short and looks like a title, it becomes the title (the usual way a
  posting starts). Otherwise the title stays empty.
"""

import re
from dataclasses import dataclass, field

FIELD_NAMES = ("title", "company_profile", "description", "requirements", "benefits")

# Known headings, written in normalized form (lowercase, letters and single spaces only, apostrophes removed:
# "What You'll Do" -> "what youll do"). Each heading belongs to exactly one kind.
_HEADINGS = {
    "title": ["title", "job title", "position", "position title", "job position"],
    "company_profile": ["about us", "about the company", "about our company", "about company", "company profile",
                        "company overview", "company description", "who we are", "our company"],
    "description": ["job description", "description", "about the role", "about the job", "about the position",
                    "role description", "role overview", "job overview", "position overview", "job summary",
                    "position summary", "summary", "the role"],
    # Kept as sub-headings inside DESCRIPTION
    "responsibilities": ["responsibilities", "key responsibilities", "job responsibilities", "main responsibilities",
                         "your responsibilities", "duties", "key duties", "main duties", "what you will do",
                         "what youll do", "what you will be doing", "what youll be doing"],
    "requirements": ["requirements", "job requirements", "qualifications", "required qualifications",
                     "minimum qualifications", "basic qualifications", "preferred qualifications",
                     "what we are looking for", "what were looking for", "who you are", "what you bring",
                     "what you need", "skills", "required skills", "skills and qualifications"],
    "benefits": ["benefits", "our benefits", "employee benefits", "perks", "perks and benefits",
                 "benefits and perks", "what we offer", "we offer", "what you get", "what youll get",
                 "compensation and benefits", "salary and benefits"],
    # Kept as sub-headings inside BENEFITS
    "compensation": ["salary", "compensation", "pay", "salary range", "pay range"],
    # Real headings that are not one of the five fields: their text is kept in DESCRIPTION with the heading
    "other": ["how to apply", "to apply", "apply now", "application process", "about the team", "location",
              "job location", "job type", "employment type", "work schedule", "schedule", "working hours",
              "equal opportunity employer", "equal opportunity", "contact", "contact us"],
}
HEADING_KINDS = {alias: kind for kind, aliases in _HEADINGS.items() for alias in aliases}

# Where the text of each kind of section goes, and whether the original heading line stays in the text
_TARGET_FIELD = {"company_profile": "company_profile", "description": "description", "responsibilities": "description",
                 "other": "description", "requirements": "requirements", "benefits": "benefits",
                 "compensation": "benefits"}
_KEEP_HEADING = {"responsibilities", "compensation", "other"}

_BULLET = re.compile(r"^(?:[-+•·●▪‣–—*]|\d+[.)])\s+")
_HEADING_CHARACTERS = re.compile(r"[A-Za-z\s'’`&]+")
_MAX_HEADING_WORDS = 7
_MAX_TITLE_CHARS = 100
_MAX_TITLE_WORDS = 14


@dataclass
class IntakeResult:
    """The five extracted fields plus a short report on what was found. Empty means "not found"."""

    title: str = ""
    company_profile: str = ""
    description: str = ""
    requirements: str = ""
    benefits: str = ""
    detected_sections: list = field(default_factory=list)   # fields that contain text
    missing_sections: list = field(default_factory=list)    # fields that are empty
    fallback_used: bool = False                             # some unplaced text was kept in DESCRIPTION

    def to_dict(self):
        return {name: getattr(self, name) for name in FIELD_NAMES} | {
            "detected_sections": list(self.detected_sections),
            "missing_sections": list(self.missing_sections),
            "fallback_used": self.fallback_used,
        }

    def fields(self):
        """Only the five model fields, ready for create_combined_text."""
        return {name: getattr(self, name) for name in FIELD_NAMES}


@dataclass
class _Section:
    kind: str | None                 # None = text before the first heading
    heading_line: str = ""
    inline_text: str = ""            # text after "Heading:" on the same line
    body: list = field(default_factory=list)


def _normalize(text):
    text = text.lower().replace("’", "").replace("'", "").replace("`", "").replace("&", " and ")
    return " ".join(re.sub(r"[^a-z\s]", " ", text).split())


def _match_heading(line):
    """Return (kind, inline_text) if the line is a section heading, else None."""
    stripped = line.strip()
    if not stripped or _BULLET.match(stripped):
        return None
    core = stripped.lstrip("#").strip().lstrip("*_").strip()
    has_colon = ":" in core
    if has_colon:
        head, rest = core.split(":", 1)
        inline_text = rest.strip().lstrip("*_").strip()
    else:
        head, inline_text = core, ""
    head = head.strip().strip("*_#").strip()
    if not head or len(head.split()) > _MAX_HEADING_WORDS or not _HEADING_CHARACTERS.fullmatch(head):
        return None
    kind = HEADING_KINDS.get(_normalize(head))
    if kind is None:
        return None
    if not has_colon:
        # A bare heading must look like one: capital first letter, not ending like a sentence
        first_letter = next((ch for ch in head if ch.isalpha()), "")
        if not first_letter.isupper() or stripped.rstrip("*_ ").endswith((".", "!", "?", ",", ";")):
            return None
    return kind, inline_text


def _split_into_sections(lines):
    sections = [_Section(kind=None)]
    for line in lines:
        match = _match_heading(line)
        if match:
            kind, inline_text = match
            sections.append(_Section(kind=kind, heading_line=line.strip(), inline_text=inline_text))
        else:
            sections[-1].body.append(line)
    return sections


def _tidy(lines):
    """Trim trailing spaces, drop blank lines at both ends and squeeze runs of blank lines into one."""
    cleaned, previous_blank = [], True
    for line in (line.rstrip() for line in lines):
        blank = line.strip() == ""
        if blank and previous_blank:
            continue
        cleaned.append(line)
        previous_blank = blank
    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _looks_like_title(line):
    text = line.strip()
    return (0 < len(text) <= _MAX_TITLE_CHARS and len(text.split()) <= _MAX_TITLE_WORDS
            and not text.endswith((".", "?", ":", ";", ",")) and not _BULLET.match(text))


def _take_unlabeled_title(sections):
    """If the posting starts with a short title-like line, remove it from the text before the first heading
    and return it. Otherwise return ""."""
    first = sections[0]
    non_empty = [i for i, line in enumerate(first.body) if line.strip()]
    if not non_empty:
        return ""
    has_more_text = len(non_empty) > 1 or any(s.heading_line or any(l.strip() for l in s.body) for s in sections[1:])
    index = non_empty[0]
    if has_more_text and _looks_like_title(first.body[index]):
        title = first.body[index].strip().lstrip("#").strip().strip("*_").strip()   # drop markdown decoration
        del first.body[index]
        return title
    return ""


def parse_posting(raw_posting):
    """Split one pasted job posting into the five model fields. Pure function: same input, same output."""
    lines = (raw_posting or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = _split_into_sections(lines)

    title = ""
    if not any(s.kind == "title" for s in sections):
        title = _take_unlabeled_title(sections)

    chunks = {name: [] for name in FIELD_NAMES}
    fallback_used = False

    for section in sections:
        if section.kind is None:                       # text before the first heading (fallback)
            text = _tidy(section.body)
            if text:
                chunks["description"].append(text)
                fallback_used = True
            continue

        if section.kind == "title" and not title:      # first explicit title: first line is the title
            own_lines = ([section.inline_text] if section.inline_text else []) + section.body
            non_empty = [i for i, line in enumerate(own_lines) if line.strip()]
            if non_empty:
                title = own_lines[non_empty[0]].strip()
                leftover = _tidy(own_lines[non_empty[0] + 1:])
                if leftover:                           # extra lines under a "Job Title" heading (fallback)
                    chunks["description"].append(leftover)
                    fallback_used = True
            continue

        kind = "other" if section.kind == "title" else section.kind   # a second title heading is kept as text
        if kind in _KEEP_HEADING:
            text = _tidy([section.heading_line] + section.body)
            has_content = bool(section.inline_text or any(line.strip() for line in section.body))
            if not has_content:
                continue                               # a heading with nothing under it carries no information
            if kind == "other":
                fallback_used = True
        else:
            text = _tidy(([section.inline_text] if section.inline_text else []) + section.body)
        if text:
            chunks[_TARGET_FIELD[kind]].append(text)

    values = {name: "\n\n".join(chunks[name]) for name in FIELD_NAMES}
    values["title"] = title
    return IntakeResult(
        **values,
        detected_sections=[name for name in FIELD_NAMES if values[name]],
        missing_sections=[name for name in FIELD_NAMES if not values[name]],
        fallback_used=fallback_used,
    )
