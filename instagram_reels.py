#!/usr/bin/env python3
"""Fase 1a - Publicacao de Reels no Instagram.

Recebe um video (arquivo local ou URL publica) + item_id do historico e publica
como Reel com CTA de comentario, respeitando piso de R$ 100 e cooldown de 14 dias.
Grava o media_id no historico para o fluxo Comentario -> Direct (Fase 1c).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

BASE_DIR = Path("/home/brn/.hermes/ecommerce")
HISTORICO_PATH = BASE_DIR / "data" / "historico_posts.json"
COOLDOWN_HORAS = 336
VALOR_MINIMO = 100.0

HASHTAGS_TEMA = {
    "casa": "#achadinhosparacasa #cozinhaorganizada #utilidadesdomesticas #achadinhosdashopee",
    "informatica": "#setupgamer #achadinhosdeinformatica #perifericos #techbarato",
    "tech": "#tecnologia #gadgets #achadinhosdetech #shopeeachados",
    "achados": "#achadinhos #achadinhosdashopee #ofertadodia #achadinhosonline",
    "feminino": "#modafeminina #achadinhosdefeminino #beleza #autocuidado",
    "beleza": "#beleza #skincare #achadinhosdebeleza #autocuidado",
    "bebes": "#bebes #enxoval #maternidade #achadinhosparabebe",
}


def carregar_historico() -> Dict[str, Any]:
    with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_historico(historico: Dict[str, Any]) -> None:
    tmp = HISTORICO_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(historico, f, indent=2, ensure_ascii=False)
    tmp.replace(HISTORICO_PATH)


def preco_numerico(valor: Any) -> Optional[float]:
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = re.sub(r"[^\d.,]", "", str(valor or ""))
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "")
    try:
        return float(texto)
    except ValueError:
        return None


def verificar_cooldown(historico: Dict[str, Any], item_id: str) -> Optional[str]:
    alvo = historico.get(item_id, {})
    chave = alvo.get("seller_product_key") or f"{alvo.get('shop_id')}_{alvo.get('item_id')}"
    agora = time.time()
    for outro_id, dados in historico.items():
        outra_chave = dados.get("seller_product_key") or f"{dados.get('shop_id')}_{dados.get('item_id')}"
        if outro_id != item_id and outra_chave != chave:
            continue
        # Reserva feita pela fabrica de Reels ainda nao e publicacao: nao conta como cooldown.
        if outro_id == item_id and dados.get("reserved_for_reel") and not dados.get("reel_posted_at"):
            continue
        for campo in ("reel_posted_at", "posted_at"):
            ts = dados.get(campo)
            if not ts:
                continue
            try:
                ts_float = float(ts)
            except (TypeError, ValueError):
                continue
            idade_h = (agora - ts_float) / 3600.0
            if idade_h < COOLDOWN_HORAS:
                tipo = "Reel" if campo == "reel_posted_at" else "Story/Feed"
                return f"produto/vendedor publicado como {tipo} ha {idade_h:.1f}h ({outro_id})"
    return None


def montar_legenda(produto: Dict[str, Any]) -> str:
    titulo = str(produto.get("title") or "Achado do dia")
    preco = str(produto.get("price") or "").strip()
    desconto = produto.get("discount")
    tema = str(produto.get("theme") or "achados").lower()
    linhas = [titulo[:120]]
    if preco:
        linhas.append(f"Por {preco}" + (f" ({desconto}% OFF)" if desconto else ""))
    linhas.append("Comenta LINK que eu te mando no direct.")
    linhas.append("")
    linhas.append(HASHTAGS_TEMA.get(tema, HASHTAGS_TEMA["achados"]))
    linhas.append("#radardeprecobaixo")
    return "\n".join(linhas)


def _url_valida(url: str) -> bool:
    """A Meta so processa o video se a URL responder 200 com content-length > 0.

    O catbox.moe costuma devolver content-length: 0 recem-uploadado (container
    REELS vai para status ERROR); a litterbox ja respondeu 500. Valide sempre.
    """
    try:
        h = requests.head(url, timeout=30, allow_redirects=True)
        cl = int(h.headers.get("content-length") or 0)
        return h.status_code == 200 and cl > 0
    except Exception:
        return False


def _upload_uguu(arquivo: Path):
    try:
        with open(arquivo, "rb") as f:
            r = requests.post("https://uguu.se/upload.php", files={"files[]": f}, timeout=180)
        if r.status_code != 200:
            return None, f"uguu: status {r.status_code}"
        dados = r.json()
        url = (dados.get("files") or [{}])[0].get("url")
        if not url:
            return None, f"uguu: resposta sem url ({str(dados)[:80]})"
        return url, None
    except Exception as e:
        return None, f"uguu: {e}"


def hospedar_video(caminho: str) -> str:
    if caminho.startswith("http://") or caminho.startswith("https://"):
        return caminho
    arquivo = Path(caminho)
    if not arquivo.exists():
        raise FileNotFoundError(f"Video nao encontrado: {caminho}")
    erros = []

    # uguu primeiro: e o host que responde 200 com content-length valido hoje.
    url, erro = _upload_uguu(arquivo)
    if url and _url_valida(url):
        return url
    erros.append(erro or f"uguu: url sem content-length valido ({url})")

    for nome, url_api, dados in (
        ("litterbox", "https://litterbox.catbox.moe/resources/internals/api.php", {"reqtype": "fileupload", "time": "72h"}),
        ("catbox", "https://catbox.moe/user/api.php", {"reqtype": "fileupload"}),
    ):
        for tentativa in range(1, 3):
            try:
                with open(arquivo, "rb") as f:
                    r = requests.post(url_api, files={"fileToUpload": f}, data=dados, timeout=180)
                corpo = r.text.strip()
                if r.status_code == 200 and corpo.startswith("http"):
                    if _url_valida(corpo):
                        return corpo
                    erros.append(f"{nome} t{tentativa}: URL sem content-length valido ({corpo[:60]})")
                else:
                    erros.append(f"{nome} t{tentativa}: status {r.status_code} corpo {corpo[:80]!r}")
            except Exception as e:
                erros.append(f"{nome} t{tentativa}: {e}")
            time.sleep(2)
    raise RuntimeError(f"Falha ao hospedar video: {'; '.join(erros)}")


def publicar(item_id: str, video: str, dry_run: bool = False, force: bool = False, legenda_extra: str = "") -> int:
    historico = carregar_historico()
    produto = historico.get(item_id)
    if not produto:
        print(f"[ERRO] item_id {item_id} nao existe em historico_posts.json")
        return 2

    preco = preco_numerico(produto.get("price"))
    if preco is None:
        print("[ERRO] Produto sem preco legivel. Abortando por seguranca.")
        return 2
    if preco < VALOR_MINIMO:
        print(f"[BLOQUEADO] Piso de R$ {VALOR_MINIMO:.2f} violado: preco R$ {preco:.2f}.")
        return 3

    link = str(produto.get("short_link") or "").strip()
    if not link:
        print("[ERRO] Produto sem short_link de afiliado.")
        return 2

    motivo = verificar_cooldown(historico, item_id)
    if motivo and not force:
        print(f"[BLOQUEADO] Cooldown de 14 dias: {motivo}")
        return 4

    legenda = montar_legenda(produto)
    if legenda_extra:
        legenda = f"{legenda_extra}\n\n{legenda}"

    print("=" * 60)
    print(f"Item: {item_id} | {produto.get('title','')[:70]}")
    print(f"Preco: R$ {preco:.2f} | Link: {link}")
    print(f"Video: {video}")
    print("-" * 60)
    print(legenda)
    print("=" * 60)

    if dry_run:
        if not (video.startswith("http://") or video.startswith("https://")) and not os.path.exists(video):
            print(f"[AVISO] Video local inexistente: {video} (dry-run segue so validando dados).")
        print("[DRY-RUN] Nenhum upload/publicacao realizado.")
        return 0

    if not (video.startswith("http://") or video.startswith("https://")) and not os.path.exists(video):
        print(f"[ERRO] Video nao encontrado: {video}")
        return 2

    if os.path.exists(video):
        print("[UPLOAD] Hospedando video temporariamente...")
        video_url = hospedar_video(video)
        print(f"[UPLOAD] OK: {video_url}")
    else:
        video_url = video

    sys.path.insert(0, str(BASE_DIR))
    from shopee_engine import postar_reel_instagram

    print("[META] Criando container e publicando Reel...")
    resposta = postar_reel_instagram(video_url, legenda)
    media_id = str(resposta.get("id") or "")
    if not media_id:
        print(f"[ERRO] Meta nao retornou media_id: {resposta}")
        return 5

    historico[item_id]["media_id"] = media_id
    historico[item_id]["reel_posted_at"] = time.time()
    historico[item_id]["reel_posted_at_iso"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    historico[item_id]["reel_caption"] = legenda
    salvar_historico(historico)
    print(f"[OK] Reel publicado. media_id={media_id} registrado no historico.")
    return 0


def publicar_da_fila(dry_run: bool = False) -> int:
    """Publica o primeiro video valido da fila data/reels_queue (nome = <item_id>.mp4)."""
    fila_dir = BASE_DIR / "data" / "reels_queue"
    postados_dir = BASE_DIR / "data" / "reels_posted"
    fila_dir.mkdir(parents=True, exist_ok=True)
    postados_dir.mkdir(parents=True, exist_ok=True)
    arquivos = sorted([p for p in fila_dir.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".m4v")])
    if not arquivos:
        print("[FILA] Nenhum video em data/reels_queue.")
        return 0

    historico = carregar_historico()
    for arquivo in arquivos:
        item_id = arquivo.stem.split("__")[0].strip()
        produto = historico.get(item_id)
        if not produto:
            print(f"[FILA] {arquivo.name}: item_id {item_id} nao existe no historico. Ignorado.")
            continue
        preco = preco_numerico(produto.get("price"))
        if preco is None or preco < VALOR_MINIMO:
            print(f"[FILA] {arquivo.name}: preco invalido/abaixo do piso (R$ {preco}). Ignorado.")
            continue
        motivo = verificar_cooldown(historico, item_id)
        if motivo and "__force" not in arquivo.stem:
            print(f"[FILA] {arquivo.name}: cooldown ativo ({motivo}). Ignorado.")
            continue

        print(f"[FILA] Publicando {arquivo.name} (item {item_id})...")
        rc = publicar(item_id, str(arquivo), dry_run=dry_run)
        if rc == 0 and not dry_run:
            arquivo.rename(postados_dir / arquivo.name)
            print(f"[FILA] Video movido para {postados_dir}.")
        return rc
    print("[FILA] Nenhum video elegivel nesta execucao.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Publica Reel de produto do historico")
    parser.add_argument("--item-id", help="Chave do produto em historico_posts.json")
    parser.add_argument("--video", help="Caminho local do .mp4 ou URL publica HTTPS")
    parser.add_argument("--queue", action="store_true", help="Publica o primeiro video valido de data/reels_queue")
    parser.add_argument("--legenda-extra", default="", help="Linha extra no topo da legenda")
    parser.add_argument("--dry-run", action="store_true", help="Valida e mostra a legenda sem publicar")
    parser.add_argument("--force", action="store_true", help="Ignora cooldown de 14 dias (piso de preco continua ativo)")
    args = parser.parse_args()

    if args.queue:
        raise SystemExit(publicar_da_fila(args.dry_run))
    if not args.item_id or not args.video:
        parser.error("--item-id e --video sao obrigatorios (ou use --queue)")
    raise SystemExit(publicar(args.item_id, args.video, args.dry_run, args.force, args.legenda_extra))


if __name__ == "__main__":
    main()
