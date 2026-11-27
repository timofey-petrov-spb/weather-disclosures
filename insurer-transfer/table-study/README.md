# Reading hurricane losses from insurance filings

Travelers reports **$227 million twice** on the Hurricane Ian line of its 2022 annual filing. One column gives losses incurred during the year. The other gives the estimate of ultimate losses at year-end. A search for unique numbers would discard a real disclosure. RenaissanceRe uses the opposite layout. Ian heads a column, and each row has a different accounting meaning. [Travelers 10-K](https://www.sec.gov/Archives/edgar/data/86312/000008631223000011/trv-20221231.htm) · [RenaissanceRe 10-K](https://www.sec.gov/Archives/edgar/data/913144/000091314423000011/rnr-20221231.htm)

## Development result

| Original Ian references | Signed table figures recovered with the right source cell | Example |
|---|---:|---|
| Travelers, Q3 and FY 2022 | 4/4 | The $326m quarterly incurred and ultimate estimates have separate column headings. A repeat of the same incurred amount in the year-to-date column is counted once. |
| RenaissanceRe, Q3 and FY 2022 | 18/18 | In the annual filing, assumed reinstatement premiums contributed +$221.801m and ceded reinstatement premiums contributed −$57.913m. The two amounts sit in different rows of the Ian column, printed in thousands. |

Across all four insurers in the previous 39-reference panel, the change raised exact event/amount coverage from **2/39 to 24/39**. Travelers and RenaissanceRe were used to develop the table reader. The other fifteen references are still missing. The method also retains the earlier false positive at Progressive, a $2.1bn limit for a possible second event. Of 25 automatic records on the development panel, 24 link to a distinct reference amount. This count does not certify every accounting field of those records. [Independent filing-cell check](development-cells.json) · [One-to-one development matches](development-score.json) · [Previous panel and its reference](../panel/README.md)

The reader uses the original HTML grid. It resolves headers across merged cells, records the named storm and reporting window, and preserves both the displayed signed value and its USD magnitude. Each table record exposes the coordinates of the amount, event, measure and unit heading. In a loss column a positive reported cost stays positive. In a signed bridge to earnings, a parenthesized entry stays negative. [Method](../v7/extract.py) · [Table geometry](../v7/tables.py)

Five controlled edits checked whether the reader followed the table when the answer changed. Moving the Ian header to a neighbouring column produced seven different amounts. Changing thousands to millions rescaled the figures. Changing the Travelers ultimate estimate to $417m left incurred losses at $326m. All five changes met their expected results when the original currency context was supplied. Two earlier Travelers runs, on cropped tables without the dollar context, returned nothing. These are sensitivity checks on development documents. [Expected and observed outputs, including the failed crops](development-perturbations.json) · [Replay script](development_perturbations.py)

## First prospective check on four new insurers

The two versions were run against the same eight primary filings, a third-quarter 10-Q and an annual 10-K per insurer. Source references were sealed before either run. The selection, scoring rules, method and reference fingerprints are preserved in the [pre-run commit](https://github.com/timofey-petrov-spb/weather-disclosures/commit/779d53deeb816e1bd14d18f65267cef6568f4e8b).

| New insurer | Ian-specific monetary references | v6 amount + event | v7 amount + event | v7 complete records |
|---|---:|---:|---:|---:|
| Arch Capital | 0 | 0 | 0 | 0 |
| AXIS Capital | 0 | 0 | 0 | 0 |
| Everest Re | 6 | 0 | 0 | 0 |
| Hanover | 1 | 1 | 1 | 0 |

Both versions returned one automatic record, correctly linking **$28m** to Ian at Hanover. The structured output omitted the pre-tax basis and nine-month window. Everest reported $700m at group level for the quarter, including $600m in Reinsurance and $100m in Insurance. The annual filing gives $699m, $599m and $99m respectively. The HTML splits the text of these disclosures across blocks. Neither version recovered them. The three amounts in each filing refer to different levels of the company and must not be added together. [References and source links for Everest](reference-everest.json) · [Hanover](reference-hanover.json)

The primary result is **1/7 for amount and sign, 0/7 for complete records**. The single automatic output was supported. The eight forms produced no duplicate, unsupported or review-only outputs. All seven reference amounts are in prose, so there is no denominator for table recall in this sample. Arch and AXIS are retained as zero-reference cases. [Per-filing scores](score.json) · [Arch source decisions](reference-arch.json) · [AXIS source decisions](reference-axis.json)

## A separate test on two new insurers with event tables

The selection rule was registered before screening for eligible tables or running predictions. Eighteen original filings from ten other insurers were assessed in the registered order. Cincinnati Financial and Palomar each qualified in their third-quarter 10-Q. Both frozen versions missed **all five table amounts**. Neither produced a record from the two selected tables, so precision for this slice is undefined. All five reference cells were positive. The test gives no new-issuer evidence about negative cells. [Selection rule](supplement-selection.json) · [Screening ledger](supplemental-screen.json) · [Five source references](supplemental-reference.json) · [Scope and scores](supplemental-score.json)

| Issuer | Amounts reported | What prevented extraction |
|---|---|---|
| Cincinnati Financial | Commercial $26m, personal $51m, other $143m, total $220m | The row says “South (Ian)”. The column headers name businesses. The accounting measure is in the title above the table. The quarter and year-to-date columns repeat these amounts. |
| Palomar | $12.5m quarterly catastrophe losses (printed as 12,500 in USD thousands) | The paragraph immediately **below** the grid attributes the 2022 quarterly catastrophe losses to Ian. The reader looked in or before the table. The neighbouring 2021 loss and year-over-year change measure something else. |

Outside that second table, both versions also mislabeled $1.3m in reinsurance expenses as claims losses. This finding is reported separately from the five selected table cells. The next experiment would test whether a table title can identify the measure while the body identifies the business, and whether a following note uniquely attributes a value to one event and reporting period. Both changes would need another set of unseen issuers. [Cincinnati 10-Q, p. 39](https://www.sec.gov/Archives/edgar/data/20286/000002028622000066/cinf-20220930.htm) · [Palomar 10-Q, p. 29](https://www.sec.gov/Archives/edgar/data/1761312/000155837022016296/plmr-20220930x10q.htm)

## Reproduce the study

From a checkout of this repository, Python 3.10 or later and the standard library are sufficient.

```sh
python insurer-transfer/table-study/run_study.py --output table-replay
python insurer-transfer/table-study/run_supplement.py --output supplemental-replay
```

The first command reconstructs the original SEC passages for the eight primary test filings and eight previous-panel development filings. It verifies the archived primary HTML and complete output digests for both versions. Use `--case travelers` to inspect one issuer. The second command verifies each additional selected filing and supports `--filing DOC_ID`. Both commands accept an offline `--primary-files DIRECTORY` containing HTML files named by document ID. The extraction files provide the model outputs, and the source ledgers explain which records received credit. [Filing roster](filings.json) · [Output fingerprints](output-digests.json) · [Scoring rules](scoring-protocol.json) · [Primary reference freeze](reference-lock.json)
