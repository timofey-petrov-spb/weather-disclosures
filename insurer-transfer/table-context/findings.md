# Eight table facts at three previously unseen insurers

Neither frozen reader produced a monetary record from the selected tables. The outputs of v9 and v10 were byte-identical in each of the three full annual reports. Each reader recovered **0/8** exact USD amount-and-event pairs, **0/8** matching economic assertions, **0/8** signed assertions and **0/8** complete table records. None of the eight appeared in a review queue. Selected-table precision is undefined because there were zero automatic table proposals. All eight reference amounts are positive, so transfer to negative cells remains unmeasured. [Scores](score.json) · [Every output and its disposition](judgments.json)

| Source | What the annual report disclosed | Table results, v9 and v10 |
|---|---|---|
| [21st Century Holding Company, FY2005](https://www.sec.gov/Archives/edgar/data/1069996/000114420406012513/v039025_10k.htm) | Katrina, 25 August. Estimated losses of $14.6m gross, $11.6m recoverable from reinsurance and $3.0m net. The headings run across two rows. The claim count of 2,076 is a separate field. | 0/3 |
| [Maiden Holdings, FY2012](https://www.sec.gov/Archives/edgar/data/1412100/000141210013000009/mhld-20121231x10k.htm) | The paragraph immediately before table 123 identifies Sandy. The table splits $31.1m of incurred losses into $6.5m for Maiden US, $22.6m for Maiden Specialty and $2.0m for the ACAC quota share. | 0/4. The $31.1m prose result corroborates the exact total. |
| [Safety Insurance Group, FY2012](https://www.sec.gov/Archives/edgar/data/1172052/000104746913002988/a2213726z10-k.htm) | The issuer explicitly attributes $7.977m of fourth-quarter losses to Sandy. In table 21 this is the full FY2012 hurricane/tropical-storm row. The MD&A specifies thousands of dollars. The footnote includes defense and cost containment and excludes adjusting and other claims settlement. The $7.025m in the adjacent column belongs to 2011. | 0/1 |

The original SEC sampling frame filled all three slots. Two separate source readings agreed on the reporting company or segment, financial meaning, year, sign, dollar scale and location of each cell before either reader was run. The ground truth covers these tabulated facts conditional on an eligible table. It does not measure the fraction of all information recovered from an entire report. [Independent source reading](independent-reference.json)

## Findings outside the selected tables

Each reader produced exactly three automatic outputs, all from Maiden prose, and none elsewhere in the other two reports. Two of the figures have direct support.

- The paragraph introducing table 123 gives $31.1m as the consolidated amount of Sandy losses incurred during FY2012. Each reader cited only that paragraph, with no table cell, header or segment assignment. It therefore counts as independent prose corroboration of the total under the registered scoring rule.
- A separate December 31 balance-sheet disclosure attributes $79.7m in estimated recoverables on unpaid claims to Sandy. The amount is a group receivable. The text says almost all the underlying business was written by Maiden Specialty.
- The company initially forecast a net underwriting impact of $25m to $35m. Each output stored a $25m point estimate even though its quoted evidence contained both bounds.

The clearest transfer failure involves the location of the storm name. Maiden names Sandy in the introducing paragraph, while Safety ties Sandy to the amount in its preceding discussion and names only the class of storm in its table. The revised reader can retrieve a financial label from a preceding paragraph, but its candidate-table rule still first requires the named storm to occur in a table cell. Resolving a metric from prose and resolving an event from prose are different operations.

