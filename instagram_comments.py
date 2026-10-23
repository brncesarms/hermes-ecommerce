#!/usr/bin/env python3
"""Fase 1c - Comentario -> Direct (Instagram Graph API).

Le comentarios dos posts/Reels mais recentes, responde publicamente e envia
o link de afiliado por Private Reply. Mapeia media_id/story_id -> produto no
historico_posts.json. Estado proprio para nao disputar o state do DM responder.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_DIR = Path("/home/brn/.hermes/ecommerce")
CONFIG_PATH = BASE_DIR / "credentials.env"
HISTORICO_PATH = BASE_DIR / "data" / "historico_posts.json"
STATE_PATH = BASE_DIR / "data" / "instagram_comments_state.json"
LOG_PATH = BASE_DIR / "data" / "instagram_comments.log"

MAX_AGE_HOURS_DEFAULT = 168
PUBLIC_REPLY = "Te mandei o link com desconto no Direct. Confere la!"

GATILHOS = [
    "quero", "eu quero", "link", "preco", "preço", "valor", "quanto custa",
    "comprar", "manda", "onde acho", "onde comprar", "shopee", "cupom",
    "desconto", "passa", "envia", "promocao", "promoção", "tenho interesse",
]
NEGACOES = [
    "nao quero", "não quero", "nao vou comprar", "não vou comprar",
    "nao preciso", "não preciso", "sem link",
]

logger = logging.getLogger("instagram_comments")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _h = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
    _s = logging.StreamHandler()
    _s.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_s)


def carregar_configuracoes() -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_GRAPH_URL", "INSTAGRAM_USERNAME"):
        if os.getenv(k):
            cfg[k] = os.getenv(k, "")
    return cfg


CFG = carregar_configuracoes()


def carregar_produtos() -> List[Dict[str, Any]]:
    if not HISTORICO_PATH.exists():
        return []
    try:
        with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
            historico = json.load(f)
        itens = []
        for item_id, dados in historico.items():
            d = dict(dados)
            d.setdefault("item_id", item_id)
            itens.append(d)
        itens.sort(key=lambda x: x.get("posted_at", 0), reverse=True)
        return itens
    except Exception as e:
        logger.warning(f"Erro ao ler historico_posts.json: {e}")
        return []


def carregar_estado() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler estado de comentarios: {e}")
    return {}


def salvar_estado(estado: Dict[str, Any]) -> None:
    try:
        ids = estado.get("processed_comment_ids", [])
        if len(ids) > 2000:
            estado["processed_comment_ids"] = ids[-2000:]
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
        tmp.replace(STATE_PATH)
    except Exception as e:
        logger.error(f"Erro ao salvar estado de comentarios: {e}")


def normalizar(texto: str) -> str:
    t = (texto or "").lower()
    return re.sub(r"\s+", " ", t).strip()


def verificar_intencao_compra(texto: str) -> bool:
    t = normalizar(texto)
    if not t:
        return False
    if any(n in t for n in NEGACOES):
        return False
    return any(g in t for g in GATILHOS)


def _graph_get(url: str, params: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    ultimo = ""
    for tentativa in range(1, 4):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}: {r.text[:250]}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * tentativa)
                continue
            break
        except Exception as e:
            ultimo = str(e)
            time.sleep(2 * tentativa)
    raise RuntimeError(ultimo)


def _graph_post(url: str, payload: Any, token: str, timeout: int = 15, json_body: bool = False) -> Tuple[bool, str]:
    ultimo = ""
    for tentativa in range(1, 4):
        try:
            if json_body:
                r = requests.post(url, json=payload, params={"access_token": token}, timeout=timeout)
            else:
                body = dict(payload)
                body["access_token"] = token
                r = requests.post(url, data=body, timeout=timeout)
            if r.status_code == 200:
                return True, r.text[:250]
            ultimo = f"HTTP {r.status_code}: {r.text[:250]}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * tentativa)
                continue
            break
        except Exception as e:
            ultimo = str(e)
            time.sleep(3 * tentativa)
    return False, ultimo


def indice_produtos_por_midia(produtos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    indice: Dict[str, Dict[str, Any]] = {}
    for p in produtos:
        for campo in ("media_id", "story_id"):
            valor = str(p.get(campo) or "").strip()
            if valor:
                indice.setdefault(valor, p)
    return indice


def link_do_produto(produto: Dict[str, Any]) -> str:
    return str(produto.get("short_link") or produto.get("affiliate_link") or produto.get("shopee_url") or "").strip()


def texto_direct(produto: Dict[str, Any]) -> str:
    titulo = str(produto.get("title", ""))[:80]
    preco = str(produto.get("price", "")).strip()
    link = link_do_produto(produto)
    linhas = ["Aqui esta o achado que voce pediu:"]
    if titulo:
        linhas.append(titulo)
    if preco:
        linhas.append(f"Por {preco}")
    linhas.append(link)
    linhas.append("Corre que o estoque e limitado.")
    return "\n".join([l for l in linhas if l])


def _idade_horas(timestamp: str) -> float:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return 0.0


def processar_comentarios(dry_run: bool = False, max_media: int = 10, max_age_hours: float = MAX_AGE_HOURS_DEFAULT) -> int:
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    ig_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0").rstrip("/")
    username = CFG.get("INSTAGRAM_USERNAME", "").lstrip("@").lower()

    if not token or not ig_id:
        logger.error("Credenciais do Instagram ausentes em credentials.env.")
        return 0

    estado = carregar_estado()
    processados = set(str(x) for x in estado.get("processed_comment_ids", []))
    produtos = carregar_produtos()
    indice = indice_produtos_por_midia(produtos)

    try:
        midias = _graph_get(
            f"{base_url}/{ig_id}/media",
            {
                "fields": "id,media_type,media_product_type,permalink,caption,timestamp,comments_count",
                "limit": max_media,
                "access_token": token,
            },
        ).get("data", [])
    except Exception as e:
        logger.error(f"Falha ao listar midias: {e}")
        return 0

    logger.info(f"Midias analisadas: {len(midias)} | produtos indexados: {len(indice)}")
    enviados = 0

    for midia in midias:
        media_id = str(midia.get("id") or "")
        if not media_id:
            continue
        produto = indice.get(media_id)
        try:
            comentarios = _graph_get(
                f"{base_url}/{media_id}/comments",
                {"fields": "id,text,username,timestamp", "limit": 50, "access_token": token},
            ).get("data", [])
        except Exception as e:
            logger.warning(f"Falha ao ler comentarios de {media_id}: {e}")
            continue

        if comentarios:
            logger.info(f"Midia {media_id} ({midia.get('media_product_type') or midia.get('media_type')}): {len(comentarios)} comentario(s)")
        time.sleep(0.3)

        for c in comentarios:
            cid = str(c.get("id") or "")
            if not cid or cid in processados:
                continue
            autor = str(c.get("username") or "").lower()
            if autor and username and autor == username:
                processados.add(cid)
                continue
            texto = str(c.get("text") or "")
            if not verificar_intencao_compra(texto):
                continue
            if _idade_horas(str(c.get("timestamp") or "")) > max_age_hours:
                logger.info(f"Comentario {cid} fora da janela de {max_age_hours:.0f}h. Ignorado.")
                processados.add(cid)
                continue
            if not produto:
                logger.warning(f"Comentario {cid} com intencao, mas midia {media_id} sem produto mapeado. Pulando.")
                continue
            link = link_do_produto(produto)
            if not link:
                logger.warning(f"Produto do comentario {cid} sem short_link. Pulando.")
                continue

            logger.info(f"Intencao detectada [{cid}] @{autor or '?'}: {texto[:80]!r} -> {str(produto.get('title',''))[:45]}")
            if dry_run:
                logger.info(f"[DRY-RUN] Responderia publico + private reply com {link}")
                enviados += 1
                continue

            ok_pub, msg_pub = _graph_post(
                f"{base_url}/{cid}/replies",
                {"message": PUBLIC_REPLY},
                token,
            )
            if ok_pub:
                logger.info(f"Resposta publica enviada em {cid}")
            else:
                logger.warning(f"Falha na resposta publica {cid}: {msg_pub}")

            ok_dm, msg_dm = _graph_post(
                f"{base_url}/{ig_id}/messages",
                {"recipient": {"comment_id": cid}, "message": {"text": texto_direct(produto)}},
                token,
                json_body=True,
            )
            if ok_dm:
                enviados += 1
                estado["total_private_replies"] = int(estado.get("total_private_replies", 0)) + 1
                logger.info(f"Private reply enviada para comentario {cid}")
                processados.add(cid)
            else:
                logger.warning(f"Falha na private reply {cid}: {msg_dm}")
            time.sleep(1.0)

    estado["processed_comment_ids"] = list(processados)
    estado["last_check"] = time.time()
    salvar_estado(estado)
    return enviados


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram Comentario -> Direct")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e sai")
    parser.add_argument("--interval", type=int, default=120, help="Intervalo do loop em segundos (padrao: 120)")
    parser.add_argument("--dry-run", action="store_true", help="Le a API mas nao responde")
    parser.add_argument("--max-media", type=int, default=10, help="Quantidade de midias recentes a varrer")
    parser.add_argument("--max-age-hours", type=float, default=MAX_AGE_HOURS_DEFAULT, help="Idade maxima do comentario")
    args = parser.parse_args()

    if args.once:
        n = processar_comentarios(args.dry_run, args.max_media, args.max_age_hours)
        logger.info(f"Ciclo concluido. Respostas: {n}")
        return

    while True:
        try:
            processar_comentarios(args.dry_run, args.max_media, args.max_age_hours)
        except Exception as e:
            logger.error(f"Erro no ciclo de comentarios: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
