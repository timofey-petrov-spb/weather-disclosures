"""Regression cases for source scope, scale, accounting identity and event attribution."""
import json
import sys
import unittest
from pathlib import Path
from extract import claim_narrative, plain_table, prefer_records, repeats_tag, single_event, tag_records

def passage(text,i=1,kind='paragraph'):
    return dict(text=text,doc_id='T',passage_id=f'T-P{i:05d}',kind=kind,event='Zeta',
                issuer='Example Inc.',source_url='https://example.test/form',accession='A')

def tagged_fact(concept,amount,dimensions=None):
    return dict(concept=concept,normalized_usd=str(amount),dimensions=dimensions or {},printed='40',
                fact_id='f',entity='1',context='c',scale=3,start='2021-01-01',end='2021-12-31')

class Rules(unittest.TestCase):
    def test_joint_events(self):
        for s in ('hurricanes Zeta and Omega cost $10 million.',
                  'Omega and Zeta caused losses of $10m.','Hurricane Zeta and Hurricane Omega'):
            self.assertFalse(single_event(s,'Zeta'))
    def test_aligned_columns(self):
        rows=[passage('Catastrophe losses by named storm (in millions)',1),
              passage('Event | Gross losses | Net losses | Number of claims',2,'table_row'),
              passage('Hurricane Zeta | 60 | 15 | 10',3,'table_row')]
        hits=plain_table(rows[-1],2,rows,'2021-Q4')
        self.assertEqual([(h['low_usd'],h['basis']) for h in hits],[(60_000_000,'gross'),(15_000_000,'net')])
    def test_mixed_causes_and_local_scope(self):
        rs=[passage('The following table summarizes premiums (amounts in thousands).',1),
            passage('Losses and loss adjustment expenses for ExampleCo were higher. The increase was due to $68,000 of losses due to additional policies and $38,000 of losses from Hurricane Zeta.',2)]
        out=claim_narrative(rs[1],1,rs,'2021-Q4')
        self.assertEqual([(x['low_usd'],x['issuer']) for x in out],[(38000,'ExampleCo')])
    def test_equal_amounts_do_not_imply_same_record(self):
        f=dict(low_usd=40,high_usd=40,amount_text='40',basis='net',issuer='ACME',evidence='The net loss was forty dollars.')
        self.assertFalse(repeats_tag(dict(f,basis='gross'),[f]))
        self.assertFalse(repeats_tag(dict(f,evidence='Paid claims this month amounted to forty dollars.'),[f]))
        self.assertTrue(repeats_tag(f,[f]))
    def test_tag_controls(self):
        row=passage('Hurricane Zeta had an impact.')
        f=tagged_fact('us-gaap:ReinsuranceRecoverablesOnUnpaidLossesAllowance',40000,{'x:CatastropheAxis':'x:HurricaneZetaMember'})
        a=tag_records(row,[f],[0],'2021-Q4')[0]
        self.assertEqual((a['measure'],a['low_usd']),('credit_loss_allowance',40000))
        f['dimensions']['x:CatastropheAxis']='x:HurricaneOmegaMember'
        self.assertFalse(tag_records(row,[f],[0],'2021-Q4'))
        f['dimensions']['x:CatastropheAxis']='x:HurricaneZetaMember'
        f['normalized_usd']='0'
        self.assertFalse(tag_records(row,[f],[0],'2021-Q4'))

if __name__=='__main__':unittest.main()

