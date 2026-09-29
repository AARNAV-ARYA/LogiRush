"""Evaluate the disaster prediction models and write data/processed/model_evaluation.json.

    python evaluate_models.py                 # synthetic holdout + CV + out-of-range report
    python evaluate_models.py --events f.csv  # score the deployed model on REAL labelled events

See src/modeling/model_evaluation.py for exactly what each number does and does not mean.
"""

import argparse
import json

from src.modeling.model_evaluation import EVALUATION_PATH, evaluate_on_events, load_or_evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", help="CSV of real labelled corridor-days to score the model on")
    args = parser.parse_args()

    if args.events:
        report = evaluate_on_events(args.events)
        print(json.dumps({k: v for k, v in report.items() if k != "targets"}, indent=2))
        for target, metrics in report["targets"].items():
            print(f"{target}: AUC {metrics['roc_auc']}  Brier {metrics['brier']} "
                  f"(no-skill {metrics['brier_no_skill']})  recall {metrics['recall']}")
        return

    report = load_or_evaluate(refresh=True)
    print(f"Wrote {EVALUATION_PATH}\n")
    for line in report["interpretation"]:
        print("-", line)


if __name__ == "__main__":
    main()
