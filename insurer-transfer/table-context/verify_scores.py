"""Verify source review, every replayed prediction and the published score."""
import argparse
from pathlib import Path

from aggregate import aggregate, digest, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path, help="Output directory of replay_study.py")
    args = parser.parse_args()
    study = Path(__file__).resolve().parent
    reference = read(study / "independent-reference.json")
    judgments = read(study / "judgments.json")
    score = read(study / "score.json")
    if digest(study / "source-decisions.json") != judgments["source_decisions_sha256"]:
        raise ValueError("Source decisions differ from the sealed judgments")
    if digest(study / "judgments.json") != score["judgments_sha256"]:
        raise ValueError("Judgments differ from the published score")
    if digest(study / "independent-reference.json") != score["source_review_sha256"]:
        raise ValueError("Source readings differ")
    if digest(study / "scoring-protocol.json") != score["scoring_protocol_sha256"]:
        raise ValueError("Scoring protocol differs")
    for version, filings in judgments["predictions"].items():
        for doc_id, decision in filings.items():
            output = args.replay / doc_id / (version + ".json")
            if digest(output) != decision["full_output_sha256"]:
                raise ValueError(f"Output differs: {doc_id} {version}")
            predictions = read(output)
            rows = decision["rows"]
            if len(predictions) != len(rows):
                raise ValueError(f"Missing or extra judgments: {doc_id} {version}")
            for index, (prediction, row) in enumerate(zip(predictions, rows)):
                if row["index"] != index or row["measure_returned"] != prediction["measure"]:
                    raise ValueError(f"Measure or position differs: {doc_id} {version} {index}")
                for key in ("passage_id", "low_usd", "high_usd", "review"):
                    if row[key] != prediction[key]:
                        raise ValueError(f"{key} differs: {doc_id} {version} {index}")
    if aggregate(reference, judgments) != score["versions"]:
        raise ValueError("Recomputed scores differ from publication")
    print("Verified both readers, all source decisions and all published scores.")


if __name__ == "__main__":
    main()

