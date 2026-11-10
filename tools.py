# -*- coding: utf-8 -*-
"""
Công cụ cho Trợ lý ảo: vẽ đồ thị/biểu đồ/sơ đồ (Pillow), cấu trúc phân tử
(PubChem), xuất PDF (fpdf2), Excel (openpyxl), Word (.docx tự viết, không cần lxml).
Không phụ thuộc Kivy nên có thể chạy thử trên máy tính.
"""

import math
import os
import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

COLORS = [(46, 107, 217), (220, 68, 55), (15, 157, 88), (244, 160, 0),
          (142, 68, 173), (0, 172, 193), (233, 30, 99), (121, 85, 72)]
INK, GRID, BG = (30, 30, 36), (225, 228, 235), (255, 255, 255)


# ------------------------------------------------------------------ fonts
def font_path(bold=False):
    names = ["Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf",
             "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    dirs = []
    try:
        from kivy import kivy_data_dir
        dirs.append(os.path.join(kivy_data_dir, "fonts"))
    except Exception:
        pass
    dirs += ["/system/fonts", "/usr/share/fonts/truetype/dejavu",
             "/usr/share/fonts/TTF", "C:/Windows/Fonts"]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None


def _font(size, bold=False):
    p = font_path(bold)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _wrap(draw, text, font, width):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            test = (cur + " " + word).strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


# ------------------------------------------------------------------ math
def ticks(a, b, n=8):
    raw = (b - a) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((k * mag for k in (1, 2, 5, 10)), key=lambda k: abs(k - raw))
    t = math.ceil(a / step - 1e-9) * step
    while t <= b + 1e-9:
        yield round(t, 10)
        t += step


_FUNCS = {n: getattr(math, n) for n in (
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "exp", "sqrt", "floor", "ceil", "fabs", "log2")}
_FUNCS.update({"ln": math.log, "log": math.log10, "abs": abs, "pi": math.pi,
               "e": math.e, "cot": lambda v: 1 / math.tan(v)})


def normalize_expr(s):
    s = s.strip().lower()
    s = re.sub(r"^(y|f\(x\))\s*=\s*", "", s)
    for a, b in (("^", "**"), ("×", "*"), ("÷", "/"), ("√", "sqrt"), ("π", "pi"),
                 ("−", "-"), (",", ".")):
        s = s.replace(a, b)
    s = re.sub(r"(\d)\s*([a-z(])", r"\1*\2", s)        # 2x -> 2*x
    s = re.sub(r"\)\s*([a-z0-9(])", r")*\1", s)        # )(  )x -> )*
    s = re.sub(r"\bx\s*([(])", r"x*\1", s)             # x(  -> x*(
    return s


def compile_expr(src):
    expr = normalize_expr(src)
    code = compile(expr, "<expr>", "eval")
    bad = [n for n in code.co_names if n != "x" and n not in _FUNCS]
    if bad:
        raise ValueError("không hiểu: " + ", ".join(bad))
    env = {"__builtins__": {}, **_FUNCS}

    def f(x):
        return eval(code, env, {"x": x})
    return f


def split_top(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch in sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [p.strip() for p in out if p.strip()]


def parse_plot(arg):
    """'sin(x); x^2 từ -5 đến 5' hoặc 'sin(x) [-5, 5]' -> (['sin(x)', 'x^2'], -5, 5)"""
    xmin, xmax = -10.0, 10.0
    num = r"(-?\s*\d+(?:\.\d+)?|-?\s*pi|-?\s*π|-?\s*\d*\s*\*?\s*pi)"
    pats = [r"\s(?:from|từ|tu|x\s*từ|x\s*from)\s+" + num + r"\s+(?:to|đến|den|tới)\s+" + num + r"\s*$",
            r"\[\s*" + num + r"\s*[,;]\s*" + num + r"\s*\]\s*$"]
    for pat in pats:
        m = re.search(pat, " " + arg, re.I)
        if m:
            conv = lambda t: float(eval(normalize_expr(t.replace(" ", "")),
                                        {"__builtins__": {}}, {"pi": math.pi}))
            xmin, xmax = conv(m.group(1)), conv(m.group(2))
            arg = (" " + arg)[:m.start()].strip()
            break
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if xmin == xmax:
        xmin, xmax = xmin - 1, xmax + 1
    exprs = split_top(arg, ";") if ";" in arg else split_top(arg, ",")
    return exprs, xmin, xmax


def plot_functions(exprs, xmin, xmax, out_dir, title=""):
    W, H, L, R, T, B = 1200, 850, 110, 40, 90, 90
    funcs = [(e, compile_expr(e)) for e in exprs]
    n = 800
    xs = [xmin + (xmax - xmin) * i / n for i in range(n + 1)]
    series, ally = [], []
    for e, f in funcs:
        ys = []
        for x in xs:
            try:
                y = float(f(x))
                ys.append(y if math.isfinite(y) else None)
            except Exception:
                ys.append(None)
        series.append((e, ys))
        ally += [y for y in ys if y is not None]
    if not ally:
        raise ValueError("không tính được giá trị nào")
    ally.sort()
    lo = ally[int(len(ally) * 0.02)]
    hi = ally[min(len(ally) - 1, int(len(ally) * 0.98))]
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.08
    ymin, ymax = lo - pad, hi + pad

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    fx = lambda x: L + (x - xmin) / (xmax - xmin) * (W - L - R)
    fy = lambda y: T + (ymax - y) / (ymax - ymin) * (H - T - B)
    f_small, f_title = _font(22), _font(34, True)

    for t in ticks(xmin, xmax):
        d.line([(fx(t), T), (fx(t), H - B)], fill=GRID, width=1)
        d.text((fx(t), H - B + 10), f"{t:g}", fill=INK, font=f_small, anchor="mt")
    for t in ticks(ymin, ymax):
        d.line([(L, fy(t)), (W - R, fy(t))], fill=GRID, width=1)
        d.text((L - 10, fy(t)), f"{t:g}", fill=INK, font=f_small, anchor="rm")
    if xmin < 0 < xmax:
        d.line([(fx(0), T), (fx(0), H - B)], fill=INK, width=2)
    if ymin < 0 < ymax:
        d.line([(L, fy(0)), (W - R, fy(0))], fill=INK, width=2)
    d.rectangle([L, T, W - R, H - B], outline=INK, width=2)

    jump = (ymax - ymin) * 0.9
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    for i, (e, ys) in enumerate(series):
        col = COLORS[i % len(COLORS)]
        seg = []
        prev = None
        for x, y in zip(xs, ys):
            ok = y is not None and ymin - jump < y < ymax + jump
            if ok and prev is not None and abs(y - prev) > jump:
                ok = False
            if ok:
                seg.append((fx(x), fy(min(max(y, ymin - pad), ymax + pad))))
            elif len(seg) > 1:
                dl.line(seg, fill=col, width=4, joint="curve")
                seg = []
            else:
                seg = []
            prev = y
        if len(seg) > 1:
            dl.line(seg, fill=col, width=4, joint="curve")
    box = (L + 1, T + 1, W - R - 1, H - B - 1)
    img.paste(layer.crop(box), box[:2], layer.crop(box))
    for i, (e, ys) in enumerate(series):
        col = COLORS[i % len(COLORS)]
        d.rectangle([L + 20, T + 15 + i * 36, L + 50, T + 35 + i * 36], fill=col)
        d.text((L + 60, T + 25 + i * 36), "y = " + e, fill=INK, font=f_small, anchor="lm")
    d.text((W / 2, 45), title or "Đồ thị hàm số", fill=INK, font=f_title, anchor="mm")
    path = os.path.join(out_dir, f"dothi_{_stamp()}.png")
    img.save(path)
    return path


# ------------------------------------------------------------------ data charts
def parse_data(arg):
    """'Dân số: Hà Nội=8.4, HCM=9.3'  ->  ('Dân số', ['Hà Nội','HCM'], [8.4, 9.3])"""
    title, _, body = arg.partition(":") if ":" in arg else ("", "", arg)
    labels, values = [], []
    for part in re.split(r"[,;]\s*(?=[^,;=]*=)", body):
        if "=" in part:
            k, v = part.split("=", 1)
            v = v.strip().replace("%", "")
            v = v.replace(",", ".") if v.count(",") == 1 and "." not in v else v.replace(",", "")
            labels.append(k.strip())
            values.append(float(v))
    if not labels:
        raise ValueError("cần dạng: Tên: A=1, B=2")
    return title.strip(), labels, values


def bar_chart(title, labels, values, out_dir):
    W, H, L, R, T, B = 1200, 850, 110, 40, 100, 150
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_small, f_title = _font(22), _font(34, True)
    vmax = max(max(values), 0)
    vmin = min(min(values), 0)
    if vmax == vmin:
        vmax += 1
    fy = lambda v: T + (vmax - v) / (vmax - vmin) * (H - T - B)
    n = len(values)
    slot = (W - L - R) / n
    vmax *= 1.08
    for v in ticks(vmin, vmax, 6):
        d.line([(L, fy(v)), (W - R, fy(v))], fill=GRID)
        d.text((L - 10, fy(v)), f"{v:g}", fill=INK, font=f_small, anchor="rm")
    for i, (lab, v) in enumerate(zip(labels, values)):
        x0 = L + i * slot + slot * 0.15
        x1 = L + (i + 1) * slot - slot * 0.15
        d.rectangle([x0, min(fy(v), fy(0)), x1, max(fy(v), fy(0))],
                    fill=COLORS[i % len(COLORS)])
        d.text(((x0 + x1) / 2, fy(v) - 8 if v >= 0 else fy(v) + 8), f"{v:g}",
               fill=INK, font=f_small, anchor="mb" if v >= 0 else "mt")
        for j, line in enumerate(_wrap(d, lab, f_small, slot - 6)[:3]):
            d.text(((x0 + x1) / 2, H - B + 14 + j * 26), line, fill=INK,
                   font=f_small, anchor="mt")
    d.line([(L, fy(0)), (W - R, fy(0))], fill=INK, width=2)
    d.text((W / 2, 50), title or "Biểu đồ cột", fill=INK, font=f_title, anchor="mm")
    path = os.path.join(out_dir, f"bieudo_{_stamp()}.png")
    img.save(path)
    return path


def pie_chart(title, labels, values, out_dir):
    W, H = 1200, 850
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_small, f_title = _font(24), _font(34, True)
    total = sum(v for v in values if v > 0) or 1
    box = [80, 130, 680, 730]
    start = -90.0
    for i, (lab, v) in enumerate(zip(labels, values)):
        if v <= 0:
            continue
        ang = 360 * v / total
        col = COLORS[i % len(COLORS)]
        d.pieslice(box, start, start + ang, fill=col, outline=BG, width=3)
        mid = math.radians(start + ang / 2)
        if ang > 12:
            d.text((380 + 200 * math.cos(mid), 430 + 200 * math.sin(mid)),
                   f"{100 * v / total:.0f}%", fill=BG, font=_font(26, True), anchor="mm")
        start += ang
    for i, (lab, v) in enumerate(zip(labels, values)):
        y = 170 + i * 50
        d.rectangle([730, y - 14, 760, y + 14], fill=COLORS[i % len(COLORS)])
        d.text((775, y), f"{lab}: {v:g}", fill=INK, font=f_small, anchor="lm")
    d.text((W / 2, 55), title or "Biểu đồ tròn", fill=INK, font=f_title, anchor="mm")
    path = os.path.join(out_dir, f"bieudotron_{_stamp()}.png")
    img.save(path)
    return path


# ------------------------------------------------------------------ flow / biology
def parse_flow(arg):
    title, _, body = arg.partition(":") if ":" in arg else ("", "", arg)
    steps = [s.strip() for s in re.split(r"\s*(?:->|→|=>|>)\s*", body) if s.strip()]
    if len(steps) < 2:
        raise ValueError("cần dạng: Tên: bước 1 -> bước 2 -> bước 3")
    return title.strip(), steps


def flow_diagram(title, steps, out_dir, cycle=False):
    W = 1000
    f_txt, f_title = _font(28), _font(34, True)
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    blocks = [_wrap(tmp, s, f_txt, W - 260) for s in steps]
    hs = [max(80, 30 + 38 * len(b)) for b in blocks]
    gap = 70
    H = 120 + sum(hs) + gap * (len(steps) - 1) + (90 if cycle else 40)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 55), title or "Sơ đồ", fill=INK, font=f_title, anchor="mm")
    y = 110
    centers = []
    for i, (b, h) in enumerate(zip(blocks, hs)):
        col = COLORS[i % len(COLORS)]
        d.rounded_rectangle([120, y, W - 120, y + h], radius=22, fill=col)
        for j, line in enumerate(b):
            d.text((W / 2, y + h / 2 + (j - (len(b) - 1) / 2) * 38), line,
                   fill=BG, font=f_txt, anchor="mm")
        centers.append((y, y + h))
        if i < len(steps) - 1:
            ax, a0, a1 = W / 2, y + h + 8, y + h + gap - 8
            d.line([(ax, a0), (ax, a1)], fill=INK, width=5)
            d.polygon([(ax - 14, a1 - 18), (ax + 14, a1 - 18), (ax, a1)], fill=INK)
        y += h + gap
    if cycle:
        top, bot = centers[0][0] + 30, centers[-1][1] - 30
        xr = W - 60
        d.line([(W - 120, bot), (xr, bot), (xr, top), (W - 118, top)], fill=INK, width=5)
        d.polygon([(W - 118, top), (W - 100, top - 14), (W - 100, top + 14)], fill=INK)
    path = os.path.join(out_dir, f"sodo_{_stamp()}.png")
    img.save(path)
    return path


# ------------------------------------------------------------------ chemistry
def chem_image(name, out_dir, fetch):
    """Ảnh cấu trúc phân tử từ PubChem (cần mạng). fetch(url) -> bytes."""
    from urllib.parse import quote
    q = quote(name.strip())
    data = fetch("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                 f"{q}/PNG?image_size=large")
    raw = os.path.join(out_dir, f"phantu_{_stamp()}_raw.png")
    with open(raw, "wb") as fh:
        fh.write(data)
    info = ""
    try:
        import json
        js = json.loads(fetch("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                              f"{q}/property/MolecularFormula,MolecularWeight,IUPACName/JSON"))
        p = js["PropertyTable"]["Properties"][0]
        info = (f"Công thức: {p.get('MolecularFormula', '?')}   "
                f"Khối lượng mol: {p.get('MolecularWeight', '?')} g/mol")
    except Exception:
        pass
    src = Image.open(raw).convert("RGB")
    W = max(900, src.width)
    img = Image.new("RGB", (W, src.height + 160), BG)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 45), name.strip().title(), fill=INK, font=_font(36, True), anchor="mm")
    img.paste(src, ((W - src.width) // 2, 85))
    d.text((W / 2, src.height + 120), info, fill=INK, font=_font(26), anchor="mm")
    path = raw.replace("_raw", "")
    img.save(path)
    os.remove(raw)
    return path, info


# ------------------------------------------------------------------ exports
def export_pdf(out_dir, title, text, images=()):
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    reg, bold = font_path(), font_path(True)
    pdf.add_font("VN", "", reg)
    pdf.add_font("VN", "B", bold or reg)
    pdf.add_page()
    # dải tiêu đề kiểu infographic
    pdf.set_fill_color(46, 107, 217)
    pdf.rect(0, 0, 210, 38, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("VN", "B", 22)
    pdf.set_xy(12, 14)
    pdf.multi_cell(186, 10, title, align="C")
    pdf.set_text_color(30, 30, 36)
    pdf.set_y(44)
    pdf.set_font("VN", "", 9)
    pdf.cell(0, 6, "Trợ lý ảo – " + datetime.now().strftime("%d/%m/%Y %H:%M"),
             align="R", new_x="LMARGIN", new_y="NEXT")
    for img in images:
        if img and os.path.exists(img):
            w, h = Image.open(img).size
            width = 186
            if pdf.get_y() + width * h / w > 280:
                pdf.add_page()
            pdf.image(img, x=12, w=width)
            pdf.ln(4)
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            pdf.ln(3)
            continue
        if para.endswith(":") or (len(para) < 70 and para.isupper()):
            pdf.set_font("VN", "B", 13)
            pdf.set_text_color(46, 107, 217)
            pdf.multi_cell(0, 7, para, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(30, 30, 36)
        else:
            pdf.set_font("VN", "", 11.5)
            pdf.multi_cell(0, 6.5, para, new_x="LMARGIN", new_y="NEXT")
    path = os.path.join(out_dir, f"{_safe(title)}_{_stamp()}.pdf")
    pdf.output(path)
    return path


def export_xlsx(out_dir, title, rows, image=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "Dữ liệu"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    for r, row in enumerate(rows, start=3):
        for c, val in enumerate(row, start=1):
            v = val
            if isinstance(v, str):
                t = v.strip().replace(" ", "")
                try:
                    v = float(t.replace(",", "")) if re.fullmatch(r"-?[\d,]*\.?\d+", t) else v.strip()
                except ValueError:
                    v = v.strip()
            cell = ws.cell(row=r, column=c, value=v)
            if r == 3:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2E6BD9")
                cell.alignment = Alignment(horizontal="center")
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 50)
    if image and os.path.exists(image):
        try:
            from openpyxl.drawing.image import Image as XLImage
            ws2 = wb.create_sheet("Biểu đồ")
            xi = XLImage(image)
            xi.width, xi.height = 720, int(720 * xi.height / xi.width)
            ws2.add_image(xi, "A1")
        except Exception:
            pass
    path = os.path.join(out_dir, f"{_safe(title)}_{_stamp()}.xlsx")
    wb.save(path)
    return path


def export_docx(out_dir, title, text, images=()):
    """Tự tạo file .docx (Office Open XML) – không cần python-docx/lxml."""
    W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

    def para(t, size=24, bold=False, color=None, center=False):
        rpr = f'<w:sz w:val="{size}"/>' + ("<w:b/>" if bold else "") + \
              (f'<w:color w:val="{color}"/>' if color else "")
        ppr = '<w:pPr><w:jc w:val="center"/></w:pPr>' if center else ""
        return (f'<w:p>{ppr}<w:r><w:rPr>{rpr}</w:rPr>'
                f'<w:t xml:space="preserve">{escape(t)}</w:t></w:r></w:p>')

    body = [para(title, 40, True, "2E6BD9", True),
            para(datetime.now().strftime("%d/%m/%Y %H:%M"), 18, center=True)]
    rels, media = [], []
    for i, img in enumerate([p for p in images if p and os.path.exists(p)], start=1):
        w, h = Image.open(img).size
        cx = 5943600                        # 6.5 inch (EMU)
        cy = int(cx * h / w)
        rid = f"rIdImg{i}"
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                    f'officeDocument/2006/relationships/image" Target="media/image{i}.png"/>')
        media.append((f"word/media/image{i}.png", img))
        body.append(
            f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{i}" name="Hinh{i}"/>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{i}" name="image{i}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    for line in text.split("\n"):
        line = line.strip()
        if line.endswith(":") and len(line) < 80:
            body.append(para(line, 28, True, "2E6BD9"))
        else:
            body.append(para(line))
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {W_NS}><w:body>{"".join(body)}'
           f'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           f'<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
           f'</w:body></w:document>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Default Extension="png" ContentType="image/png"/>'
              '<Override PartName="/word/document.xml" ContentType="application/'
              'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                 '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(rels) + '</Relationships>')
    path = os.path.join(out_dir, f"{_safe(title)}_{_stamp()}.docx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for arc, src in media:
            z.write(src, arc)
    return path


def parse_table(text):
    """Dòng dạng 'a | b | c' (hoặc phân tách bằng tab/;) -> list các hàng."""
    rows = []
    for line in text.split("\n"):
        line = line.strip().strip("|")
        if not line or set(line) <= set("-|: "):
            continue
        for sep in ("|", "\t", ";"):
            if sep in line:
                rows.append([c.strip() for c in line.split(sep)])
                break
    return rows


def _safe(name):
    s = re.sub(r"[^\w\- ]+", "", name, flags=re.U).strip().replace(" ", "_")
    return (s or "tai_lieu")[:40]
