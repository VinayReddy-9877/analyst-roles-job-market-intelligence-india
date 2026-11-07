"""Score the manually reviewed role-taxonomy sample."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = ROOT / "reports" / "taxonomy_manual_validation.csv"
SUMMARY_FILE = ROOT / "reports" / "taxonomy_validation_summary.txt"
DISAGREEMENT_FILE = ROOT / "reports" / "taxonomy_validation_disagreements.csv"


def parse_label(value: object) -> bool | None:
    label = str(value).strip().lower()
    if label in {"1", "true", "yes", "in", "include", "in scope"}:
        return True
    if label in {"0", "false", "no", "out", "exclude", "out of scope"}:
        return False
    return None


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "Copy taxonomy_validation_sample.csv to taxonomy_manual_validation.csv, "
            "then complete manual_in_scope before scoring."
        )

    review = pd.read_csv(INPUT_FILE)
    required = {"model_in_scope", "manual_in_scope"}
    missing = sorted(required - set(review.columns))
    if missing:
        raise ValueError(f"Validation file is missing columns: {', '.join(missing)}")

    review["model_label"] = review["model_in_scope"].map(parse_label)
    review["manual_label"] = review["manual_in_scope"].map(parse_label)
    if review["model_label"].isna().any():
        raise ValueError("model_in_scope contains an unrecognized value.")
    unlabeled = int(review["manual_label"].isna().sum())
    if unlabeled:
        raise ValueError(
            f"Complete all manual labels before scoring ({unlabeled} blank)."
        )

    predicted = review["model_label"].astype(bool)
    actual = review["manual_label"].astype(bool)
    true_positive = int((predicted & actual).sum())
    false_positive = int((predicted & ~actual).sum())
    true_negative = int((~predicted & ~actual).sum())
    false_negative = int((~predicted & actual).sum())

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    accuracy = (true_positive + true_negative) / len(review)

    lines = [
        "ROLE TAXONOMY MANUAL VALIDATION",
        "=" * 40,
        f"Reviewed rows: {len(review)}",
        f"True positives: {true_positive}",
        f"False positives: {false_positive}",
        f"True negatives: {true_negative}",
        f"False negatives: {false_negative}",
        f"Precision: {precision:.3f}",
        f"Recall: {recall:.3f}",
        f"Accuracy: {accuracy:.3f}",
    ]
    SUMMARY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    disagreements = review.loc[predicted.ne(actual)].drop(
        columns=["model_label", "manual_label"]
    )
    disagreements.to_csv(DISAGREEMENT_FILE, index=False)

    print("\n".join(lines))
    print(f"Disagreements: {DISAGREEMENT_FILE}")


if __name__ == "__main__":
    main()
