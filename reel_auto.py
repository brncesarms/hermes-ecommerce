#!/usr/bin/env python3
"""Gerador AUTONOMO de Reels: descobre oferta fresca, renderiza e publica.

Uso:
    python3 reel_auto.py [--limit N] [--force] [--dry-run] [--publish] [--quiet]

Fluxo com --publish:
    1. roda `shopee_engine.py discover --limit N` (JSON array de ofertas)
    2. escolhe a melhor oferta FRESCA (itemId ausente de historico_posts.json e
       da fila) com preco >= piso (R$ 100) e cujo VENDEDOR (shopId) tambem nao
       esta no historico (o cooldown e por produto E por vendedor)
    3. renderiza data/reels_queue/<item_id>.mp4 (reel_factory._frame + ffmpeg)
    4. registra a oferta no historico (registro da publicacao)
    5. publica via `instagram_reels.py --item-id <id> --video <mp4> --force`
       (o --force anula o falso positivo de cooldown gerado pela propria entrada)
    6. VERIFICA o resultado no Graph API (read-back do media_id)
    7. move o mp4 para data/reels_posted/

Sem --publish apenas renderiza (nao toca no historico nem publica).
Com --quiet fica silencioso (exit 0, sem stdout) quando nao ha oferta elegivel.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import reel_factory as rf  # noqa: E402

HIST = os.path.join(BASE, "data", "historico_posts.json")
QUEUE = os.path.join(BASE, "data", "reels_queue")
POSTED = os.path.join(BASE, "data", "reels_posted")
ENGINE = os.path.join(BASE, "shopee_engine.py")
PUBLISHER = os.path.join(BASE, "instagram_reels.py")
CREDS = os.path.join(BASE, "credentials.env")


COOLDOWN_FAMILIA_DIAS = 7

# BLACKLIST PERMANENTE (ordem direta do Bruno, 22/10/2026): familias que NUNCA
# devem ser publicadas, em nenhum pipeline. Adicione/remova aqui.
FAMILIAS_BLOQUEADAS = {"mala_viagem"}

FAMILIAS_KEYWORDS = {
    "mala_viagem": ["mala", "bordo", "viagem", "frasqueira", "bagagem", "rodinhas 360"],
    "air_fryer": ["air fryer", "airfryer", "fritadeira"],
    "aspirador": ["aspirador", "robo aspirador", "roborock"],
    "fone_audio": ["fone de ouvido", "headset", "earbuds", "airpods"],
    "cadeira_gamer": ["cadeira gamer", "cadeira ergonomica", "cadeira de escritorio"],
    "teclado_mouse": ["teclado mecanico", "teclado gamer", "mouse gamer", "mouse sem fio"],
    "ventilador_ar": ["ventilador", "climatizador", "umidificador", "ar condicionado"],
    "panela_cozinha": ["panela", "frigideira", "jogo de panelas", "cacarola"],
    "copo_termico": ["copo termico", "garrafa termica", "stanley", "arete"],
    "relogio_smart": ["smartwatch", "relogio inteligente", "smartband"],
}

def _remover_acentos(texto):
    mapa = str.maketrans("áàãâéêíóôõúüçÁÀÃÂÉÊÍÓÔÕÚÜÇ", "aaaaeeiooouucAAAAEEIOOOUUC")
    return texto.translate(mapa)

def _familia_produto(nome):
    txt = _remover_acentos(str(nome or "").lower())
    for fam, kws in FAMILIAS_KEYWORDS.items():
        for kw in kws:
            if re.search(r"\b" + re.escape(_remover_acentos(kw)) + r"\b", txt):
                return fam
    return None

TEMAS_POR_KEYWORD = {
    "gamer": "informatica", "teclado": "informatica", "mouse": "informatica",
    "monitor": "informatica", "cadeira": "informatica", "setup": "informatica",
    "cozinha": "casa", "air fryer": "casa", "aspirador": "casa", "panela": "casa",
    "casa": "casa", "beleza": "feminino", "maquiagem": "feminino", "moda": "feminino",
    "bebe": "feminino", "brinquedo": "achados", "organizador": "achados",
}


def _creds():
    d = {}
    if not os.path.exists(CREDS):
        return d
    with open(CREDS, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def _tema(oferta):
    txt = (str(oferta.get("productName") or "") + " " + str(oferta.get("_keyword_origem") or "")).lower()
    for kw, tema in TEMAS_POR_KEYWORD.items():
        if kw in txt:
            return tema
    return "achados"


def _carregar_hist():
    try:
        with open(HIST, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _publicado(v):
    """True se a entrada do historico representa PUBLICACAO real (Story/Feed/Reel).

    Entradas apenas RESERVADAS (reserved_for_reel / posted_at 0, sem media_id e
    sem story_id) nao bloqueiam: sao placeholders e ainda podem ser publicadas.
    """
    if not isinstance(v, dict):
        return True
    if v.get("media_id") or v.get("story_id"):
        return True
    if v.get("reserved_for_reel") or not v.get("posted_at"):
        return False
    return True


def _historico_ids(hist):
    ids = set()
    for k, v in hist.items():
        if not _publicado(v):
            continue
        ids.add(str(k))
        if isinstance(v, dict):
            for campo in ("item_id", "itemId"):
                if v.get(campo):
                    ids.add(str(v[campo]))
    return ids


def _fila_ids():
    if not os.path.isdir(QUEUE):
        return set()
    return {f[:-4] for f in os.listdir(QUEUE) if f.endswith(".mp4")}


def descobrir(limite=15):
    r = subprocess.run([sys.executable, ENGINE, "discover", "--limit", str(limite)],
                       capture_output=True, text=True, cwd=BASE)
    if r.returncode != 0:
        raise SystemExit(f"discover falhou (exit {r.returncode}): {r.stderr[-500:]}")
    txt = r.stdout.strip()
    ini = txt.find("[")
    if ini < 0:
        raise SystemExit(f"discover sem JSON na saida: {txt[-300:]}")
    try:
        return json.loads(txt[ini:])
    except json.JSONDecodeError as e:
        raise SystemExit(f"JSON invalido do discover: {e}")


def escolher(ofertas, hist, force=False):
    ids_hist = _historico_ids(hist)
    vendedores_hist = {str(v.get("shop_id") or v.get("shopId"))
                       for v in hist.values() if isinstance(v, dict) and _publicado(v)}
    agora = time.time()
    limite_familia = agora - (COOLDOWN_FAMILIA_DIAS * 86400)
    familias_recentes = set()
    for v in hist.values():
        if isinstance(v, dict) and _publicado(v):
            p_at = float(v.get("posted_at") or 0)
            if p_at > agora:
                p_at = agora
            if p_at >= limite_familia:
                fam = v.get("family") or _familia_produto(v.get("title") or "")
                if fam:
                    familias_recentes.add(fam)
    fila = _fila_ids()
    cands = []
    cands = []
    for o in ofertas:
        if not isinstance(o, dict):
            continue
        iid = str(o.get("itemId") or o.get("item_id") or "")
        if not iid or iid in fila or os.path.exists(os.path.join(QUEUE, f"{iid}.mp4")):
            continue
        if not force and iid in ids_hist:
            continue
        if not force and str(o.get("shopId")) in vendedores_hist:
            continue
        fam_candidato = _familia_produto(o.get("productName") or "")
        if fam_candidato in FAMILIAS_BLOQUEADAS:
            print(f"[BLACKLIST] Ignorando familia bloqueada permanentemente: {fam_candidato}")
            continue
        if not force and fam_candidato and fam_candidato in familias_recentes:
            continue
        preco = rf._preco_float(o.get("priceMin") or o.get("price") or o.get("preco"))
        if preco < rf.PRECO_MIN:
            continue
        cands.append((float(o.get("_viral_score") or 0.0), iid, preco, o))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)
    return cands[0]


def renderizar(item_id, nome, preco, img_url, force=False):
    os.makedirs(QUEUE, exist_ok=True)
    out = os.path.join(QUEUE, f"{item_id}.mp4")
    if os.path.exists(out) and not force:
        print(f"[REEL JA EXISTE] {out}")
        return out
    item = {"item_id": str(item_id), "nome": str(nome), "preco": float(preco), "img_url": str(img_url)}
    frames = rf.FPS * rf.DUR
    tmp = tempfile.mkdtemp(prefix="reel_auto_")
    try:
        bg, ov = rf._frame(item, tmp)
        filt = (f"[0:v]scale=1620:2880,zoompan=z='min(zoom+0.0006,1.15)':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={rf.W}x{rf.H}:fps={rf.FPS}[v];"
                f"[v][1:v]overlay=0:0,format=yuv420p[o]")
        cmd = [rf.FFMPEG, "-y", "-loglevel", "error", "-i", bg, "-i", ov,
               "-filter_complex", filt, "-map", "[o]", "-frames:v", str(frames),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"[REEL GERADO] {out}")
    return out


def registrar(oferta, iid):
    hist = _carregar_hist()
    if iid in hist:
        return hist, False
    hist[iid] = {
        "item_id": int(iid),
        "shop_id": oferta.get("shopId"),
        "seller_product_key": f"{oferta.get('shopId')}_{iid}",
        "title": oferta.get("productName"),
        "price": f"R$ {str(oferta.get('priceMin')).replace('.', ',')}",
        "discount": oferta.get("priceDiscountRate"),
        "posted_at": time.time(),
        "posted_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "short_link": oferta.get("offerLink"),
        "theme": _tema(oferta),
        "family": _familia_produto(oferta.get("productName")),
    }
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return hist, True


def desregistrar(iid):
    hist = _carregar_hist()
    if iid in hist:
        del hist[iid]
        with open(HIST, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
        print(f"[ROLLBACK] entrada {iid} removida do historico")


def publicar(iid, video):
    r = subprocess.run([sys.executable, PUBLISHER, "--item-id", str(iid), "--video", video, "--force"],
                       capture_output=True, text=True, cwd=BASE)
    saida = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"media_id=(\d+)", saida)
    return r.returncode, (m.group(1) if m else None), saida


def verificar(media_id):
    c = _creds()
    base = (c.get("INSTAGRAM_GRAPH_URL") or "https://graph.instagram.com/v21.0").rstrip("/")
    tok = c.get("INSTAGRAM_ACCESS_TOKEN")
    if not tok:
        return None
    url = f"{base}/{media_id}?fields=id,media_type,media_product_type,permalink,timestamp&access_token={tok}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode())
        return None if "error" in d else d
    except Exception as e:
        return {"erro": str(e)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reel autonomo de oferta fresca da Shopee")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--force", action="store_true", help="ignora historico/cooldown")
    ap.add_argument("--dry-run", action="store_true", help="mostra a oferta escolhida sem renderizar")
    ap.add_argument("--publish", action="store_true", help="publica no Instagram e verifica")
    ap.add_argument("--quiet", action="store_true", help="sem saida quando nao ha oferta elegivel")
    args = ap.parse_args(argv)

    hist = _carregar_hist()
    ofertas = descobrir(args.limit)
    if not isinstance(ofertas, list):
        ofertas = ofertas.get("data") if isinstance(ofertas, dict) else []
    esc = escolher(ofertas, hist, force=args.force)
    if not esc:
        if not args.quiet:
            print("[AUTO] Nenhuma oferta fresca elegivel (>= R$ 100 e ausente de historico/fila).")
        return 0
    score, iid, preco, o = esc
    print(f"[AUTO] Oferta: {iid} | R$ {preco:.2f} | -{o.get('priceDiscountRate')}% | score {score:.2f}")
    print(f"[AUTO] {o.get('productName')}")
    if args.dry_run:
        return 0

    video = renderizar(iid, o.get("productName"), preco, o.get("imageUrl"), force=args.force)
    if not args.publish:
        print(json.dumps({"item_id": iid, "video": video, "price": preco, "score": score}))
        return 0

    _hist, criado = registrar(o, iid)
    rc, media_id, saida = 1, None, ""
    for tentativa in range(1, 4):
        rc, media_id, saida = publicar(iid, video)
        if rc == 0 and media_id:
            break
        if tentativa < 3:
            print(f"[RETRY {tentativa}/3] Meta recusou o Reel {iid}; nova tentativa em 20s")
            time.sleep(20)
    if rc != 0 or not media_id:
        print(saida[-1500:])
        if criado:
            desregistrar(iid)
        print(f"[ERRO] Falha ao publicar o Reel {iid} (exit {rc}); fila mantida.")
        return 1

    ver = verificar(media_id)
    if not ver or ver.get("erro") or str(ver.get("id")) != str(media_id):
        print(f"[ALERTA] media_id {media_id} nao confirmado no Graph API: {ver}")
        return 1

    os.makedirs(POSTED, exist_ok=True)
    try:
        shutil.move(video, os.path.join(POSTED, os.path.basename(video)))
    except Exception as e:
        print(f"[AVISO] nao movi o mp4 para reels_posted: {e}")

    print(f"[OK] Reel publicado e verificado: {ver.get('permalink')} | "
          f"{ver.get('media_product_type')} | {ver.get('timestamp')} | media_id={media_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
