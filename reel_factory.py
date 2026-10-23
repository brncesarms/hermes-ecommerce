#!/usr/bin/env python3
"""Reel factory: gera Reels 1080x1920 (zoompan + overlays Montserrat) em data/reels_queue/<item_id>.mp4"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

BASE = "/home/brn/.hermes/ecommerce"
sys.path.insert(0, BASE)
HIST = os.path.join(BASE, "data", "historico_posts.json")
QUEUE = os.path.join(BASE, "data", "reels_queue")
FONTS = os.path.join(BASE, "fonts")
FFMPEG = "/home/brn/.local/bin/ffmpeg" if os.path.exists("/home/brn/.local/bin/ffmpeg") else (shutil.which("ffmpeg") or "ffmpeg")
W, H = 1080, 1920
FPS = 30
DUR = 9
PRECO_MIN = 100.0
ACCENT = (238, 77, 45)
WHITE = (255, 255, 255)


def _preco_float(v):
    """Converte 'R$ 1.234,56' / 12.5 / '12.50' em float. Retorna 0.0 se falhar."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^0-9,.\-]", "", str(v))
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _achar(obj, chave):
    if isinstance(obj, dict):
        if obj.get(chave):
            return obj[chave]
        for v in obj.values():
            r = _achar(v, chave)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _achar(v, chave)
            if r:
                return r
    return None


def _carregar_item(item_id):
    item_id = str(item_id)
    with open(HIST, "r", encoding="utf-8") as f:
        hist = json.load(f)
    dados = None
    if isinstance(hist, dict):
        dados = hist.get(item_id)
    elif isinstance(hist, list):
        for d in hist:
            if str(d.get("item_id") or d.get("itemId")) == item_id:
                dados = d
                break
    if not dados:
        raise SystemExit(f"item_id {item_id} nao encontrado em {HIST}")
    shop_id = dados.get("shop_id") or dados.get("shopId")
    img = dados.get("imageUrl") or dados.get("image_url")
    nome = dados.get("nome") or dados.get("titulo") or dados.get("title") or dados.get("productName")
    preco = dados.get("preco") or dados.get("price") or dados.get("priceMin")
    if not img or not nome or not preco:
        import shopee_engine
        url = f"https://shopee.com.br/product/{shop_id}/{item_id}"
        res = shopee_engine.consultar_oferta_shopee(url) or {}
        img = img or _achar(res, "imageUrl")
        nome = nome or _achar(res, "productName") or _achar(res, "nome")
        preco = preco or _achar(res, "price") or _achar(res, "priceMin")
    if not img:
        raise SystemExit("imageUrl nao encontrada")
    if not nome:
        raise SystemExit("titulo nao encontrado")
    valor = _preco_float(preco)
    if valor < PRECO_MIN:
        raise SystemExit(f"preco R$ {valor:.2f} abaixo do piso R$ {PRECO_MIN:.0f}; abortado")
    return {"item_id": item_id, "nome": str(nome).strip(), "preco": valor, "img_url": str(img)}


def _baixar_imagem(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def _font(size, bold=True):
    peso = "Bold" if bold else "Regular"
    caminho = os.path.join(FONTS, f"Montserrat-{peso}.otf")
    if os.path.exists(caminho):
        return ImageFont.truetype(caminho, size)
    achados = sorted(glob.glob(os.path.join(FONTS, "**", f"*{peso}*.otf"), recursive=True))
    if achados:
        return ImageFont.truetype(achados[0], size)
    achados = sorted(glob.glob(os.path.join(FONTS, "**", "*.otf"), recursive=True))
    if achados:
        return ImageFont.truetype(achados[0], size)
    return ImageFont.load_default()


def _centro(draw, texto, y, fonte, fill=WHITE, stroke=0):
    b = draw.textbbox((0, 0), texto, font=fonte, stroke_width=stroke)
    w, h = b[2] - b[0], b[3] - b[1]
    draw.text(((W - w) // 2 - b[0], y - b[1]), texto, font=fonte, fill=fill,
              stroke_width=stroke, stroke_fill=(0, 0, 0))
    return h


def _centro_box(draw, texto, y, fonte, fill=WHITE, bg=ACCENT, padx=50, pady=26, radius=40):
    b = draw.textbbox((0, 0), texto, font=fonte)
    w, h = b[2] - b[0], b[3] - b[1]
    x0 = (W - w) // 2 - padx
    draw.rounded_rectangle([x0, y, x0 + w + 2 * padx, y + h + 2 * pady], radius=radius, fill=bg)
    draw.text(((W - w) // 2 - b[0], y + pady - b[1]), texto, font=fonte, fill=fill)
    return h + 2 * pady


def _wrap(draw, texto, fonte, largura, max_linhas=3):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        t = (atual + " " + p).strip()
        if draw.textlength(t, font=fonte) <= largura:
            atual = t
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1].rstrip(".,; ")[:-1] + "..."
    return linhas


def _frame(item, tmp):
    img = _baixar_imagem(item["img_url"])
    bg = ImageOps.fit(img, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    prod = ImageOps.contain(img, (940, 940), Image.LANCZOS)
    bg.paste(prod, ((W - prod.width) // 2, 620))
    bg_path = os.path.join(tmp, "bg.png")
    bg.save(bg_path)

    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, 440], fill=(0, 0, 0, 150))
    _centro(d, "ACHADINHO DA SHOPEE", 80, _font(50), fill=(255, 214, 0))
    y = 185
    for ln in _wrap(d, item["nome"], _font(52), W - 140):
        y += _centro(d, ln, y, _font(52), stroke=2) + 16
    ptxt = "R$ " + f"{item['preco']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    _centro_box(d, ptxt, 1560, _font(92))
    _centro_box(d, "COMENTA LINK", 1740, _font(52), fill=(0, 0, 0), bg=WHITE, pady=18)
    _centro(d, "@radar.de.preco.baixo", 1850, _font(34, bold=False))
    ov_path = os.path.join(tmp, "overlay.png")
    ov.save(ov_path)
    return bg_path, ov_path


def gerar(item_id, force=False):
    item = _carregar_item(item_id)
    os.makedirs(QUEUE, exist_ok=True)
    out = os.path.join(QUEUE, f"{item['item_id']}.mp4")
    if os.path.exists(out) and not force:
        print(out)
        return out
    frames = FPS * DUR
    tmp = tempfile.mkdtemp(prefix="reel_")
    try:
        bg, ov = _frame(item, tmp)
        filt = (f"[0:v]scale=1620:2880,zoompan=z='min(zoom+0.0006,1.15)':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[v];"
                f"[v][1:v]overlay=0:0,format=yuv420p[o]")
        cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", bg, "-i", ov,
               "-filter_complex", filt, "-map", "[o]", "-frames:v", str(frames),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def reservar(item):
    """Reserva o produto no historico (sem contar como publicacao) com link de afiliado."""
    hist = {}
    if os.path.exists(HIST):
        with open(HIST, "r", encoding="utf-8") as fh:
            hist = json.load(fh)
    iid = str(item.get("itemId"))
    if iid in hist:
        return
    valor = float(item.get("priceMin") or 0)
    preco_txt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sid = item.get("shopId")
    hist[iid] = {
        "item_id": int(iid) if iid.isdigit() else iid,
        "shop_id": int(str(sid)) if str(sid).isdigit() else sid,
        "seller_product_key": f"{sid}_{iid}",
        "title": item.get("productName"),
        "price": preco_txt,
        "discount": int(item.get("priceDiscountRate") or 0),
        "posted_at": 0,
        "short_link": item.get("offerLink") or "",
        "theme": "reel",
        "story_id": None,
        "reserved_for_reel": True,
    }
    tmp = HIST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, HIST)


def candidatos(limite=8):
    """Ofertas novas (nunca publicadas) direto da Shopee - modelo reel-first."""
    from shopee_engine import buscar_melhores_ofertas

    with open(HIST, "r", encoding="utf-8") as fh:
        hist = json.load(fh)
    ofertas = buscar_melhores_ofertas(min_desconto=15, limit_fetch=40, min_preco=PRECO_MIN)
    escolhidos = []
    for of in ofertas:
        iid = str(of.get("itemId") or "")
        if not iid or iid in hist:
            continue
        if float(of.get("priceMin") or 0) < PRECO_MIN:
            continue
        escolhidos.append(of)
        if len(escolhidos) >= limite:
            break
    return escolhidos


def auto(force=False, extra=None):
    """Modo automatico: delega ao publicador canonico reel_auto.py.

    Descobre a melhor oferta FRESCA (ausente de historico/fila, preco >= piso,
    vendedor inedito), renderiza 1080x1920, publica no Instagram e VERIFICA o
    media_id no Graph API. Flags extras sao repassadas (ex.: --dry-run).
    """
    import reel_auto
    argv = ["--publish"] + list(extra or [])
    if force:
        argv.append("--force")
    return reel_auto.main(argv)


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("uso: reel_factory.py <item_id|auto> [--force] [--dry-run]")
        return 1
    force = "--force" in argv
    extra = [a for a in argv if a.startswith("--") and a != "--force"]
    args = [a for a in argv if not a.startswith("--")]
    if args[0] == "auto":
        print(auto(force=force, extra=extra))
    else:
        print(gerar(args[0], force=force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
