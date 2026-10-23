#!/usr/bin/env python3
"""Gera artes editoriais 1080x1350 para o Feed do Instagram.

Uso:
    python3 feed_factory.py boas-vindas [--out DIR]
    python3 feed_factory.py top [--out DIR] [--n 5]

As imagens sao gravadas em data/feed_queue/<slug>/ e publicadas com:
    python3 shopee_engine.py carousel --images a.png b.png c.png --caption "..."
"""
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

BASE = "/home/brn/.hermes/ecommerce"
FONTS = os.path.join(BASE, "fonts")
HIST = os.path.join(BASE, "data", "historico_posts.json")
OUT_ROOT = os.path.join(BASE, "data", "feed_queue")

W, H = 1080, 1350
ACCENT = (238, 77, 45)
WHITE = (255, 255, 255)
BG = (14, 14, 16)
CARD = (26, 26, 30)
MUTED = (168, 168, 176)
PRECO_MIN = 100.0

HANDLE = "@radar.de.preco.baixo"


def fonte(size, bold=True):
    nome = "Montserrat-ExtraBold.otf" if bold else "Montserrat-Medium.otf"
    caminho = os.path.join(FONTS, nome)
    try:
        return ImageFont.truetype(caminho, size)
    except OSError:
        return ImageFont.load_default()


def texto_centro(draw, texto, y, f, fill=WHITE, spacing=14):
    caixa = draw.multiline_textbbox((0, 0), texto, font=f, spacing=spacing, align="center")
    x = (W - (caixa[2] - caixa[0])) / 2 - caixa[0]
    draw.multiline_text((x, y), texto, font=f, fill=fill, spacing=spacing, align="center")
    return y + (caixa[3] - caixa[1])


def bloco_acento(draw, texto, y, f, padx=54, pady=26, radius=44):
    caixa = draw.textbbox((0, 0), texto, font=f)
    larg, alt = caixa[2] - caixa[0], caixa[3] - caixa[1]
    x0 = (W - larg) / 2 - padx
    y0 = y
    draw.rounded_rectangle(
        (x0, y0, x0 + larg + padx * 2, y0 + alt + pady * 2), radius=radius, fill=ACCENT
    )
    draw.text((W / 2 - larg / 2 - caixa[0], y0 + pady - caixa[1]), texto, font=f, fill=WHITE)
    return y0 + alt + pady * 2


def wrap(draw, texto, f, largura, max_linhas=4):
    palavras = texto.split()
    linhas = []
    atual = ""
    truncado = False
    for p in palavras:
        teste = (atual + " " + p).strip()
        if draw.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
            if len(linhas) >= max_linhas:
                truncado = True
                break
    if atual and len(linhas) < max_linhas:
        linhas.append(atual)
    elif atual and len(linhas) >= max_linhas:
        truncado = True
    if truncado and linhas:
        ult = linhas[-1]
        while ult and draw.textlength(ult + "...", font=f) > largura:
            partes = ult.split()
            if len(partes) <= 1:
                ult = ult[:-1]
            else:
                ult = " ".join(partes[:-1])
        linhas[-1] = (ult + "...") if ult else "..."
    return "\n".join(linhas)


def fundo(draw=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.ellipse((-260, -320, 420, 360), fill=(44, 22, 18))
    d.ellipse((W - 380, H - 420, W + 260, H + 200), fill=(38, 20, 16))
    return img, d


def rodape(draw, texto=HANDLE):
    f = fonte(34)
    texto_centro(draw, texto, H - 96, f, MUTED)


def slide_capa():
    img, d = fundo()
    d.rounded_rectangle((70, 96, 330, 152), radius=28, fill=ACCENT)
    d.text((98, 108), "RADAR", font=fonte(34), fill=WHITE)
    texto_centro(d, "DE PREÇO BAIXO", 178, fonte(40), MUTED)
    texto_centro(d, "ACHADOS", 320, fonte(150), WHITE)
    bloco_acento(d, "ACIMA DE R$100", 500, fonte(74))
    texto_centro(d, "que realmente\nvalem a pena", 700, fonte(86), WHITE, spacing=8)
    texto_centro(
        d,
        "Sem baratinho que quebra\nem uma semana.",
        960,
        fonte(44, False),
        MUTED,
        spacing=10,
    )
    rodape(d)
    return img


def slide_como_funciona():
    img, d = fundo()
    texto_centro(d, "COMO FUNCIONA", 120, fonte(76), WHITE)
    passos = [
        ("1", "A gente garimpa a Shopee e seleciona só o que passa de R$ 100 e vale o preço."),
        ("2", "Você comenta LINK no post do produto que te interessou."),
        ("3", "O link cai no seu direct em segundos. Sem cadastro, sem enrolação."),
    ]
    y = 280
    fnum, ftexto = fonte(64), fonte(44, False)
    for num, txt in passos:
        d.rounded_rectangle((70, y, W - 70, y + 240), radius=36, fill=CARD)
        d.ellipse((106, y + 32, 196, y + 122), fill=ACCENT)
        n = d.textbbox((0, 0), num, font=fnum)
        d.text((151 - (n[2] - n[0]) / 2 - n[0], y + 52), num, font=fnum, fill=WHITE)
        d.multiline_text(
            (232, y + 40),
            wrap(d, txt, ftexto, W - 360, 4),
            font=ftexto,
            fill=WHITE,
            spacing=10,
        )
        y += 268
    texto_centro(d, "4 publicações por dia. Só achado aprovado.", 1160, fonte(36), MUTED)
    rodape(d)
    return img


def slide_cta():
    img, d = fundo()
    texto_centro(d, "COMENTA", 260, fonte(104), WHITE)
    bloco_acento(d, "LINK", 430, fonte(190), padx=80, pady=20, radius=56)
    texto_centro(d, "que eu te mando\no link no direct", 790, fonte(64), WHITE, spacing=10)
    texto_centro(d, "Stories todo dia · Feed com os melhores", 1060, fonte(36), MUTED)
    rodape(d)
    return img


def slide_produto(indice, produto, total):
    img, d = fundo()
    d.rounded_rectangle((70, 90, 300, 146), radius=26, fill=ACCENT)
    d.text((98, 102), f"{indice}/{total}", font=fonte(34), fill=WHITE)
    titulo = produto.get("title") or "Achado aprovado"
    f = fonte(52)
    d.multiline_text((70, 200), wrap(d, titulo, f, W - 140, 2), font=f, fill=WHITE, spacing=12)
    preco_val = produto.get("price")
    texto_centro(d, formata_preco(preco_val), 560, fonte(120, True), WHITE)
    desconto = produto.get("discount")
    if desconto:
        d_str = str(desconto).replace("%", "").strip()
        bloco_acento(d, f"{d_str}% OFF", 740, fonte(64))
    texto_centro(d, "Comenta LINK que eu te mando no direct.", 980, fonte(42, False), MUTED)
    rodape(d)
    return img


def carregar_historicos():
    with open(HIST, encoding="utf-8") as fh:
        dados = json.load(fh)
    itens = dados.values() if isinstance(dados, dict) else dados
    return [i for i in itens if isinstance(i, dict)]


def parse_preco(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        m = re.search(r"[-+]?\d*\.?\d+", s)
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0


def formata_preco(v):
    val = parse_preco(v)
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def preco(v):
    return parse_preco(v)


def melhores(n):
    itens = [i for i in carregar_historicos() if parse_preco(i.get("price")) >= PRECO_MIN]
    itens.sort(key=lambda i: (i.get("discount") or 0, parse_preco(i.get("price"))), reverse=True)
    vistos, saida = set(), []
    for i in itens:
        chave = i.get("seller_product_key") or i.get("item_id")
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(i)
        if len(saida) >= n:
            break
    return saida


def salvar(imagens, slug):
    pasta = os.path.join(OUT_ROOT, slug)
    os.makedirs(pasta, exist_ok=True)
    caminhos = []
    for i, img in enumerate(imagens, 1):
        caminho = os.path.join(pasta, f"{i:02d}.png")
        img.save(caminho, "PNG", optimize=True)
        caminhos.append(caminho)
    return caminhos


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip())
        return 1
    modo = argv[0]
    if modo == "boas-vindas":
        caminhos = salvar([slide_capa(), slide_como_funciona(), slide_cta()], "boas-vindas")
    elif modo == "top":
        n = 5
        if "--n" in argv:
            n = int(argv[argv.index("--n") + 1])
        itens = melhores(n)
        if not itens:
            print("Nenhum produto >= R$ 100 no historico")
            return 3
        imagens = [slide_cta()]
        imagens = [slide_produto(i, p, len(itens)) for i, p in enumerate(itens, 1)]
        caminhos = salvar(imagens, "top-achados")
    else:
        print(f"Modo invalido: {modo}")
        return 2
    for c in caminhos:
        print(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
