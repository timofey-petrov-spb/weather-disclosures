# Hurricane losses in insurer filings

PXRE printed **771,010** in the Katrina row. The heading `($000’s)` puts the amount in thousands, making it a **$771.010 million gross loss**. The same row reports $638.010 million after outward reinsurance recoveries. A paragraph elsewhere in the filing independently puts the gross loss at $771.0 million, rounded. The earlier reader found both columns but treated their contents as single dollars. [PXRE 2005 Form 10-K](https://www.sec.gov/Archives/edgar/data/1091748/000112528206001680/b412207_10k.htm)

## Development and source checks

| Insurer | Source evidence | Previous / revised |
|---|---|---|
| PXRE | A shorthand unit applies to the gross and net columns. The adjoining footnote explains the treatment of outward reinsurance. | 0/2 → 2/2 |
| [Converium](https://www.sec.gov/Archives/edgar/data/1162586/000115697306000763/u50380e20vf.htm) | The paragraph above the table defines net incurred property losses. The Katrina row gives $44.6m. The $15.6m Run-Off loss in the footnote and separate prose relates to three storms. | 0/1 → 1/1 |
| [Philadelphia Consolidated](https://www.sec.gov/Archives/edgar/data/909109/000089322006000532/w18434e10vk.htm) | One heading gives two Katrina occurrences, 8/25/05 and 8/29/05. Personal lines report $2.0m and commercial lines $5.7m, totalling $7.7m in net loss and loss adjustment expense estimates. | 0/3 → 3/3 |

The six development targets were the test cases in the [previous round](../event-accounting/README.md). On these tables the revised method matched the source cell, USD value, scale, accounting measure and owner for 6/6. Philadelphia's records retain both dates in ISO format. Converium no longer returns the shared Run-Off loss as a single-storm loss. Thirteen earlier regression inputs produced byte-identical outputs to the prior reader. [Development results and source coordinates](development.json) · [Frozen implementation and regression fingerprints](../v10/lock.json)

Six controlled source edits checked whether the same rules responded to changes in evidence. In all six, the amounts and coordinates agreed with the expected result, including an empty result when a cell was changed to describe two storms. Two of six also matched the **literal** gross/net label used by the registered check. In three cases the reader returned a more specific net-of-reinsurance label. When the PXRE heading was changed to plain dollars, it returned a generic net result and lost the explicit reinsurance qualifier. These controls are edited copies of known documents. [Planned edits](control-cases.json) · [Observed outputs](control-results.json) · [Comparison of amounts and wording](control-interpretation.json)

## Test on three new insurers

The frozen readers each recovered **0/8 exact financial assertions** from the three selected tables. They produced no automatic table records or review flags. Table precision is undefined because there were no predictions. Source retrieval had a different outcome. With a budget of three tables per filing, the separate search **ranked the target first for 2/3 companies**. For each of those companies it proposed three tables. It offered none for the third. No human accuracy or review-time estimate was measured. [Every extraction decision](judgments.json) · [Retrieval ranks and candidate sizes](review-results.json) · [Scores by company](score.json)

| Insurer and storm | Figures verified against the original table | Automated table matches | Rank for human review |
|---|---|---:|---:|
| [21st Century Holding, Katrina, 2005](https://www.sec.gov/Archives/edgar/data/1069996/000114420406012513/v039025_10k.htm) | $14.6m gross losses, $11.6m recoveries, $3.0m net losses | 0/3 | 1 of 3 |
| [Maiden Holdings, Sandy, 2012](https://www.sec.gov/Archives/edgar/data/1412100/000141210013000009/mhld-20121231x10k.htm) | $6.5m Maiden US, $22.6m Maiden Specialty, $2.0m ACAC, $31.1m consolidated | 0/4 | 1 of 3 |
| [Safety Insurance Group, Sandy, 2012](https://www.sec.gov/Archives/edgar/data/1172052/000104746913002988/a2213726z10-k.htm) | $7.977m incurred losses, tied to Sandy through the preceding quarterly disclosure and the 2012 column | 0/1 | No suggestion |

At 21st Century, the row gives the storm with a date in parentheses and the header identifies the hurricane season. At Converium in development, the paragraph supplied the measure and the row named the storm. Maiden reverses those roles. The text names Sandy and the table supplies losses by business. At Safety, the link crosses two intervening passages, and the reporting section supplies the unit. The past and current years also share the same storm-category row.

Both readers returned three additional prose records, all from Maiden. The $31.1m group loss was supported by text elsewhere in the filing, as was a distinct $79.7m estimated reinsurance recoverable. The other prediction converted an initial $25m–$35m range into a $25m point estimate. The $31.1m prose disclosure does not supply a source cell for the four-column table. [Source judgments and accounting distinctions](findings.md)

The registered selection considered ten of twelve issuer families. Nine contributed documents, and one was excluded under the family-overlap rule. The screen examined 19 Forms 10-K, one Form 20-F and three IPO prospectuses. All three qualifying tables were found in the original annual-report group. The quarterly and international contingency samples contributed zero test filings. Eight positive monetary assertions across Katrina and Sandy cannot establish accuracy for other insurers or for negative values. [Screen and exclusion reasons](screen.json) · [Two source readings](reference.json) · [Independent reference](independent-reference.json)

The public history records the [selection rules](https://github.com/timofey-petrov-spb/weather-disclosures/commit/3ebe6219afe37c8e6e098dbf83024f1b4505a743), [review-table ranking and controls](https://github.com/timofey-petrov-spb/weather-disclosures/commit/2e37ec390488e6688d68fbf199710bf7a60db59f), [method freeze](https://github.com/timofey-petrov-spb/weather-disclosures/commit/263e8521c9a82771d26d08d28a6d9e89b14c22b2) and [source reference](https://github.com/timofey-petrov-spb/weather-disclosures/commit/eceeb823b6b3703de555440451d39691ebdeb1ab).

## Reproduce the results

Use Python 3.10 or later. The extraction and score checks use the standard library. From the repository root:

```sh
python insurer-transfer/table-context/replay_study.py --output table-context-replay
python insurer-transfer/table-context/verify_scores.py table-context-replay
python insurer-transfer/table-context/check_development.py table-context-replay --primary-files table-context-replay/primary --output development-replay.json
python insurer-transfer/table-context/controls.py --primary-files table-context-replay/primary --output control-replay.json
python insurer-transfer/table-context/score_review.py table-context-replay --primary-files table-context-replay/primary --output review-replay.json
```

The replay rebuilds the source passages and runs both frozen readers against the full HTML filing for each registered case, then checks the output fingerprints. The review task ranks up to three tables per filing. It does not assign a loss or automate verification of any amount. [Filing roster](filings.json) · [Extraction scoring rules](scoring-protocol.json) · [Review task rules](review-protocol.json)
