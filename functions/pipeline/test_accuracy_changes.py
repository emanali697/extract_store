"""Unit tests for the raise-extraction-accuracy task.

كل الاختبارات deterministic وبدون أي اتصال شبكي: نختبر اختيار أوضح فريم،
أبعاد قص اللافتات بدون تكبير، حد التصغير في analyzer، تجميع multi-frame
(median GPS + تصويت الهواتف)، وبوابة تحقق الحقول في auto_review.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extractor import (
    _pick_sharpest,
    _select_sharpest_windows,
    enhance_image,
    extract_sign_crop,
    filter_frames_by_speed,
    sign_region_blur_score,
)
from multi_frame import enrich_stores_with_aggregates
from auto_review import (
    _decide,
    _normalized_phone_digits,
    compute_field_verification,
    compute_phone_sources,
)

QUIET = lambda *args, **kwargs: None


def _frame(idx, timestamp, blur=0.0):
    return {
        "idx": idx,
        "timestamp": timestamp,
        "frame_path": f"raw_frames/frame_{idx:04d}.jpg",
        "gps_path": f"raw_gps/gps_{idx:04d}.jpg",
        "blur": blur,
    }


class SharpestWindowSelectionTest(unittest.TestCase):
    def test_picks_sharpest_frame_in_each_speed_window(self):
        # سرعة 10 كم/س → نافذة 1.0s؛ فريمات كل 0.25s
        frames = [_frame(i, (i - 1) * 0.25, blur=b)
                  for i, b in enumerate([10, 50, 20, 30, 5, 60, 15, 25], start=1)]
        gps = [{"speed": 10} for _ in frames]
        selected = filter_frames_by_speed(frames, gps, log_fn=QUIET)
        picked = [(f["idx"], f["blur"]) for f in selected]
        self.assertEqual(picked, [(2, 50), (6, 60)])

    def test_tie_breaks_to_earliest_frame(self):
        frames = [_frame(1, 0.0, blur=40), _frame(2, 0.25, blur=40)]
        selected = filter_frames_by_speed(frames, [{"speed": 10}] * 2, log_fn=QUIET)
        self.assertEqual([f["idx"] for f in selected], [1])

    def test_stationary_frames_are_skipped(self):
        frames = [_frame(1, 0.0, blur=10), _frame(2, 0.25, blur=90),
                  _frame(3, 0.5, blur=10), _frame(4, 0.75, blur=30)]
        gps = [{"speed": 0}, {"speed": 0}, {"speed": 0}, {"speed": 30}]
        selected = filter_frames_by_speed(frames, gps, log_fn=QUIET)
        self.assertEqual([f["idx"] for f in selected], [4])

    def test_zero_speeds_trigger_time_fallback(self):
        frames = [_frame(i, (i - 1) * 0.25, blur=float(i)) for i in range(1, 13)]
        gps = [{"speed": 0} for _ in frames]
        selected = filter_frames_by_speed(frames, gps, log_fn=QUIET)
        # fallback كل 1.0s مع اختيار الأوضح داخل كل نافذة
        self.assertTrue(selected)
        self.assertEqual([f["idx"] for f in selected], [4, 8, 12])

    def test_cached_frames_without_blur_keep_time_order(self):
        frames = [{"idx": 1, "timestamp": 0.0},
                  {"idx": 2, "timestamp": 0.25},
                  {"idx": 3, "timestamp": 1.25}]
        gps = [{"speed": 10}] * 3
        selected = filter_frames_by_speed(frames, gps, log_fn=QUIET)
        self.assertEqual([f["idx"] for f in selected], [1, 3])

    def test_empty_input_returns_empty(self):
        self.assertEqual(filter_frames_by_speed([], [], log_fn=QUIET), [])

    def test_select_sharpest_windows_directly(self):
        candidates = [_frame(1, 0.0, 5), _frame(2, 0.1, 9), _frame(3, 2.0, 1)]
        selected = _select_sharpest_windows(candidates, lambda speed: 0.5)
        self.assertEqual([f["idx"] for f in selected], [2, 3])
        self.assertEqual(_pick_sharpest([_frame(7, 0.0, 3), _frame(8, 0.1, 3)])["idx"], 7)


class ImageChainTest(unittest.TestCase):
    def test_sign_crop_keeps_native_dimensions(self):
        frame = np.zeros((500, 1000, 3), dtype=np.uint8)
        crop = extract_sign_crop(frame)
        # 40%..65% من الارتفاع: 500*0.08=40 → 500*0.65=325 → 285 صفًا، العرض كامل
        self.assertEqual(crop.shape, (285, 1000, 3))

    def test_enhance_without_sharpen_preserves_shape(self):
        img = np.full((60, 120, 3), 128, dtype=np.uint8)
        out = enhance_image(img, sharpen=False)
        self.assertEqual(out.shape, img.shape)

    def test_blur_score_is_numeric_and_higher_for_textured_region(self):
        flat = np.zeros((360, 640, 3), dtype=np.uint8)
        textured = flat.copy()
        cv2.randu(textured, 0, 255)
        self.assertGreaterEqual(sign_region_blur_score(flat), 0.0)
        self.assertGreater(sign_region_blur_score(textured),
                           sign_region_blur_score(flat))

    def test_image_bytes_does_not_downscale_native_4k_strip(self):
        from analyzer import _image_bytes
        img = Image.new("RGB", (3840, 220), color=(200, 200, 200))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            img.save(tmp.name, "JPEG")
            path = tmp.name
        try:
            data = _image_bytes(path)
        finally:
            os.unlink(path)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.width, 3840)

    def test_image_bytes_downscales_above_bound(self):
        from analyzer import _image_bytes
        img = Image.new("RGB", (5000, 300), color=(200, 200, 200))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            img.save(tmp.name, "JPEG")
            path = tmp.name
        try:
            data = _image_bytes(path)
        finally:
            os.unlink(path)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.width, 3840)


class MultiFrameEnrichmentTest(unittest.TestCase):
    def _processed(self):
        return [{"final_idx": i} for i in (1, 2, 3)]

    def test_gemini_phone_is_preserved_and_ocr_votes_recorded(self):
        stores = [{"frame": "1,2,3", "phone": "0501111222",
                   "phone_source": "gemini_visual", "name_ar": "متجر"}]
        ocr_texts = ["0551234567", "نص 0551234567", "0551234567"]
        gps = [{"lat": 24.0, "lng": 46.0},
               {"lat": 24.1, "lng": 46.1},
               {"lat": 24.2, "lng": 46.2}]
        enrich_stores_with_aggregates(stores, ocr_texts, gps, self._processed())
        store = stores[0]
        self.assertEqual(store["phone"], "0501111222")
        self.assertEqual(store["phone_source"], "gemini_visual")
        self.assertEqual(store["phones_all"][0]["phone"], "0551234567")
        self.assertEqual(store["phone_votes"], 3)
        self.assertIn("vision_ocr_text", store)

    def test_ocr_fills_phone_only_when_empty(self):
        stores = [{"frame": "1,2,3", "phone": "", "name_ar": "متجر"}]
        ocr_texts = ["0551234567", "0551234567", "0551234567"]
        enrich_stores_with_aggregates(stores, ocr_texts, [], self._processed())
        self.assertEqual(stores[0]["phone"], "0551234567")
        self.assertEqual(stores[0]["phone_source"], "cloud_vision_ocr")

    def test_median_gps_replaces_first_frame_coordinate(self):
        stores = [{"frame": "1,2,3", "phone": "", "name_ar": "متجر"}]
        gps = [{"lat": 24.0, "lng": 46.0},
               {"lat": 24.1, "lng": 46.1},
               {"lat": 24.2, "lng": 46.2}]
        enrich_stores_with_aggregates(stores, [], gps, self._processed())
        self.assertEqual(stores[0]["lat"], f"{24.1:.5f}")
        self.assertEqual(stores[0]["lng"], f"{46.1:.5f}")
        self.assertEqual(stores[0]["gps_samples"], 3)


class PhoneSourceVerificationTest(unittest.TestCase):
    def test_normalization_handles_international_and_arabic_digits(self):
        self.assertEqual(_normalized_phone_digits("+966 541 234 567"), "0541234567")
        self.assertEqual(_normalized_phone_digits("٠٥٤١٢٣٤٥٦٧"), "0541234567")

    def test_sources_from_two_independent_readers(self):
        store = {
            "phone": "0541234567",
            "phone_source": "gemini_visual",
            "multimodal": {"phone": "0541234567"},
            "phones_all": [{"phone": "0541234567", "kind": "mobile", "votes": 1}],
        }
        sources = compute_phone_sources(store)
        self.assertEqual(sources["0541234567"], {"gemini_first", "gemini_verify"})

    def test_ocr_votes_need_at_least_two_frames(self):
        store = {
            "phone": "0541234567",
            "phone_source": "gemini_visual",
            "phones_all": [{"phone": "0541234567", "kind": "mobile", "votes": 2}],
        }
        sources = compute_phone_sources(store)
        self.assertEqual(sources["0541234567"], {"gemini_first", "ocr_votes"})
        store["phones_all"][0]["votes"] = 1
        self.assertEqual(compute_phone_sources(store)["0541234567"], {"gemini_first"})


def _passing_store(**overrides):
    store = {
        "name_ar": "مؤسسة القمعة الذهبية",
        "_judge": {"confidence": 0.9, "reason": "ok"},
        "_phones_clean": [],
        "multimodal": {
            "verification_pass": True,
            "visible": True,
            "same_store": True,
            "name": "مؤسسة القمعة الذهبية",
            "initial_name": "مؤسسة القمعة الذهبية",
            "image_clarity": 0.95,
            "phone": "",
        },
    }
    store.update(overrides)
    return store


class FieldGateDecisionTest(unittest.TestCase):
    def test_auto_passed_without_any_phone(self):
        decision, conf, reason, _ = _decide(_passing_store())
        self.assertEqual(decision, "auto_passed")

    def test_auto_passed_with_phone_confirmed_by_two_sources(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567"],
        )
        store["multimodal"]["phone"] = "0541234567"
        decision, _, reason, _ = _decide(store)
        self.assertEqual(decision, "auto_passed")

    def test_single_source_phone_blocks_auto_pass(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567"],
        )
        decision, conf, reason, _ = _decide(store)
        self.assertEqual(decision, "needs_human")
        self.assertLessEqual(conf, 0.84)
        self.assertIn("الهاتف", reason)

    def test_conflicting_phones_block_auto_pass(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567", "0549999999"],
        )
        store["multimodal"]["phone"] = "0541234567"
        decision, _, _, _ = _decide(store)
        self.assertEqual(decision, "needs_human")

    def test_ocr_votes_plus_first_pass_verify_phone(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567"],
            phones_all=[{"phone": "0541234567", "kind": "mobile", "votes": 2}],
        )
        decision, _, _, _ = _decide(store)
        self.assertEqual(decision, "auto_passed")

    def test_places_phone_cross_match_verifies(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567"],
            v5={"status": "frame_only",
                "candidate": {"phone": "+966 54 123 4567"}},
        )
        decision, _, _, _ = _decide(store)
        self.assertEqual(decision, "auto_passed")


class FieldVerificationAnnotationTest(unittest.TestCase):
    def test_field_block_shape_and_location_rules(self):
        store = _passing_store(
            phone="0541234567",
            phone_source="gemini_visual",
            _phones_clean=["0541234567"],
            phones_all=[{"phone": "0541234567", "kind": "mobile", "votes": 2}],
            location_source="dashcam_frame",
            gps_samples=3,
        )
        verification = compute_field_verification(store)
        self.assertTrue(verification["name"])
        self.assertTrue(verification["phone"])
        self.assertTrue(verification["location"])
        self.assertEqual(
            verification["phone_sources"]["0541234567"],
            ["gemini_first", "ocr_votes"],
        )

    def test_v5_confirmed_marks_name_and_location(self):
        store = _passing_store(v5={"status": "confirmed_high", "candidate": {}})
        verification = compute_field_verification(store)
        self.assertTrue(verification["name"])
        self.assertTrue(verification["location"])
        self.assertIsNone(verification["phone"])

    def test_single_gps_sample_is_not_verified_location(self):
        store = _passing_store(location_source="dashcam_frame", gps_samples=1)
        self.assertFalse(compute_field_verification(store)["location"])


if __name__ == "__main__":
    unittest.main()
