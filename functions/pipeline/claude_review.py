"""
Claude Review - إعداد مراجعة Claude للمتاجر المشكوك فيها

هذا السكربت:
1. يقرأ stores_raw.json
2. يجمع الفريمات اللي فيها متاجر محتاجة مراجعة
3. يعمل ملف markdown فيه المتاجر + مسار صور اللوحات
4. Claude يقرأ الملف والصور ويضيف مراجعته

Usage:
    python claude_review.py <output_dir>
"""
import os
import sys
import json
import argparse

sys.stdout.reconfigure(encoding='utf-8')


def prepare_review(output_dir):
    """تجهيز ملف للمراجعة يدوياً أو بواسطة Claude"""
    json_path = os.path.join(output_dir, "stores_raw.json")
    if not os.path.exists(json_path):
        print(f"ERROR: {json_path} not found. Run main.py first.")
        return 1

    with open(json_path, 'r', encoding='utf-8') as f:
        stores = json.load(f)

    flagged = [s for s in stores if s.get('needs_review')]
    print(f"Total stores: {len(stores)}")
    print(f"Flagged for review: {len(flagged)}")

    if not flagged:
        print("Nothing to review!")
        return 0

    # جمع صور الـ signs لكل متجر flagged
    signs_dir = os.path.join(output_dir, "signs")
    review_md = os.path.join(output_dir, "REVIEW_NEEDED.md")

    with open(review_md, 'w', encoding='utf-8') as f:
        f.write("# متاجر محتاجة مراجعة\n\n")
        f.write(f"عدد: {len(flagged)}\n\n")
        f.write("---\n\n")
        for i, s in enumerate(flagged, 1):
            name = s.get('name_ar', '(فاضي)')
            category = s.get('category', '')
            reasons = ", ".join(s.get('review_flags', []))
            frame = s.get('frame', '')

            f.write(f"## {i}. {name}\n")
            f.write(f"- **التصنيف:** {category}\n")
            f.write(f"- **أسباب المراجعة:** {reasons}\n")
            f.write(f"- **الإطارات:** {frame}\n")

            # روابط لصور اللوحات
            if frame:
                # parse frame numbers
                frame_nums = []
                for part in str(frame).split(','):
                    part = part.strip()
                    if '-' in part:
                        try:
                            a, b = part.split('-')
                            frame_nums.extend(range(int(a), int(b) + 1))
                        except:
                            pass
                    elif part.isdigit():
                        frame_nums.append(int(part))

                for fn in frame_nums[:3]:  # أول 3 فريمات بس
                    sign_path = os.path.join(signs_dir, f"sign_{fn:04d}.jpg")
                    if os.path.exists(sign_path):
                        rel = os.path.relpath(sign_path, output_dir)
                        f.write(f"- **صورة الفريم {fn}:** `{rel}`\n")

            f.write(f"\n### مراجعة Claude:\n")
            f.write(f"(املأ هنا بعد المراجعة)\n\n")
            f.write("---\n\n")

    print(f"\nReview file: {review_md}")
    print("Open this file and review each store, or send to Claude to review")
    return 0


def apply_review(output_dir):
    """تطبيق مراجعة Claude من ملف claude_reviews.json"""
    json_path = os.path.join(output_dir, "stores_raw.json")
    reviews_path = os.path.join(output_dir, "claude_reviews.json")

    if not os.path.exists(reviews_path):
        print(f"ERROR: {reviews_path} not found.")
        print("Expected format: {\"store_name_or_frame\": \"review text\", ...}")
        return 1

    with open(json_path, 'r', encoding='utf-8') as f:
        stores = json.load(f)

    with open(reviews_path, 'r', encoding='utf-8') as f:
        reviews = json.load(f)

    # apply reviews
    applied = 0
    for s in stores:
        name = s.get('name_ar', '')
        frame = str(s.get('frame', ''))
        if name in reviews:
            s['claude_review'] = reviews[name]
            applied += 1
        elif frame in reviews:
            s['claude_review'] = reviews[frame]
            applied += 1

    # save
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(stores, f, ensure_ascii=False, indent=2)

    print(f"Applied {applied} reviews")
    print(f"Now re-run export: python -c \"from exporter import export_excel; import json; "
          f"stores = json.load(open('{json_path}','r',encoding='utf-8')); "
          f"export_excel(stores, '{output_dir}/stores_final.xlsx')\"")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", help="Output directory from main.py")
    parser.add_argument("--apply", action="store_true",
                        help="Apply reviews from claude_reviews.json")
    args = parser.parse_args()

    if args.apply:
        sys.exit(apply_review(args.output_dir))
    else:
        sys.exit(prepare_review(args.output_dir))
