"""
استخراج الفريمات بشكل ذكي حسب سرعة السيارة
"""
import os
import re
import cv2
import numpy as np
from config import (
    SPEED_TO_INTERVAL, BASE_EXTRACTION_INTERVAL, STATIONARY_SPEED_THRESHOLD,
    GPS_ZOOM_FACTOR, SIGN_CROP_Y_RANGE,
    GPS_CROP_BOTTOM_PX, GPS_CROP_X_RATIO,
)
from progress import emit_progress, progress_ticker


def save_img(path, img, quality=95):
    """حفظ صورة يدعم المسارات العربية"""
    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    buf.tofile(path)


def enhance_image(img, sharpen=True):
    """تحسين جودة الصورة - contrast + sharpness (اختياري)

    الـsharpening أصبح اختياريًا لأن مسار اللافتات يترك التحديد الحاد لنقطة
    واحدة لاحقة (analyzer)؛ sharpening مزدوج يشوّه الحروف العربية.
    """
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    if sharpen:
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        enhanced = cv2.filter2D(enhanced, -1, kernel)
    return enhanced


def open_video(video_path):
    """فتح الفيديو مع دعم المسارات العربية"""
    cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        # Fallback: use 8.3 short path
        import subprocess
        result = subprocess.run(
            ['cmd', '/c', f'for %I in ("{video_path}") do @echo %~sI'],
            capture_output=True, text=True
        )
        short_path = result.stdout.strip()
        if short_path:
            cap = cv2.VideoCapture(short_path)
    return cap


def extract_gps_crop(frame):
    """قص منطقة GPS من الإطار"""
    h, w = frame.shape[:2]
    gps_crop = frame[h - GPS_CROP_BOTTOM_PX:h, 0:int(w * GPS_CROP_X_RATIO)]
    enhanced = enhance_image(gps_crop)
    enlarged = cv2.resize(enhanced, None, fx=GPS_ZOOM_FACTOR, fy=GPS_ZOOM_FACTOR,
                          interpolation=cv2.INTER_CUBIC)
    return enlarged


def extract_sign_crop(frame):
    """قص منطقة اللوحات من الإطار بدقة أصلية (بدون تكبير).

    التكبير 2× السابق كان يُعاد تصغيره لاحقًا قبل Gemini (resampling مزدوج
    يفقد التفاصيل)، لذلك نحفظ القص بدقته الأصلية مع CLAHE خفيف فقط.
    """
    h, w = frame.shape[:2]
    y1 = int(h * SIGN_CROP_Y_RANGE[0])
    y2 = int(h * SIGN_CROP_Y_RANGE[1])
    sign_crop = frame[y1:y2, 0:w]
    return enhance_image(sign_crop, sharpen=False)


def sign_region_blur_score(frame):
    """درجة وضوح منطقة اللافتات (تباين Laplacian) — أعلى = أوضح.

    تُحسب على نسخة مصغرة (640px عرضًا) حتى تبقى رخيصة أثناء Pass 1،
    وتُستخدم لاختيار أوضح فريم داخل كل نافذة سرعة.
    """
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (640, max(1, round(640 * h / w))),
                       interpolation=cv2.INTER_AREA)
    sh = small.shape[0]
    region = small[int(sh * SIGN_CROP_Y_RANGE[0]):int(sh * SIGN_CROP_Y_RANGE[1]), :]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def get_interval_for_speed(speed_kmh):
    """إرجاع فترة التقطيع المناسبة للسرعة"""
    for max_speed, interval in SPEED_TO_INTERVAL:
        if speed_kmh <= max_speed:
            return interval
    return SPEED_TO_INTERVAL[-1][1]


def extract_frames_pass1(video_path, output_base, start_seconds=0, log_fn=print):
    """
    Pass 1: استخراج كل الفريمات المحتملة (كل BASE_EXTRACTION_INTERVAL)
    بدون OCR، بس نحفظها ونجهز للـ pass التاني
    """
    os.makedirs(f"{output_base}/raw_frames", exist_ok=True)
    os.makedirs(f"{output_base}/raw_gps", exist_ok=True)

    cap = open_video(video_path)
    if not cap.isOpened():
        log_fn(f"ERROR: Cannot open video: {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames_count / fps
    frame_interval = max(1, int(fps * BASE_EXTRACTION_INTERVAL))

    log_fn(f"Video: {duration:.0f}s, {fps:.0f}fps, {total_frames_count} frames")

    # Seek to the requested start point (jump, don't read-and-discard).
    start_frame = 0
    if start_seconds and start_seconds > 0:
        start_frame = int(start_seconds * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        log_fn(f"Seeking to {start_seconds:.0f}s (frame {start_frame})")

    log_fn(f"Pass 1: Extracting every {BASE_EXTRACTION_INTERVAL}s ({frame_interval} frames)")

    extracted = []  # [(frame_idx, timestamp, gps_path, frame_path)]
    frame_count = start_frame
    saved_count = 0
    expected_frames = max(1, (total_frames_count - start_frame) // frame_interval)
    tick = progress_ticker(expected_frames, log_fn=log_fn, every=1)
    tick(0)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % frame_interval == 0:
            saved_count += 1
            timestamp = frame_count / fps

            frame_path = f"{output_base}/raw_frames/frame_{saved_count:04d}.jpg"
            gps_path = f"{output_base}/raw_gps/gps_{saved_count:04d}.jpg"

            save_img(frame_path, frame)
            save_img(gps_path, extract_gps_crop(frame))

            extracted.append({
                'idx': saved_count,
                'frame_idx': frame_count,
                'timestamp': timestamp,
                'frame_path': frame_path,
                'gps_path': gps_path,
                'blur': sign_region_blur_score(frame),
            })
            tick(saved_count)

        frame_count += 1

    cap.release()
    emit_progress(saved_count, saved_count, log_fn=log_fn)
    log_fn(f"Pass 1 done: {saved_count} raw frames")
    return extracted


def parse_gps_text(text):
    """استخراج السرعة والإحداثيات من نص OCR"""
    speed = 0
    lat, lng = None, None

    # Speed: NNNKM/H or similar
    speed_match = re.search(r'(\d+)\s*KM/?H', text, re.IGNORECASE)
    if speed_match:
        speed = int(speed_match.group(1))

    # GPS coordinates
    lat_match = re.search(r'N[:\s]*(\d+\.\d+)', text)
    lng_match = re.search(r'E[:\s]*(\d+\.\d+)', text)
    if lat_match:
        lat = float(lat_match.group(1))
    if lng_match:
        lng = float(lng_match.group(1))

    return {'speed': speed, 'lat': lat, 'lng': lng}


def _pick_sharpest(window):
    """أوضح فريم في النافذة؛ كسر التعادل للأقدم زمنيًا (deterministic)."""
    return max(window, key=lambda f: (float(f.get('blur') or 0.0),
                                      -int(f.get('idx') or 0)))


def _select_sharpest_windows(candidates, interval_for_speed):
    """
    تجميع الفريمات المرشحة في نوافذ زمنية بطول الفترة المطلوبة لسرعة أول
    مرشح في النافذة، واختيار أوضح فريم (أعلى blur) من كل نافذة.
    """
    selected = []
    window = []
    window_end = None
    for cand in candidates:
        timestamp = cand['timestamp']
        if window and timestamp < window_end - 0.01:
            window.append(cand)
            continue
        if window:
            selected.append(_pick_sharpest(window))
        window = [cand]
        window_end = timestamp + interval_for_speed(cand.get('speed', 0))
    if window:
        selected.append(_pick_sharpest(window))
    return selected


def filter_frames_by_speed(raw_frames, gps_data_list, speed_mode="auto", log_fn=print):
    """
    Pass 2: فلترة الفريمات حسب السرعة
    - نتخطى لما السيارة واقفة
    - نختار أوضح فريم داخل كل نافذة زمنية بطول فترة تناسب السرعة
    """
    if not raw_frames:
        return []

    log_fn(f"Pass 2: Filtering frames by speed...")

    total = len(raw_frames)
    tick = progress_ticker(total, log_fn=log_fn, every=max(1, total // 50))
    tick(0)

    moving = []
    skipped_stationary = 0

    for i, frame_info in enumerate(raw_frames):
        tick(i + 1)
        gps = gps_data_list[i] if i < len(gps_data_list) else {}
        speed = gps.get('speed', 0)

        # تخطي الفريم لو السيارة واقفة
        if speed < STATIONARY_SPEED_THRESHOLD:
            skipped_stationary += 1
            continue

        moving.append({**frame_info, **gps})

    if speed_mode == "fast":
        interval_for_speed = lambda speed: 1.0
    elif speed_mode == "precise":
        interval_for_speed = lambda speed: 0.5
    else:
        interval_for_speed = get_interval_for_speed

    selected = _select_sharpest_windows(moving, interval_for_speed)
    skipped_interval = len(moving) - len(selected)

    emit_progress(total, total, log_fn=log_fn)

    # Cloud Vision or the overlay parser can occasionally return speed=0 for
    # every frame even though the vehicle is moving. Never let that failure
    # silently discard the whole video. Fall back to deterministic time-based
    # sampling so sign OCR and Gemini still receive frames.
    if not selected and raw_frames:
        if speed_mode == "precise":
            fallback_interval = 0.5
        elif speed_mode == "fast":
            fallback_interval = 1.5
        else:
            fallback_interval = 1.0

        log_fn(
            "WARNING: No moving-speed frames were detected; "
            f"using time-based fallback every {fallback_interval:.1f}s"
        )
        all_frames = [
            {**frame_info, **(gps_data_list[i] if i < len(gps_data_list) else {})}
            for i, frame_info in enumerate(raw_frames)
        ]
        selected = _select_sharpest_windows(
            all_frames, lambda _speed: fallback_interval
        )

    log_fn(f"Pass 2 done: {len(selected)} selected "
           f"(skipped: {skipped_stationary} stationary + {skipped_interval} dense)")
    return selected


def process_selected_frames(selected_frames, output_base, log_fn=print):
    """
    Pass 3: معالجة الفريمات المختارة - قص اللوحات + تحسين
    """
    os.makedirs(f"{output_base}/signs", exist_ok=True)
    os.makedirs(f"{output_base}/gps", exist_ok=True)

    log_fn(f"Pass 3: Processing {len(selected_frames)} selected frames...")

    total = len(selected_frames)
    tick = progress_ticker(total, log_fn=log_fn, every=max(1, total // 50))
    tick(0)

    processed = []
    for i, info in enumerate(selected_frames, 1):
        tick(i)
        frame = cv2.imread(info['frame_path'])
        if frame is None:
            # Arabic path fallback
            with open(info['frame_path'], 'rb') as f:
                data = f.read()
            arr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        if frame is None:
            log_fn(f"  Warning: couldn't read {info['frame_path']}")
            continue

        sign_path = f"{output_base}/signs/sign_{i:04d}.jpg"
        gps_path = f"{output_base}/gps/gps_{i:04d}.jpg"

        save_img(sign_path, extract_sign_crop(frame))
        save_img(gps_path, extract_gps_crop(frame))

        processed.append({
            **info,
            'final_idx': i,
            'sign_path': sign_path,
            'gps_final_path': gps_path,
        })

    log_fn(f"Pass 3 done: {len(processed)} processed frames")
    return processed
