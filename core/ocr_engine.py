"""Tier 2: read a Student ID / Certificate of Registration (COR) from a camera frame.

Built like a licence-plate reader (ANPR), in stages:

  1. Detect   - find where text is (EasyOCR's CRAFT text detector), on a small copy (fast).
  2. Orient   - sideways text gives tall boxes, upright text gives wide boxes: turn the frame
                so the boxes are wide. Upside-down is caught later (step 5).
  3. Crop     - cut the frame down to the area that holds text, then enlarge it, so the
                characters are big for the recogniser (like cropping to the plate).
  4. Read     - recognise each text box, then rebuild the printed lines from the box
                positions (EasyOCR returns boxes, not lines in reading order).
  5. Validate - parse with the document's patterns. No student number found -> try the
                frame turned 180 degrees once.
  6. Vote     - ScanVoter (used by the scan dialog) combines several frames, like a plate
                reader confirming a plate over several frames before logging it.

Document patterns (Kolehiyo ng Lungsod ng Lipa):
  ID (both designs)  name line  SURNAME, GIVEN NAMES M.        number  04141-24-0549
  COR                "Name: SURNAME, GIVEN [SUFFIX] MIDDLE"     "Student No: 04141-24-3344"
OCR mistakes handled: ';' or ':' read for ',' and '.', commas dropped, letters read for digits
(O->0, I->1, S->5, B->8 ...) inside the number, misspelled labels ("Nama:", "Studont No:").
"""
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Tuple

from core import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- patterns
_SEP = r"[-–—_. ]"
_D = r"[0-9OoDQIl|!SsBZz]"                                 # a digit, or a letter OCR confuses with one
_NUMBER_LOOSE = re.compile(rf"(?<![0-9A-Za-z]){_D}{{5}}\s?{_SEP}\s?{_D}{{2}}\s?{_SEP}\s?{_D}{{4}}(?![0-9A-Za-z])")
_NUMBER = re.compile(config.STUDENT_NUMBER_PATTERN)
_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                           "!": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})

_LAST = r"\b(?:last\s*name|surname|family\s*name)\b"
_FIRST = r"\b(?:first\s*name|given\s*name)\b"
# plain "Name" / "Student Name" and OCR misspellings (Nama, Narne), not "Last/First/Middle Name"
_FULL = r"(?<!last )(?<!first )(?<!given )(?<!middle )(?<!family )\b(?:name|nama|narne|nane|neme)\b"
_COMMA_NAME = re.compile(r"^([A-Za-z][A-Za-z.'\- ]{1,40}?)\s*,\s*([A-Za-z][A-Za-z.'\- ]{1,40})$")
_CAPS_NAME = re.compile(r"^[A-Z][A-Z.'\-]+(?:\s+[A-Z][A-Z.'\-]*){1,6}$")      # BONIFE JAY AR S.
_NOT_A_NAME = re.compile(r"\b(CITY|BATANGAS|LIPA|KOLEHIYO|LUNSOD|LUNGSOD|COLLEGE|STUDIES|SEMESTER|"
                         r"UNIVERSITY|REPUBLIC|PHILIPPINES|SCHOOL|SIGNATURE|STUDENT|TEMPORARY|COMPUTER|"
                         r"BACHELOR|SCIENCE|CERTIFICATE|REGISTRATION|ENROLLED|COPY|COURSE|FULL|NAME|"
                         r"NUMBER|BARANGAY|FIRST|SECOND|YEAR|LEVEL|DATE|CODE|DESCRIPTION|BSCS|BSIT)\b", re.I)
_COR_WORDS = re.compile(r"CERTIFICATE|REGISTRATION|REGISTRAR|ENROLLED|ASSESSMENT|UNITS", re.I)
_INITIALS = re.compile(r"(\s+[A-Za-z]\.?)+$")               # trailing middle initial(s)
_SUF = r"(?:JR|SR|I[IL1]{1,2}|IV)"                                # II / III, also as OCR reads them: Ili, Il1
_SUFFIX = re.compile(rf"[\s,]+{_SUF}\.?$", re.I)
_SUFFIX_MIDDLE = re.compile(rf"\s+({_SUF})\.?(\s+.*)?$", re.I)   # COR order: GIVEN SUFFIX MIDDLE
_PARTICLES = {"DE", "DEL", "DELA", "DELOS", "LA", "LOS", "SAN", "STA", "STO", "VAN", "VON"}
_ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,.-:'()"

_DETECT_SIDE = 800          # long side of the copy used for detection / orientation
_READ_SIDE = 1200           # long side of the text crop given to the recogniser


@dataclass
class OcrResult:
    student_number: str = ""
    first_name: str = ""
    last_name: str = ""
    raw_text: str = ""
    review: bool = False        # name read, but the split into first/last/middle is uncertain
    confidence: float = 0.0     # lowest OCR confidence of the lines the fields came from
    doc_type: str = ""          # "id" | "cor" | ""

    @property
    def success(self) -> bool:
        """Complete enough to log without a human re-typing anything."""
        return bool(self.student_number and self.first_name and self.last_name) and not self.review


# ---------------------------------------------------------------- text parsing
def _clean(text: str) -> str:
    return re.sub(r"[^A-Za-z.,'\- ]", "", text).strip(" ,.-")


def _normalise(line: str) -> str:
    """Undo the punctuation EasyOCR typically gets wrong on name lines."""
    line = line.replace(";", ",")
    line = re.sub(r"\s*:\s*$", ".", line)                   # 'JAY AR S:' -> 'JAY AR S.'
    return re.sub(r"\s+", " ", line).strip()


def find_student_number(line: str) -> str:
    m = _NUMBER.search(line)
    if m:
        return re.sub(rf"\s*{_SEP}+\s*", "-", m.group(0)).replace(" ", "")
    m = _NUMBER_LOOSE.search(line)
    if not m:
        return ""
    digits = re.sub(r"[^0-9]", "", m.group(0).translate(_TO_DIGIT))
    if len(digits) != 11 or sum(c.isdigit() for c in m.group(0)) < 8:   # mostly real digits only
        return ""
    return f"{digits[:5]}-{digits[5:7]}-{digits[7:]}"


def _value_after(lines: List[str], label: str) -> Tuple[str, int]:
    """(text after `label` or on the next line, line index) - EasyOCR often splits label and value."""
    for i, line in enumerate(lines):
        m = re.search(label + r"[ \t]*[:;\-.]?[ \t]*(.*)", line, re.I)
        if not m:
            continue
        value, at = _clean(m.group(1)), i
        if not value and i + 1 < len(lines):
            value, at = _clean(lines[i + 1]), i + 1
        if value and not _NOT_A_NAME.search(value):
            return value, at
    return "", -1


def _split_given(given: str) -> Tuple[str, bool]:
    """Given names without middle name/initial. review=True when that cannot be told apart."""
    given = given.strip(" ,.")
    cut = _SUFFIX_MIDDLE.search(given)
    if cut:                                                  # the suffix marks where the middle name starts
        return given[:cut.start()].strip(), False
    stripped = _INITIALS.sub("", given).strip(" .")
    if stripped and stripped != given:
        return stripped, False                               # 'JAY AR S.' -> 'JAY AR'
    # no initial and no suffix: a full middle name looks exactly like a second given name
    return given, len(given.split()) > 1


def _split_surname_first(text: str) -> Tuple[str, str, bool]:
    """'RECINTO MARC FROILAN III TENORIO' (comma lost) -> (first, last, review)."""
    words = text.split()
    n = 1
    while n < len(words) - 1 and words[n - 1].upper().strip(".") in _PARTICLES:
        n += 1                                               # DELA CRUZ, DE LOS SANTOS
    last, given = " ".join(words[:n]), " ".join(words[n:])
    first, review = _split_given(given)
    return first, last, review


def _comma_name(lines: List[str], number_line: Optional[int]) -> Tuple[str, str, int, bool]:
    """(first, last, line, review) from the 'SURNAME, GIVEN NAMES M.' line closest to the number."""
    best = None
    for i, line in enumerate(lines):
        m = _COMMA_NAME.match(line)
        if not m or _NOT_A_NAME.search(line):
            continue
        distance = abs(i - number_line) if number_line is not None else i
        if best is None or distance < best[0]:
            best = (distance, m.group(1), m.group(2), i)
    if best is None:
        return "", "", -1, False
    last = _SUFFIX.sub("", best[1].strip(" ."))
    given = best[2] if _SUFFIX_MIDDLE.search(best[2]) and _SUFFIX_MIDDLE.search(best[2]).group(2) \
        else _SUFFIX.sub("", best[2].strip())
    first, review = _split_given(given)
    return first, last, best[3], review


def _caps_line_near(lines: List[str], number_line: int) -> Tuple[str, int]:
    """Comma lost on an ID: the all-caps line right above or below the student number."""
    for i in (number_line - 1, number_line + 1, number_line - 2, number_line + 2):
        if 0 <= i < len(lines) and _CAPS_NAME.match(lines[i]) and not _NOT_A_NAME.search(lines[i]):
            return lines[i], i
    return "", -1


def parse_document_text(text: str, confidences: Optional[List[float]] = None) -> OcrResult:
    """Pull student number and name out of OCR text (one printed line per text line)."""
    lines = [_normalise(ln) for ln in text.splitlines() if ln.strip()]
    conf = confidences if confidences and len(confidences) == len(lines) else [1.0] * len(lines)
    result = OcrResult(raw_text=text)
    is_cor = bool(_COR_WORDS.search(text))
    result.doc_type = "cor" if is_cor else ("id" if lines else "")

    number_line = None
    for i, line in enumerate(lines):
        number = find_student_number(line)
        if number:
            result.student_number, number_line = number, i
            break

    name_line, review = -1, False
    (last, li), (first, fi) = _value_after(lines, _LAST), _value_after(lines, _FIRST)
    if last and first:
        name_line = max(li, fi)
    else:
        first, last, name_line, review = _comma_name(lines, number_line)
    if not (last and first):
        full, name_line = _value_after(lines, _FULL)
        mid = _SUFFIX_MIDDLE.search(full) if full else None
        if "," in full:                                      # "DELA CRUZ, JUAN III SANTOS"
            last, given = [p.strip() for p in full.split(",", 1)]
            first, review = _split_given(given)
        elif full and (is_cor or (mid and mid.group(2))):    # COR with the comma lost
            first, last, review = _split_surname_first(full)
        elif full:                                           # "Juan Dela Cruz"
            parts = full.split()
            first, last = " ".join(parts[:-1]), parts[-1]
    if not (last and first) and number_line is not None:
        caps, name_line = _caps_line_near(lines, number_line)
        if caps:
            first, last, _ = _split_surname_first(caps)
            review = True                                    # no comma: the guard confirms the split

    result.first_name, result.last_name, result.review = first.title(), last.title(), review
    used = [i for i in (number_line, name_line) if i is not None and i >= 0]
    result.confidence = min((conf[i] for i in used), default=0.0)
    return result


# ---------------------------------------------------------------- image pipeline
def _resize_long(image, side):
    import cv2
    h, w = image.shape[:2]
    s = side / max(h, w)
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    return cv2.resize(image, (max(1, int(w * s)), max(1, int(h * s))), interpolation=interp), s


def group_lines(boxes) -> Tuple[List[str], List[float]]:
    """EasyOCR (box, text, conf) list -> printed lines top to bottom, words left to right."""
    items = []
    for box, text, c in boxes:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), max(ys), min(xs), text.strip(), float(c), max(xs)))
    items.sort(key=lambda t: ((t[0] + t[1]) / 2, t[2]))
    rows: List[list] = []
    for it in items:
        mid, height = (it[0] + it[1]) / 2, it[1] - it[0]
        for row in rows:
            r_mid = sum((x[0] + x[1]) / 2 for x in row) / len(row)
            r_h = sum(x[1] - x[0] for x in row) / len(row)
            if abs(mid - r_mid) < 0.5 * min(height, r_h):   # same printed line
                gap = it[2] - max(x[5] for x in row)
                if gap < 3.0 * max(height, r_h):           # same column (the COR has two)
                    row.append(it)
                    break
        else:
            rows.append([it])
    lines, confs = [], []
    for row in rows:
        row.sort(key=lambda t: t[2])
        words = [t for t in row if t[3]]
        if words:
            lines.append(" ".join(t[3] for t in words))
            confs.append(min(t[4] for t in words))
    return lines, confs


class DocumentOCR:
    """EasyOCR loads slowly (and downloads models on first use), so it is created on demand."""

    def __init__(self):
        self._reader = None

    @property
    def reader(self):
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(["en"], gpu=config.OCR_GPU, verbose=False)
        return self._reader

    def warm_up(self) -> None:
        """Load the models ahead of the first scan (call from a background thread)."""
        try:
            _ = self.reader
        except Exception:
            log.exception("OCR warm-up failed")

    # -- steps 1-3: detect, orient, crop
    def _text_boxes(self, image):
        small, s = _resize_long(image, _DETECT_SIDE)
        horizontal, _ = self.reader.detect(small, min_size=8, text_threshold=0.6)
        return [(b[0] / s, b[1] / s, b[2] / s, b[3] / s) for b in horizontal[0]]

    def locate(self, image):
        """Turn the frame so its text is horizontal and crop it to the text."""
        import cv2
        boxes = self._text_boxes(image)
        wide = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in boxes if x1 - x0 > 1.8 * (y1 - y0))
        tall = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in boxes if y1 - y0 > 1.8 * (x1 - x0))
        if tall > wide:                                      # sideways document
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            boxes = self._text_boxes(image)
        boxes = [b for b in boxes if b[1] - b[0] > 1.5 * (b[3] - b[2])]
        if not boxes:
            return image
        h, w = image.shape[:2]
        x0, x1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
        y0, y1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
        mx, my = 0.04 * w, 0.04 * h
        x0, y0 = int(max(0, x0 - mx)), int(max(0, y0 - my))
        x1, y1 = int(min(w, x1 + mx)), int(min(h, y1 + my))
        return image[y0:y1, x0:x1] if (x1 - x0) > 40 and (y1 - y0) > 20 else image

    # -- steps 4-5: read and validate
    def _read_crop(self, crop) -> OcrResult:
        big, _ = _resize_long(crop, _READ_SIDE)
        boxes = self.reader.readtext(big, detail=1, paragraph=False, allowlist=_ALLOW,
                                     text_threshold=0.6, low_text=0.35)
        lines, confs = group_lines(boxes)
        return parse_document_text("\n".join(lines), confs)

    def read(self, image) -> OcrResult:
        """Never raises: any failure returns an empty result."""
        try:
            import cv2
            crop = self.locate(image)
            result = self._read_crop(crop)
            if not result.student_number:                    # maybe upside down
                flipped = self._read_crop(cv2.rotate(crop, cv2.ROTATE_180))
                if flipped.student_number:
                    result = flipped
            return result
        except Exception:
            log.exception("OCR failed")
            return OcrResult()


# ---------------------------------------------------------------- step 6: multi-frame voting
class ScanVoter:
    """Combine reads of consecutive frames, the way a plate reader confirms a plate.

    A value is confirmed when two frames agree on it, or one frame reads it with high
    confidence (config.OCR_ACCEPT_CONFIDENCE counts double). `best` always holds the
    most-voted values, for pre-filling the manual form.
    """

    def __init__(self, accept_confidence: Optional[float] = None):
        self.accept = getattr(config, "OCR_ACCEPT_CONFIDENCE", 0.6) if accept_confidence is None \
            else accept_confidence
        self.numbers: Counter = Counter()
        self.names: Counter = Counter()
        self.review_names: set = set()
        self.frames = 0

    def add(self, r: OcrResult) -> Optional[OcrResult]:
        """Returns the confirmed result once the document is read reliably, else None."""
        self.frames += 1
        weight = 2 if r.confidence >= self.accept else 1
        if r.student_number:
            self.numbers[r.student_number] += weight
        if r.first_name and r.last_name:
            key = (r.first_name, r.last_name)
            self.names[key] += 1 if r.review else weight
            if r.review:
                self.review_names.add(key)
        best = self.best
        if best.success and self.numbers[best.student_number] >= 2 \
                and self.names[(best.first_name, best.last_name)] >= 2:
            return best
        return None

    @property
    def best(self) -> OcrResult:
        out = OcrResult()
        if self.numbers:
            out.student_number = self.numbers.most_common(1)[0][0]
        if self.names:
            (out.first_name, out.last_name), _ = self.names.most_common(1)[0]
            out.review = (out.first_name, out.last_name) in self.review_names
        return out
