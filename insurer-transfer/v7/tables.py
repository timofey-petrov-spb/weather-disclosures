"""Source-faithful table geometry for SEC financial statements (standard library)."""
from dataclasses import dataclass, field
import re
from source_reader import VisibleText


def tidy(text):
    return ' '.join(text.split())


@dataclass
class Cell:
    row: int
    width: int
    height: int
    tag: str
    pieces: list = field(default_factory=list)
    col: int = 0

    @property
    def text(self):
        return tidy(''.join(self.pieces))

    def covers(self, col):
        return self.col <= col < self.col + self.width


@dataclass
class Row:
    cells: list = field(default_factory=list)
    passage: int | None = None


@dataclass
class Table:
    number: int
    rows: list = field(default_factory=list)
    nested: bool = False
    caption: list = field(default_factory=list)
    caption_passage: int | None = None

    def position(self):
        occupied = {}
        for i, row in enumerate(self.rows):
            col = 0
            for cell in row.cells:
                while any(occupied.get(c, 0) > i for c in range(col, col + cell.width)):
                    col += 1
                cell.col = col
                if cell.height > 1:
                    for c in range(col, col + cell.width):
                        occupied[c] = i + cell.height
                col += cell.width


def span(value):
    try:
        return min(1000, max(1, int(value or 1)))
    except ValueError:
        return 1


class TableReader(VisibleText):
    """Use the archived passage splitter itself to assign stable source addresses."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.active = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.hidden():
            return
        if tag == 'table':
            if self.active:
                self.active[-1].nested = True
            table = Table(len(self.tables) + 1)
            self.tables.append(table)
            self.active.append(table)
        elif self.active:
            table = self.active[-1]
            if tag == 'tr':
                table.rows.append(Row())
            elif tag in {'td', 'th'} and table.rows and self.inside('tr'):
                attrs = dict(attrs)
                table.rows[-1].cells.append(Cell(len(table.rows) - 1, span(attrs.get('colspan')),
                                                span(attrs.get('rowspan')), tag))
            elif tag == 'br' and table.rows and table.rows[-1].cells and self.inside('tr'):
                table.rows[-1].cells[-1].pieces.append(' ')

    def handle_data(self, data):
        super().handle_data(data)
        if self.active and not self.hidden():
            table = self.active[-1]
            if self.inside('caption'):
                table.caption.append(data)
            elif table.rows and table.rows[-1].cells and (self.inside('td') or self.inside('th')):
                table.rows[-1].cells[-1].pieces.append(data)

    def handle_endtag(self, tag):
        active = self.active[-1] if self.active and not self.hidden() else None
        before = len(self.rows)
        super().handle_endtag(tag)
        if active and tag == 'tr' and active.rows and len(self.rows) > before and self.rows[-1][0] == 'table_row':
            active.rows[-1].passage = len(self.rows) - 1
        if active and tag == 'table':
            self.active.pop()


def read_tables(raw, rows):
    try:
        source = raw.decode('utf-8')
    except UnicodeDecodeError:
        source = raw.decode('cp1252')
    parser = TableReader()
    parser.feed(source)
    parser.close()
    parser.flush()
    if len(rows) != len(parser.rows) or any(r['text'] != p[2] for r, p in zip(rows, parser.rows)):
        raise ValueError('Source HTML does not match passage manifest: ' + rows[0]['doc_id'])
    for table in parser.tables:
        if not table.nested:
            table.position()
            yield table
