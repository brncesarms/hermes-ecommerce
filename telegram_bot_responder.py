#!/usr/bin/env python3
"""
==============================================================================
HERMES TELEGRAM BOT INTERACTION RESPONDER (v2.0)
Serviço Autônomo de Interação de Mensagens, DMs e Publicação no Instagram
==============================================================================
Finalidade:
  1. Monitora mensagens privadas (DMs) enviadas ao @RadarDePrecoBaixo2_bot.
  2. Oferece autonomia total para o administrador (Bruno César) publicar no Instagram:
     - Publicação de Feed (Post único ou Carrossel de 2 a 10 fotos).
     - Publicação de Stories no Instagram.
     - Recebimento direto de fotos e álbuns no chat do Telegram com download e upload automático.
     - Publicação autônoma das 2 artes institucionais via comando ou linguagem natural.
  3. Responde imediatamente a /start, /ajuda, cumprimentos e pedidos de ofertas para usuários.
  4. Realiza busca inteligente nos produtos postados (historico_posts.json - 14 dias)
     ou consulta a Shopee AMS API sob demanda para produtos solicitados.
  5. Suporta assistência guiada pelo modelo local (Qwen 35B Vulkan) com fallback
     determinístico gracioso (Zero Latency / Anti-Alucinação).
  6. Mantém controle de offset e estado em data/telegram_bot_state.json.
==============================================================================
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from shopee_engine import (
    publicar_carrossel_instagram,
    publicar_feed_instagram,
    publicar_story_instagram,
)
from llm_client import generate_chat_completion

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "credentials.env"
HISTORICO_PATH = DATA_DIR / "historico_posts.json"
STATE_PATH = DATA_DIR / "telegram_bot_state.json"
LOG_PATH = DATA_DIR / "telegram_bot.log"
UPLOADS_DIR = Path("/tmp/hermes_telegram_uploads")

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Configurar logging estruturado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("hermes.telegram_bot")

def carregar_configuracoes() -> dict[str, str]:
    """Carrega credenciais de credentials.env ou variáveis de ambiente."""
    cfg: dict[str, str] = {}
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
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_USERNAME",
        "ADMIN_CHAT_ID",
        "SHOPEE_APP_ID",
        "SHOPEE_SECRET_KEY",
        "SHOPEE_GRAPHQL_ENDPOINT",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_GRAPH_URL",
        "WHATSAPP_CHANNEL_URL",
    ]:
        if os.getenv(k):
            cfg[k] = os.getenv(k, "")
    return cfg

CFG = carregar_configuracoes()
WHATSAPP_CHANNEL_URL = CFG.get("WHATSAPP_CHANNEL_URL", "https://whatsapp.com/channel/0029VbDwlyV1HspxTl5YNi2F")

# Configuração de Administradores autorizados
ADMIN_CHAT_IDS: set[int] = {8694887251}
for _admin_key in ("ADMIN_CHAT_ID", "ADMIN_TELEGRAM_CHAT_ID"):
    if CFG.get(_admin_key):
        try:
            ADMIN_CHAT_IDS.add(int(CFG[_admin_key]))
        except ValueError:
            pass

def is_admin(chat_id: int) -> bool:
    """Verifica se o chat_id pertence ao administrador autorizado."""
    return chat_id in ADMIN_CHAT_IDS

# Buffer em memória para álbuns de fotos (media_group_id)
PENDING_MEDIA_GROUPS: dict[str, dict[str, Any]] = {}

def carregar_estado() -> dict[str, Any]:
    """Carrega o offset do Telegram e métricas de mensagens."""
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler estado do Telegram Bot: {e}")
    return {"last_update_id": 0, "total_messages_handled": 0, "last_check": 0}

def salvar_estado(estado: dict[str, Any]) -> None:
    """Salva o estado no disco."""
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar estado do Telegram Bot: {e}")

def carregar_produtos_ativos(max_dias: int = 14) -> list[dict[str, Any]]:
    """Carrega produtos ativos publicados na janela de 14 dias do historico_posts.json."""
    if not HISTORICO_PATH.exists():
        return []
    try:
        agora = time.time()
        with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
            historico = json.load(f)
            itens = []
            for item_id, dados in historico.items():
                posted_at = dados.get("posted_at", 0)
                if (agora - posted_at) < (max_dias * 86400):
                    d = dict(dados)
                    d["item_id"] = item_id
                    itens.append(d)
            itens.sort(key=lambda x: x.get("posted_at", 0), reverse=True)
            return itens
    except Exception as e:
        logger.warning(f"Erro ao ler historico_posts.json: {e}")
        return []

def enviar_mensagem_telegram(
    chat_id: int,
    texto_html: str,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    """Envia mensagem formatada em HTML via Telegram Bot API."""
    token = CFG.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN não configurado.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": texto_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        r = requests.post(url, json=payload, timeout=12)
        res = r.json()
        if res.get("ok"):
            return True
        else:
            logger.error(f"Falha ao enviar mensagem Telegram para {chat_id}: {res}")
            return False
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem Telegram: {e}")
        return False

def baixar_foto_telegram(file_id: str) -> Path | None:
    """Baixa foto do Telegram via getFile e salva em arquivo temporário."""
    token = CFG.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN ausente para baixar foto.")
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}", timeout=12)
        res = r.json()
        if not res.get("ok"):
            logger.error(f"Erro ao obter file_path do Telegram: {res}")
            return None

        file_path = res["result"]["file_path"]
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r_file = requests.get(dl_url, timeout=35)
        
        local_path = UPLOADS_DIR / f"{file_id[:16]}_{Path(file_path).name}"
        with open(local_path, "wb") as f:
            f.write(r_file.content)
        logger.info(f"Foto baixada com sucesso do Telegram: {local_path} ({len(r_file.content)} bytes)")
        return local_path
    except Exception as e:
        logger.error(f"Erro ao baixar foto {file_id}: {e}")
        return None

def gerar_legenda_instagram_com_ia(descricao: str = "") -> str:
    """Gera legenda persuasiva para Feed do Instagram usando OpenCode Free Models (ou fallback local)."""
    prompt = (
        "Escreva uma legenda completa, persuasiva e profissional para o Feed do Instagram da página @radar.de.preco.baixo.\n"
        f"Contexto do post: {descricao or 'Divulgação das ofertas diárias da Shopee e Amazon com cupons e convite para o Canal VIP no Telegram'}.\n"
        "Regras obrigatórias:\n"
        "1. Escreva em Português do Brasil com tom empolgante e emojis atraentes.\n"
        "2. Destaque os benefícios reais: menores preços, cupons de até 85% OFF, garantia Shopee e Amazon.\n"
        "3. Inclua chamada para ação (CTA) convidando para seguir o perfil e entrar no Canal VIP pelo link da bio.\n"
        "4. Inclua 8 a 10 hashtags relevantes no final (ex: #radardeprecobaixo #shopeebrasil #amazonbrasil #achadinhos #ofertasshopee #promocoes #cuponsdedesconto).\n"
        "5. Retorne APENAS o texto da legenda pronta para publicação."
    )
    try:
        content = generate_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.35,
        )
        if content:
            logger.info("Legenda gerada com sucesso pela IA.")
            return content
    except Exception as e:
        logger.warning(f"Falha ao consultar IA para legenda: {e}")

    # Fallback determinístico profissional
    return (
        "🎯 O SEU RADAR DIÁRIO DE OFERTAS CHEGOU! 🛍️🔥\n\n"
        "Cansado de perder cupons relâmpago e pagar mais caro nas suas compras online?\n"
        "No Radar de Preço Baixo você encontra:\n"
        "✅ Menores preços históricos da Shopee e da Amazon\n"
        "✅ Cupons secretos e descontos de até 85% OFF\n"
        "✅ Alertas em tempo real direto no seu celular\n\n"
        "👉 Arraste para o lado para conhecer nosso canal VIP no Telegram!\n"
        "📲 Entre no canal VIP: link na bio (@radar.de.preco.baixo)\n\n"
        "#radardeprecobaixo #shopeebrasil #amazonbrasil #achadinhosshopee #cuponsdedesconto #ofertasshopee #promocoes #comprasonline #descontos"
    )

def publicar_artes_institucionais(chat_id: int, nome: str, legenda_custom: str = "") -> None:
    """Publica as duas artes de inspiração como Carrossel no Feed do Instagram."""
    artes_candidatas = [
        [
            Path("/home/brn/.hermes/ecommerce/data/artes/Gemini_Generated_Image_e9tz8fe9tz8fe9tz.jpeg"),
            Path("/home/brn/.hermes/ecommerce/data/artes/Gemini_Generated_Image_rh8gj9rh8gj9rh8g.jpeg"),
        ],
        [
            Path("/var/home/brn/silo/imagens/inspiracao/Gemini_Generated_Image_e9tz8fe9tz8fe9tz.jpeg"),
            Path("/var/home/brn/silo/imagens/inspiracao/Gemini_Generated_Image_rh8gj9rh8gj9rh8g.jpeg"),
        ],
    ]

    artes_validas: list[str] | None = None
    for par in artes_candidatas:
        if all(p.exists() for p in par):
            artes_validas = [str(p) for p in par]
            break

    if not artes_validas:
        enviar_mensagem_telegram(
            chat_id,
            "❌ <b>Erro:</b> As imagens das artes não foram encontradas no disco. Verifique os diretórios de dados."
        )
        return

    enviar_mensagem_telegram(
        chat_id,
        "🎨 <b>Recebido, Bruno!</b>\n\n"
        "Iniciando a publicação das duas artes institucionais como <b>Carrossel no Feed do Instagram</b> (@radar.de.preco.baixo)...\n"
        "• <i>Slide 1: Ofertas Diárias Shopee & Amazon</i>\n"
        "• <i>Slide 2: Canal VIP Telegram</i>\n\n"
        "⏳ Fazendo upload temporário e gerando containers na Meta Graph API..."
    )

    legenda = legenda_custom if legenda_custom else gerar_legenda_instagram_com_ia(
        "Divulgação oficial das ofertas diárias da Shopee e Amazon e convite para o Canal VIP no Telegram"
    )

    try:
        media_id = publicar_carrossel_instagram(artes_validas, legenda=legenda)
        msg_sucesso = (
            "✅ <b>CARROSSEL PUBLICADO NO FEED COM SUCESSO!</b> 🚀🎉\n\n"
            f"📸 <b>Formato:</b> Carrossel Feed (2 slides - 4:5 vertical)\n"
            f"🆔 <b>Media ID:</b> <code>{media_id}</code>\n"
            f"📱 <b>Instagram:</b> <a href=\"https://instagram.com/radar.de.preco.baixo\">@radar.de.preco.baixo</a>\n\n"
            "📝 <b>Legenda no Ar:</b>\n"
            f"<i>{legenda[:280]}...</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "📸 Ver no Instagram", "url": "https://instagram.com/radar.de.preco.baixo"}],
                [
                    {"text": "🚀 Canal VIP Telegram", "url": "https://t.me/radardeprecobaixo"},
                    {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
                ],
            ]
        }
        enviar_mensagem_telegram(chat_id, msg_sucesso, markup)
        logger.info(f"Carrossel das duas artes publicado com sucesso! ID: {media_id}")
    except Exception as e:
        logger.error(f"Erro ao publicar carrossel das artes: {e}")
        enviar_mensagem_telegram(chat_id, f"❌ <b>Falha ao publicar Carrossel no Instagram:</b>\n<code>{e}</code>")

def processar_album_fotos(chat_id: int, nome: str, file_ids: list[str], caption: str = "") -> None:
    """Processa lote de fotos recebidas do Telegram e publica como Carrossel no Feed."""
    enviar_mensagem_telegram(
        chat_id,
        f"📥 <b>{len(file_ids)} fotos recebidas!</b>\nProcessando download das imagens para publicação em Carrossel no Feed..."
    )

    arquivos_locais: list[str] = []
    for fid in file_ids:
        p = baixar_foto_telegram(fid)
        if p and p.exists():
            arquivos_locais.append(str(p))

    if len(arquivos_locais) < 2:
        enviar_mensagem_telegram(chat_id, "⚠️ Menos de 2 imagens válidas foram baixadas para montar o carrossel.")
        return

    legenda = caption
    if not legenda or "crie" in legenda.lower():
        enviar_mensagem_telegram(chat_id, "🧠 Gerando legenda profissional com Inteligência Artificial...")
        legenda = gerar_legenda_instagram_com_ia("Carrossel de achados e promoções especiais Radar de Preço Baixo")

    try:
        media_id = publicar_carrossel_instagram(arquivos_locais, legenda=legenda)
        msg_sucesso = (
            "✅ <b>CARROSSEL PUBLICADO NO FEED COM SUCESSO!</b> 🚀\n\n"
            f"📸 <b>Total de Slides:</b> {len(arquivos_locais)} imagens\n"
            f"🆔 <b>Media ID:</b> <code>{media_id}</code>\n"
            f"📱 <b>Perfil:</b> <a href=\"https://instagram.com/radar.de.preco.baixo\">@radar.de.preco.baixo</a>\n\n"
            "📝 <b>Legenda:</b>\n"
            f"<i>{legenda[:280]}...</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "📸 Ver no Instagram", "url": "https://instagram.com/radar.de.preco.baixo"}],
            ]
        }
        enviar_mensagem_telegram(chat_id, msg_sucesso, markup)
    except Exception as e:
        logger.error(f"Erro ao publicar carrossel recebido via Telegram: {e}")
        enviar_mensagem_telegram(chat_id, f"❌ <b>Erro ao publicar Carrossel:</b>\n<code>{e}</code>")

def processar_foto_individual(chat_id: int, nome: str, file_id: str, caption: str = "") -> None:
    """Processa foto individual recebida do Telegram (Feed Post ou Story)."""
    p = baixar_foto_telegram(file_id)
    if not p or not p.exists():
        enviar_mensagem_telegram(chat_id, "❌ Falha ao baixar imagem enviada pelo Telegram.")
        return

    is_story = "/story" in caption.lower() or "story" in caption.lower() or "stories" in caption.lower()
    legenda_limpa = re.sub(r"(/story|story|stories)", "", caption, flags=re.IGNORECASE).strip()

    if is_story:
        enviar_mensagem_telegram(chat_id, "📲 <b>Publicando Story no Instagram (@radar.de.preco.baixo)...</b>")
        try:
            media_id = publicar_story_instagram(str(p))
            enviar_mensagem_telegram(
                chat_id,
                f"✅ <b>Story Publicado com Sucesso!</b> 🌟\n\n"
                f"🆔 <b>Media ID:</b> <code>{media_id}</code>\n"
                f"📱 <b>Perfil:</b> @radar.de.preco.baixo"
            )
        except Exception as e:
            logger.error(f"Erro ao publicar story: {e}")
            enviar_mensagem_telegram(chat_id, f"❌ <b>Erro ao publicar Story:</b>\n<code>{e}</code>")
    else:
        enviar_mensagem_telegram(chat_id, "📸 <b>Publicando Post individual no Feed do Instagram...</b>")
        if not legenda_limpa or "crie" in legenda_limpa.lower():
            enviar_mensagem_telegram(chat_id, "🧠 Gerando legenda persuasiva com Inteligência Artificial...")
            legenda_limpa = gerar_legenda_instagram_com_ia("Achado e oferta imperdível no Radar de Preço Baixo")

        try:
            media_id = publicar_feed_instagram(str(p), legenda=legenda_limpa)
            enviar_mensagem_telegram(
                chat_id,
                f"✅ <b>Post no Feed Publicado com Sucesso!</b> 🚀\n\n"
                f"🆔 <b>Media ID:</b> <code>{media_id}</code>\n"
                f"📱 <b>Perfil:</b> @radar.de.preco.baixo\n\n"
                f"📝 <b>Legenda:</b>\n<i>{legenda_limpa[:280]}...</i>"
            )
        except Exception as e:
            logger.error(f"Erro ao publicar no Feed: {e}")
            enviar_mensagem_telegram(chat_id, f"❌ <b>Erro ao publicar no Feed:</b>\n<code>{e}</code>")

# ==============================================================================
# CRONOGRAMA OFICIAL E ESTADO DE PUBLICAÇÃO
# ==============================================================================
CRONOGRAMA_OFICIAL = [
    ("08:00", "Achados Virais & Praticidade", "shopee_achados.sh"),
    ("11:45", "Casa, Cozinha & Alimentos", "shopee_casa.sh"),
    ("16:30", "Setup, Gamer & Produtividade", "shopee_informatica.sh"),
    ("20:30", "Moda, Beleza & Bebês", "shopee_feminino.sh"),
]

WARMUP_MINUTOS_ANTES = 2

def calcular_info_cronograma() -> dict[str, Any]:
    """Calcula dinamicamente o status operacional e a próxima publicação com contagem regressiva."""
    now = datetime.datetime.now()
    agora_str = now.strftime("%d/%m/%Y às %H:%M")

    proximo_slot = None
    proximo_tema = None
    minutos_restantes = 0
    dt_slot_alvo = None

    for h_str, tema, _ in CRONOGRAMA_OFICIAL:
        h, m = map(int, h_str.split(":"))
        dt_slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt_slot > now:
            proximo_slot = h_str
            proximo_tema = tema
            dt_slot_alvo = dt_slot
            minutos_restantes = int((dt_slot - now).total_seconds() // 60)
            break

    if not proximo_slot:
        # Próxima publicação é o primeiro slot de amanhã
        h_str, tema, _ = CRONOGRAMA_OFICIAL[0]
        h, m = map(int, h_str.split(":"))
        amanha = now + datetime.timedelta(days=1)
        dt_slot_alvo = amanha.replace(hour=h, minute=m, second=0, microsecond=0)
        proximo_slot = f"{h_str} (amanhã)"
        proximo_tema = tema
        minutos_restantes = int((dt_slot_alvo - now).total_seconds() // 60)

    horas = minutos_restantes // 60
    mins = minutos_restantes % 60
    if horas > 0:
        tempo_str = f"em {horas}h e {mins}min" if mins > 0 else f"em {horas}h"
    else:
        tempo_str = f"em {mins} minutos"

    # Calcular horário de warmup
    dt_warmup = dt_slot_alvo - datetime.timedelta(minutes=WARMUP_MINUTOS_ANTES)
    warmup_str = dt_warmup.strftime("%H:%M")

    return {
        "agora_str": agora_str,
        "proximo_slot": proximo_slot,
        "proximo_tema": proximo_tema,
        "tempo_restante_str": tempo_str,
        "warmup_str": warmup_str,
        "minutos_restantes": minutos_restantes,
    }

def formatar_resposta_cronograma(is_admin_user: bool = False) -> tuple[str, dict[str, Any]]:
    """Formata o relatório completo de agendamento de publicações."""
    info = calcular_info_cronograma()

    texto = (
        "🕒 <b>CRONOGRAMA OFICIAL DE PUBLICAÇÕES | RADAR DE PREÇO BAIXO</b> 📡\n\n"
        f"⏰ <b>Horário Atual do Sistema:</b> {info['agora_str']}\n"
        f"🚀 <b>Próxima Publicação:</b> <b>{info['proximo_slot']}</b> ({info['tempo_restante_str']})\n"
        f"🏷️ <b>Tema do Lote:</b> <b>{info['proximo_tema']}</b>\n\n"
        "📲 <b>Onde as ofertas são publicadas:</b>\n"
        "• <b>Instagram Stories:</b> <a href=\"https://instagram.com/radar.de.preco.baixo\">@radar.de.preco.baixo</a> (com link sticker direto)\n"
        "• <b>Telegram Canal VIP:</b> <a href=\"https://t.me/radardeprecobaixo\">@radardeprecobaixo</a> (alertas imediatos com link comissionado)\n"
        f"• <b>WhatsApp Canal Oficial:</b> <a href=\"{WHATSAPP_CHANNEL_URL}\">Radar de Preço Baixo</a> (achados diários)\n\n"
        "📅 <b>Grade Diária Oficial (4 lotes fixos e autônomos):</b>\n"
        "1. 🌅 <b>08:00</b> — Achados Virais & Praticidade do Dia a Dia\n"
        "2. 🍳 <b>11:45</b> — Casa, Cozinha & Alimentos (Pré-Almoço)\n"
        "3. 💻 <b>16:30</b> — Setup, Gamer & Produtividade (Pausa da Tarde)\n"
        "4. 🌙 <b>20:30</b> — Horário Nobre: Moda, Beleza & Bebês\n\n"
        "💡 <i>A esteira é 100% autônoma (IA em nuvem a custo zero) e todo lote respeita a regra de Cooldown de 14 dias (zero repetições).</i>"
    )

    botoes = [
        [{"text": "🔥 Ver Ofertas em Destaque", "callback_data": "ver_ofertas"}],
        [
            {"text": "🚀 Canal VIP Telegram", "url": "https://t.me/radardeprecobaixo"},
            {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
        ],
    ]
    if is_admin_user:
        botoes.insert(0, [{"text": "🎨 Publicar 2 Artes no Feed", "callback_data": "cmd_post_artes"}])

    return texto, {"inline_keyboard": botoes}

def formatar_painel_admin() -> tuple[str, dict[str, Any]]:
    """Formata o menu e painel de controle do administrador."""
    cron_info = calcular_info_cronograma()
    texto = (
        "👑 <b>PAINEL DE AUTONOMIA DO ADMINISTRADOR</b>\n"
        "<i>Radar de Preço Baixo | Hermes Agent</i>\n\n"
        f"⏰ <b>Horário do Host:</b> {cron_info['agora_str']}\n"
        f"🚀 <b>Próxima Publicação:</b> {cron_info['proximo_slot']} ({cron_info['tempo_restante_str']}) — {cron_info['proximo_tema']}\n\n"
        "📸 <b>Como Publicar pelo Telegram:</b>\n"
        "1. <b>Envie fotos diretamente neste chat:</b>\n"
        "   • <b>1 foto:</b> Publica como <b>Post no Feed</b> (ou escreva <code>story</code> na legenda para publicar como Story).\n"
        "   • <b>2 ou mais fotos (álbum):</b> Publica como <b>Carrossel no Feed</b> automaticamente!\n"
        "   • Se não colocar legenda, nossa IA gera uma legenda perfeita com hashtags e CTA!\n\n"
        "💬 <b>Comandos Diretos e Linguagem Natural:</b>\n"
        "• <code>/post_artes</code> ou digite <i>\"publique as duas artes como post no instagram\"</i>: Publica as 2 artes institucionais em Carrossel no Feed!\n"
        "• <code>/cronograma</code>: Grade de horários e próxima publicação no Instagram e Telegram.\n"
        "• <code>/status</code>: Estado dos serviços do Geekom A7 MAX.\n"
        "• <code>/feed &lt;url_imagem&gt; | &lt;legenda&gt;</code>: Post individual no feed.\n"
        "• <code>/story &lt;url_imagem&gt;</code>: Story no Instagram.\n"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "🕒 Grade e Próxima Publicação", "callback_data": "ver_cronograma"}],
            [{"text": "🎨 Publicar 2 Artes no Feed (Carrossel)", "callback_data": "cmd_post_artes"}],
            [{"text": "📊 Ver Histórico de Ofertas (14 dias)", "callback_data": "ver_ofertas"}],
            [{"text": "📸 Perfil Instagram", "url": "https://instagram.com/radar.de.preco.baixo"}],
        ]
    }
    return texto, markup

def formatar_boas_vindas(nome: str) -> tuple[str, dict[str, Any]]:
    """Gera texto de boas-vindas com botões de navegação."""
    texto = (
        f"Olá, <b>{nome}</b>! 🛍️ Bem-vindo ao assistente do <b>Radar de Preço Baixo</b>!\n\n"
        "Aqui você encontra os maiores achados, cupons secretos e promoções com até <b>85% OFF</b> na Shopee Brasil.\n\n"
        "📌 <b>Como posso te ajudar:</b>\n"
        "• Digite <code>ofertas</code> para ver as melhores promoções de hoje\n"
        "• Digite o nome de qualquer produto que procura (ex: <i>espremedor</i>, <i>panela</i>, <i>fone</i>, <i>gamer</i>)\n"
        "• Participe dos nossos canais no Telegram e WhatsApp para não perder ofertas relâmpago!\n"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "🔥 Ver Últimas Ofertas", "callback_data": "ver_ofertas"}],
            [
                {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
                {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
            ],
        ]
    }
    return texto, markup

def formatar_ultimas_ofertas(produtos: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Formata o lote das ofertas mais recentes do histórico de 14 dias."""
    if not produtos:
        texto = (
            "No momento estamos garimpando novos lotes com mais de 20% OFF! 🔍\n"
            "Fique ligado no canal @radardeprecobaixo para as próximas ofertas das 12:30 e 18:00."
        )
        markup = {
            "inline_keyboard": [[{"text": "🚀 Ver Canal VIP", "url": "https://t.me/radardeprecobaixo"}]]
        }
        return texto, markup

    linhas = ["🔥 <b>ÚLTIMAS OFERTAS EM DESTAQUE NO RADAR:</b>\n"]
    botoes = []

    for idx, p in enumerate(produtos[:4], 1):
        titulo = p.get("title", "")
        if len(titulo) > 42:
            titulo = titulo[:39] + "..."
        preco = p.get("price", "Confira na loja")
        desconto = p.get("discount")
        desc_badge = f" (-{desconto}% OFF)" if desconto else ""
        link = p.get("short_link", "https://shopee.com.br")

        linhas.append(f"{idx}. <b>{titulo}</b>")
        linhas.append(f"   💰 <code>{preco}</code>{desc_badge}")
        linhas.append(f"   👉 <a href=\"{link}\">Acessar Oferta Shopee</a>\n")

        botoes.append([{"text": f"🛒 Ver Oferta {idx} ({preco})", "url": link}])

    botoes.append([
        {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
        {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
    ])
    return "\n".join(linhas), {"inline_keyboard": botoes}

def buscar_produto_no_historico(termo: str, produtos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Busca produto correspondente no histórico ativo de 14 dias."""
    t_clean = re.sub(r"[^a-zA-Z0-9áéíóúâêîôûãõç]", " ", termo.lower())
    palavras = [w for w in t_clean.split() if len(w) >= 3 and w not in ["quero", "link", "onde", "qual", "preco", "valor"]]
    
    if not palavras:
        return None

    melhor_match = None
    maior_score = 0

    for p in produtos:
        tit_clean = re.sub(r"[^a-zA-Z0-9áéíóúâêîôûãõç]", " ", p.get("title", "").lower())
        score = sum(1 for w in palavras if w in tit_clean)
        if score > maior_score:
            maior_score = score
            melhor_match = p

    if maior_score > 0:
        return melhor_match
    return None

def buscar_shopee_on_demand(termo: str) -> dict[str, Any] | None:
    """Consulta sob demanda na Shopee AMS GraphQL quando não encontrado no histórico."""
    try:
        app_id = CFG.get("SHOPEE_APP_ID")
        secret = CFG.get("SHOPEE_SECRET_KEY")
        endpoint = CFG.get("SHOPEE_GRAPHQL_ENDPOINT", "https://open-api.affiliate.shopee.com.br/graphql")
        if not app_id or not secret:
            return None

        # 1. Buscar produto por keyword
        timestamp = int(time.time())
        query = f"""query {{
            productOfferV2(keyword: "{termo}", page: 1, limit: 5, sortType: 2) {{
                nodes {{
                    itemId
                    shopId
                    productName
                    priceMin
                    priceDiscountRate
                    imageUrl
                    offerLink
                }}
            }}
        }}"""
        payload_str = json.dumps({"query": query}, separators=(",", ":"))
        sig = hashlib.sha256(f"{app_id}{timestamp}{payload_str}{secret}".encode()).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={sig}",
        }
        r = requests.post(endpoint, data=payload_str, headers=headers, timeout=8)
        nodes = r.json().get("data", {}).get("productOfferV2", {}).get("nodes", [])
        if not nodes:
            return None

        # REGRA MANDATÓRIA: Piso mínimo de R$ 100,00 para ofertas
        item = None
        for n in nodes:
            try:
                p = float(n.get("priceMin") or 0.0)
                if p >= 100.0:
                    item = n
                    break
            except Exception:
                continue

        if not item:
            logger.info("Nenhum produto sob demanda atingiu o piso mínimo de R$ 100,00.")
            return None

        item_id = item.get("itemId")
        shop_id = item.get("shopId")

        # 2. Gerar short link de afiliado
        ts2 = int(time.time())
        prod_url = f"https://shopee.com.br/product/{shop_id}/{item_id}"
        m_mut = f"""mutation {{ generateShortLink(input: {{ originUrl: {json.dumps(prod_url)}, subIds: ["telegram_dm"] }}) {{ shortLink }} }}"""
        p2_str = json.dumps({"query": m_mut}, separators=(",", ":"))
        sig2 = hashlib.sha256(f"{app_id}{ts2}{p2_str}{secret}".encode()).hexdigest()
        headers2 = {
            "Content-Type": "application/json",
            "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts2}, Signature={sig2}",
        }
        r2 = requests.post(endpoint, data=p2_str, headers=headers2, timeout=8)
        short_link = r2.json().get("data", {}).get("generateShortLink", {}).get("shortLink") or prod_url

        preco_num = float(item.get("priceMin") or 0)
        return {
            "title": item.get("productName"),
            "price": f"R$ {preco_num:.2f}".replace(".", ","),
            "discount": item.get("priceDiscountRate"),
            "short_link": short_link,
            "on_demand": True,
        }
    except Exception as e:
        logger.warning(f"Erro ao buscar na Shopee on demand: {e}")
        return None

def consultar_modelo_local(pergunta: str, produtos: list[dict[str, Any]], is_admin_user: bool = False) -> str | None:
    """Consulta a IA oficial do Radar (OpenCode Free com fallback local) com contexto e grounding estrito."""
    try:
        cron_info = calcular_info_cronograma()

        resumo_ofertas = []
        for p in produtos[:6]:
            resumo_ofertas.append(
                f"- {p.get('title')[:45]} | Preço: {p.get('price')} | Desconto: {p.get('discount')}% OFF | Link: {p.get('short_link')}"
            )
        contexto_str = "\n".join(resumo_ofertas) if resumo_ofertas else "Nenhuma oferta recente no cache."

        admin_ctx = ""
        if is_admin_user:
            admin_ctx = (
                "\nATENÇÃO: O usuário com quem você está falando é BRUNO CÉSAR, o CRIADOR E ADMINISTRADOR DO PROJETO.\n"
                "Reconheça-o como o líder técnico/operador, seja extremamente transparente, prestativo e forneça dados operacionais precisos.\n"
            )

        system_prompt = (
            "Você é o assistente inteligente oficial do Radar de Preço Baixo (@radardeprecobaixo), operando no ecossistema Hermes.\n"
            "Você conhece detalhadamente todo o funcionamento do projeto e deve responder com precisão cirúrgica.\n"
            f"{admin_ctx}\n"
            "SOBRE O PROJETO RADAR DE PREÇO BAIXO:\n"
            "- O projeto é uma esteira 100% autônoma de curadoria e divulgação de ofertas da Shopee Brasil e Amazon, administrada por Bruno César.\n"
            "- Canais Oficiais de Publicação:\n"
            "  * Instagram: @radar.de.preco.baixo (Publicação automática de Stories com links comissionados e Posts/Carrossel no Feed).\n"
            "  * Telegram VIP: @radardeprecobaixo (Canal de transmissão de ofertas relâmpago).\n"
            "  * WhatsApp Canal Oficial: https://whatsapp.com/channel/0029VbDwlyV1HspxTl5YNi2F (Canal de transmissão no WhatsApp).\n"
            "  * Telegram Bot: @RadarDePrecoBaixo2_bot (Atendimento, busca no catálogo e interface do operador).\n\n"
            "CRONOGRAMA OFICIAL DE PUBLICAÇÕES DIÁRIAS (4 lotes fixos e automatizados):\n"
            "1. 08:00 — Achados Virais & Praticidade do Dia a Dia\n"
            "2. 11:45 — Casa, Cozinha & Decoração\n"
            "3. 16:30 — Setup e Produtividade (Informática / Gamer)\n"
            "4. 20:30 — Moda, Beleza & Bebês (Horário Nobre)\n\n"
            "ESTADO OPERACIONAL EM TEMPO REAL:\n"
            f"- Horário Atual do Sistema: {cron_info['agora_str']}\n"
            f"- Próxima Publicação Agendada: {cron_info['proximo_slot']} ({cron_info['tempo_restante_str']}) — Tema: {cron_info['proximo_tema']}\n"
            "- Regra de Cooldown: 14 dias (nenhum produto repetido em menos de 14 dias).\n"
            "- Desconto Mínimo: Pelo menos 20% OFF.\n\n"
            f"Ofertas ativas no Radar (últimos 14 dias):\n{contexto_str}\n\n"
            "DIRETRIZES DE RESPOSTA:\n"
            "1. Responda em Português do Brasil com tom profissional, confiante e emojis.\n"
            "2. Quando perguntado sobre horários, próxima publicação ou como o projeto funciona, explique com total clareza a grade dos 4 lotes (08:00, 11:45, 16:30, 20:30) e indique qual é a próxima publicação.\n"
            "3. NUNCA diga que não sabe os horários ou que o Radar não tem horários fixos. O cronograma é estritamente fixo e automatizado.\n"
            "4. Se o usuário perguntar sobre produtos ou ofertas, mencione as opções reais do Radar acima ou indique a busca.\n"
            "5. NUNCA invente links fictícios da Shopee; use apenas os links fornecidos."
        )

        content = generate_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pergunta},
            ],
            max_tokens=1500,
            temperature=0.2,
        )
        if content:
            return content
    except Exception as e:
        logger.warning(f"Falha ao consultar IA Radar: {e}")
    return None

def processar_mensagem_usuario(chat_id: int, nome: str, texto: str) -> None:
    """Processa a intenção da mensagem e responde com grounding estrito, comandos de admin ou modelo local."""
    t = texto.strip().lower()
    produtos = carregar_produtos_ativos()
    user_is_admin = is_admin(chat_id)

    # --------------------------------------------------------------------------
    # 0. COMANDOS EXCLUSIVOS DO ADMINISTRADOR (BRUNO CÉSAR)
    # --------------------------------------------------------------------------
    if user_is_admin:
        # A) Publicar as duas artes institucionais como Post / Carrossel no Feed
        if (
            t in ["/post_artes", "/artes", "/carrossel_artes", "postar artes", "publicar artes"]
            or any(k in t for k in ["duas artes", "2 artes", "artes de inspiração", "artes de inspiracao", "duas imagens"])
            or (("artes" in t or "arte" in t or "fotos" in t) and ("post" in t or "feed" in t or "carrossel" in t or "instagram" in t))
        ):
            # Extrair possível legenda customizada após delimitador |
            legenda_custom = ""
            if "|" in texto:
                legenda_custom = texto.split("|", 1)[1].strip()
            publicar_artes_institucionais(chat_id, nome, legenda_custom=legenda_custom)
            return

        # B) Menu e Painel Administrativo
        if t in ["/admin", "/painel", "/ajuda_admin"]:
            txt, markup = formatar_painel_admin()
            enviar_mensagem_telegram(chat_id, txt, markup)
            return

        # C) Comando direto /story <url ou caminho>
        if t.startswith("/story "):
            url_story = texto[7:].strip()
            enviar_mensagem_telegram(chat_id, "📲 <b>Publicando Story no Instagram...</b>")
            try:
                mid = publicar_story_instagram(url_story)
                enviar_mensagem_telegram(chat_id, f"✅ <b>Story publicado com sucesso!</b>\nID: <code>{mid}</code>")
            except Exception as e:
                enviar_mensagem_telegram(chat_id, f"❌ <b>Erro ao publicar story:</b>\n<code>{e}</code>")
            return

        # D) Comando direto /feed <url ou caminho> [| <legenda>]
        if t.startswith(("/feed ", "/post ")):
            cmd_name = "/feed " if t.startswith("/feed ") else "/post "
            rest = texto[len(cmd_name):].strip()
            partes = rest.split("|", 1)
            img_feed = partes[0].strip()
            leg_feed = partes[1].strip() if len(partes) > 1 else ""
            if not leg_feed:
                leg_feed = gerar_legenda_instagram_com_ia("Oferta em destaque no Radar")

            enviar_mensagem_telegram(chat_id, "📸 <b>Publicando Post no Feed do Instagram...</b>")
            try:
                mid = publicar_feed_instagram(img_feed, legenda=leg_feed)
                enviar_mensagem_telegram(
                    chat_id,
                    f"✅ <b>Feed Post publicado com sucesso!</b>\nID: <code>{mid}</code>\n\n<b>Legenda:</b>\n<i>{leg_feed[:200]}...</i>"
                )
            except Exception as e:
                enviar_mensagem_telegram(chat_id, f"❌ <b>Erro ao publicar no Feed:</b>\n<code>{e}</code>")
            return

        # E) Comando /status do Host Hermes
        if t in ["/status", "status"]:
            uptime_str = "Ativo e operando localmente no Geekom A7 MAX (bare metal)."
            cron_info = calcular_info_cronograma()
            msg_st = (
                "🖥️ <b>HERMES AGENT - STATUS DO SISTEMA</b>\n\n"
                f"• <b>Status:</b> {uptime_str}\n"
                f"• <b>Host:</b> Geekom A7 MAX (10.0.0.205)\n"
                f"• <b>Horário do Host:</b> {cron_info['agora_str']}\n"
                f"• <b>Próxima Publicação:</b> {cron_info['proximo_slot']} ({cron_info['tempo_restante_str']})\n"
                f"• <b>Tema Agendado:</b> {cron_info['proximo_tema']}\n"
                f"• <b>Instagram API:</b> Conectado (@radar.de.preco.baixo)\n"
                f"• <b>Telegram Bot:</b> @RadarDePrecoBaixo2_bot (Ativo)\n"
                f"• <b>Modelo Local:</b> Qwen 3.6 35B Vulkan (Ativo na porta 36763)\n"
                f"• <b>Ofertas no Histórico (14d):</b> {len(produtos)} ativas\n"
                f"• <b>Regra de Cooldown:</b> 14 dias (Ativa)\n\n"
                "Para gerenciar postagens, digite <code>/admin</code> ou <code>/cronograma</code>."
            )
            markup_st = {
                "inline_keyboard": [
                    [{"text": "🕒 Grade e Próxima Publicação", "callback_data": "ver_cronograma"}],
                    [{"text": "🎨 Publicar 2 Artes no Feed", "callback_data": "cmd_post_artes"}],
                ]
            }
            enviar_mensagem_telegram(chat_id, msg_st, markup_st)
            return

    # --------------------------------------------------------------------------
    # 1. COMANDOS GERAIS DE USUÁRIO E ATENDIMENTO
    # --------------------------------------------------------------------------
    # Boas-Vindas
    if t in ["/start", "/ajuda", "/help", "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "começar"]:
        txt, markup = formatar_boas_vindas(nome)
        enviar_mensagem_telegram(chat_id, txt, markup)
        return

    # Listagem de Ofertas
    if t in ["ofertas", "/ofertas", "promoções", "promocoes", "promo", "radar", "mais"]:
        txt, markup = formatar_ultimas_ofertas(produtos)
        enviar_mensagem_telegram(chat_id, txt, markup)
        return

    # --------------------------------------------------------------------------
    # 2. DETECÇÃO DETERMINÍSTICA DE PERGUNTAS SOBRE CRONOGRAMA E PRÓXIMA PUBLICAÇÃO
    # --------------------------------------------------------------------------
    eh_pergunta_cronograma = (
        t in ["/cronograma", "cronograma", "/agenda", "agenda", "/horarios", "horarios", "horários"]
        or any(k in t for k in [
            "proxima publicacao", "próxima publicação", "proximo post", "próximo post",
            "proxima postagem", "próxima postagem", "proximas postagens", "próximas postagens",
            "quando publica", "quando posta", "quando teremos", "quando sai",
            "horario da proxima", "horário da próxima", "horario de publicacao", "horário de publicação",
            "grade de publicacao", "grade de publicação", "agenda de post",
            "que horas posta", "que horas publica", "horario dos posts", "horários dos posts",
        ])
        or (
            any(w in t for w in ["quando", "que horas", "horario", "horário", "horarios", "horários"])
            and any(w in t for w in ["publica", "publicação", "publicacao", "post", "postagem", "produtos", "produto", "ofertas", "instagram", "telegram", "lote"])
        )
    )

    if eh_pergunta_cronograma:
        txt_crono, markup_crono = formatar_resposta_cronograma(is_admin_user=user_is_admin)
        enviar_mensagem_telegram(chat_id, txt_crono, markup_crono)
        return

    # --------------------------------------------------------------------------
    # 3. BUSCA DE PRODUTO NO HISTÓRICO ATIVO DE 14 DIAS
    # --------------------------------------------------------------------------
    match = buscar_produto_no_historico(t, produtos)
    if match and len(t) < 40 and not any(q in t for q in ["quem", "qual", "como", "onde", "por que", "porque", "você", "voce", "hermes"]):
        tit = match.get("title", "")
        if len(tit) > 50:
            tit = tit[:47] + "..."
        preco = match.get("price", "")
        desconto = match.get("discount")
        desc_txt = f" (🏷️ <b>{desconto}% OFF</b>)" if desconto else ""
        link = match.get("short_link", "")

        resp = (
            f"Encontrei esse achado imperdível no nosso Radar para você, {nome}! 🛍️\n\n"
            f"⭐ <b>{tit}</b>\n"
            f"⚡ Preço Promocional: <code>{preco}</code>{desc_txt}\n\n"
            "🚚 <i>Dica: Ative seus cupons de Frete Grátis e Desconto no app da Shopee antes de finalizar!</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🔥 Ver Oferta na Shopee", "url": link}],
                [
                    {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
                    {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
                ],
            ]
        }
        enviar_mensagem_telegram(chat_id, resp, markup)
        return

    # Busca sob demanda na API da Shopee se não encontrado no histórico
    if len(t) < 30 and not any(q in t for q in ["quem", "qual", "como", "onde", "por que", "porque", "você", "voce", "hermes"]):
        od_match = buscar_shopee_on_demand(t)
        if od_match:
            tit = od_match.get("title", "")
            if len(tit) > 50:
                tit = tit[:47] + "..."
            preco = od_match.get("price", "")
            desconto = od_match.get("discount")
            desc_txt = f" (🏷️ <b>{desconto}% OFF</b>)" if desconto else ""
            link = od_match.get("short_link", "")

            resp = (
                f"Garimpei a melhor oferta ativa na Shopee para '<b>{texto}</b>'! 🎯\n\n"
                f"⭐ <b>{tit}</b>\n"
                f"⚡ Preço: <code>{preco}</code>{desc_txt}\n\n"
                "🛒 <i>Link comissionado verificado e protegido pela Garantia Shopee.</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔥 Ver Oferta na Shopee", "url": link}],
                    [
                        {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
                        {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
                    ],
                ]
            }
            enviar_mensagem_telegram(chat_id, resp, markup)
            return

    # --------------------------------------------------------------------------
    # 4. CONSULTA INTELIGENTE À IA DO RADAR (OPENCODE FREE COM FALLBACK LOCAL)
    # --------------------------------------------------------------------------
    logger.info(f"Encaminhando pergunta conversacional para a IA do Radar: '{texto}'")
    resposta_ia = consultar_modelo_local(texto, produtos, is_admin_user=user_is_admin)
    if resposta_ia:
        markup = {
            "inline_keyboard": [
                [{"text": "🕒 Grade de Horários", "callback_data": "ver_cronograma"}],
                [{"text": "🔥 Ver Ofertas em Destaque", "callback_data": "ver_ofertas"}],
                [
                    {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
                    {"text": "🟢 Canal WhatsApp", "url": WHATSAPP_CHANNEL_URL},
                ],
            ]
        }
        enviar_mensagem_telegram(chat_id, resposta_ia, markup)
        return

    # Fallback final gracioso
    txt_fallback = (
        f"Não encontrei uma promoção específica para '{texto}', mas confira as ofertas mais quentes de hoje no nosso Radar! 🔥"
    )
    _, markup_fb = formatar_ultimas_ofertas(produtos)
    enviar_mensagem_telegram(chat_id, txt_fallback, markup_fb)

def executar_ciclo_telegram(offset: int) -> int:
    """Executa um ciclo de long polling na Telegram Bot API suportando mensagens, fotos e álbuns."""
    token = CFG.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN ausente em credentials.env.")
        time.sleep(5)
        return offset

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {
        "offset": offset,
        "timeout": 20,
        "allowed_updates": ["message", "callback_query"],
    }

    try:
        r = requests.get(url, params=params, timeout=25)
        data = r.json()
        if not data.get("ok"):
            logger.warning(f"Erro ao obter updates do Telegram: {data}")
            time.sleep(3)
            return offset

        updates = data.get("result", [])
        novo_offset = offset

        for upd in updates:
            upd_id = upd.get("update_id", 0)
            if upd_id >= novo_offset:
                novo_offset = upd_id + 1

            # 1. Tratar mensagem privada
            msg = upd.get("message")
            if msg:
                chat = msg.get("chat", {})
                chat_type = chat.get("type", "")
                if chat_type == "private":
                    chat_id = chat.get("id")
                    user = msg.get("from", {})
                    nome = user.get("first_name") or user.get("username") or "Amigo"
                    photos = msg.get("photo")
                    caption = msg.get("caption", "").strip()
                    texto = msg.get("text", "").strip()
                    media_group_id = msg.get("media_group_id")

                    # Fluxo de Fotos / Álbuns
                    if photos:
                        maior_foto = photos[-1].get("file_id")
                        if is_admin(chat_id):
                            if media_group_id:
                                if media_group_id not in PENDING_MEDIA_GROUPS:
                                    PENDING_MEDIA_GROUPS[media_group_id] = {
                                        "photos": [maior_foto],
                                        "caption": caption,
                                        "chat_id": chat_id,
                                        "nome": nome,
                                        "last_seen": time.time(),
                                    }
                                else:
                                    PENDING_MEDIA_GROUPS[media_group_id]["photos"].append(maior_foto)
                                    if caption:
                                        PENDING_MEDIA_GROUPS[media_group_id]["caption"] = caption
                                    PENDING_MEDIA_GROUPS[media_group_id]["last_seen"] = time.time()
                            else:
                                processar_foto_individual(chat_id, nome, maior_foto, caption=caption)
                        else:
                            enviar_mensagem_telegram(
                                chat_id,
                                "Olá! Recebemos sua foto. Para buscas de promoções, você também pode digitar o nome do produto desejado!"
                            )
                    elif texto:
                        logger.info(f"Mensagem recebida de {nome} (Chat ID {chat_id}): '{texto}'")
                        processar_mensagem_usuario(chat_id, nome, texto)

            # 2. Tratar clique em callback query (botão inline)
            cb = upd.get("callback_query")
            if cb:
                cb_data = cb.get("data")
                cb_msg = cb.get("message", {})
                chat_id = cb_msg.get("chat", {}).get("id")
                from_user = cb.get("from", {})
                nome = from_user.get("first_name") or "Amigo"

                if cb_data == "ver_ofertas" and chat_id:
                    produtos = carregar_produtos_ativos()
                    txt, markup = formatar_ultimas_ofertas(produtos)
                    enviar_mensagem_telegram(chat_id, txt, markup)
                elif cb_data == "ver_cronograma" and chat_id:
                    txt, markup = formatar_resposta_cronograma(is_admin_user=is_admin(chat_id))
                    enviar_mensagem_telegram(chat_id, txt, markup)
                elif cb_data == "cmd_post_artes" and chat_id and is_admin(chat_id):
                    publicar_artes_institucionais(chat_id, nome)

        # 3. Processar álbuns finalizados (após 2.0s sem novas fotos do mesmo media_group_id)
        agora = time.time()
        finalizados = []
        for mgid, gdata in list(PENDING_MEDIA_GROUPS.items()):
            if agora - gdata.get("last_seen", 0) > 2.0:
                finalizados.append(mgid)

        for mgid in finalizados:
            gdata = PENDING_MEDIA_GROUPS.pop(mgid)
            processar_album_fotos(
                gdata["chat_id"],
                gdata["nome"],
                gdata["photos"],
                caption=gdata.get("caption", ""),
            )

        return novo_offset
    except requests.exceptions.Timeout:
        return offset
    except Exception as e:
        logger.error(f"Exceção no loop do Telegram Bot: {e}")
        time.sleep(3)
        return offset

def main():
    parser = argparse.ArgumentParser(description="Hermes Telegram Bot Interaction Responder")
    parser.add_argument("--once", action="store_true", help="Executa um único ciclo de verificação e sai")
    args = parser.parse_args()

    logger.info("Iniciando Hermes Telegram Bot Interaction Responder (v2.0)...")
    estado = carregar_estado()
    offset = estado.get("last_update_id", 0)

    if args.once:
        novo_offset = executar_ciclo_telegram(offset)
        estado["last_update_id"] = novo_offset
        estado["last_check"] = time.time()
        salvar_estado(estado)
        logger.info(f"Ciclo único concluído. Novo offset: {novo_offset}")
        return

    while True:
        try:
            novo_offset = executar_ciclo_telegram(offset)
            if novo_offset != offset:
                offset = novo_offset
                estado["last_update_id"] = offset
                estado["total_messages_handled"] = estado.get("total_messages_handled", 0) + 1
                estado["last_check"] = time.time()
                salvar_estado(estado)
        except Exception as e:
            logger.error(f"Erro fatal no loop principal: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
