"""Regression tests for the offline extraction evaluator."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.extraction_eval import (
    EvaluationInputError,
    evaluate,
    load_json,
    normalize_name,
    validate_ground_truth,
    write_report,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "evaluation" / "examples"


class ExtractionEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ground_truth = load_json(EXAMPLES / "ground-truth.synthetic.json")
        cls.predictions = load_json(EXAMPLES / "predictions-v6.synthetic.json")
        cls.mapping = load_json(EXAMPLES / "manual-mapping.synthetic.json")

    def test_synthetic_metrics_cover_required_error_types(self) -> None:
        report = evaluate(
            self.ground_truth,
            self.predictions,
            sample_id="synthetic-street-001",
            manual_mapping_data=self.mapping,
        )
        metrics = report["metrics"]

        self.assertEqual(
            metrics["store_detection_precision"],
            {"value": 0.6, "numerator": 3, "denominator": 5},
        )
        self.assertEqual(
            metrics["store_detection_recall"],
            {"value": 0.75, "numerator": 3, "denominator": 4},
        )
        self.assertEqual(
            metrics["store_detection_f1"],
            {"value": 0.666667, "numerator": 6, "denominator": 9},
        )
        self.assertEqual(metrics["exact_name_accuracy"]["numerator"], 2)
        self.assertEqual(metrics["exact_name_accuracy"]["denominator"], 3)
        self.assertEqual(
            metrics["normalized_fuzzy_name_accuracy"],
            {"value": 1.0, "numerator": 3, "denominator": 3},
        )
        self.assertEqual(
            metrics["phone_coverage_all_businesses"],
            {"value": 0.5, "numerator": 2, "denominator": 4},
        )
        self.assertEqual(
            metrics["phone_exact_precision"],
            {"value": 0.5, "numerator": 2, "denominator": 4},
        )
        self.assertEqual(
            metrics["phone_exact_recall_visible"],
            {"value": 0.5, "numerator": 1, "denominator": 2},
        )
        self.assertEqual(
            metrics["duplicate_rate"],
            {"value": 0.2, "numerator": 1, "denominator": 5},
        )
        self.assertEqual(
            metrics["auto_passed_accuracy"],
            {"value": 0.25, "numerator": 1, "denominator": 4},
        )
        self.assertEqual(
            report["false_positive_counts"],
            {"duplicate": 1, "unmatched": 0, "non_business_advertisement": 1},
        )
        self.assertEqual(
            [item["entity_id"] for item in report["errors"]["false_negatives"]],
            ["store-004"],
        )
        self.assertEqual(len(report["errors"]["name_errors"]), 1)
        self.assertEqual(len(report["errors"]["phone_errors"]), 2)

    def test_not_visible_phone_with_value_is_rejected_with_context(self) -> None:
        invalid = copy.deepcopy(self.ground_truth)
        entity = invalid["samples"][0]["entities"][1]
        entity["phone"]["values"] = ["0501234999"]

        with self.assertRaises(EvaluationInputError) as context:
            validate_ground_truth(invalid)

        message = str(context.exception)
        self.assertIn("sample/synthetic-street-001/entity/store-002", message)
        self.assertIn("not_visible phone must have empty values", message)

    def test_arabic_normalization_keeps_exact_and_fuzzy_separate(self) -> None:
        self.assertEqual(normalize_name("مؤسسة الرؤية"), normalize_name("مؤسسة الرؤية"))
        predictions = [{"name_ar": "مغسلة الصفا التجريبية", "phone": ""}]
        report = evaluate(
            self.ground_truth,
            predictions,
            sample_id="synthetic-street-001",
        )
        detail = report["predictions"][0]
        self.assertEqual(detail["entity_id"], "store-002")
        self.assertFalse(detail["name_exact"])
        self.assertGreaterEqual(detail["name_similarity"], 0.85)

    def test_v3_list_and_ui_wrapper_are_both_supported(self) -> None:
        v3_report = evaluate(
            self.ground_truth,
            [{"name_ar": "متجر النور التجريبي", "phone": "0501234001"}],
            sample_id="synthetic-street-001",
        )
        wrapped_report = evaluate(
            self.ground_truth,
            {"stores": [{"name": "متجر النور التجريبي", "phone": "0501234001"}]},
            sample_id="synthetic-street-001",
        )
        self.assertEqual(v3_report["metrics"], wrapped_report["metrics"])

    def test_excluded_and_auto_rejected_predictions_are_not_surfaced(self) -> None:
        predictions = [
            {"name_ar": "متجر النور التجريبي", "excluded_from_results": True},
            {
                "name_ar": "مغسلة الصفاء التجريبية",
                "auto_review": {"decision": "auto_rejected"},
            },
            {"name_ar": "تموينات المثال"},
        ]
        report = evaluate(
            self.ground_truth,
            predictions,
            sample_id="synthetic-street-001",
        )
        self.assertEqual(report["coverage"]["source_predictions"], 3)
        self.assertEqual(report["coverage"]["surfaced_predictions"], 1)
        self.assertEqual(report["coverage"]["excluded_predictions"], 1)
        self.assertEqual(report["coverage"]["auto_rejected_predictions"], 1)
        self.assertEqual(report["predictions"][0]["prediction_id"], "prediction-0003")

    def test_reports_are_deterministic(self) -> None:
        report = evaluate(
            self.ground_truth,
            self.predictions,
            sample_id="synthetic-street-001",
            manual_mapping_data=self.mapping,
        )
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_json, first_markdown = write_report(report, first_dir)
            second_json, second_markdown = write_report(report, second_dir)
            self.assertEqual(first_json.read_bytes(), second_json.read_bytes())
            self.assertEqual(first_markdown.read_bytes(), second_markdown.read_bytes())
            markdown = first_markdown.read_text(encoding="utf-8")
            self.assertIn("prediction-0004", markdown)
            self.assertIn("store-004", markdown)

    def test_malformed_prediction_is_rejected(self) -> None:
        with self.assertRaises(EvaluationInputError) as context:
            evaluate(
                self.ground_truth,
                ["not-an-object"],
                sample_id="synthetic-street-001",
            )
        self.assertIn("prediction-0001", str(context.exception))


if __name__ == "__main__":
    unittest.main()
