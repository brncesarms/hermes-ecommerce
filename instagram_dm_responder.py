#!/usr/bin/env python3
"""
==============================================================================
HERMES INSTAGRAM DIRECT AUTO-RESPONDER (v1.0)
Serviço Autônomo de Resposta de DMs ("EU QUERO") para Hermes no Geekom
==============================================================================
Finalidade:
  1. Monitora a caixa de entrada (Direct Messages) da conta @radar.de.preco.baixo.
  2. Detecta quando um seguidor responde a um Story ou envia termos de compra
     ("QUERO", "LINK", "PREÇO", "ONDE COMPRO", "VALOR", etc.).
  3. Cruza o Story respondido com o historico_posts.json para identificar o
     produto exato e seu link de afiliado Shopee comissionado.
  4. Envia imediatamente via Meta Graph API a resposta no Direct com o link.
  5. Mantém controle persistente de IDs de mensagens já processadas para evitar
     duplicações ou loops.
==============================================================================
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "credentials.env"
HISTORICO_PATH = DATA_DIR / "historico_posts.json"
STATE_PATH = DATA_DIR / "dm_responder_state.json"
LOG_PATH = DATA_DIR / "dm_responder.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Configurar logging estruturado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("hermes.dm_responder")

def carregar_configuracoes() -> Dict[str, str]:
    """Carrega credenciais de credentials.env ou variáveis de ambiente."""
    cfg: Dict[str, str] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in [
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_GRAPH_URL",
    ]:
        if os.getenv(k):
            cfg[k] = os.getenv(k, "")
    return cfg

CFG = carregar_configuracoes()

def carregar_estado() -> Dict[str, Any]:
    """Carrega o histórico de mensagens já respondidas."""
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler estado de mensagens: {e}")
    return {"processed_message_ids": [], "total_replies_sent": 0, "last_check": 0}

def salvar_estado(estado: Dict[str, Any]) -> None:
    """Salva o estado no disco de forma defensiva."""
    try:
        # Manter no máximo os últimos 1000 IDs para não inchar o arquivo
        if len(estado.get("processed_message_ids", [])) > 1000:
            estado["processed_message_ids"] = estado["processed_message_ids"][-1000:]
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar estado de mensagens: {e}")

def carregar_produtos_ativos() -> List[Dict[str, Any]]:
    """Carrega os produtos postados recentemente do histórico ordenados por data."""
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
            # Ordenar pelos mais recentes primeiro
            itens.sort(key=lambda x: x.get("posted_at", 0), reverse=True)
            return itens
    except Exception as e:
        logger.warning(f"Erro ao ler historico_posts.json: {e}")
        return []

PALAVRAS_GATILHO = [
    "quero", "eu quero", "link", "preco", "preço", "valor", "quanto custa",
    "comprar", "manda o link", "onde acho", "onde comprar", "shopee", "cupom",
    "desconto", "qual o link", "passa o link", "envia o link", "promoção", "promocao"
]

def verificar_intencao_compra(texto: str) -> bool:
    """Verifica se a mensagem contém intenção genuína de compra ou pedido de link."""
    if not texto:
        return False
    t = texto.lower()
    # Ignora negações comuns (ex: "não quero", "não vou comprar")
    if re.search(r"\b(não|nao)\s+(quero|preciso|vou|tenho)\b", t):
        return False
    # Verifica ocorrência de termos gatilho com limites de palavra
    for g in PALAVRAS_GATILHO:
        if re.search(r"\b" + re.escape(g) + r"\b", t):
            return True
    return False

def extrair_story_id(story_info: Optional[Dict[str, Any]]) -> str:
    """Extrai com precisão o ID do Story a partir da estrutura Meta Graph API."""
    if not story_info or not isinstance(story_info, dict):
        return ""
    if story_info.get("id"):
        return str(story_info.get("id")).strip()
    reply_to = story_info.get("reply_to")
    if isinstance(reply_to, dict):
        if reply_to.get("id"):
            return str(reply_to.get("id")).strip()
        link = str(reply_to.get("link", ""))
        m = re.search(r"asset_id=(\d+)", link)
        if m:
            return m.group(1).strip()
    m = re.search(r"(\d{15,})", str(story_info))
    if m:
        return m.group(1).strip()
    return ""

def buscar_produto_correspondente(
    msg_texto: str,
    story_info: Optional[Dict[str, Any]],
    produtos: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Identifica o produto correto com base no Story ou no texto da mensagem.
    
    Retorna uma tupla (produto, motivo):
      - (produto, 'match_story'): Match exato por Story ID.
      - (produto, 'match_keyword'): Match por palavras-chave do título.
      - (None, 'story_nao_encontrado'): Mensagem veio de Story, mas o ID não foi mapeado no histórico.
      - (None, 'dm_sem_match'): Mensagem direta sem match com produtos ativos (não responder).
      - (None, 'sem_produtos'): Nenhum produto cadastrado no histórico.
    """
    if not produtos:
        return None, "sem_produtos"

    story_id = extrair_story_id(story_info)

    # 1. Se a mensagem veio como resposta a um Story específico
    if story_id:
        logger.info(f"Detectado Story ID na resposta: {story_id}")
        for p in produtos:
            if str(p.get("story_id", "")).strip() == story_id:
                logger.info(f"Match exato por Story ID {story_id} -> Produto: {p.get('title')[:35]}")
                return p, "match_story"

        logger.warning(f"Story ID {story_id} não encontrado no historico_posts.json ({len(produtos)} produtos cadastrados).")

        # 1.1 Tenta match por palavras-chave no texto caso o seguidor tenha citado o nome
        t_msg = msg_texto.lower()
        for p in produtos:
            titulo = p.get("title", "").lower()
            palavras_titulo = [w for w in re.findall(r"\b\w{4,}\b", titulo) if w not in ["para", "com", "inox", "cozinha", "produto"]]
            matches = sum(1 for w in palavras_titulo if w in t_msg)
            if matches >= 2:
                logger.info(f"Match por palavras-chave em Story não mapeado -> Produto: {p.get('title')[:35]}")
                return p, "match_keyword"

        # NUNCA fazer fallback para produtos[0] quando o seguidor respondeu a um Story específico!
        return None, "story_nao_encontrado"

    # 2. Se NÃO veio de Story (mensagem direta avulsa no chat)
    # Exige intenção explícita de compra E match de palavras-chave do produto
    if not verificar_intencao_compra(msg_texto):
        return None, "dm_sem_match"

    t_msg = msg_texto.lower()
    for p in produtos:
        titulo = p.get("title", "").lower()
        palavras_titulo = [w for w in re.findall(r"\b\w{4,}\b", titulo) if w not in ["para", "com", "inox", "cozinha", "produto"]]
        matches = sum(1 for w in palavras_titulo if w in t_msg)
        if matches >= 2:
            logger.info(f"Match por palavras-chave em DM avulsa -> Produto: {p.get('title')[:35]}")
            return p, "match_keyword"

    # Se não houver match específico por produto, NUNCA enviar fallback cego de produtos[0].
    # Isso preserva conversas normais entre humanos no direct sem intervenção robótica indesejada.
    return None, "dm_sem_match"

def formatar_resposta_clarificacao_story() -> str:
    """Mensagem enviada quando um Story não pôde ser identificado para evitar envio de link errado."""
    return (
        "Oi! 🛍️ Recebi sua mensagem sobre o Story, mas não consegui identificar com certeza qual oferta você deseja.\n\n"
        "👉 Me diga o nome do produto ou envie um print aqui no chat que te mando o link com desconto exclusivo na hora! 😊"
    )

def enviar_mensagem_direct(
    recipient_id: str,
    texto: str,
    dry_run: bool = False
) -> bool:
    """Envia uma mensagem no Direct do usuário via Meta Graph API."""
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    ig_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")

    if not token or not ig_id:
        logger.error("Credenciais do Instagram ausentes.")
        return False

    if dry_run:
        logger.info(f"[DRY-RUN] Enviando mensagem para IGSID {recipient_id}:\n{texto}")
        return True

    endpoint = f"{base_url}/{ig_id}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": texto},
    }

    try:
        resp = requests.post(
            endpoint,
            json=payload,
            params={"access_token": token},
            timeout=15,
        )
        res_json = resp.json()
        if resp.status_code == 200 and "message_id" in res_json:
            logger.info(f"[SUCESSO] Mensagem enviada para {recipient_id}. Message ID: {res_json.get('message_id')}")
            return True
        else:
            logger.error(f"Falha ao enviar Direct para {recipient_id}: status={resp.status_code}, resp={res_json}")
            return False
    except Exception as e:
        logger.error(f"Exceção ao enviar Direct para {recipient_id}: {e}")
        return False

def formatar_resposta_direct(produto: Dict[str, Any]) -> str:
    """Formata a resposta em copywriting persuasivo com o link de afiliado."""
    titulo = produto.get("title", "")
    if len(titulo) > 55:
        titulo = titulo[:52] + "..."
    preco = produto.get("price", "")
    link = produto.get("short_link", "")

    return (
        f"Oi! 🛍️ Aqui está o link com desconto exclusivo do produto que você pediu:\n\n"
        f"👉 {link}\n\n"
        f"⚡ {titulo}\n"
        f"💰 Preço promocional: {preco}\n\n"
        f"🚚 Dica de Ouro: Não se esqueça de resgatar os Cupons de Frete Grátis e Desconto no app da Shopee antes de finalizar o pedido!\n\n"
        f"⚠️ Aproveite enquanto dura o lote promocional!"
    )

def executar_ciclo_verificacao(dry_run: bool = False) -> int:
    """Executa um ciclo completo de checagem da caixa de entrada e respostas."""
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    ig_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")

    if not token or not ig_id:
        logger.error("Credenciais do Instagram não configuradas.")
        return 0

    estado = carregar_estado()
    processed_ids = set(estado.get("processed_message_ids", []))
    produtos = carregar_produtos_ativos()

    endpoint = f"{base_url}/{ig_id}/conversations"
    params = {
        "platform": "instagram",
        "fields": "id,updated_time,participants,messages{id,message,created_time,from,story,attachments}",
        "access_token": token,
    }

    try:
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code != 200:
            logger.warning(f"Meta Graph API retornou status {r.status_code}: {r.text[:200]}")
            return 0
        data = r.json().get("data", [])
    except Exception as e:
        logger.error(f"Erro ao buscar conversas no Instagram: {e}")
        return 0

    respostas_enviadas = 0

    for conv in data:
        messages_node = conv.get("messages", {}).get("data", [])
        for msg in messages_node:
            msg_id = msg.get("id")
            if not msg_id or msg_id in processed_ids:
                continue

            sender = msg.get("from", {})
            sender_id = sender.get("id")
            sender_username = sender.get("username", "")

            # Ignorar mensagens enviadas pelo próprio perfil
            if sender_id == ig_id or sender_username == "radar.de.preco.baixo":
                processed_ids.add(msg_id)
                continue

            # Verificar janela de 24 horas da Meta (ignorar mensagens antigas para evitar erro 403)
            created_str = msg.get("created_time")
            if created_str:
                try:
                    from datetime import datetime, timezone
                    msg_dt = datetime.fromisoformat(created_str)
                    idade_s = (datetime.now(timezone.utc) - msg_dt).total_seconds()
                    if idade_s > 23 * 3600:
                        logger.info(f"Ignorando mensagem {msg_id} fora da janela de 24h ({idade_s/3600:.1f}h)")
                        processed_ids.add(msg_id)
                        continue
                except Exception:
                    pass

            msg_text = msg.get("message", "").strip()
            story_info = msg.get("story")

            # Verifica se é uma resposta a um story ou contém termo de interesse explícito
            deve_responder = False
            if story_info:
                deve_responder = True
            elif verificar_intencao_compra(msg_text):
                deve_responder = True

            if deve_responder and produtos:
                produto_escolhido, motivo = buscar_produto_correspondente(msg_text, story_info, produtos)
                if produto_escolhido:
                    texto_resposta = formatar_resposta_direct(produto_escolhido)
                    logger.info(f"Respondendo usuário {sender_username or sender_id} sobre produto: {produto_escolhido.get('title')[:30]}... [motivo: {motivo}]")
                    ok = enviar_mensagem_direct(sender_id, texto_resposta, dry_run=dry_run)
                    if ok:
                        respostas_enviadas += 1
                        estado["total_replies_sent"] = estado.get("total_replies_sent", 0) + 1
                elif motivo == "story_nao_encontrado":
                    texto_resposta = formatar_resposta_clarificacao_story()
                    logger.info(f"Enviando mensagem de clarificação para {sender_username or sender_id} (Story não mapeado)")
                    ok = enviar_mensagem_direct(sender_id, texto_resposta, dry_run=dry_run)
                    if ok:
                        respostas_enviadas += 1
                        estado["total_replies_sent"] = estado.get("total_replies_sent", 0) + 1
                else:
                    logger.info(f"Mensagem de {sender_username or sender_id} ignorada pelo auto-responder (motivo: {motivo}). Permitindo conversa humana normal.")

            processed_ids.add(msg_id)

    estado["processed_message_ids"] = list(processed_ids)
    estado["last_check"] = time.time()
    salvar_estado(estado)

    return respostas_enviadas

COMMENTS_INTERVAL = 180
_comments_last_run = 0.0

def executar_ciclo_comentarios(dry_run: bool = False) -> int:
    """Executa o fluxo Comentario -> Direct no maximo a cada COMMENTS_INTERVAL segundos."""
    global _comments_last_run
    if time.time() - _comments_last_run < COMMENTS_INTERVAL:
        return 0
    _comments_last_run = time.time()
    try:
        import instagram_comments
        return instagram_comments.processar_comentarios(dry_run=dry_run)
    except Exception as e:
        logger.error(f"Falha no ciclo de comentarios: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Hermes Instagram Direct Auto-Responder")
    parser.add_argument("--once", action="store_true", help="Executa uma única verificação e sai")
    parser.add_argument("--interval", type=int, default=30, help="Intervalo de polling em segundos (padrão: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Simula o envio sem disparar mensagens reais")
    args = parser.parse_args()

    logger.info("Iniciando Hermes Instagram Direct Auto-Responder...")
    logger.info(f"Configuração: interval={args.interval}s, dry_run={args.dry_run}, once={args.once}")

    if args.once:
        enviadas = executar_ciclo_verificacao(dry_run=args.dry_run)
        respostas_comentarios = executar_ciclo_comentarios(dry_run=args.dry_run)
        logger.info(f"Ciclo concluído. Mensagens respondidas: {enviadas} | Comentarios: {respostas_comentarios}")
        return

    while True:
        try:
            executar_ciclo_verificacao(dry_run=args.dry_run)
            executar_ciclo_comentarios(dry_run=args.dry_run)
        except Exception as e:
            logger.error(f"Erro no ciclo principal: {e}")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
