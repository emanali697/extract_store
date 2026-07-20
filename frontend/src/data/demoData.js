export const demoResultsSummary = {
  total: 46,
  active: 12,
  phones: 52,
  precise: 31,
}

export const demoStores = [
  { id: 1, name: 'تموينات الأمين', category: 'بقالة', phone: '0530037820', status: '✅ نشط', tier: 1, distance: '30م' },
  { id: 2, name: 'بوفية جودة الجوهرة', category: 'مطعم', phone: '0537164252', status: '✅ نشط', tier: 1, distance: '38م' },
  { id: 3, name: 'مطعم عالم الشواية', category: 'مطعم', phone: '0508401149', status: '✅ نشط', tier: 1, distance: '105م' },
  { id: 4, name: 'اللهيبي للكهرباء', category: 'كهرباء', phone: '', status: '✅ نشط', tier: 1, distance: '71م' },
  { id: 5, name: 'هلا كوكو للمعسلات', category: 'معسلات', phone: '0558972436', status: '✅ نشط', tier: 1, distance: '126م' },
  { id: 6, name: 'مغسلة النخبة', category: 'مغسلة', phone: '0501234567', status: '⚠️ غير مؤكد', tier: 2, distance: '88م' },
  { id: 7, name: 'صالون الأناقة', category: 'صالون', phone: '', status: '⚪ يحتاج تحقق', tier: 3, distance: '142م' },
]

export const demoReviewItems = [
  {
    id: 'r1',
    suggestedName: 'مطعم الفلاح',
    rawOcr: 'مطعم الفـلـاح للمأكولات',
    category: 'مطعم',
    phone: '0541234567',
    confidence: 0.62,
    tier: 3,
    signImageUrl: '',
    note: 'الاسم ظاهر مرتين بكتابة مختلفة في الفيديو',
  },
  {
    id: 'r2',
    suggestedName: 'بقالة الحي',
    rawOcr: 'بـقالـة الحي - مفتوح 24',
    category: 'بقالة',
    phone: '',
    confidence: 0.48,
    tier: 3,
    signImageUrl: '',
    note: 'الـ OCR التقط جزء من اللافتة فقط',
  },
  {
    id: 'r3',
    suggestedName: 'مكتبة الطالب',
    rawOcr: 'مكتبة الطالـب للقرطاسية',
    category: 'مكتبة',
    phone: '0555555555',
    confidence: 0.71,
    tier: 3,
    signImageUrl: '',
    note: 'مش متطابق مع نتائج Google Places',
  },
]
