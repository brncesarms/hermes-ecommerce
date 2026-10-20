#!/usr/bin/env python3
"""
==============================================================================
HERMES MANYCHAT BRIDGE (v1.0)
Servidor Webhook Dinâmico de Produtos Shopee para ManyChat
==============================================================================
Recebe requisições do ManyChat (Story Reply ou DM), consulta o histórico de
ofertas no Geekom e retorna o produto exato e seu link comissionado em formato
ManyChat Dynamic Block v2 + campos planos para mapeamento.
==============================================================================
"""

import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORICO_PATH = DATA_DIR / "historico_posts.json"
LOG_PATH = DATA_DIR / "manychat_bridge.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("hermes.manychat_bridge")


def carregar_produtos() -> list[dict]:
    """Carrega os produtos do histórico persistente ordenados por mais recentes."""
    if not HISTORICO_PATH.exists():
        return []
    try:
        with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
            historico = json.load(f)
            itens = []
            for item_id, dados in historico.items():
                d = dict(dados)
                d["item_id"] = item_id
                itens.append(d)
            itens.sort(key=lambda x: x.get("posted_at", 0), reverse=True)
            return itens
    except Exception as e:
        logger.error(f"Erro ao ler historico_posts.json: {e}")
        return []


def resolver_produto(story_id: str, texto_busca: str, produtos: list[dict]) -> dict | None:
    """Identifica o produto correspondente por story_id ou busca textual."""
    if not produtos:
        return None

    # 1. Por Story ID exato
    if story_id:
        sid_limpo = str(story_id).strip()
        for p in produtos:
            if str(p.get("story_id", "")).strip() == sid_limpo:
                logger.info(f"Produto encontrado por story_id={sid_limpo}: {p.get('title')[:30]}")
                return p

    # 2. Por palavras-chave no texto
    if texto_busca:
        t_busca = texto_busca.lower()
        for p in produtos:
            titulo = p.get("title", "").lower()
            palavras = [w for w in re.findall(r"\b\w{4,}\b", titulo) if w not in ["para", "com", "inox", "cozinha", "produto"]]
            matches = sum(1 for w in palavras if w in t_busca)
            if matches >= 2:
                logger.info(f"Produto encontrado por busca textual: {p.get('title')[:30]}")
                return p

    # 3. Sem correspondência válida
    logger.info("Nenhum produto correspondente encontrado por story_id ou palavras-chave.")
    return None


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ["/", "/health"]:
            self._responder_json(200, {"status": "ok", "service": "hermes-manychat-bridge", "version": "1.0"})
            return

        if parsed.path in ["/api/product", "/webhook", "/api/shopee/product"]:
            params = parse_qs(parsed.query)
            story_id = params.get("story_id", [""])[0]
            texto_busca = params.get("text", params.get("query", params.get("keyword", [""])))[0]
            self._processar_consulta(story_id, texto_busca)
            return

        self._responder_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

        story_id = ""
        texto_busca = ""

        # Tentar ler como JSON
        if body:
            try:
                dados = json.loads(body)
                story_id = str(dados.get("story_id", dados.get("last_story_id", "")))
                texto_busca = str(dados.get("text", dados.get("user_input", dados.get("last_input_text", ""))))
            except Exception:
                # Tentar ler como form-urlencoded
                params = parse_qs(body)
                story_id = params.get("story_id", [""])[0]
                texto_busca = params.get("text", params.get("query", [""]))[0]

        # Se vier por query param também
        qs = parse_qs(parsed.query)
        if not story_id and "story_id" in qs:
            story_id = qs["story_id"][0]
        if not texto_busca and "text" in qs:
            texto_busca = qs["text"][0]

        self._processar_consulta(story_id, texto_busca)

    def _processar_consulta(self, story_id: str, texto_busca: str):
        produtos = carregar_produtos()
        produto = resolver_produto(story_id, texto_busca, produtos)

        if not produto:
            resposta = {
                "status": "not_found",
                "message": "Nenhum produto encontrado no momento.",
                "url": "https://t.me/radardeprecobaixo",
                "version": "v2",
                "content": {
                    "type": "instagram",
                    "messages": [
                        {
                            "type": "text",
                            "text": "Oi! 🛍️ Não encontrei o link desse produto no momento, mas veja todas as ofertas com desconto no nosso Canal VIP:",
                            "buttons": [
                                {
                                    "type": "url",
                                    "caption": "🚀 Ver Canal VIP Telegram",
                                    "url": "https://t.me/radardeprecobaixo"
                                }
                            ]
                        }
                    ]
                }
            }
            self._responder_json(200, resposta)
            return

        titulo = produto.get("title", "")
        if len(titulo) > 55:
            titulo = titulo[:52] + "..."
        preco = produto.get("price", "")
        link = produto.get("short_link", "")

        texto_msg = (
            f"Oi! 🛍️ Aqui está o link com desconto exclusivo que você pediu no Story:\n\n"
            f"⚡ {titulo}\n"
            f"💰 Preço promocional: {preco}\n\n"
            f"🚚 Dica de Ouro: Resgate os cupons de frete grátis no app da Shopee antes de finalizar o pedido!"
        )

        resposta = {
            "status": "success",
            "title": titulo,
            "price": preco,
            "url": link,
            "short_link": link,
            "message": texto_msg,
            # Formato ManyChat Dynamic Content v2
            "version": "v2",
            "content": {
                "type": "instagram",
                "messages": [
                    {
                        "type": "text",
                        "text": texto_msg,
                        "buttons": [
                            {
                                "type": "url",
                                "caption": "👉 Ver Oferta na Shopee",
                                "url": link
                            }
                        ]
                    }
                ]
            }
        }
        self._responder_json(200, resposta)

    def _responder_json(self, status_code: int, dados: dict):
        corpo = json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(corpo)


def main():
    porta = 8050
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), BridgeHandler)
    logger.info(f"Hermes ManyChat Bridge escutando em http://127.0.0.1:{porta}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando servidor...")
        servidor.server_close()


if __name__ == "__main__":
    main()
