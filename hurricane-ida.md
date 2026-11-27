# Hurricane Ida in nine SEC filings

Entergy first put the cost of restoring its electrical network at **$2.1–2.6 billion**. It repeated that estimate in a slide deck. In November it revised the range to **$2.1–2.5 billion**. A text search located the initial estimate and the revision but missed the intervening disclosure. The deck was published as images. [Initial filing](https://www.sec.gov/Archives/edgar/data/65984/000006598421000267/etr-20210921.htm) · [Investor slide 24](https://www.sec.gov/Archives/edgar/data/65984/000006598421000277/slide24.jpg) · [Quarterly filing](https://www.sec.gov/Archives/edgar/data/65984/000006598421000291/etr-20210930.htm)

## What the test covered

The National Hurricane Center reported Ida’s Louisiana landfall on August 29, 2021. Two new issuers, Entergy and H&E Equipment Services, were selected before their reports were read. The sample used forms 8-K, 10-Q, 10-K and amendments in two windows spanning days 0–60 and 61–120. All nine eligible submissions fell within the pre-set cap. The primary filing and every attached EX-99 exhibit were reviewed, including the image-only presentation. SEC acceptance time was used to reconstruct availability. [Weather bulletin](https://www.nhc.noaa.gov/archive/2021/al09/al092021.update.08291653.shtml?lang=en) · [Entergy filing history](https://data.sec.gov/submissions/CIK0000065984.json) · [H&E filing history](https://data.sec.gov/submissions/CIK0001339605.json)

The search, amount rules and local text extractor from the original pilot were fixed before evaluation. Only event-specific configuration was changed to Ida. Search retained up to three windows per event and document. The extractor used the target paragraph and its immediate neighbours. A separate source review established the reference without seeing the predictions. The reference has not undergone independent human double annotation. This is an archival study of two issuers.

## Results

| Stage | Observed on this sample |
| --- | --- |
| Source coverage | 9 submissions, 15 primary filings and exhibits. Of these, 14 yielded searchable text and one contained 31 slide images. |
| Search | 7,901 searchable passages narrowed to 32. Four submissions disclosed an Ida impact. Search surfaced supporting passages from three and returned no passages from the five H&E submissions. |
| Fixed extraction rules | Zero source-linked monetary records. |
| Local text extractor | 15 dollar-bearing passages yielded 23 proposals. Eight passed the literal evidence check. All eight were labelled booked. |
| Audited ranges | The source contained 15 records of restoration costs or lost non-fuel revenue, counted once per filing, entity and measure. Seven were present in the selected passages. After the literal check the extracted amounts matched three distinct source ranges; none was fully correct on entity, financial meaning, status and period. |

The fifteen range records comprise six in Entergy’s first filing, the same six in a second filing, and three restoration ranges in the quarterly filing. Counts retain repeat publications across dates because the test asks which disclosures a reader could find. They cannot be added as economic losses. The wider reference separately records accounting balances, financing and a shareholder commitment.

## What each filing contributed

Dates below are UTC acceptance dates. The last column counts paragraphs queued for review, including adjacent context.

| Accepted | Issuer and source | Finding in the filing | Queued |
| --- | --- | --- | ---: |
| Sep 21 | [Entergy 8-K](https://www.sec.gov/Archives/edgar/data/65984/000006598421000267/etr-20210921.htm) | Preliminary restoration and lost non-fuel revenue estimates for the group, Louisiana and New Orleans. | 17 |
| Sep 28 | [Entergy 8-K exhibit](https://www.sec.gov/Archives/edgar/data/65984/000006598421000277/a06120991a.htm) | Slide 24 repeats six ranges and reports that over 99% of customers able to receive power had service restored. SEC accepted the filing on Sep 28 at 22:38:48 UTC. Its official filing date is Sep 29. | 0 |
| Oct 1 | [H&E 8-K](https://www.sec.gov/Archives/edgar/data/1339605/000156459021049843/hees-8k_20211001.htm) | The $130m crane-business sale was agreed in July. The filing and exhibit disclose no Ida effect. | 0 |
| Nov 2 | [H&E 8-K exhibit](https://www.sec.gov/Archives/edgar/data/1339605/000156459021053300/hees-ex991_31.htm) | The earnings release discusses demand for equipment. No Ida effect was identified. | 0 |
| Nov 2 | [H&E 10-Q](https://www.sec.gov/Archives/edgar/data/1339605/000156459021053558/hees-10q_20210930.htm) | The weather-related closures affecting about 40% of locations occurred in February, months before Ida. | 0 |
| Nov 3 | [Entergy 8-K exhibit](https://www.sec.gov/Archives/edgar/data/65984/000006598421000289/a06521991.htm) | Ida affected retail sales volume. The release gives no separate dollar estimate for Ida. | 6 |
| Nov 5 | [Entergy 10-Q](https://www.sec.gov/Archives/edgar/data/65984/000006598421000291/etr-20210930.htm) | The upper bounds fell for Entergy and Entergy Louisiana. The New Orleans range remained $120–150m. | 9 |
| Nov 10 | [H&E dividend exhibit](https://www.sec.gov/Archives/edgar/data/1339605/000156459021056185/hees-ex991_10.htm) | Regular quarterly dividend of $0.275 per share. | 0 |
| Nov 18 | [H&E 8-K](https://www.sec.gov/Archives/edgar/data/1339605/000156459021057548/hees-8k_20211118.htm) | Points to a presentation on the issuer’s website. No EX-99 accompanied the filing. The external presentation was outside the study. | 0 |

In days 0–60, search found one of two relevant submissions and the filtered extractor matched two distinct source ranges by value. In days 61–120, it found both relevant submissions and matched one range by value. Across H&E’s five submissions, absence of an explicit disclosure leaves the company’s actual economic exposure unknown.

## Why the eight accepted records still needed review

Five proposals copied genuine restoration ranges. Two repeated a range already returned from the same filing. The original reports identified the $120–150m range as Entergy New Orleans’ estimate, but the extracted description named both Louisiana subsidiaries. Preliminary and revised cost estimates were marked as booked. The six lost-revenue ranges across the two September filings yielded no accepted revenue record. [September report](https://www.sec.gov/Archives/edgar/data/65984/000006598421000267/etr-20210921.htm) · [November report](https://www.sec.gov/Archives/edgar/data/65984/000006598421000291/etr-20210930.htm)

The other three proposals illustrate different errors. The $9.5bn represented five years of infrastructure investment. The $72m was a balance held in storm escrows. Neither figure quantified Ida’s impact. The $1.25m did concern the storm, but it was a shareholder commitment for community support. The extractor classified it as booked claims losses. The original target or its neighbours contained both a storm name and a dollar amount in all three cases. [Entergy’s September release](https://www.sec.gov/Archives/edgar/data/65984/000006598421000267/a05821release.htm)

## Following up on the missing slide

A subsequent English OCR pass read all 31 images. It found Ida on slides 3, 24 and 27. Only slide 24 contained candidate dollar ranges under the rule requiring two dollar-prefixed values on one line. Five of the six ranges preserved both endpoints and the million or billion units. For Louisiana restoration costs, the printed **$2.0B–$2.4B** became **$2.08–$2.48**; both units disappeared. The unit check left that range for review. The company and measure were checked against the slide headings. This was a diagnostic on a known miss, after evaluation. The figures in the results table are for the original text-only run. [Original slide](https://www.sec.gov/Archives/edgar/data/65984/000006598421000277/slide24.jpg)
