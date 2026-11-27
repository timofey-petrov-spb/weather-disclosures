"""Rank up to three financial tables for a human reviewing a named hurricane."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v4"))
sys.path.insert(0, str(ROOT / "v7"))
from tables import read_tables

NUMBER = re.compile(r"^\(?\s*(?:US\$|\$)?\s*[+−-]?\d[\d,]*(?:\.\d+)?\s*\)?$")
MONEY = re.compile(r"\$|\b(?:USD|dollars?|thousands?|millions?|billions?)\b", re.I)
MEASURE = re.compile(r"\b(?:loss(?:es)?|incurred|premiums?|expenses?|recover(?:ies|ables?)|reserves?|claims?|income|damages?)\b", re.I)


def rank(body, rows, storm):
    event = re.compile(r"(?<!\w)"+re.escape(storm)+r"(?!\w)", re.I)
    candidates = []
    for table in read_tables(body, rows):
        indexes = [row.passage for row in table.rows if row.passage is not None]
        if not indexes:
            continue
        cells = [cell for row in table.rows for cell in row.cells if cell.text]
        numeric = sum(bool(NUMBER.fullmatch(cell.text)) for cell in cells)
        if not numeric:
            continue
        inside = [cell for cell in cells if event.search(cell.text)]
        caption = " ".join(table.caption)
        first, last = min(indexes), max(indexes)
        nearby = []
        for start, step in ((first-1,-1),(last+1,1)):
            for offset in range(2):
                i = start + step*offset
                if not 0 <= i < len(rows) or rows[i]["kind"]=="table_row":
                    break
                nearby.append(i)
        surrounding = [i for i in nearby if event.search(rows[i]["text"])]
        if not (inside or event.search(caption) or surrounding):
            continue
        words = " ".join([caption] + [c.text for c in cells] + [rows[i]["text"] for i in nearby])
        score = 8 if any(len(c.text)<=80 for c in inside) else 5 if inside or event.search(caption) else 1
        score += 2*bool(MONEY.search(words)) + 2*bool(MEASURE.search(words)) + (numeric>=2)
        anchor = next((table.rows[c.row].passage for c in inside if table.rows[c.row].passage is not None),
                      surrounding[0] if surrounding else first)
        candidates.append(dict(table=table.number,score=score,first_passage=rows[first]["passage_id"],
                               last_passage=rows[last]["passage_id"],event_passage=rows[anchor]["passage_id"],
                               numeric_cells=numeric,rows=len(table.rows)))
    return sorted(candidates,key=lambda item:(-item["score"],item["table"]))[:3]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs",type=Path)
    parser.add_argument("primary",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    rows=[json.loads(line) for line in args.inputs.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    actual=rank(args.primary.read_bytes(),rows,rows[0]["event"])
    args.output.write_bytes((json.dumps(actual,indent=2)+"\n").encode())


if __name__=="__main__":
    main()

