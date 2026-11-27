# Linking a hurricane to the right table amount

Cincinnati Financial's quarterly report puts “South (Ian)” in a geography row. The table title supplies the financial measure, and the columns name the businesses. Palomar prints an amount in its table and identifies the hurricane in the next paragraph. These were the five missed values in the [previous transfer test](../table-study/README.md).

## What changed on the two development filings

| Filing | What the original source says | What must be kept separate |
|---|---|---|
| Cincinnati Financial, Q3 2022 | Incurred catastrophe losses and loss expenses, net of reinsurance, were $26m in Commercial lines, $51m in Personal lines and $143m in Other. The consolidated property and casualty insurance total was $220m. | The quarter and year-to-date column groups repeat the same four amounts. The E&S entries are dashes. The $220m total already includes the three businesses. |
| Palomar, Q3 2022 | Under “Catastrophe losses”, the 2022 column shows 12,500 in USD thousands. The following paragraph attributes the quarterly losses to Hurricane Ian. | The $17.487m comparison relates to 2021. The parenthesized $4.987m is the year-on-year decrease. The source says which business was most affected without assigning it the entire $12.5m. |

The previous version returned none of these five table facts. The revised reader links each recovered value to the reported amount, currency scale, accounting window, event evidence and the relevant title or row label. Cincinnati's repeated observations retain both source cells. A separate $1.3m amount at Palomar concerns acceleration and reinstatement expenses for reinsurance. [Cincinnati 10-Q, page 39](https://www.sec.gov/Archives/edgar/data/20286/000002028622000066/cinf-20220930.htm) · [Palomar 10-Q, page 29](https://www.sec.gov/Archives/edgar/data/1761312/000155837022016296/plmr-20220930x10q.htm) · [Verified development records](development.json)

An independent extraction of the original cells confirmed **5/5**. Six tests on modified copies checked whether the result changed when the evidence changed. Raising Cincinnati's Commercial figure from $26m to $39m and adjusting the total to $233m changed only the corresponding two records. When Palomar's note attributed the loss only partly to Ian, the reader withheld the $12.5m. A separate test exposed a conflict it does not resolve: a new “Claims Paid” heading above Cincinnati's table disagreed with the preceding sentence describing *incurred* losses, and the reader still accepted the latter. [Six controlled checks](probe-results.json) · [Counterexample and additional checks](additional-controls.json)

## Frozen test on three new insurers

The [public freeze](https://github.com/timofey-petrov-spb/weather-disclosures/commit/9c5dac6168cce18db47910b5ba2087c0232a22ea) records the executable rules, selection order, scoring policy and fingerprint of an independent source review. Two readings reconciled the figures before either model saw the test filings. The first qualifying annual table from each of the first three eligible insurers in the registered order concerned Hurricane Katrina in 2005. The models ran on the entire original SEC 10-K. Recall below applies to the selected table rather than every monetary mention in the filing. [Selection](selection.json) · [Tables screened](screen.json) · [Verified source cells, signs and qualifiers](reference.json)

| Selected new insurer | Reference facts | v7 correct event, amount and measure | v8 correct event, amount and measure | Exact number and event alone (both versions) |
|---|---:|---:|---:|---:|
| PartnerRe | 4 | 0 | 0 | 1 |
| XL Capital | 11 | 0 | 0 | 0 |
| Aspen | 1 | 0 | 0 | 0 |
| Total | 16 | 0 | 0 | 1 |

Both versions produced identical outputs on the three filings. The only automatic proposal in the selected tables pointed to PartnerRe's Katrina row and returned $54m. The column says **reinstatement or additional premiums earned**. The method labelled it a catastrophe loss. The same row actually reports **−$563m** of net losses and loss expenses, **−$2m** of acquisition costs and a **−$511m** impact on pre-tax net income. Giving credit for the number and event alone yields **1/16**. The registered measure, which requires the right financial assertion, gives **0/16**. The method captured **0/5** negative cells with the correct sign and measure. [PartnerRe 10-K](https://www.sec.gov/Archives/edgar/data/911421/000119312506043961/d10k.htm)

XL's Katrina figures sit within accounting sections under insurance, reinsurance, financial products and consolidated columns. The matched scope matters: a segment figure and a consolidated figure are separate disclosures. Aspen placed Katrina next to other years' events on the same physical row. Its $427.5m loss belongs to Property Reinsurance and is net of recoveries. [XL Capital 10-K](https://www.sec.gov/Archives/edgar/data/875159/000093041306001850/c41009_10k.htm) · [Aspen 10-K](https://www.sec.gov/Archives/edgar/data/1267395/000095013606001663/file001.htm)

Inspection of the frozen rules explains three specific failures. At PartnerRe the table reader recognized the four signed numbers but could not resolve the currency scale from a long sentence above the table. The older extraction rule then returned the single mislabeled figure. XL puts the measure in the preceding section row and the business in a column. Aspen prints its measure heading above a different year block from the Katrina cell. These layouts left the appropriate financial field unresolved. [Diagnostics for each table](error-analysis.json)

This test changed the insurers, storm, year and HTML layouts together. It establishes how the frozen rule performed on these three tables and cannot isolate the individual effect of year, issuer or storm. Seven automatic proposals and three review candidates fell outside the three selected tables. No full-filing recall is claimed for them. [Source-linked findings](findings.md) · [Scores](score.json) · [Row-by-row review](judgments.json)

## Reproduce the results

From a checkout of this repository, use Python 3.10 or later and its standard library.

```sh
python insurer-transfer/filing-tables/run_study.py --output filing-table-replay
python insurer-transfer/filing-tables/probe.py --primary-files filing-table-replay/primary --output probe-results.json
```

The first command verifies the frozen method, original filing bytes and source passages, then reproduces the complete outputs of both versions. It accepts `--filing DOC_ID` and an optional `--primary-files DIRECTORY` with cached originals named by document ID. The second command runs the six development controls on disposable copies of Cincinnati and Palomar. [Source roster and expected output digests](filings.json) · [Method](../v8/extract.py) · [Scoring rules](scoring-protocol.json)
