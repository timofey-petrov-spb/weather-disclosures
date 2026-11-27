# Separating hurricane losses from earned premiums

PartnerRe reports four figures on its Hurricane Katrina line. The older reader returned $54 million and labelled it a catastrophe loss. The column actually reports earned premiums. Net losses and loss expenses of **−$563m**, acquisition costs of **−$2m** and earned premiums of **+$54m** reconcile to a **−$511m impact on pre-tax net income**. Several closing parentheses occupy their own HTML cells. The unit, millions of U.S. dollars, appears in the sentence introducing the table. [PartnerRe 2005 Form 10-K](https://www.sec.gov/Archives/edgar/data/911421/000119312506043961/d10k.htm)

## Development filings

| Issuer | What identifies the financial measure and amount |
|---|---|
| PartnerRe | The heading over each column supplies the accounting measure. The sign must incorporate a closing parenthesis even when the HTML puts it in the next cell. |
| XL Capital | A section row gives the measure. The column identifies Insurance, Reinsurance, Financial Products and Services or the consolidated total. The −$74.6m Insurance premium entry is distinct from the +$16.3m Reinsurance premium entry in the same storm row. |
| Aspen | Three year blocks sit side by side. The $427.5m Katrina figure belongs to Property Reinsurance in 2005. The $15.3m on the same row belongs to California brush fires in 2003. The text after the table gives the 2005 reinsurance basis. |

These three filings were the independent test in the [previous study](../filing-tables/README.md). They are development material for this revision. The source reference contains 4 PartnerRe, 11 XL and 1 Aspen figure. Five signed entries are negative. [XL Capital 10-K](https://www.sec.gov/Archives/edgar/data/875159/000093041306001850/c41009_10k.htm) · [Aspen 10-K](https://www.sec.gov/Archives/edgar/data/1267395/000095013606001663/file001.htm) · [Original sealed reference](../filing-tables/reference.json)

The revised method matched **16/16** source assertions, including **5/5** negative entries. The checks cover the original printed cell, source unit and sign, financial measure, owner and reporting window. On the same three tables the previous version had one numerical match and no correct financial measure. Five controlled changes checked how the frozen reader behaved when the documents changed. For example, changing the currency scale to thousands throughout the PartnerRe table caption produced a +$54,000 premium. Flipping the sign of XL's Insurance premium and updating the consolidated figure preserved the premium label for all four owners. All five met their expected values, measures and source columns. [Cell-by-cell development check](development.json) · [Observed controls](control-results.json) · [Expected edits](control-cases.json)

## Test on previously unseen insurers

Both frozen readers returned **0 of 6 exact USD amounts**. They produced identical outputs for all three companies. Two automatic proposals came from the selected tables. Both located the right PXRE row and column, but used a dollar scale of 1 instead of 1,000. The other four expected figures received no proposal. [Row-by-row decisions](judgments.json) · [Results by insurer and selection group](score.json)

| Selection group | Filing | What the Katrina table reported | What the frozen reader returned |
|---|---|---|---|
| Original | [PXRE 10-K](https://www.sec.gov/Archives/edgar/data/1091748/000112528206001680/b412207_10k.htm) | $771.010m gross and $638.010m net incurred loss | $771,010 and $638,010. It cited the heading `($000’s)` as evidence of currency, then interpreted the amounts as single dollars. |
| Reserve | [Converium 20-F](https://www.sec.gov/Archives/edgar/data/1162586/000115697306000763/u50380e20vf.htm) | $44.6m net incurred property losses | No table record. The preceding paragraph defines the measure. A separate prose output assigned the $15.6m Run-Off loss from three hurricanes to Katrina alone. |
| Reserve | [Philadelphia Consolidated 10-K](https://www.sec.gov/Archives/edgar/data/909109/000089322006000532/w18434e10vk.htm) | $2.0m personal lines and $5.7m commercial lines, totalling $7.7m in net loss and adjustment expense estimates | No record anywhere in the filing. The event headings give two landfall dates using two-digit years; the reader could not establish the required period for these cells. |

The original screen covered nine insurer families, 41 annual filings, one prospectus and six incorporated annual-report exhibits. Only PXRE had an eligible table. A reserve order was registered when the original screen proved sparse, before the reserve documents were examined or any test predictions were generated. The first three reserve families contributed two eligible tables from five filings. The eight original families and the one reserve family with no eligible table remain in the screening records. Two source readings agreed on all six cells before the comparison. [Original screen](main-screen.json) · [Reserve screen](reserve-screen.json) · [Original reserve ledger](reserve-ledger.json) · [Independent source reading](independent-reference.json)

All six reference amounts are positive and come from FY2005 Katrina tables. Negative-sign performance on new insurers remains unmeasured. Outside the selected tables the readers produced eight records: three distinct source-supported prose assertions, one repeat and four erroneous allocations of multi-storm figures. The table reference cannot measure recall across whole filings. [Detailed findings](findings.md)

The public history preserves the sequence of the [method freeze](https://github.com/timofey-petrov-spb/weather-disclosures/commit/b73ed79320adc5986bfa4a00dfeea38d858b3d9f), the [reserve selection rule](https://github.com/timofey-petrov-spb/weather-disclosures/commit/2fcf475f70535231f6c36073297e9404f45efdcb) and the [source reference](https://github.com/timofey-petrov-spb/weather-disclosures/commit/72a28a5cf1fed0c947f47701d3bb79b1feb95d66).

## Reproduce the comparison

From a checkout of this repository, use Python 3.10 or later with the standard library.

```sh
python insurer-transfer/event-accounting/replay_study.py --output event-accounting-replay
python insurer-transfer/event-accounting/verify_scores.py event-accounting-replay
python insurer-transfer/event-accounting/controls.py --primary-files event-accounting-replay/primary --output control-results.json
```

The first command verifies the original HTML, source passages, frozen code and complete outputs of both versions. Use `--filing DOC_ID` to replay one filing or `--primary-files DIRECTORY` for a cache of original documents. The second command checks the row-level judgments against both replayed outputs and recalculates the published scores. The final command reruns the development controls on disposable copies. [Filing roster and output digests](filings.json) · [Frozen reader](../v9/extract.py) · [Selection](selection.json) · [Scoring definitions](scoring-protocol.json)
