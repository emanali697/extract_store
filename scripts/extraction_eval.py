"""Deterministic, offline evaluation for Store Extractor pipeline results."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
DEFAULT_FUZZY_THRESHOLD = 0.85
AMBIGUITY_MARGIN = 0.05
BUSINESS_TYPES = {"store", "service_business"}
ENTITY_TYPES = BUSINESS_TYPES | {
    "institution", "advertisement", "vehicle", "road_sign", "other",
}
PHONE_VISIBILITIES = {"visible", "not_visible", "unreadable"}
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_NORMALIZATION = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي",
})


class EvaluationInputError(ValueError):
    """One or more evaluation input files violate the documented contract."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    source_index: int
    name: str
    phones: tuple[str, ...]
    frames: frozenset[int]
    auto_decision: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Assignment:
    entity_id: str | None
    reason: str
    score: float
    duplicate: bool = False


def load_json(path: str | Path) -> Any:
    file_path = Path(path)
    try:
        return json.loads(file_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise EvaluationInputError([f"File not found: {file_path}"]) from error
    except json.JSONDecodeError as error:
        raise EvaluationInputError([
            f"Malformed JSON in {file_path}: line {error.lineno}, column {error.colno}",
        ]) from error


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalize_phone(value: Any) -> str:
    return re.sub(r"\D", "", str(value or "").translate(ARABIC_DIGITS))


def extract_phones(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        chunks = value
    else:
        chunks = re.split(r"[,،;|/]", str(value or ""))
    output: list[str] = []
    for chunk in chunks:
        digits = normalize_phone(chunk)
        if 7 <= len(digits) <= 15 and digits not in output:
            output.append(digits)
    return tuple(output)


def normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    text = text.translate(ARABIC_NORMALIZATION)
    text = re.sub(r"[^\u0600-\u06ff0-9a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_frames(value: Any) -> frozenset[int]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[,،]", str(value or ""))
    frames: set[int] = set()
    for value in values:
        if isinstance(value, int):
            if value > 0:
                frames.add(value)
            continue
        part = str(value).strip()
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start, end = map(int, range_match.groups())
            if 0 < start <= end and end - start <= 10_000:
                frames.update(range(start, end + 1))
            continue
        if part.isdigit() and int(part) > 0:
            frames.add(int(part))
    return frozenset(frames)


def entity_frames(entity: dict[str, Any]) -> frozenset[int]:
    frames: set[int] = set()
    for value in entity.get("frames") or []:
        if not isinstance(value, dict):
            continue
        start, end = value.get("start"), value.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 < start <= end:
            frames.update(range(start, end + 1))
    return frozenset(frames)


def validate_ground_truth(data: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise EvaluationInputError(["ground-truth: root must be a JSON object"])
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"ground-truth: schema_version must be {SCHEMA_VERSION!r}"
        )
    if not _is_nonempty_string(data.get("dataset_id")):
        errors.append("ground-truth: dataset_id must be a non-empty string")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        errors.append("ground-truth: samples must be a non-empty array")
        samples = []

    sample_ids: set[str] = set()
    for sample_index, sample in enumerate(samples, 1):
        prefix = f"sample[{sample_index}]"
        if not isinstance(sample, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        sample_id = sample.get("sample_id")
        if not _is_nonempty_string(sample_id):
            errors.append(f"{prefix}: sample_id must be a non-empty string")
            sample_id = f"<missing-{sample_index}>"
        elif sample_id in sample_ids:
            errors.append(f"sample/{sample_id}: duplicate sample_id")
        else:
            sample_ids.add(sample_id)
        prefix = f"sample/{sample_id}"
        entities = sample.get("entities")
        if not isinstance(entities, list):
            errors.append(f"{prefix}: entities must be an array")
            continue
        entity_ids: set[str] = set()
        for entity_index, entity in enumerate(entities, 1):
            entity_prefix = f"{prefix}/entity[{entity_index}]"
            if not isinstance(entity, dict):
                errors.append(f"{entity_prefix}: must be an object")
                continue
            entity_id = entity.get("entity_id")
            if not _is_nonempty_string(entity_id):
                errors.append(f"{entity_prefix}: entity_id must be a non-empty string")
                entity_id = f"<missing-{entity_index}>"
            elif entity_id in entity_ids:
                errors.append(f"{prefix}/entity/{entity_id}: duplicate entity_id")
            else:
                entity_ids.add(entity_id)
            entity_prefix = f"{prefix}/entity/{entity_id}"
            entity_type = entity.get("entity_type")
            if entity_type not in ENTITY_TYPES:
                errors.append(
                    f"{entity_prefix}: entity_type must be one of {sorted(ENTITY_TYPES)}"
                )
            name_exact = entity.get("name_exact")
            if not isinstance(name_exact, str):
                errors.append(f"{entity_prefix}: name_exact must be a string")
            accepted_names = entity.get("accepted_names", [])
            if not isinstance(accepted_names, list) or any(
                not _is_nonempty_string(name) for name in accepted_names
            ):
                errors.append(
                    f"{entity_prefix}: accepted_names must contain non-empty strings"
                )
            phone = entity.get("phone")
            if not isinstance(phone, dict):
                errors.append(f"{entity_prefix}: phone must be an object")
            else:
                visibility = phone.get("visibility")
                values = phone.get("values")
                if visibility not in PHONE_VISIBILITIES:
                    errors.append(
                        f"{entity_prefix}: phone.visibility must be one of "
                        f"{sorted(PHONE_VISIBILITIES)}"
                    )
                if not isinstance(values, list):
                    errors.append(f"{entity_prefix}: phone.values must be an array")
                    values = []
                normalized_values = [normalize_phone(value) for value in values]
                if any(not 7 <= len(value) <= 15 for value in normalized_values):
                    errors.append(
                        f"{entity_prefix}: every phone value must contain 7-15 digits"
                    )
                if len(normalized_values) != len(set(normalized_values)):
                    errors.append(f"{entity_prefix}: phone.values contains duplicates")
                if visibility == "visible" and not normalized_values:
                    errors.append(
                        f"{entity_prefix}: visible phone requires at least one value"
                    )
                if visibility in {"not_visible", "unreadable"} and normalized_values:
                    errors.append(
                        f"{entity_prefix}: {visibility} phone must have empty values"
                    )
            frames = entity.get("frames", [])
            if not isinstance(frames, list):
                errors.append(f"{entity_prefix}: frames must be an array")
            else:
                for frame_index, frame_range in enumerate(frames, 1):
                    if not isinstance(frame_range, dict):
                        errors.append(
                            f"{entity_prefix}/frames[{frame_index}]: must be an object"
                        )
                        continue
                    start, end = frame_range.get("start"), frame_range.get("end")
                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or start < 1
                        or end < start
                    ):
                        errors.append(
                            f"{entity_prefix}/frames[{frame_index}]: "
                            "start/end must be positive integers with start <= end"
                        )
            coordinates = entity.get("coordinates")
            if coordinates is not None:
                if not isinstance(coordinates, dict):
                    errors.append(f"{entity_prefix}: coordinates must be an object")
                else:
                    lat, lng = coordinates.get("lat"), coordinates.get("lng")
                    if not isinstance(lat, (int, float)) or not -90 <= lat <= 90:
                        errors.append(f"{entity_prefix}: coordinates.lat is invalid")
                    if not isinstance(lng, (int, float)) or not -180 <= lng <= 180:
                        errors.append(f"{entity_prefix}: coordinates.lng is invalid")
    if errors:
        raise EvaluationInputError(errors)
    return data


def validate_mapping(
    data: Any,
    sample: dict[str, Any],
) -> dict[str, str | None]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise EvaluationInputError(["mapping: root must be a JSON object"])
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"mapping: schema_version must be {SCHEMA_VERSION!r}")
    sample_id = sample["sample_id"]
    if data.get("sample_id") != sample_id:
        errors.append(
            f"mapping: sample_id {data.get('sample_id')!r} does not match {sample_id!r}"
        )
    mappings = data.get("mappings")
    if not isinstance(mappings, list):
        errors.append("mapping: mappings must be an array")
        mappings = []
    entity_ids = {entity["entity_id"] for entity in sample["entities"]}
    output: dict[str, str | None] = {}
    for index, item in enumerate(mappings, 1):
        prefix = f"mapping[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        prediction_id = item.get("prediction_id")
        entity_id = item.get("entity_id")
        if not _is_nonempty_string(prediction_id):
            errors.append(f"{prefix}: prediction_id must be a non-empty string")
            continue
        if prediction_id in output:
            errors.append(f"{prefix}: duplicate prediction_id {prediction_id!r}")
            continue
        if entity_id is not None and entity_id not in entity_ids:
            errors.append(f"{prefix}: unknown entity_id {entity_id!r}")
            continue
        output[prediction_id] = entity_id
    if errors:
        raise EvaluationInputError(errors)
    return output


def select_sample(data: dict[str, Any], sample_id: str | None) -> dict[str, Any]:
    samples = data["samples"]
    if sample_id is None:
        if len(samples) != 1:
            raise EvaluationInputError([
                "ground-truth contains multiple samples; pass --sample-id",
            ])
        return samples[0]
    for sample in samples:
        if sample["sample_id"] == sample_id:
            return sample
    raise EvaluationInputError([f"Unknown sample_id: {sample_id!r}"])


def _prediction_name(raw: dict[str, Any]) -> str:
    v5_candidate = (raw.get("v5") or {}).get("candidate") or {}
    places = raw.get("places") or {}
    return str(
        raw.get("name_ar")
        or raw.get("name")
        or raw.get("name_en")
        or v5_candidate.get("name")
        or places.get("name")
        or ""
    ).strip()


def load_predictions(data: Any) -> tuple[list[Prediction], dict[str, int]]:
    if isinstance(data, dict) and isinstance(data.get("stores"), list):
        raw_predictions = data["stores"]
    elif isinstance(data, list):
        raw_predictions = data
    else:
        raise EvaluationInputError([
            "predictions: expected a v3/v5/v6 JSON array or an object with stores[]",
        ])

    errors: list[str] = []
    predictions: list[Prediction] = []
    excluded = 0
    rejected = 0
    for index, raw in enumerate(raw_predictions, 1):
        prediction_id = f"prediction-{index:04d}"
        if not isinstance(raw, dict):
            errors.append(f"predictions/{prediction_id}: must be an object")
            continue
        decision = (raw.get("auto_review") or {}).get("decision")
        if raw.get("excluded_from_results"):
            excluded += 1
            continue
        if decision == "auto_rejected":
            rejected += 1
            continue
        frames = parse_frames(
            raw.get("evidence_frames")
            or (raw.get("visual_evidence") or {}).get("frames")
            or raw.get("frame")
        )
        predictions.append(Prediction(
            prediction_id=prediction_id,
            source_index=index,
            name=_prediction_name(raw),
            phones=extract_phones(raw.get("phone") or ""),
            frames=frames,
            auto_decision=str(decision) if decision is not None else None,
            raw=raw,
        ))
    if errors:
        raise EvaluationInputError(errors)
    return predictions, {
        "source_predictions": len(raw_predictions),
        "surfaced_predictions": len(predictions),
        "excluded_predictions": excluded,
        "auto_rejected_predictions": rejected,
    }


def _entity_names(entity: dict[str, Any]) -> list[str]:
    return [entity.get("name_exact", ""), *(entity.get("accepted_names") or [])]


def name_score(prediction: Prediction, entity: dict[str, Any]) -> float:
    predicted = normalize_name(prediction.name)
    if not predicted:
        return 0.0
    scores = [
        SequenceMatcher(None, predicted, normalize_name(candidate)).ratio()
        for candidate in _entity_names(entity)
        if normalize_name(candidate)
    ]
    return max(scores, default=0.0)


def _exact_name(prediction: Prediction, entity: dict[str, Any]) -> bool:
    return prediction.name.strip() == str(entity.get("name_exact") or "").strip()


def _normalized_name(prediction: Prediction, entity: dict[str, Any]) -> bool:
    predicted = normalize_name(prediction.name)
    return bool(predicted) and predicted in {
        normalize_name(candidate) for candidate in _entity_names(entity)
    }


def _entity_phones(entity: dict[str, Any]) -> set[str]:
    return {
        normalize_phone(value)
        for value in (entity.get("phone") or {}).get("values", [])
        if normalize_phone(value)
    }


def _phone_matches(prediction: Prediction, entity: dict[str, Any]) -> bool:
    return bool(set(prediction.phones) & _entity_phones(entity))


def _frame_overlap(prediction: Prediction, entity: dict[str, Any]) -> bool:
    truth_frames = entity_frames(entity)
    return bool(prediction.frames and truth_frames and prediction.frames & truth_frames)


def match_predictions(
    predictions: list[Prediction],
    entities: list[dict[str, Any]],
    manual_mapping: dict[str, str | None] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> dict[str, Assignment]:
    manual_mapping = manual_mapping or {}
    entity_by_id = {entity["entity_id"]: entity for entity in entities}
    prediction_by_id = {prediction.prediction_id: prediction for prediction in predictions}
    unknown_predictions = sorted(set(manual_mapping) - set(prediction_by_id))
    if unknown_predictions:
        raise EvaluationInputError([
            f"mapping: unknown surfaced prediction_id {value!r}"
            for value in unknown_predictions
        ])

    assignments: dict[str, Assignment] = {}
    primary_by_entity: dict[str, str] = {}

    def assign(
        prediction: Prediction,
        entity_id: str | None,
        reason: str,
        score: float,
    ) -> None:
        duplicate = bool(entity_id and entity_id in primary_by_entity)
        assignments[prediction.prediction_id] = Assignment(
            entity_id=entity_id,
            reason=reason,
            score=score,
            duplicate=duplicate,
        )
        if entity_id and not duplicate:
            primary_by_entity[entity_id] = prediction.prediction_id

    for prediction in predictions:
        if prediction.prediction_id not in manual_mapping:
            continue
        entity_id = manual_mapping[prediction.prediction_id]
        score = name_score(prediction, entity_by_id[entity_id]) if entity_id else 0.0
        assign(prediction, entity_id, "manual", score)

    def available_entities() -> list[dict[str, Any]]:
        return [
            entity for entity in entities
            if entity["entity_id"] not in primary_by_entity
        ]

    # Exact phone matches are the strongest automatic evidence when unique.
    for prediction in predictions:
        if prediction.prediction_id in assignments or not prediction.phones:
            continue
        candidates = [
            entity for entity in available_entities()
            if _phone_matches(prediction, entity)
        ]
        if len(candidates) == 1:
            assign(prediction, candidates[0]["entity_id"], "unique_phone", 1.0)

    # Exact normalized names are deterministic and tolerate Arabic glyph variants.
    for prediction in predictions:
        if prediction.prediction_id in assignments:
            continue
        predicted_name = normalize_name(prediction.name)
        if not predicted_name:
            continue
        candidates = [
            entity for entity in available_entities()
            if predicted_name in {
                normalize_name(candidate) for candidate in _entity_names(entity)
            }
        ]
        if len(candidates) == 1:
            assign(prediction, candidates[0]["entity_id"], "normalized_name", 1.0)

    # Conservative fuzzy matching. Ambiguous pairs remain unmatched for review.
    fuzzy_candidates: list[tuple[float, int, str, str]] = []
    for prediction in predictions:
        if prediction.prediction_id in assignments:
            continue
        scored: list[tuple[float, int, str]] = []
        for entity in available_entities():
            score = name_score(prediction, entity)
            overlap = 1 if _frame_overlap(prediction, entity) else 0
            scored.append((score, overlap, entity["entity_id"]))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        if not scored or scored[0][0] < fuzzy_threshold:
            continue
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if scored[0][0] - runner_up < AMBIGUITY_MARGIN:
            continue
        top = scored[0]
        fuzzy_candidates.append((top[0], top[1], prediction.prediction_id, top[2]))

    fuzzy_candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    for score, _overlap, prediction_id, entity_id in fuzzy_candidates:
        if prediction_id in assignments or entity_id in primary_by_entity:
            continue
        assign(prediction_by_id[prediction_id], entity_id, "fuzzy_name", score)

    # Remaining high-agreement predictions for an already matched entity are duplicates.
    for prediction in predictions:
        if prediction.prediction_id in assignments:
            continue
        candidates: list[tuple[float, str]] = []
        for entity_id in primary_by_entity:
            entity = entity_by_id[entity_id]
            score = name_score(prediction, entity)
            if _phone_matches(prediction, entity):
                score = 1.0
            if score >= fuzzy_threshold:
                candidates.append((score, entity_id))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if candidates and (
            len(candidates) == 1
            or candidates[0][0] - candidates[1][0] >= AMBIGUITY_MARGIN
        ):
            assign(prediction, candidates[0][1], "duplicate_evidence", candidates[0][0])

    for prediction in predictions:
        if prediction.prediction_id not in assignments:
            assign(prediction, None, "unmatched", 0.0)
    return assignments


def _metric(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "value": round(numerator / denominator, 6) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _f1(true_positives: int, false_positives: int, false_negatives: int) -> dict[str, Any]:
    numerator = 2 * true_positives
    denominator = numerator + false_positives + false_negatives
    return _metric(numerator, denominator)


def evaluate(
    ground_truth: dict[str, Any],
    predictions_data: Any,
    sample_id: str | None = None,
    manual_mapping_data: dict[str, Any] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> dict[str, Any]:
    if not 0.0 < fuzzy_threshold <= 1.0:
        raise EvaluationInputError(["fuzzy_threshold must be > 0 and <= 1"])
    validate_ground_truth(ground_truth)
    sample = select_sample(ground_truth, sample_id)
    predictions, source_metadata = load_predictions(predictions_data)
    manual_mapping = (
        validate_mapping(manual_mapping_data, sample)
        if manual_mapping_data is not None else {}
    )
    entities = sample["entities"]
    entity_by_id = {entity["entity_id"]: entity for entity in entities}
    assignments = match_predictions(
        predictions,
        entities,
        manual_mapping=manual_mapping,
        fuzzy_threshold=fuzzy_threshold,
    )

    details: list[dict[str, Any]] = []
    primary_business_predictions: dict[str, Prediction] = {}
    assigned_predictions_by_entity: dict[str, list[Prediction]] = {}
    duplicate_count = 0
    non_business_false_positives: dict[str, int] = {}
    unmatched_false_positives = 0

    for prediction in predictions:
        assignment = assignments[prediction.prediction_id]
        entity = entity_by_id.get(assignment.entity_id) if assignment.entity_id else None
        if entity:
            assigned_predictions_by_entity.setdefault(entity["entity_id"], []).append(prediction)
        disposition = "false_positive_unmatched"
        if assignment.duplicate:
            disposition = "duplicate"
            duplicate_count += 1
        elif entity and entity["entity_type"] in BUSINESS_TYPES:
            disposition = "true_positive"
            primary_business_predictions[entity["entity_id"]] = prediction
        elif entity:
            disposition = "false_positive_non_business"
            non_business_false_positives[entity["entity_type"]] = (
                non_business_false_positives.get(entity["entity_type"], 0) + 1
            )
        else:
            unmatched_false_positives += 1

        score = name_score(prediction, entity) if entity else 0.0
        exact = bool(entity and _exact_name(prediction, entity))
        normalized = bool(entity and _normalized_name(prediction, entity))
        phone_correct = bool(entity and _phone_matches(prediction, entity))
        details.append({
            "prediction_id": prediction.prediction_id,
            "source_index": prediction.source_index,
            "name": prediction.name,
            "phones": list(prediction.phones),
            "frames": sorted(prediction.frames),
            "auto_decision": prediction.auto_decision,
            "entity_id": assignment.entity_id,
            "entity_type": entity.get("entity_type") if entity else None,
            "disposition": disposition,
            "match_reason": assignment.reason,
            "match_score": round(assignment.score, 6),
            "name_exact": exact,
            "name_normalized": normalized,
            "name_similarity": round(score, 6),
            "phone_correct": phone_correct,
        })

    business_entities = [
        entity for entity in entities if entity["entity_type"] in BUSINESS_TYPES
    ]
    true_positives = len(primary_business_predictions)
    false_positives = len(predictions) - true_positives
    false_negatives = len(business_entities) - true_positives
    precision = _metric(true_positives, true_positives + false_positives)
    recall = _metric(true_positives, true_positives + false_negatives)

    matched_pairs = [
        (entity_by_id[entity_id], prediction)
        for entity_id, prediction in sorted(primary_business_predictions.items())
    ]
    exact_names = sum(_exact_name(prediction, entity) for entity, prediction in matched_pairs)
    fuzzy_names = sum(
        name_score(prediction, entity) >= fuzzy_threshold
        for entity, prediction in matched_pairs
    )

    phone_coverage = sum(bool(prediction.phones) for _entity, prediction in matched_pairs)
    predictions_with_phone = [prediction for prediction in predictions if prediction.phones]
    correct_phone_predictions = 0
    for prediction in predictions_with_phone:
        assignment = assignments[prediction.prediction_id]
        entity = entity_by_id.get(assignment.entity_id) if assignment.entity_id else None
        if entity and _phone_matches(prediction, entity):
            correct_phone_predictions += 1

    visible_phone_entities = [
        entity for entity in business_entities
        if (entity.get("phone") or {}).get("visibility") == "visible"
    ]
    recovered_visible_phones = 0
    for entity in visible_phone_entities:
        assigned = assigned_predictions_by_entity.get(entity["entity_id"], [])
        if any(_phone_matches(prediction, entity) for prediction in assigned):
            recovered_visible_phones += 1

    auto_passed_details = [
        detail for detail in details if detail["auto_decision"] == "auto_passed"
    ]
    correct_auto_passed = sum(
        detail["disposition"] == "true_positive"
        and detail["name_similarity"] >= fuzzy_threshold
        and (not detail["phones"] or detail["phone_correct"])
        for detail in auto_passed_details
    )

    missing_businesses = [
        {
            "entity_id": entity["entity_id"],
            "name_exact": entity["name_exact"],
            "phone_visibility": entity["phone"]["visibility"],
        }
        for entity in business_entities
        if entity["entity_id"] not in primary_business_predictions
    ]
    name_errors = [
        {
            "prediction_id": detail["prediction_id"],
            "entity_id": detail["entity_id"],
            "predicted": detail["name"],
            "expected": entity_by_id[detail["entity_id"]]["name_exact"],
            "similarity": detail["name_similarity"],
        }
        for detail in details
        if detail["disposition"] == "true_positive" and not detail["name_exact"]
    ]
    phone_errors = [
        {
            "prediction_id": detail["prediction_id"],
            "entity_id": detail["entity_id"],
            "predicted": detail["phones"],
            "visibility": (
                entity_by_id[detail["entity_id"]]["phone"]["visibility"]
                if detail["entity_id"] else None
            ),
            "expected": (
                entity_by_id[detail["entity_id"]]["phone"]["values"]
                if detail["entity_id"] else []
            ),
        }
        for detail in details
        if detail["phones"] and not detail["phone_correct"]
    ]

    false_positive_counts = {
        "duplicate": duplicate_count,
        "unmatched": unmatched_false_positives,
        **{
            f"non_business_{entity_type}": count
            for entity_type, count in sorted(non_business_false_positives.items())
        },
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": ground_truth["dataset_id"],
        "sample_id": sample["sample_id"],
        "settings": {"fuzzy_threshold": fuzzy_threshold},
        "coverage": {
            "ground_truth_entities": len(entities),
            "ground_truth_businesses": len(business_entities),
            **source_metadata,
            "manual_mappings": len(manual_mapping),
            "predictions_with_frames": sum(bool(value.frames) for value in predictions),
        },
        "metrics": {
            "store_detection_precision": precision,
            "store_detection_recall": recall,
            "store_detection_f1": _f1(
                true_positives, false_positives, false_negatives
            ),
            "exact_name_accuracy": _metric(exact_names, len(matched_pairs)),
            "normalized_fuzzy_name_accuracy": _metric(fuzzy_names, len(matched_pairs)),
            "phone_coverage_all_businesses": _metric(
                phone_coverage, len(business_entities)
            ),
            "phone_exact_precision": _metric(
                correct_phone_predictions, len(predictions_with_phone)
            ),
            "phone_exact_recall_visible": _metric(
                recovered_visible_phones, len(visible_phone_entities)
            ),
            "duplicate_rate": _metric(duplicate_count, len(predictions)),
            "auto_passed_accuracy": _metric(
                correct_auto_passed, len(auto_passed_details)
            ),
        },
        "false_positive_counts": false_positive_counts,
        "errors": {
            "false_negatives": missing_businesses,
            "name_errors": name_errors,
            "phone_errors": phone_errors,
            "false_positives": [
                detail for detail in details
                if detail["disposition"].startswith("false_positive")
                or detail["disposition"] == "duplicate"
            ],
        },
        "predictions": details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Store Extraction Evaluation",
        "",
        f"- Dataset: `{report['dataset_id']}`",
        f"- Sample: `{report['sample_id']}`",
        f"- Fuzzy threshold: `{report['settings']['fuzzy_threshold']}`",
        "",
        "## Coverage",
        "",
        "| Field | Count |",
        "|---|---:|",
    ]
    for key, value in report["coverage"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend([
        "",
        "## Metrics",
        "",
        "| Metric | Value | Numerator | Denominator |",
        "|---|---:|---:|---:|",
    ])
    for name, metric in report["metrics"].items():
        value = "N/A" if metric["value"] is None else f"{metric['value']:.2%}"
        numerator = "N/A" if metric["numerator"] is None else metric["numerator"]
        denominator = "N/A" if metric["denominator"] is None else metric["denominator"]
        lines.append(f"| `{name}` | {value} | {numerator} | {denominator} |")
    lines.extend(["", "## False Positive Counts", ""])
    if report["false_positive_counts"]:
        for name, count in report["false_positive_counts"].items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- None")

    def add_error_table(title: str, items: list[dict[str, Any]], fields: list[str]) -> None:
        lines.extend(["", f"## {title}", ""])
        if not items:
            lines.append("None.")
            return
        lines.append("| " + " | ".join(fields) + " |")
        lines.append("|" + "|".join(["---"] * len(fields)) + "|")
        for item in items:
            values = [str(item.get(field, "")).replace("|", "\\|") for field in fields]
            lines.append("| " + " | ".join(values) + " |")

    add_error_table(
        "False Negatives",
        report["errors"]["false_negatives"],
        ["entity_id", "name_exact", "phone_visibility"],
    )
    add_error_table(
        "Name Errors",
        report["errors"]["name_errors"],
        ["prediction_id", "entity_id", "predicted", "expected", "similarity"],
    )
    add_error_table(
        "Phone Errors",
        report["errors"]["phone_errors"],
        ["prediction_id", "entity_id", "predicted", "expected", "visibility"],
    )
    add_error_table(
        "False Positives and Duplicates",
        report["errors"]["false_positives"],
        ["prediction_id", "entity_id", "name", "disposition", "match_reason"],
    )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline evaluation for Store Extractor JSON results",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate ground truth")
    validate_parser.add_argument("--ground-truth", required=True)
    validate_parser.add_argument("--sample-id")
    validate_parser.add_argument("--mapping")

    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate predictions")
    evaluate_parser.add_argument("--ground-truth", required=True)
    evaluate_parser.add_argument("--predictions", required=True)
    evaluate_parser.add_argument("--sample-id")
    evaluate_parser.add_argument("--mapping")
    evaluate_parser.add_argument("--output-dir", required=True)
    evaluate_parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=DEFAULT_FUZZY_THRESHOLD,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        ground_truth = validate_ground_truth(load_json(args.ground_truth))
        sample = select_sample(ground_truth, args.sample_id)
        mapping_data = load_json(args.mapping) if args.mapping else None
        if args.command == "validate":
            if mapping_data is not None:
                validate_mapping(mapping_data, sample)
            print(
                f"Valid: dataset={ground_truth['dataset_id']} "
                f"sample={sample['sample_id']} entities={len(sample['entities'])}"
            )
            return 0

        predictions_data = load_json(args.predictions)
        report = evaluate(
            ground_truth,
            predictions_data,
            sample_id=sample["sample_id"],
            manual_mapping_data=mapping_data,
            fuzzy_threshold=args.fuzzy_threshold,
        )
        json_path, markdown_path = write_report(report, args.output_dir)
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 0
    except EvaluationInputError as error:
        for message in error.errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
