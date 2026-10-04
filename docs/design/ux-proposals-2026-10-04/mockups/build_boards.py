import os
import base64
from PIL import Image
from playwright.sync_api import sync_playwright

mockup_dir = os.path.abspath('docs/design/ux-proposals-2026-10-04/mockups')
before_dir = os.path.abspath('docs/design/ux-proposals-2026-10-04/before')

def to_data_uri(img):
    import io
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{b64}'

def img_file_to_data_uri(path):
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return f'data:image/png;base64,{b64}'

boards = [
    {
        'id': 'board_ux-01-02',
        'badge': 'UX-01 & UX-02',
        'title': 'الصفحة الرئيسية: إزالة النسب وادعاءات الدقة واستبدالها بأعداد توجيهية + إبراز مساري القراءة والمختص',
        'before_img': img_file_to_data_uri(os.path.join(before_dir, 'index.png')),
        'after_img': img_file_to_data_uri(os.path.join(mockup_dir, 'ux-01-02_index.png')),
        'w': 2960,
        'h': 1050,
        'item_w': 1440,
        'item_h': 900
    },
    {
        'id': 'board_ux-04',
        'badge': 'UX-04',
        'title': 'وضع القراءة: مفتاح صريح لحواشي المحقق مع إخفاء شارات الحواشي من المتن فعلياً عند الإطفاء',
        'before_img': to_data_uri(Image.open(os.path.join(before_dir, 'reader.png')).crop((0, 0, 1440, 500))),
        'after_img': img_file_to_data_uri(os.path.join(mockup_dir, 'ux-04_footnotes.png')),
        'w': 2960,
        'h': 650,
        'item_w': 1440,
        'item_h': 500
    },
    {
        'id': 'board_ux-05-06',
        'badge': 'UX-05 & UX-06',
        'title': 'وضع المراجعة: فصل عنوان طابور المواضع عن التبويبات + تخفيف إطارات الشواهد مع حصر التأطير في الموضع النشط',
        'before_img': img_file_to_data_uri(os.path.join(before_dir, 'review.png')),
        'after_img': img_file_to_data_uri(os.path.join(mockup_dir, 'ux-05-06_review.png')),
        'w': 2960,
        'h': 1050,
        'item_w': 1440,
        'item_h': 900
    },
    {
        'id': 'board_ux-07',
        'badge': 'UX-07',
        'title': 'مراجعة الجوال: رأس مضغوط في صف واحد لإظهار المتن فوراً مع شريط قرار سفلي ثابت',
        'before_img': img_file_to_data_uri(os.path.join(before_dir, 'review_mobile.png')),
        'after_img': img_file_to_data_uri(os.path.join(mockup_dir, 'ux-07_review_mobile.png')),
        'w': 860,
        'h': 980,
        'item_w': 390,
        'item_h': 844
    },
    {
        'id': 'board_ux-08',
        'badge': 'UX-08',
        'title': 'الفهرس الكلاسيكي: وسم الواجهة القديمة بوضوح كـ «كلاسيكية للمقارنة» وإبراز زر الانتقال للواجهة الجديدة',
        'before_img': to_data_uri(Image.open(os.path.join(before_dir, 'fahras.png')).crop((0, 0, 1440, 300))),
        'after_img': img_file_to_data_uri(os.path.join(mockup_dir, 'ux-08_fahras_classic.png')),
        'w': 2960,
        'h': 450,
        'item_w': 1440,
        'item_h': 300
    }
]

html_template = '''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0E1326;
      color: #FFFFFF;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Readex Pro", "IBM Plex Sans Arabic", Tahoma, sans-serif;
      direction: rtl;
      padding: 20px;
      width: {w}px;
      height: {h}px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .board-header {{
      display: flex;
      align-items: center;
      gap: 14px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      padding: 10px 20px;
      flex-shrink: 0;
    }}
    .badge {{
      background: #5B3FD9;
      color: #FFFFFF;
      font-weight: 800;
      font-size: 1.05rem;
      padding: 4px 14px;
      border-radius: 8px;
      white-space: nowrap;
    }}
    .board-title {{
      font-size: 1.15rem;
      font-weight: 700;
      color: #E2E7FF;
    }}
    .columns-wrap {{
      display: flex;
      gap: 20px;
      flex: 1;
      justify-content: center;
      align-items: stretch;
      min-height: 0;
    }}
    .col-box {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: {item_w}px;
      flex-shrink: 0;
    }}
    .col-label {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.95rem;
      font-weight: 700;
      padding: 2px 4px;
    }}
    .tag-before {{
      color: #E08A6A;
      background: rgba(224, 138, 106, 0.15);
      padding: 2px 10px;
      border-radius: 6px;
      border: 1px solid rgba(224, 138, 106, 0.3);
    }}
    .tag-after {{
      color: #2EF2C2;
      background: rgba(46, 242, 194, 0.15);
      padding: 2px 10px;
      border-radius: 6px;
      border: 1px solid rgba(46, 242, 194, 0.3);
    }}
    .img-frame {{
      width: {item_w}px;
      height: {item_h}px;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.15);
      box-shadow: 0 8px 30px rgba(0,0,0,0.4);
      background: #000;
      flex-shrink: 0;
    }}
    .img-frame img {{
      display: block;
      width: {item_w}px;
      height: {item_h}px;
    }}
  </style>
</head>
<body>
  <div class="board-header">
    <span class="badge">{badge}</span>
    <span class="board-title">{title}</span>
  </div>
  <div class="columns-wrap">
    <div class="col-box">
      <div class="col-label"><span class="tag-before">قبل (الوضع الحالي)</span></div>
      <div class="img-frame"><img src="{before_img}" alt="قبل"></div>
    </div>
    <div class="col-box">
      <div class="col-label"><span class="tag-after">بعد (المقترح المتفق عليه)</span></div>
      <div class="img-frame"><img src="{after_img}" alt="بعد"></div>
    </div>
  </div>
</body>
</html>'''

with sync_playwright() as p:
    browser = p.chromium.launch()
    for b in boards:
        html = html_template.format(
            w=b['w'],
            h=b['h'],
            badge=b['badge'],
            title=b['title'],
            before_img=b['before_img'],
            after_img=b['after_img'],
            item_w=b['item_w'],
            item_h=b['item_h']
        )
        page = browser.new_page(viewport={'width': b['w'], 'height': b['h']})
        page.set_content(html)
        out_png = os.path.join(mockup_dir, f"{b['id']}.png")
        page.screenshot(path=out_png, full_page=False)
        page.close()
        print(f"Generated: {out_png} size={os.path.getsize(out_png)}")
    browser.close()
print('All boards generated successfully!')
