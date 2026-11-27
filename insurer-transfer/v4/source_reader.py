"""Source passage mapping, compatible with the archived corpus reader."""
from html.parser import HTMLParser
import re

class VisibleText(HTMLParser):
    """Preserve inline text, join table cells as rows and keep NHC's bulletin body."""

    void = set("area base br col embed hr img input link meta param source track wbr".split())
    skip = set("head script style nav footer noscript template ix:header ix:hidden ix:resources".split())
    blocks = set("address article blockquote div h1 h2 h3 h4 h5 h6 li p section table ul".split())

    def __init__(self, bulletin=False):
        super().__init__(convert_charrefs=True)
        self.bulletin = bulletin
        self.stack = []
        self.fragments = []
        self.rows = []

    def hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def inside(self, name):
        return any(tag == name for tag, _ in self.stack)

    def flush(self, kind="paragraph"):
        raw = "".join(self.fragments)
        self.fragments.clear()
        if self.bulletin and kind != "bulletin":
            return
        paragraphs = re.split(r"\n\s*\n", raw) if kind == "bulletin" else [raw]
        for para in paragraphs:
            text = " ".join(para.split()).strip(" |")
            if text:
                self.rows.append((kind, None, text))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = re.sub(r"\s+", "", (attributes.get("style") or "").lower())
        hidden = (self.hidden() or tag in self.skip or "hidden" in attributes
                  or attributes.get("aria-hidden") == "true" or "display:none" in style
                  or "visibility:hidden" in style or attributes.get("role") == "navigation")
        if not hidden:
            if tag == "tr" or (tag in self.blocks and not self.inside("tr")) or tag == "pre":
                self.flush()
            elif tag in {"td", "th"} and self.inside("tr"):
                self.fragments.append(" | ")
            elif tag == "br":
                self.fragments.append(" ")
        if tag not in self.void:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                break
        else:
            return
        if not self.hidden():
            if tag == "pre":
                self.flush("bulletin" if self.bulletin else "paragraph")
            elif tag == "tr":
                self.flush("table_row")
            elif tag in self.blocks and not self.inside("tr"):
                self.flush()
        del self.stack[i:]

    def handle_data(self, data):
        if not self.hidden() and (not self.bulletin or self.inside("pre")):
            self.fragments.append(data)


class TaggedText(VisibleText):
    """Keep the visible monetary tag IDs and their position inside each passage."""

    def __init__(self):
        super().__init__()
        self.marks = []
        self.row_facts = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == 'ix:nonfraction' and not self.hidden():
            identifier = dict(attrs).get('id')
            if identifier:
                before = ' '.join(''.join(self.fragments).split()).strip(' |')
                self.marks.append((identifier, len(before)))

    def flush(self, kind='paragraph'):
        count = len(self.rows)
        super().flush(kind)
        if len(self.rows) > count:
            self.row_facts.append(self.marks)
        self.marks = []
