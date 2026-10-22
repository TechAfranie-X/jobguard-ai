"""Job Scam Signal Scanner: transparent, rule-based warning signs found in a pasted job posting.

This module answers one question: "What in this text should I look at more carefully?"
It does NOT answer "Why did DistilBERT give this score?". The two systems are independent:

  * DistilBERT (backend/model_service.py) produces the machine-learning fraud-risk score.
  * This scanner looks for concrete phrases that match patterns described in consumer-protection guidance
    (for example the U.S. FTC's public job-scam advice) and shows the exact words it found.

Design rules (they are tested in backend/test_scam_signals.py):
  * Deterministic: plain regular expressions and small helper functions. No AI service, no network, no model.
  * Evidence is always cut out of the user's own text. A signal is only reported together with a real excerpt;
    nothing is paraphrased and presented as a quote.
  * Context matters: negated phrases ("No application fee is required") are not reported, and ambiguous words
    (PayPal, laptop, remote) are only reported when the surrounding words connect them to the applicant.
  * No score. The scanner reports how many warning signs it found, never a "scam percentage" or risk level.
  * A signal is a reason to verify, not proof that a posting is fake.

Public function:   scan_job_signals(raw_text, extracted_fields=None)
"""

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------------------------

MAX_EVIDENCE_CHARS = 180        # one excerpt is never longer than this
MAX_EVIDENCE_PER_SIGNAL = 3     # the main excerpt plus at most two more

SEVERITIES = ("high", "medium", "notice")          # the only allowed severity words
_SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}

# Free / consumer e-mail providers. Seeing one is a reason to verify the sender, not proof of anything.
FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "protonmail.com", "proton.me", "aol.com", "mail.com", "gmx.com", "yandex.com",
})


def _re(pattern):
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------------------
# Reading the text: sentences, excerpts and negation
# ---------------------------------------------------------------------------------------------------------------

# A sentence ends at . ! ? followed by white space (so "$5.50" and e-mail addresses are not split), or at a new line.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|\Z)|\n")
_LEADING_JUNK = set(" \t\r\f\v-*\u2022\u00b7\u25aa\u25cf\u25a0>#")

# Words that break a clause, so a "no" in an earlier clause does not cancel a phrase in a later one.
_CLAUSE_BREAK = _re(r"[.!?;:\n]|\b(?:but|however|although|though|except|whereas|yet)\b")
_AFTER_CUT = re.compile(r"[.!?;\n]")

_NEGATION = r"\b(?:no|not|never|without|nor|neither|zero|cannot|nothing)\b|n['\u2019]t\b|\bfree\s+(?:of|from)\b"
_NEGATION_BASIC = _re(_NEGATION)
# For fees and costs, "we cover / reimburse / provide ..." also means the applicant is not the one paying.
_NEGATION_COST = _re(
    _NEGATION
    + r"|\b(?:cover|covers|covered|covering|reimburse|reimburses|reimbursed|waive|waives|waived|provide|provides|"
      r"provided|refund|refunds|refunded|absorb|absorbs)\b|\b(?:we|company|employer)\s+(?:will\s+)?pays?\b"
)
# What may directly follow a phrase and cancel it: "fee is not required", "fee waived", "fee: none".
_AFTER_NEGATION = _re(
    r"^\W*(?:(?:is|are|was|were|will\s+be|be|being|shall\s+be)\s+){0,2}"
    r"(?:not|never|waived|free|refunded|covered|provided|reimbursed|included|absorbed|none|zero|n/a)\b"
    r"|^\W*(?:is|are|was|were)n['\u2019]t\b|^\W*\$\s?0(?:\.00)?\b"
)


class _Text:
    """The user's text plus helpers that always return positions inside that exact text."""

    def __init__(self, raw):
        self.raw = raw
        self._boundaries = [(m.start(), m.end()) for m in _SENTENCE_END.finditer(raw)]
        self._ends = [end for _, end in self._boundaries]

    def sentence_span(self, position):
        """(start, end) of the sentence that contains `position`."""
        index = bisect_right(self._ends, position)
        start = self._ends[index - 1] if index else 0
        if index < len(self._boundaries):
            boundary_start, boundary_end = self._boundaries[index]
            end = boundary_start if self.raw[boundary_start] == "\n" else boundary_end
        else:
            end = len(self.raw)
        return start, end

    def excerpt(self, start, end):
        """A short, readable piece of the ORIGINAL text around [start, end): the sentence, trimmed if very long."""
        raw = self.raw
        sentence_start, _ = self.sentence_span(start)
        _, sentence_end = self.sentence_span(max(start, end - 1))
        s, e = sentence_start, sentence_end
        while s < e and raw[s] in _LEADING_JUNK:
            s += 1
        while e > s and raw[e - 1].isspace():
            e -= 1
        if e - s > MAX_EVIDENCE_CHARS:
            matched = end - start
            if matched >= MAX_EVIDENCE_CHARS:
                window_start, window_end = start, start + MAX_EVIDENCE_CHARS
            else:
                window_start = max(s, start - (MAX_EVIDENCE_CHARS - matched) // 2)
                window_end = min(e, window_start + MAX_EVIDENCE_CHARS)
                window_start = max(s, window_end - MAX_EVIDENCE_CHARS)
            # Move the edges to word boundaries without cutting into the matched words.
            if window_start > s:
                while window_start < start and not raw[window_start - 1].isspace():
                    window_start += 1
            if window_end < e:
                while window_end > end and not raw[window_end].isspace():
                    window_end -= 1
            s, e = window_start, window_end
            while e > s and raw[e - 1].isspace():
                e -= 1
        return raw[s:e]

    def negated(self, start, end, cost=False):
        """True when the phrase at [start, end) is denied or covered by nearby words ("No application fee")."""
        before = self.raw[max(0, start - 70):start]
        clause_start = 0
        for boundary in _CLAUSE_BREAK.finditer(before):
            clause_start = boundary.end()
        if (_NEGATION_COST if cost else _NEGATION_BASIC).search(before[clause_start:]):
            return True
        after = self.raw[end:end + 45]
        cut = _AFTER_CUT.search(after)
        if cut:
            after = after[:cut.start()]
        return bool(_AFTER_NEGATION.search(after))


@dataclass
class _Hit:
    """What a rule found: spans in the original text (the first one is the main evidence) and optional details."""

    spans: list
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    category: str
    severity: str
    explanation: str
    recommended_action: str
    find: Callable[[_Text], "_Hit | None"]


def _spans_of(text, patterns, negation=None):
    """Every match of the patterns that is not negated, in text order, as (start, end) spans."""
    found = {}
    for pattern in patterns:
        for match in pattern.finditer(text.raw):
            if negation and text.negated(match.start(), match.end(), cost=(negation == "cost")):
                continue
            found.setdefault(match.start(), (match.start(), match.end()))
    return [found[key] for key in sorted(found)]


def _phrase_finder(patterns, negation="basic"):
    """A rule that fires when any of the phrases appears and is not negated."""
    def find(text):
        spans = _spans_of(text, patterns, negation)
        return _Hit(spans) if spans else None
    return find


# ---------------------------------------------------------------------------------------------------------------
# Rule 1: upfront payments (money to get or start a job)
# ---------------------------------------------------------------------------------------------------------------

_FEE_NOUN = _re(
    r"\b(?:registration|application|processing|training|certification|equipment|activation|enrol?lment|onboarding|"
    r"administrative|admin)\s+(?:fees?|charges?|costs?)\b"
)
_STARTER_KIT = _re(
    r"\b(?:buy|purchase|pay\s+for)\s+(?:a\s+|an\s+|the\s+|your\s+|our\s+)?(?:own\s+)?"
    r"(?:starter[\s-]?(?:kit|pack(?:age)?)|training\s+(?:materials?|kit|package|course|program))\b"
)
_PAY_A_FEE = _re(
    r"\b(?:pay|paying|send|sending|wire|wiring|submit|submitting|deposit|depositing)\s+(?:us\s+|the\s+company\s+)?"
    r"(?:a\s+|an\s+|the\s+|your\s+|any\s+|this\s+|that\s+)?(?:\$\s?\d[\d,]*(?:\.\d{2})?\s+)?"
    r"(?:(?:small|one[\s-]time|nominal|refundable|initial|upfront|up[\s-]front|modest|minimal|required|mandatory|"
    r"security|processing|registration|onboarding)\s+)*(?:fees?|deposits?)\b"
)
_APPLICANT_MUST_PAY = _re(
    r"\b(?:you|applicants?|candidates?|new\s+hires?|recruits?)\s+(?:will\s+)?"
    r"(?:must|need\s+to|needs\s+to|have\s+to|has\s+to|are\s+required\s+to|is\s+required\s+to|will\s+need\s+to|"
    r"will\s+be\s+required\s+to|should)\s+(?:first\s+|then\s+)?"
    r"(?:pay|make|send|submit)\s+(?:us\s+)?(?:a\s+|an\s+|the\s+|your\s+|any\s+)?"
    r"(?:\$\s?\d[\d,]*(?:\.\d{2})?\s+)?(?:\w+\s+){0,2}?(?:fees?|payments?|deposits?)\b"
)
_PAY_BEFORE_STARTING = _re(
    r"\b(?:pay|payment|fee|fees|deposit)\b[^.!?\n]{0,40}\b(?:before|prior\s+to)\s+(?:you\s+)?"
    r"(?:start(?:ing)?|begin(?:ning)?|begins?|being\s+hired|working|hiring|onboarding|training|"
    r"(?:the\s+)?first\s+day|your\s+first)\b"
)

_find_upfront_payment = _phrase_finder(
    [_FEE_NOUN, _STARTER_KIT, _PAY_A_FEE, _APPLICANT_MUST_PAY, _PAY_BEFORE_STARTING], negation="cost"
)


# ---------------------------------------------------------------------------------------------------------------
# Rule 2: fake-check and equipment scams
# ---------------------------------------------------------------------------------------------------------------

_CHECK_NOUN = _re(
    r"\b(?:a|the|your|this|that|our|first|initial)\s+"
    r"(?:(?:cashier['\u2019]s|certified|company|business|personal|initial|advance|signing|large|partial|mobile)\s+)?"
    r"(?:check|cheque)s?\b"
)
_DEPOSIT_IT = _re(
    r"\b(?:deposit(?:ing|ed)?|cash(?:ing|ed)?)\s+(?:it|them|the\s+(?:\w+\s+)?(?:check|cheque|funds|money|amount)|"
    r"this\s+(?:check|cheque)|that\s+(?:check|cheque)|your\s+(?:check|cheque))\b"
)
_BUY_EQUIPMENT = _re(
    r"\b(?:purchas(?:e|ing)|buy(?:ing)?|order(?:ing)?|pay\s+for)\s+(?:the\s+|your\s+|any\s+|all\s+)?"
    r"(?:(?:necessary|required|needed|own|office|work)\s+)*"
    r"(?:equipment|laptops?|computers?|supplies|software|materials|gift\s+cards?|phones?|printers?|devices?|tools?|kit)\b"
)
_SEND_BALANCE = _re(
    r"\b(?:send|wire|transfer|forward|remit|return|pay)\b[^.!?\n]{0,50}?\b"
    r"(?:remaining|remainder|balance|rest|excess|difference|extra|leftover|surplus)\b"
)
_CHECK_WINDOW = 300     # the check and what the applicant must do with it have to be this close together


def _find_fake_check(text):
    for check in _CHECK_NOUN.finditer(text.raw):
        if text.negated(check.start(), check.end()):
            continue
        window_start = max(0, check.start() - _CHECK_WINDOW)
        window_end = min(len(text.raw), check.end() + _CHECK_WINDOW)
        actions = []
        for pattern in (_DEPOSIT_IT, _BUY_EQUIPMENT, _SEND_BALANCE):
            for action in pattern.finditer(text.raw, window_start, window_end):
                if not text.negated(action.start(), action.end()):
                    actions.append((action.start(), action.end()))
                    break
        if actions:
            return _Hit([(check.start(), check.end())] + sorted(actions))
    return None


_BUY_THEN_REIMBURSE = _re(
    r"\b(?:buy|purchase|order|pay\s+for)\s+(?:your|the|all|any)\s+(?:own\s+)?(?:\w+\s+){0,2}"
    r"(?:equipment|laptops?|computers?|supplies|software|materials|phones?|devices?|tools?)\b"
    r"[^.!?\n]{0,80}?\b(?:reimburs\w+|refund\w*|repay\w*|pay\s+you\s+back)\b"
)
_REIMBURSE_AFTER_BUYING = _re(
    r"\b(?:reimburs\w+|refund\w*|repay\w*|pay\s+you\s+back)\b[^.!?\n]{0,60}?"
    r"\b(?:after|once|when)\s+you\s+(?:buy|purchase|order|pay\s+for)\b"
)
_find_purchase_reimbursement = _phrase_finder([_BUY_THEN_REIMBURSE, _REIMBURSE_AFTER_BUYING], negation="basic")


# ---------------------------------------------------------------------------------------------------------------
# Rule 3: sensitive information requested
# ---------------------------------------------------------------------------------------------------------------

# (pattern, clear_on_its_own). Items that are common in ordinary job text ("bank account", "credit card",
# "passport") are only reported when the words around them show it is the applicant's own information.
_SENSITIVE_ITEMS = [
    (_re(r"\bsocial\s+security(?:\s+(?:number|no\.?|#|card))?"), True),
    (_re(r"\bssn\b"), True),
    (_re(r"\brouting\s+numbers?\b"), True),
    (_re(r"\bcvv\b"), True),
    (_re(r"\bbank\s+account(?:\s+(?:details?|information|info|numbers?|login|credentials|statements?))?"), False),
    (_re(r"\b(?:debit|credit)\s+card(?:\s+(?:details?|information|info|numbers?|credentials))?"), False),
    (_re(r"\bcard\s+(?:number|details|information)\b"), False),
    (_re(r"\bonline\s+banking\s+(?:login|details|credentials|password)\b"), False),
    (_re(r"\bdriver['\u2019]?s?\s+licen[cs]e(?:\s+(?:number|copy|photo|scan))?"), False),
    (_re(r"\bpassport(?:\s+(?:number|copy|photo|scan|details))?(?![\s-]*(?:size|sized))"), False),
    (_re(r"\b(?:government|national|state)[\s-]+(?:issued\s+)?(?:photo\s+)?(?:id|identification)"
         r"(?:\s+(?:card|documents?|number|copy))?"), False),
    (_re(r"\bidentity\s+(?:documents?|proof|card)\b"), False),
    (_re(r"\bid\s+(?:card|documents?|copy|scan|photo)\b"), False),
]
# Words that show the applicant is being asked to hand something over (not merely that the job needs it).
_ASKS_TO_HAND_OVER = _re(
    r"\b(?:send|provide|submit|share|email|e-mail|text|upload|give|supply|enter|fill\s+in|reply\s+with|attach|"
    r"forward|disclose|scan)\b"
    r"|\b(?:need|needs|require|requires|requesting|requests?|collect|collecting|ask(?:s|ing)?\s+for|asked\s+for)"
    r"\s+(?:your|a\s+copy)\b"
)
_OWN_INFORMATION_CUE = _re(r"\byour\b|\b(?:copy|copies|photos?|pictures?|scans?|images?)\s+of\b")
_DETAIL_WORD = _re(r"\b(?:details?|information|info|numbers?|login|credentials|statements?|copy|photo|scan)\b")
# Normal later steps of a real hiring process ("after you are hired", "on your first day", I-9).
_NORMAL_LATER_STEP = _re(
    r"\b(?:after|once|upon|following|when)\s+(?:you(?:['\u2019]re|\s+are|\s+have\s+been|\s+were)?\s+)?"
    r"(?:hired|offered|accept\w*|onboard\w*|selected|joining)\b"
    r"|\b(?:after|once|upon|following)\s+(?:an?\s+|the\s+|your\s+)?(?:job\s+)?offer\b"
    r"|\b(?:on\s+your\s+first\s+day|first\s+day\s+of\s+(?:work|employment)|on\s+day\s+one|during\s+onboarding|"
    r"at\s+onboarding|upon\s+hire|if\s+hired|if\s+selected|if\s+offered|e-?verify|i-?9)\b"
)


def _find_sensitive_info(text):
    spans = []
    for pattern, clear_on_its_own in _SENSITIVE_ITEMS:
        for match in pattern.finditer(text.raw):
            if text.negated(match.start(), match.end()):
                continue
            sentence_start, sentence_end = text.sentence_span(match.start())
            sentence = text.raw[sentence_start:sentence_end]
            if not _ASKS_TO_HAND_OVER.search(sentence) or _NORMAL_LATER_STEP.search(sentence):
                continue
            if not clear_on_its_own:
                own = _OWN_INFORMATION_CUE.search(text.raw, sentence_start, match.start())
                if not (own or _DETAIL_WORD.search(match.group(0))):
                    continue
            spans.append((match.start(), match.end()))
    spans.sort()
    return _Hit(spans) if spans else None


# ---------------------------------------------------------------------------------------------------------------
# Rule 4: risky payment methods tied to the applicant's money
# ---------------------------------------------------------------------------------------------------------------

_PAYMENT_METHOD = _re(
    r"\b(?:gift\s*cards?|itunes\s+cards?|google\s+play\s+cards?|steam\s+cards?|prepaid\s+cards?|reload\s+cards?|"
    r"crypto(?:currency|currencies)?|bitcoins?|btc|usdt|ethereum|cash\s*app|zelle|venmo|paypal|"
    r"wire\s+transfers?|money\s+transfers?|money\s+orders?|western\s+union|moneygram)\b"
)
_MONEY_VERB = _re(r"\b(?:send|sends|pay|transfer|wire|deposit|buy|purchase|load|remit|forward|invest|reload)\b")
_PAY_NEEDS_OBJECT = _re(r"\s+(?:us\b|the\b|a\b|an\b|your\b|any\b|all\b|\$|\d)")
# The verb is an instruction to the reader ("Send ...", "Please send ...", "You must send ...").
_INSTRUCTION_PREFIX = _re(
    r"(?:^|\b(?:please|kindly|then|first|next|simply|just|now|you(?:\s+(?:must|will|can|may|should|need\s+to|"
    r"have\s+to|are\s+required\s+to|will\s+need\s+to|will\s+have\s+to|are\s+asked\s+to))?|you['\u2019]ll"
    r"(?:\s+need\s+to)?|applicants?(?:\s+(?:must|will|should|need\s+to))?|candidates?(?:\s+(?:must|will|should|"
    r"need\s+to))?))\s*$"
)
# "You will receive payments ... and forward the money" (or the same as an instruction at the start of a sentence).
# "You" must come right before "receive", so "you will design systems that receive payments" is not matched.
_RECEIVE_THEN_FORWARD = _re(
    r"(?:^[\s\-*\u2022]*|\byou\s+(?:will\s+|would\s+|must\s+|can\s+|need\s+to\s+|are\s+to\s+)?(?:then\s+)?)"
    r"(?:receive|accept|collect)\s+(?:\w+\s+){0,2}(?:payments?|funds|money|transfers?)\b[^.!?\n]{0,100}?"
    r"\b(?:forward|send|transfer|wire|remit)\s+(?:the\s+|that\s+|those\s+|these\s+|all\s+|any\s+|part\s+of\s+(?:the\s+)?)?"
    r"(?:money|funds|payments?|balance|amount|remaining|rest|cash)\b"
)
_PREFIX_TRIM = " \t-*\u2022:,("


def _money_is_moving(sentence, method_start):
    """True when the sentence tells the applicant to pay, send or move money (so the method is part of that)."""
    for verb in _MONEY_VERB.finditer(sentence, 0, method_start):
        if verb.group(0).lower() == "pay" and not _PAY_NEEDS_OBJECT.match(sentence, verb.end()):
            continue
        if _INSTRUCTION_PREFIX.search(sentence[:verb.start()].strip(_PREFIX_TRIM)):
            return True
    return bool(_RECEIVE_THEN_FORWARD.search(sentence))


def _find_payment_method(text):
    spans = []
    for method in _PAYMENT_METHOD.finditer(text.raw):
        if text.negated(method.start(), method.end()):
            continue
        sentence_start, sentence_end = text.sentence_span(method.start())
        sentence = text.raw[sentence_start:sentence_end]
        if _money_is_moving(sentence, method.start() - sentence_start):
            spans.append((method.start(), method.end()))
    return _Hit(spans) if spans else None


# ---------------------------------------------------------------------------------------------------------------
# Rule 5: unrealistic earnings for little effort (needs BOTH parts)
# ---------------------------------------------------------------------------------------------------------------

_PAY_AMOUNT = _re(
    r"\$\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b|thousand\b)?\s*\+?\s*"
    r"(?:(?:/|per|a|an|each|every|in\s+a)\s*)?(?P<unit>day|daily|week|weekly|hour|hourly|hr|month|monthly)\b"
)
# An amount only counts as "very high" above these levels. Salaries per year are never looked at.
_VERY_HIGH_PAY = {"day": 300, "week": 1500, "hour": 100, "month": 10000}
_UNIT_GROUP = {"day": "day", "daily": "day", "week": "week", "weekly": "week", "hour": "hour", "hourly": "hour",
               "hr": "hour", "month": "month", "monthly": "month"}
_PAY_WORDING = _re(
    r"\b(?:earn|make|get\s+paid|receive)\s+(?:up\s+to\s+)?(?:thousands|hundreds)\s+(?:of\s+dollars\s+)?"
    r"(?:every|each|per|a)\s+(?:day|week)\b"
)
_LITTLE_EFFORT = [
    _re(r"\bno\s+(?:prior\s+|previous\s+)?experience(?:\s+(?:needed|required|necessary))?\b"),
    _re(r"\bwithout\s+(?:any\s+)?experience\b"),
    _re(r"\bno\s+(?:skills|qualifications|degree)\s+(?:needed|required|necessary)\b"),
    _re(r"\b(?:little|minimal|no)\s+(?:effort|work)\b"),
    _re(r"\b(?:work(?:ing)?|only|just|spend(?:ing)?|in)\s+(?:only\s+|just\s+)?(?:about\s+)?"
        r"(?:one|1|two|2|three|3|an?|a\s+few)\s+(?:hours?|hrs?|minutes?|mins?)\b"),
    _re(r"\b(?:one|1|two|2|three|3|an?|a\s+few)\s+(?:hours?|hrs?|minutes?)\s+(?:daily|a\s+day|per\s+day|each\s+day|"
        r"every\s+day)\b"),
    _re(r"\b(?:simple|easy)\s+(?:tasks?|work|jobs?|online\s+work)\b"),
    _re(r"\bguaranteed\s+(?:income|earnings?|pay|paycheck|salary|money|weekly\s+pay)\b"),
    _re(r"\beasy\s+money\b"),
    _re(r"\bget\s+paid\s+to\s+(?:click|watch|like|type|scroll)\b"),
]
_PAY_AND_EFFORT_DISTANCE = 300      # the two parts must be this close together


def _find_unrealistic_pay(text):
    pay_spans = []
    for match in _PAY_AMOUNT.finditer(text.raw):
        amount = float(match.group("num").replace(",", ""))
        if match.group("k"):
            amount *= 1000
        if amount >= _VERY_HIGH_PAY[_UNIT_GROUP[match.group("unit").lower()]]:
            pay_spans.append((match.start(), match.end()))
    pay_spans += [(m.start(), m.end()) for m in _PAY_WORDING.finditer(text.raw)]
    if not pay_spans:
        return None
    effort_spans = sorted((m.start(), m.end()) for p in _LITTLE_EFFORT for m in p.finditer(text.raw))
    for pay_start, pay_end in sorted(pay_spans):
        near = [(s, e) for s, e in effort_spans if max(s - pay_end, pay_start - e, 0) <= _PAY_AND_EFFORT_DISTANCE]
        if near:
            return _Hit([(pay_start, pay_end)] + near[:2])
    return None


# ---------------------------------------------------------------------------------------------------------------
# Rule 6: pressure / urgency
# ---------------------------------------------------------------------------------------------------------------

_URGENCY = [
    _re(r"\bact\s+(?:now|fast|quickly|immediately|today)\b"),
    _re(r"\blimited\s+(?:spots?|openings?|positions?|slots?|vacanc(?:y|ies))\b"),
    _re(r"\b(?:only\s+)?\d+\s+(?:spots?|positions?|openings?|slots?)\s+(?:left|remaining|available)\b"),
    _re(r"\bimmediate\s+start\b"),
    _re(r"\bstart\s+(?:immediately|today|right\s+away|now|tomorrow)\b"),
    _re(r"\bbegin\s+(?:immediately|today|right\s+away)\b"),
    _re(r"\b(?:reply|respond)\s+(?:immediately|asap|right\s+away|today)\b"),
    _re(r"\burgent(?:ly)?\s+(?:hiring|need(?:ed)?|required|vacanc(?:y|ies)|openings?)\b"),
    _re(r"\bhiring\s+(?:urgently|immediately|asap)\b"),
    _re(r"\b(?:offer|position|opportunity)\s+(?:will\s+)?expires?\b"),
    _re(r"\b(?:reply|respond|apply|answer|confirm|contact\s+\w+)\s+(?:back\s+)?within\s+(?:the\s+next\s+)?"
        r"\d+\s*(?:hours?|hrs?|minutes?|mins?)\b"),
    _re(r"\bdon['\u2019]?t\s+miss\s+(?:out|this)\b"),
    _re(r"\blast\s+chance\b"),
    _re(r"\bfirst\s+come,?\s+first\s+served\b"),
]
_find_urgency = _phrase_finder(_URGENCY)


# ---------------------------------------------------------------------------------------------------------------
# Rule 7: instant offer / no interview (only explicit wording)
# ---------------------------------------------------------------------------------------------------------------

_INSTANT_OFFER = [
    _re(r"\bno\s+interviews?(?:\s+(?:is\s+|are\s+)?(?:required|needed|necessary))?\b"),
    _re(r"\bwithout\s+(?:an?\s+)?interview\b"),
    _re(r"\bskip\s+the\s+interview\b"),
    _re(r"\byou(?:['\u2019]re|\s+are)\s+(?:already\s+)?hired\b"),
    _re(r"\bhired\s+(?:on\s+the\s+spot|immediately|instantly|today|right\s+away)\b"),
    _re(r"\binstant(?:ly)?\s+hir(?:e|ed|ing)\b"),
    _re(r"\bguaranteed\s+(?:job|position|hire|hiring|employment|placement)\b"),
]
_find_instant_offer = _phrase_finder(_INSTANT_OFFER)


# ---------------------------------------------------------------------------------------------------------------
# Rule 8: package reshipping
# ---------------------------------------------------------------------------------------------------------------

_RESHIP_STRONG = [
    _re(r"\bre-?ship\w*"),
    _re(r"\b(?:package|parcel)\s+(?:re-?)?forwarding\b"),
    _re(r"\bforward(?:ing)?\s+(?:the\s+|these\s+|those\s+|all\s+|your\s+)?(?:packages?|parcels?)\s+(?:\w+\s+){0,3}"
        r"(?:overseas|abroad|internationally|to\s+(?:another|a\s+different|our\s+(?:clients?|customers?|overseas|"
        r"partners?)|an?\s+(?:international|overseas)))"),
]
_PACKAGES_AT_HOME = _re(
    r"\b(?:receive|accept|get|take\s+delivery\s+of)\s+(?:\w+\s+){0,3}(?:packages?|parcels?|shipments?|boxes|"
    r"merchandise)\b[^.!?\n]{0,40}\b(?:at|to|in)\s+(?:your|their)\s+(?:own\s+)?(?:home|house|residence|apartment|address)\b"
)
_THEN_MOVE_ON = _re(r"\b(?:forward|re-?ship|re-?pack(?:age)?|re-?label|re-?mail|ship|send|mail|inspect)\w*\b")


def _find_reshipping(text):
    spans = _spans_of(text, _RESHIP_STRONG, "basic")
    for match in _PACKAGES_AT_HOME.finditer(text.raw):
        if text.negated(match.start(), match.end()):
            continue
        if _THEN_MOVE_ON.search(text.raw, match.end(), min(len(text.raw), match.end() + 200)):
            spans.append((match.start(), match.end()))
    spans.sort()
    return _Hit(spans) if spans else None


# ---------------------------------------------------------------------------------------------------------------
# Rules 9 and 10: task / review schemes
# ---------------------------------------------------------------------------------------------------------------

_TASK_DEPOSIT = [
    _re(r"\b(?:deposit|recharge|top[\s-]?up|pay|fund)\b[^.!?\n]{0,40}?\b(?:to\s+)?(?:unlock|activate|release|withdraw|"
        r"receive|get)\b[^.!?\n]{0,30}?\b(?:tasks?|commissions?|earnings|orders?|account|bonus)\b"),
    _re(r"\b(?:commissions?|earnings|tasks?)\b[^.!?\n]{0,30}?\b(?:unlock(?:ed)?|released?|available)\s+"
        r"(?:after|upon|once|when)\s+(?:you\s+)?(?:make\s+)?(?:a\s+)?(?:deposit|recharge|payment|top[\s-]?up|pay)\b"),
    _re(r"\brecharge\s+(?:your\s+)?(?:work\s+|task\s+|merchant\s+)?account\b"),
    _re(r"\b(?:pay|deposit)\s+(?:money\s+|funds\s+)?to\s+(?:complete|finish|unlock|continue|start)\s+"
        r"(?:the\s+|your\s+|more\s+)?(?:tasks?|orders?|set)\b"),
    _re(r"\b(?:tasks?|orders?)\s+(?:require|requires|need|needs)\s+(?:a\s+)?(?:deposit|recharge|payment)\b"),
]
_find_task_deposit = _phrase_finder(_TASK_DEPOSIT, negation="cost")

_PAID_ENGAGEMENT = [
    _re(r"\b(?:get\s+paid|earn|paid)\b[^.!?\n]{0,25}?\b(?:to\s+)?(?:like|liking|rate|rating|review|reviewing|boost|"
        r"boosting|click(?:ing)?|follow(?:ing)?|subscrib\w+)\b[^.!?\n]{0,40}?\b(?:products?|videos?|posts?|apps?|"
        r"pages?|listings?|ads?|reviews?|channels?|accounts?|restaurants?|hotels?)\b"),
    _re(r"\b(?:paid|pay)\s+(?:product\s+)?(?:ratings?|reviews?|likes?)\b"),
    _re(r"\bproduct\s+(?:rating|review|boosting)\s+(?:job|tasks?|work)\b"),
    _re(r"\bapp\s+(?:optimi[sz]ation)\s+tasks?\b"),
    _re(r"\b(?:optimi[sz]e|boost)\s+(?:apps?|products?|rankings?|ratings?)\b[^.!?\n]{0,30}?\btasks?\b"),
    _re(r"\b(?:rate|review|like)\s+(?:products?|apps?|videos?)\s+and\s+(?:earn|get\s+paid)\b"),
    _re(r"\bdata\s+optimi[sz]ation\s+tasks?\b"),
]
_find_paid_engagement = _phrase_finder(_PAID_ENGAGEMENT)


# ---------------------------------------------------------------------------------------------------------------
# Rule 11: personal (free-provider) e-mail address
# ---------------------------------------------------------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@(?P<domain>[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})")


def _find_personal_email(text):
    spans, addresses = [], []
    for match in _EMAIL.finditer(text.raw):
        if match.group("domain").lower() in FREE_EMAIL_DOMAINS:
            spans.append((match.start(), match.end()))
            if match.group(0) not in addresses:
                addresses.append(match.group(0))
    return _Hit(spans, {"emails": addresses}) if spans else None


# ---------------------------------------------------------------------------------------------------------------
# The rule table. The order here is the display order inside each severity.
# ---------------------------------------------------------------------------------------------------------------

RULES = [
    Rule("upfront_payment", "Upfront payment requested", "money", "high",
         "Legitimate employers generally do not require applicants to pay a fee to get or start a job.",
         "Do not send money. Verify the position directly with the employer, using contact details you find yourself.",
         _find_upfront_payment),
    Rule("fake_check", "Check-deposit or equipment-purchase instructions", "money", "high",
         "A known scam sends a check, asks you to deposit it, and then has you buy equipment or send part of the money "
         "onward. The check can later turn out to be fake.",
         "Do not deposit a check and send money onward. Confirm the employer and the offer independently first.",
         _find_fake_check),
    Rule("sensitive_info", "Sensitive information requested", "personal_info", "high",
         "Employers may need details like these later in a verified hiring process, but a posting or early message "
         "that asks for them deserves a closer look.",
         "Do not share banking or identity details until you have verified the employer and the hiring process.",
         _find_sensitive_info),
    Rule("payment_method", "Money sent through a hard-to-reverse payment method", "money", "high",
         "Gift cards, cryptocurrency, wire transfers and payment apps are hard to reverse. Honest employers do not "
         "ask applicants to pay or move money this way.",
         "Do not send money this way. Check the request with the employer using contact details you find yourself.",
         _find_payment_method),
    Rule("task_deposit", "Deposit required to unlock tasks or earnings", "task_scheme", "high",
         "Honest employers do not ask you to deposit your own money to receive work or to withdraw earnings.",
         "Do not deposit money. Research the company independently before doing anything else.",
         _find_task_deposit),
    Rule("purchase_reimbursement", "Asked to buy equipment, with repayment promised", "money", "medium",
         "Some employers do reimburse expenses, but scammers also promise repayment to get applicants to spend "
         "their own money first.",
         "Get the reimbursement policy in writing from the employer, using contact details you find yourself, "
         "before buying anything.",
         _find_purchase_reimbursement),
    Rule("unrealistic_pay", "Very high pay for little effort", "pay", "medium",
         "High earnings are sometimes legitimate, but very large pay combined with 'no experience' or very few hours "
         "is a pattern often used to attract victims.",
         "Look for specific duties, a named employer and a real hiring process before going further.",
         _find_unrealistic_pay),
    Rule("instant_offer", "Instant-offer or no-interview wording", "hiring_process", "medium",
         "Most employers interview candidates before hiring them. Wording that promises a job without that step is "
         "worth verifying.",
         "Ask how the hiring process works, and confirm it on the employer's official website.",
         _find_instant_offer),
    Rule("reshipping", "Package reshipping duties", "job_duties", "medium",
         "Receiving packages and sending them on to another address is a pattern sometimes used to move stolen "
         "goods. It warrants additional verification.",
         "Do not receive or forward packages until you have verified the employer independently.",
         _find_reshipping),
    Rule("paid_engagement", "Pay for ratings, reviews or likes", "task_scheme", "medium",
         "Work that pays for ratings, likes or 'optimization' tasks matches a known online task-scam pattern.",
         "Be cautious. Research the company, and avoid any platform that later asks you to deposit money.",
         _find_paid_engagement),
    Rule("personal_email", "Personal email address used", "contact", "medium",
         "Recruiters representing established employers generally use a company email domain. "
         "Verify the sender independently.",
         "Verify the recruiter and the role through the company's official website before replying.",
         _find_personal_email),
    Rule("urgency", "Pressure or urgency language", "pressure", "notice",
         "Pressure to act quickly leaves less time to check an offer. It is not proof of a scam on its own.",
         "Take your time. Verify the employer before replying or sharing anything.",
         _find_urgency),
]


# ---------------------------------------------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------------------------------------------

def _evidence_for(text, spans):
    """Cut readable excerpts of the user's own text for the spans: (main_evidence, more_evidence)."""
    excerpts = []
    for start, end in spans:
        piece = text.excerpt(start, end)
        if piece and not any(piece in kept or kept in piece for kept in excerpts):
            excerpts.append(piece)
        if len(excerpts) == MAX_EVIDENCE_PER_SIGNAL:
            break
    return (excerpts[0], excerpts[1:]) if excerpts else ("", [])


def scan_job_signals(raw_text, extracted_fields=None):
    """Find warning signs in a pasted job posting.

    raw_text         the posting exactly as the user pasted it (evidence is always cut from this text)
    extracted_fields the intake parser's five fields, if available. Reserved for rules that need section context;
                     no current rule uses it, so the result depends on raw_text only.

    Returns {"signals": [...], "signal_count": n}. Each signal has:
      id, title, category, severity ("high" | "medium" | "notice"), evidence (exact excerpt of raw_text),
      more_evidence (up to two more exact excerpts), explanation, recommended_action, details (extra facts, e.g. emails).
    There is deliberately no score: the count is the only summary.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return {"signals": [], "signal_count": 0}

    text = _Text(raw_text)
    signals = []
    for rule in RULES:
        hit = rule.find(text)
        if hit is None:
            continue
        evidence, more_evidence = _evidence_for(text, hit.spans)
        if not evidence:                    # no real excerpt, so the signal is not shown
            continue
        signals.append({
            "id": rule.id,
            "title": rule.title,
            "category": rule.category,
            "severity": rule.severity,
            "evidence": evidence,
            "more_evidence": more_evidence,
            "explanation": rule.explanation,
            "recommended_action": rule.recommended_action,
            "details": hit.details,
        })
    signals.sort(key=lambda signal: _SEVERITY_ORDER[signal["severity"]])      # stable: rule order kept inside a level
    return {"signals": signals, "signal_count": len(signals)}
