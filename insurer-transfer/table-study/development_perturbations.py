"""Replay controlled edits to two *development* tables against a locked reader.

python development_perturbations.py --method /path/to/v7/extract.py --primary-files /path/to/RQ.htm /path/to/TQ.htm --output results.json

The original tables, nested cell tags, CSS and spans remain intact apart from the
literal replacements specified below. Original files and model source are read-only.
Only Python's standard library is required.
"""
import argparse
from collections import Counter
import hashlib
from html import escape
import importlib.util
import json
from pathlib import Path
import re
import sys


def digest(b):
    return hashlib.sha256(b).hexdigest()


SOURCES = {
    'b2bad728aaa7d7da9cb0f308600a28c6c26646cfa9625553f44d6599ee8111f3': (
        'RQ', 'RenaissanceRe Holdings Ltd.', 56,
        'https://www.sec.gov/Archives/edgar/data/913144/000091314422000099/rnr-20220930.htm'),
    '9bda447d23e6921bf6fcc595f8a43a7c961b7b170673349659db97c51f7ab072': (
        'TQ', 'The Travelers Companies, Inc.', 54,
        'https://www.sec.gov/Archives/edgar/data/86312/000008631222000065/trv-20220930.htm'),
}
LOCK = 'a7f296d399348884cc89c6168d2d616978cb1766cfc2f94abeeee9e5a2a8f370'


def verify_and_load(path):
    root = path.parent.parent
    lock = json.loads((path.parent/'lock.json').read_text(encoding='utf8'))
    sources = {name: digest((root/name).read_bytes()) for name in lock['implementation']}
    fingerprint = digest(json.dumps(sources,sort_keys=True,separators=(',',':')).encode())
    if sources != lock['implementation'] or fingerprint != LOCK or path.resolve() != (root/'v7/extract.py').resolve():
        raise ValueError('Method does not match the frozen v7 implementation.')
    sys.path.insert(0,str(path.resolve().parent))
    spec = importlib.util.spec_from_file_location('frozen_table_method',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(table, before, after):
    if table.count(before) != 1:
        raise ValueError('Fixture substitution did not identify exactly one original literal: '+before)
    return table.replace(before,after,1)


def reprice_ultimate(table):
    matches = [m for m in re.finditer(r'<tr\b[^>]*>.*?</tr>',table,re.I|re.S) if 'Hurricane Ian' in m[0]]
    if len(matches)!=1:
        raise ValueError('Ambiguous original storm row')
    row = matches[0]
    literal = '>326&#160;</span>'
    if row[0].count(literal)!=3:
        raise ValueError('Expected QTD, YTD and ultimate cells.')
    left,sep,right=row[0].rpartition(literal)
    return table[:row.start()]+left+sep.replace('326','417')+right+table[row.end():]


# Observations below are specified independently of model output, by reading
# the two original tables. All non-target cells are checked as well.
RE_CLAIMS = 'Net claims and claims expenses incurred'
RE_LABELS = (RE_CLAIMS,'Assumed reinstatement premiums earned','Ceded reinstatement premiums earned',
             'Earned (lost) profit commissions','Net negative impact on underwriting result','Redeemable noncontrolling interest',
             'Net negative impact on net income (loss) available (attributable) to RenaissanceRe common shareholders')
RE_IAN = dict(zip(RE_LABELS,(-990382000,221799000,-57733000,-1487000,-827803000,288383000,-539701000)))
RE_OTHER = dict(zip(RE_LABELS,(-152418000,14105000,-283000,-1285000,-139881000,40621000,-99260000)))
TR = {'incurred':326000000,'ultimate estimate':326000000}


def experiments(tables):
    re_table,tr_table=tables['RQ'],tables['TQ']
    yield 'RQ','original',re_table,RE_IAN
    yield 'TQ','original',tr_table,TR
    yield 'RQ','change sign and amount of net claims',replace_once(re_table,'>(990,382)</span>','>123,456</span>'),{**RE_IAN,RE_CLAIMS:123456000}
    moved=replace_once(re_table,'>Hurricane Ian</span>','>Hurricane Vega</span>')
    moved=replace_once(moved,'>Other Q3 2022 Catastrophe Events </span>','>Hurricane Ian </span>')
    yield 'RQ','move Ian label to adjacent catastrophe column',moved,RE_OTHER
    yield 'RQ','change reported unit from thousands to millions',replace_once(re_table,'>(in thousands)</span>','>(in millions)</span>'),{label:n*1000 for label,n in RE_IAN.items()}
    yield 'TQ','change ultimate loss only, keeping incurred QTD and YTD unchanged',reprice_ultimate(tr_table),{**TR,'ultimate estimate':417000000}
    combined=replace_once(re_table,'>Hurricane Ian</span>','>Hurricanes Ian and Vega</span>')
    yield 'RQ','replace Ian-only heading with a joint storm heading',combined,{}


def replay(method, doc, company, url, table, intro):
    from source_reader import VisibleText
    body=('<html><body><p>For the quarterly period ended September 30, 2022.</p>'+intro+table+'</body></html>').encode()
    reader=VisibleText()
    reader.feed(body.decode()); reader.close(); reader.flush()
    rows=[dict(doc_id=doc,passage_id='FRAGMENT-P%05d'%i,text=text,kind=kind,event='Ian',
               issuer=company,source_url=url,accession='DEVELOPMENT-FRAGMENT',source_kind='10-Q')
          for i,(kind,_,text) in enumerate(reader.rows,1)]
    return method.extract_filing(rows,body)


def main():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--method',required=True,type=Path)
    args.add_argument('--primary-files',required=True,nargs=2,type=Path)
    args.add_argument('--output',type=Path)
    args=args.parse_args()
    method=verify_and_load(args.method)
    from source_reader import VisibleText
    sources,tables={},{}
    introductions={}
    for path in args.primary_files:
        raw=path.read_bytes()
        sha=digest(raw)
        if sha not in SOURCES:
            raise ValueError('Supply the two original source HTML files listed in SOURCES.')
        doc,company,number,url=SOURCES[sha]
        matches=re.findall(r'<table\b[\s\S]*?</table\s*>',raw.decode('utf8'),re.I)
        table=matches[number-1]
        if 'Hurricane Ian' not in table: raise ValueError('Expected source table missing.')
        tables[doc]=table
        sources[doc]=dict(issuer=company,source_url=url,source_sha256=sha,table_index_one_based=number,original_table_sha256=digest(table.encode()))
        if doc=='TQ':
            visible=VisibleText()
            visible.feed(raw.decode('utf8'))
            visible.close()
            visible.flush()
            first=next(i for i,r in enumerate(visible.rows) if r[2]=='Losses Incurred/Unfavorable (Favorable) Prior Year Reserve Development')
            preceding=[r[2] for r in visible.rows[first-4:first]]
            if 'For purposes of the table' not in preceding[0] or '$100 million' not in preceding[0]:
                raise ValueError('Unexpected source passages preceding the Travelers table.')
            introductions[doc]=''.join('<p>'+escape(t)+'</p>' for t in preceding)
            sources[doc]['governing_passages']=['TQ-P%05d'%(i+1) for i in range(first-4,first)]
    report={'study':'Controlled perturbations of two development tables','method_fingerprint':LOCK,'sources':sources,
            'unit':'One measure per filing, with its printed sign and units converted to USD. Compare all returned labels and amounts as a multiset; extra rows, duplicates and review-only rows fail the case.',
            'scope':'Real HTML fragments inside an in-memory filing wrapper. These deliberately constructed examples provide a parser sensitivity check; they do not estimate accuracy on new issuers or independently validate economic meaning.', 'cases':[], 'initial_context_ablation':[]}
    for doc,name,table,expected in experiments(tables):
        variants=[('cases',introductions.get(doc,''))]
        if doc=='TQ':
            variants.insert(0,('initial_context_ablation',''))
        for group,intro in variants:
            output=replay(method,doc,sources[doc]['issuer'],sources[doc]['source_url'],table,intro)
            actual=[(r['measure'] if doc=='RQ' else r['status'],r.get('signed_usd')) for r in output]
            ok=Counter(actual)==Counter(expected.items()) and not any(r['review'] for r in output)
            report[group].append({'fixture':doc,'edit':name,'governing_paragraphs_included':bool(intro),
                                  'table_sha256':digest(table.encode()),'expected_signed_usd':expected,'observed_signed_usd':actual,'pass':ok})
    report['original_controls_passed']=sum(c['pass'] for c in report['cases'] if c['edit']=='original')
    report['perturbations_passed']=sum(c['pass'] for c in report['cases'] if c['edit']!='original')
    report['failed_cases']=[c['edit'] for c in report['cases'] if not c['pass']]
    report['ablation_note']='In the first run, the source paragraph preceding the Travelers table was omitted. Both Travelers fragments then produced zero rows because the table gives a scale in millions without a dollar marker. The initial expectations and their failures are retained. The repeat reinstates the actual four source passages preceding the same table; the method and the expected values are unchanged.'
    serialized=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.write_text(serialized,encoding='utf8')
    else:
        print(serialized)
    return int(bool(report['failed_cases']))


if __name__=='__main__':
    raise SystemExit(main())
