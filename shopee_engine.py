#!/usr/bin/env python3
"""
==============================================================================
SHOPEE HERMES ENGINE (v2.0)
Motor Determinístico de Automação de Afiliados Shopee para Hermes Agent
==============================================================================
Finalidade:
  Permite que modelos locais (SLMs) operem sem alucinação, delegando:
  1. Conversão de links Shopee para links de afiliado com assinatura SHA256.
  2. Geração de cards de Story verticais (1080x1920) profissionais com Pillow.
  3. Upload temporário HTTPS para compatibilidade com Meta Graph API.
  4. Publicação autônoma de Stories no Instagram (@radar.de.preco.baixo).
  5. Disparo no canal VIP do Telegram (@radardeprecobaixo) com botão inline.
==============================================================================
"""

import argparse
import base64
import datetime
import difflib
import hashlib
import json
import math
import os
import re
import sys
import textwrap
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------------------
# 1. CARREGAMENTO DETERMINÍSTICO DE CONFIGURAÇÕES
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

def obter_caminho_config() -> Path:
    """Retorna o arquivo de credenciais buscando no diretório atual ou caminhos conhecidos."""
    for p in [
        BASE_DIR / "credentials.env",
        BASE_DIR / "chaves-api-instagram-e-shopee-v3.txt",
        Path.home() / ".hermes/ecommerce/credentials.env",
    ]:
        if p.exists():
            return p
    return BASE_DIR / "credentials.env"

CONFIG_PATH = obter_caminho_config()
FONTS_DIR = BASE_DIR / "fonts"
TEMPLATES_DIR = BASE_DIR / "templates"
LOGOS_DIR = BASE_DIR / "logos"
DATA_DIR = BASE_DIR / "data" if (BASE_DIR / "data").exists() else BASE_DIR

def carregar_configuracoes() -> dict[str, str]:
    """Carrega chaves do arquivo v3/v2 ou das variáveis de ambiente."""
    config: dict[str, str] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip('"').strip("'")
    
    # Sobrescrever com variáveis de ambiente do sistema caso existam
    for k in [
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_GRAPH_URL",
        "SHOPEE_APP_ID",
        "SHOPEE_SECRET_KEY",
        "SHOPEE_GRAPHQL_ENDPOINT",
        "SHOPEE_DEFAULT_SUB_IDS",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ADMIN_TELEGRAM_BOT_TOKEN",
        "ADMIN_TELEGRAM_CHAT_ID",
    ]:
        if os.getenv(k):
            config[k] = os.getenv(k, "")
            
    return config

CFG = carregar_configuracoes()

def notificar_alerta_erro_telegram(
    origem: str,
    erro_msg: str,
    tema: str | None = None,
    detalhes: str | None = None,
) -> bool:
    """
    Envia alerta IMEDIATO no Telegram para Bruno (@brncesarms_bot) quando ocorre qualquer falha
    na esteira de e-commerce, garantindo que o operador possa agir instantaneamente de qualquer lugar.
    """
    admin_token = (
        CFG.get("ADMIN_TELEGRAM_BOT_TOKEN")
        or CFG.get("TELEGRAM_BOT_TOKEN")
        or os.getenv("ADMIN_TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or ""
    )
    admin_chat_id = (
        CFG.get("ADMIN_TELEGRAM_CHAT_ID")
        or os.getenv("ADMIN_TELEGRAM_CHAT_ID")
        or CFG.get("TELEGRAM_CHAT_ID")
        or ""
    )

    if not admin_token or not admin_chat_id:
        logger.warning("Credenciais de alerta admin do Telegram não configuradas.")
        return False

    agora_str = time.strftime("%d/%m/%Y %H:%M:%S")
    tema_str = f"📦 <b>Tema:</b> <code>{tema.upper() if tema else 'Geral'}</code>\n" if tema else ""
    
    detalhes_limpos = ""
    if detalhes:
        det_curto = str(detalhes).strip()
        if len(det_curto) > 800:
            det_curto = det_curto[:400] + "\n...\n" + det_curto[-400:]
        detalhes_limpos = f"\n🔍 <b>Traceback / Detalhes:</b>\n<pre>{det_curto}</pre>"

    texto = (
        f"🚨 <b>ALERTA CRÍTICO: FALHA NA ESTEIRA DE AFILIADOS</b> 🚨\n\n"
        f"⏰ <b>Horário:</b> {agora_str}\n"
        f"📍 <b>Origem:</b> <code>{origem}</code>\n"
        f"{tema_str}"
        f"❌ <b>Erro:</b> {erro_msg}\n"
        f"{detalhes_limpos}\n"
        f"⚡ <i>Aviso automático despachado para intervenção imediata via @brncesarms_bot.</i>"
    )

    endpoint = f"https://api.telegram.org/bot{admin_token}/sendMessage"
    payload = {
        "chat_id": admin_chat_id,
        "text": texto,
        "parse_mode": "HTML",
    }

    try:
        r = requests.post(endpoint, json=payload, timeout=10)
        res = r.json()
        if res.get("ok"):
            print(f"[ALERTA TELEGRAM] Notificação enviada para Bruno ({admin_chat_id}) via @brncesarms_bot.")
            return True
        else:
            print(f"[ALERTA TELEGRAM FALHOU] Resposta Telegram: {res}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"[ALERTA TELEGRAM FALHOU] Erro de rede ao postar alerta: {exc}", file=sys.stderr)
        return False


# ------------------------------------------------------------------------------
# 2. MÓDULO SHOPEE AFFILIATE (AMS BRAZIL GRAPHQL)
# ------------------------------------------------------------------------------
def shopee_graphql_request(query: str, variables: dict | None = None) -> dict:
    """Executa requisições autenticadas com SHA256 na Shopee AMS Brasil."""
    app_id = CFG.get("SHOPEE_APP_ID")
    secret = CFG.get("SHOPEE_SECRET_KEY")
    endpoint = CFG.get("SHOPEE_GRAPHQL_ENDPOINT", "https://open-api.affiliate.shopee.com.br/graphql")
    
    if not app_id or not secret:
        raise ValueError("SHOPEE_APP_ID e SHOPEE_SECRET_KEY são obrigatórios.")
        
    timestamp = int(time.time())
    payload_dict = {"query": query}
    if variables:
        payload_dict["variables"] = variables
        
    payload_str = json.dumps(payload_dict, separators=(",", ":"))
    raw_signature = f"{app_id}{timestamp}{payload_str}{secret}"
    signature = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}",
    }
    
    resp = requests.post(endpoint, data=payload_str, headers=headers, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        print(f"[ERRO SHOPEE GRAPHQL] {data.get('errors')}", file=sys.stderr)
    return data

def extrair_item_id_shopee(url: str) -> tuple[int | None, int | None]:
    """Extrai (item_id, shop_id) de URLs da Shopee, resolvendo redirects de links encurtados."""
    target_url = url
    try:
        if "s.shopee.com.br" in target_url or "shope.ee" in target_url:
            r = requests.get(target_url, allow_redirects=True, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            target_url = r.url
            
        m = re.search(r"[-/](?:i\.|product/|opaanlp/)?(\d{6,})[./](\d{6,})", target_url)
        if m:
            shop_id = int(m.group(1))
            item_id = int(m.group(2))
            return item_id, shop_id
    except Exception as e:
        print(f"[AVISO] Falha ao extrair item_id da URL ({url}): {e}", file=sys.stderr)
    return None, None

def gerar_link_afiliado_shopee(origin_url: str, sub_ids: list | None = None) -> str:
    """Converte URL de produto Shopee em link rastreável de afiliado (short_link)."""
    if sub_ids is None:
        sub_ids_str = CFG.get("SHOPEE_DEFAULT_SUB_IDS", "hermes,story,telegram")
        sub_ids = [s.strip() for s in sub_ids_str.split(",") if s.strip()]
        
    sub_ids_json = json.dumps(sub_ids)
    origin_url_json = json.dumps(origin_url)
    
    mutation = f"""
    mutation {{
      generateShortLink(input: {{
        originUrl: {origin_url_json},
        subIds: {sub_ids_json}
      }}) {{
        shortLink
      }}
    }}
    """
    res = shopee_graphql_request(mutation)
    short_link = res.get("data", {}).get("generateShortLink", {}).get("shortLink")
    if not short_link:
        raise RuntimeError(f"Falha ao gerar link Shopee: {res}")
    return short_link

def consultar_oferta_shopee(product_url: str) -> dict | None:
    """Consulta dados de produto na Shopee AMS via GraphQL pelo itemId ou fallback."""
    item_id, _shop_id = extrair_item_id_shopee(product_url)
    if not item_id:
        return None
        
    query = f"""
    query {{
      productOfferV2(itemId: {item_id}) {{
        nodes {{
          itemId
          shopId
          productName
          priceMin
          priceMax
          priceDiscountRate
          imageUrl
          offerLink
        }}
      }}
    }}
    """
    try:
        res = shopee_graphql_request(query)
        nodes = res.get("data", {}).get("productOfferV2", {}).get("nodes", [])
        if nodes:
            return nodes[0]
    except Exception as e:
        print(f"[AVISO] Falha ao consultar metadados Shopee via API para itemId {item_id}: {e}", file=sys.stderr)
    return None

# ------------------------------------------------------------------------------
# 3. MÓDULO VISUAL: RENDERIZADOR DE STORIES 9:16 (1080x1920)
# ------------------------------------------------------------------------------
def obter_fonte(estilo: str = "Bold", tamanho: int = 40) -> ImageFont.ImageFont:
    """Tenta carregar fonte Montserrat com fallback defensivo."""
    caminhos_fontes = [
        str(FONTS_DIR / f"Montserrat-{estilo}.otf"),
        str(FONTS_DIR / "Montserrat-Bold.otf"),
        str(BASE_DIR / f"fonts/Montserrat-{estilo}.otf"),
        str(BASE_DIR / "fonts/Montserrat-Bold.otf"),
        f"/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-{estilo}.otf",
        "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf",
        "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
        "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Bold.otf",
    ]
    for p in caminhos_fontes:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, tamanho)
            except Exception:
                continue
    return ImageFont.load_default()

def renderizar_card_story(
    imagem_produto_url_ou_path: str,
    titulo: str,
    preco: str,
    desconto: str | None = None,
    cupom: str | None = None,
    preco_original: str | None = None,
    output_path: str | None = None,
) -> str:
    """Compõe um card 1080x1920 profissional para Instagram Stories sem sobreposições."""
    if output_path is None:
        output_path = f"/tmp/story_shopee_{int(time.time())}.jpg"
        
    template_limpo = TEMPLATES_DIR / "story_shopee_template_limpo_1080x1920.png"
    if not template_limpo.exists():
        template_limpo = BASE_DIR / "imagens/inspiracao/story_shopee_template_limpo_1080x1920.png"
        
    template_legado = TEMPLATES_DIR / "story_instagram_sem_botao_1080x1920.png"
    if not template_legado.exists():
        template_legado = BASE_DIR / "imagens/inspiracao/story_instagram_sem_botao_1080x1920.png"
        
    logo_path = LOGOS_DIR / "shopee-logo.webp"
    if not logo_path.exists():
        logo_path = BASE_DIR / "imagens/logo/shopee-logo.webp"
    
    # 1. Base Canvas 1080x1920
    if template_limpo.exists():
        canvas = Image.open(template_limpo).convert("RGBA")
    elif template_legado.exists():
        canvas = Image.open(template_legado).convert("RGBA")
    else:
        # Fundo gradiente/navy com card branco caso nenhum template esteja disponível
        canvas = Image.new("RGBA", (1080, 1920), (5, 21, 44, 255))
        draw_temp = ImageDraw.Draw(canvas)
        draw_temp.rounded_rectangle([(55, 340), (1025, 1690)], radius=35, fill=(255, 255, 255, 255))
        draw_temp.rounded_rectangle([(80, 1730), (1000, 1835)], radius=52, fill=(238, 77, 45, 255))
        
    draw = ImageDraw.Draw(canvas)
    
    # 2. Logo Oficial da Shopee (Topo Direito do Card)
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((240, 90), Image.Resampling.LANCZOS)
        canvas.paste(logo, (1000 - logo.width, 365), logo)
        
    # 3. Selo de Desconto (Topo Esquerdo do Card)
    if desconto:
        badge_txt = desconto.strip().replace("🔥", "").strip()
        if not badge_txt.startswith("-"):
            badge_txt = f"-{badge_txt}"
        fonte_badge = obter_fonte("ExtraBold", 34)
        bbox = fonte_badge.getbbox(badge_txt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        bx0, by0 = 85, 365
        bx1, by1 = bx0 + tw + 40, by0 + th + 26
        draw.rounded_rectangle([(bx0, by0), (bx1, by1)], radius=12, fill=(238, 77, 45, 255))
        draw.text((bx0 + 20, by0 + 8), badge_txt, font=fonte_badge, fill=(255, 255, 255, 255))
        
    # 4. Carregar e Inserir Imagem do Produto Centralizada
    if imagem_produto_url_ou_path.startswith("http"):
        r = requests.get(imagem_produto_url_ou_path, timeout=12)
        from io import BytesIO
        prod_img = Image.open(BytesIO(r.content)).convert("RGBA")
    else:
        prod_img = Image.open(imagem_produto_url_ou_path).convert("RGBA")
        
    prod_img.thumbnail((760, 740), Image.Resampling.LANCZOS)
    px = (1080 - prod_img.width) // 2
    py = 460 + (740 - prod_img.height) // 2
    canvas.paste(prod_img, (px, py), prod_img if prod_img.mode == "RGBA" else None)
    
    # 5. Linha separadora sutil
    draw.line([(85, 1225), (995, 1225)], fill=(235, 235, 235, 255), width=2)
    
    # 6. Título do Produto (com quebra inteligente de linha e sem cortar)
    fonte_titulo = obter_fonte("Bold", 42)
    linhas_titulo = textwrap.wrap(titulo, width=32)[:2]
    ty = 1255
    for linha in linhas_titulo:
        draw.text((85, ty), linha, font=fonte_titulo, fill=(20, 20, 20, 255))
        ty += 52
        
    # 7. Bloco de Preço (De / Por)
    if preco_original:
        fonte_strike = obter_fonte("Medium", 32)
        draw.text((85, ty + 10), preco_original, font=fonte_strike, fill=(140, 140, 140, 255))
        obbox = fonte_strike.getbbox(preco_original)
        ow = obbox[2] - obbox[0]
        draw.line([(85, ty + 28), (85 + ow, ty + 28)], fill=(140, 140, 140, 255), width=2)
        
    price_y = ty + 50 if preco_original else ty + 20
    fonte_preco_grande = obter_fonte("ExtraBold", 74)
    draw.text((85, price_y), preco, font=fonte_preco_grande, fill=(0, 166, 80, 255))
    
    # Cupom de desconto opcional
    if cupom:
        fonte_cupom = obter_fonte("Bold", 28)
        c_txt = f"Cupom: {cupom}"
        c_bbox = fonte_cupom.getbbox(c_txt)
        cw = c_bbox[2] - c_bbox[0]
        p_bbox = fonte_preco_grande.getbbox(preco)
        pw = p_bbox[2] - p_bbox[0]
        draw.rounded_rectangle([(85 + pw + 30, price_y + 15), (85 + pw + 50 + cw, price_y + 55)], radius=8, fill=(255, 240, 200, 255))
        draw.text((85 + pw + 40, price_y + 20), c_txt, font=fonte_cupom, fill=(180, 90, 0, 255))
        
    # 8. Bullets de Benefícios
    fonte_sub = obter_fonte("SemiBold", 26)
    benefit_y = price_y + 92
    draw.ellipse([(85, benefit_y + 6), (97, benefit_y + 18)], fill=(0, 166, 80, 255))
    draw.text((110, benefit_y), "Frete Grátis e Cupons disponíveis no App Shopee", font=fonte_sub, fill=(70, 70, 70, 255))
    
    draw.ellipse([(85, benefit_y + 40), (97, benefit_y + 52)], fill=(0, 166, 80, 255))
    draw.text((110, benefit_y + 34), "Compra 100% Protegida pela Garantia Shopee", font=fonte_sub, fill=(70, 70, 70, 255))
    
    # 9. Botão de Chamada para Ação (CTA) no Bottom Safe Zone
    fonte_cta = obter_fonte("Bold", 34)
    cta_msg = "Responda QUERO para receber o link!"
    cta_bbox = fonte_cta.getbbox(cta_msg)
    cw = cta_bbox[2] - cta_bbox[0]
    draw.text(((1080 - cw) // 2, 1762), cta_msg, font=fonte_cta, fill=(255, 255, 255, 255))
    
    # Salvar em JPEG alta qualidade
    final_img = canvas.convert("RGB")
    final_img.save(output_path, "JPEG", quality=95)
    return output_path

# ------------------------------------------------------------------------------
# 4. MÓDULO DE HOSPEDAGEM TEMPORÁRIA HTTPS (Para Meta API)
# ------------------------------------------------------------------------------
def hospedar_imagem_temporaria(caminho_imagem: str) -> str:
    """
    Faz upload da imagem local para serviço temporário HTTPS para consumo pela Meta Graph API.
    Utiliza estratégia defensiva multi-provedor com prioridade para hosts compatíveis com o crawler da Meta:
      1. Uguu.se (primário: alta velocidade, CDN limpa, 100% aceito pelo crawler da Meta, retenção 3h)
      2. Litterbox (fallback 1: endpoint 1h do Catbox com infraestrutura separada)
      3. Tmpfiles.org (fallback 2: upload com link direto /dl/)
      4. Catbox.moe (fallback 3: upload padrão)
    """
    erros = []

    # Provedor 1: Uguu.se (Primário - totalmente compatível com crawler Meta)
    url_uguu = "https://uguu.se/upload.php"
    for tentativa in range(1, 3):
        try:
            with open(caminho_imagem, "rb") as f:
                resp = requests.post(
                    url_uguu,
                    files={"files[]": f},
                    timeout=15,
                )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and "files" in data and len(data["files"]) > 0:
                    url = data["files"][0].get("url", "").strip()
                    if url.startswith("http") and len(url) > 12:
                        return url
                erros.append(f"Uguu t{tentativa}: payload inesperado ({data})")
            else:
                erros.append(f"Uguu t{tentativa}: status {resp.status_code}")
        except Exception as e:
            erros.append(f"Uguu t{tentativa}: {e}")
        time.sleep(1.0)

    # Provedor 2: Litterbox (Catbox temporário de 1h)
    url_litterbox = "https://litterbox.catbox.moe/resources/internals/api.php"
    for tentativa in range(1, 3):
        try:
            with open(caminho_imagem, "rb") as f:
                resp = requests.post(
                    url_litterbox,
                    files={"fileToUpload": f},
                    data={"reqtype": "fileupload", "time": "1h"},
                    timeout=15,
                )
            if resp.status_code == 200:
                url = resp.text.strip()
                if url.startswith("http") and len(url) > 12:
                    return url
                erros.append(f"Litterbox t{tentativa}: corpo inválido ({repr(url)})")
            else:
                erros.append(f"Litterbox t{tentativa}: status {resp.status_code}")
        except Exception as e:
            erros.append(f"Litterbox t{tentativa}: {e}")
        time.sleep(1.0)

    # Provedor 3: Tmpfiles.org (Fallback secundário)
    try:
        with open(caminho_imagem, "rb") as f:
            resp = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": f},
                timeout=15,
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success" and "data" in data and "url" in data["data"]:
                raw_url = data["data"]["url"]
                dl_url = raw_url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
                if dl_url.startswith("http") and len(dl_url) > 12:
                    return dl_url
            erros.append(f"Tmpfiles payload inesperado: {data}")
        else:
            erros.append(f"Tmpfiles status: {resp.status_code}")
    except Exception as e:
        erros.append(f"Tmpfiles: {e}")

    # Provedor 4: Catbox.moe (Fallback final)
    url_upload = "https://catbox.moe/user/api.php"
    for tentativa in range(1, 3):
        try:
            with open(caminho_imagem, "rb") as f:
                resp = requests.post(
                    url_upload,
                    files={"fileToUpload": f},
                    data={"reqtype": "fileupload"},
                    timeout=15,
                )
            if resp.status_code == 200:
                url = resp.text.strip()
                if url.startswith("http") and len(url) > 12:
                    return url
                erros.append(f"Catbox t{tentativa}: corpo inválido ({repr(url)})")
            else:
                erros.append(f"Catbox t{tentativa}: status {resp.status_code}")
        except Exception as e:
            erros.append(f"Catbox t{tentativa}: {e}")
        time.sleep(1.0)

    raise RuntimeError(f"Falha ao hospedar imagem em todos os provedores: {'; '.join(erros)}")

# ------------------------------------------------------------------------------
# 5. DISPARADOR INSTAGRAM (STORIES, FEED E CARROSSEL VIA META GRAPH API)
# ------------------------------------------------------------------------------
def publicar_story_instagram(caminho_ou_url_imagem: str, dry_run: bool = False) -> str:
    """Cria container STORIES na Meta API e publica no ar."""
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    account_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")
    
    if not token or not account_id:
        raise ValueError("INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_BUSINESS_ACCOUNT_ID são obrigatórios.")
        
    if not caminho_ou_url_imagem.startswith("http"):
        image_url = hospedar_imagem_temporaria(caminho_ou_url_imagem)
    else:
        image_url = caminho_ou_url_imagem

    if dry_run:
        print(f"[DRY-RUN] Simulação de publicação de Story com URL: {image_url}")
        return "DRY_RUN_CONTAINER_ID"
        
    # 1. Criar container Stories
    payload_container = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": token,
    }
    endpoint_media = f"{base_url}/{account_id}/media"
    r1 = requests.post(endpoint_media, data=payload_container, timeout=20)
    res1 = r1.json()
    container_id = res1.get("id")
    if not container_id:
        raise RuntimeError(f"Erro ao criar container de Story: {res1}")
        
    print(f"[INSTAGRAM] Container de Story criado: {container_id}. Aguardando processamento...")
    
    # 2. Aguardar processamento da mídia com polling defensivo (até 45s)
    status_endpoint = f"{base_url}/{container_id}"
    ready = False
    for tentativa in range(1, 15):
        time.sleep(3)
        try:
            r_st = requests.get(status_endpoint, params={"fields": "status_code,status", "access_token": token}, timeout=10)
            data_st = r_st.json()
            st_code = data_st.get("status_code")
            print(f"[INSTAGRAM] Story status {tentativa}/15: status_code={st_code}")
            if st_code == "FINISHED":
                ready = True
                break
            elif st_code == "ERROR":
                raise RuntimeError(f"Meta API retornou erro no processamento do container: {data_st}")
        except Exception as e:
            if "retornou erro" in str(e):
                raise
            print(f"[AVISO] Tentativa {tentativa} de checagem de status: {e}")

    if not ready:
        raise TimeoutError(f"Tempo limite excedido aguardando processamento do Story: {container_id}")

    # 3. Publicar container
    payload_publish = {
        "creation_id": container_id,
        "access_token": token,
    }
    endpoint_publish = f"{base_url}/{account_id}/media_publish"
    r2 = requests.post(endpoint_publish, data=payload_publish, timeout=20)
    res2 = r2.json()
    media_id = res2.get("id")
    if not media_id:
        raise RuntimeError(f"Erro ao publicar Story: {res2}")
        
    print(f"[SUCESSO] Story publicado no ar! ID da Mídia: {media_id}")
    return media_id

def publicar_feed_instagram(
    caminho_ou_url_imagem: str,
    legenda: str = "",
    dry_run: bool = False,
) -> str:
    """Cria container IMAGE no Feed da Meta API e publica no ar."""
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    account_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")

    if not token or not account_id:
        raise ValueError("INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_BUSINESS_ACCOUNT_ID são obrigatórios.")

    if not caminho_ou_url_imagem.startswith("http"):
        image_url = hospedar_imagem_temporaria(caminho_ou_url_imagem)
    else:
        image_url = caminho_ou_url_imagem

    if dry_run:
        print(f"[DRY-RUN] Simulação de publicação de Feed Post com URL: {image_url}")
        return "DRY_RUN_FEED_CONTAINER_ID"

    # 1. Criar container Feed
    payload = {
        "image_url": image_url,
        "caption": legenda,
        "access_token": token,
    }
    endpoint_media = f"{base_url}/{account_id}/media"
    r1 = requests.post(endpoint_media, data=payload, timeout=20)
    res1 = r1.json()
    container_id = res1.get("id")
    if not container_id:
        raise RuntimeError(f"Erro ao criar container de Feed Post: {res1}")

    print(f"[INSTAGRAM] Container de Feed criado: {container_id}. Aguardando processamento...")

    # 2. Polling defensivo
    status_endpoint = f"{base_url}/{container_id}"
    ready = False
    for tentativa in range(1, 15):
        time.sleep(3)
        try:
            r_st = requests.get(status_endpoint, params={"fields": "status_code,status", "access_token": token}, timeout=10)
            data_st = r_st.json()
            st_code = data_st.get("status_code")
            print(f"[INSTAGRAM] Feed status {tentativa}/15: status_code={st_code}")
            if st_code == "FINISHED":
                ready = True
                break
            elif st_code == "ERROR":
                raise RuntimeError(f"Meta API retornou erro no container de Feed: {data_st}")
        except Exception as e:
            if "retornou erro" in str(e):
                raise
            print(f"[AVISO] Tentativa {tentativa} de checagem Feed: {e}")

    if not ready:
        raise TimeoutError(f"Tempo limite excedido aguardando processamento do Feed Post: {container_id}")

    # 3. Publicar container Feed
    payload_publish = {
        "creation_id": container_id,
        "access_token": token,
    }
    endpoint_publish = f"{base_url}/{account_id}/media_publish"
    r2 = requests.post(endpoint_publish, data=payload_publish, timeout=20)
    res2 = r2.json()
    media_id = res2.get("id")
    if not media_id:
        raise RuntimeError(f"Erro ao publicar Feed Post: {res2}")

    print(f"[SUCESSO] Feed Post publicado no ar! ID da Mídia: {media_id}")
    return media_id

def publicar_carrossel_instagram(
    caminhos_ou_urls: list[str],
    legenda: str = "",
    dry_run: bool = False,
) -> str:
    """Cria container CAROUSEL na Meta API com múltiplos itens (2 a 10) e publica no Feed."""
    token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
    account_id = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")

    if not token or not account_id:
        raise ValueError("INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_BUSINESS_ACCOUNT_ID são obrigatórios.")

    if not caminhos_ou_urls or len(caminhos_ou_urls) < 2:
        raise ValueError("Carrossel requer no mínimo 2 imagens.")
    if len(caminhos_ou_urls) > 10:
        raise ValueError("Carrossel suporta no máximo 10 imagens.")

    urls_publicas: list[str] = []
    for item in caminhos_ou_urls:
        if not item.startswith("http"):
            u = hospedar_imagem_temporaria(item)
            urls_publicas.append(u)
        else:
            urls_publicas.append(item)

    if dry_run:
        print(f"[DRY-RUN] Simulação de publicação de Carrossel ({len(urls_publicas)} itens): {urls_publicas}")
        return "DRY_RUN_CAROUSEL_ID"

    # 1. Criar containers filhos (is_carousel_item=true)
    child_ids = []
    endpoint_media = f"{base_url}/{account_id}/media"

    for idx, img_url in enumerate(urls_publicas, 1):
        payload_child = {
            "image_url": img_url,
            "is_carousel_item": "true",
            "access_token": token,
        }
        r_child = requests.post(endpoint_media, data=payload_child, timeout=20)
        res_child = r_child.json()
        child_id = res_child.get("id")
        if not child_id:
            raise RuntimeError(f"Erro ao criar container filho {idx}: {res_child}")
        print(f"[INSTAGRAM] Item {idx}/{len(urls_publicas)} do carrossel criado: {child_id}. Aguardando...")

        status_endpoint = f"{base_url}/{child_id}"
        for tentativa in range(1, 15):
            time.sleep(2)
            r_st = requests.get(status_endpoint, params={"fields": "status_code,status", "access_token": token}, timeout=10)
            data_st = r_st.json()
            if data_st.get("status_code") == "FINISHED":
                break
            elif data_st.get("status_code") == "ERROR":
                raise RuntimeError(f"Erro no processamento do item {idx}: {data_st}")

        child_ids.append(child_id)

    # 2. Criar container pai CAROUSEL
    payload_parent = {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": legenda,
        "access_token": token,
    }
    r_parent = requests.post(endpoint_media, data=payload_parent, timeout=20)
    res_parent = r_parent.json()
    parent_id = res_parent.get("id")
    if not parent_id:
        raise RuntimeError(f"Erro ao criar container do carrossel pai: {res_parent}")

    print(f"[INSTAGRAM] Container pai do Carrossel criado: {parent_id}. Aguardando finalização...")

    # Aguardar container pai
    status_parent = f"{base_url}/{parent_id}"
    for tentativa in range(1, 15):
        time.sleep(3)
        r_st = requests.get(status_parent, params={"fields": "status_code,status", "access_token": token}, timeout=10)
        data_st = r_st.json()
        st_code = data_st.get("status_code")
        print(f"[INSTAGRAM] Carrossel pai status {tentativa}/15: status_code={st_code}")
        if st_code == "FINISHED":
            break
        elif st_code == "ERROR":
            raise RuntimeError(f"Erro no processamento do container pai: {data_st}")

    # 3. Publicar container pai
    payload_publish = {
        "creation_id": parent_id,
        "access_token": token,
    }
    endpoint_publish = f"{base_url}/{account_id}/media_publish"
    r_pub = requests.post(endpoint_publish, data=payload_publish, timeout=20)
    res_pub = r_pub.json()
    media_id = res_pub.get("id")
    if not media_id:
        raise RuntimeError(f"Erro ao publicar Carrossel: {res_pub}")

    print(f"[SUCESSO] Carrossel publicado com sucesso! ID da Mídia: {media_id}")
    return media_id


# ------------------------------------------------------------------------------
# 6. DISPARADOR TELEGRAM BOT (CANAL VIP COM BOTÃO INLINE)
# ------------------------------------------------------------------------------
def publicar_canal_telegram(
    caminho_ou_url_imagem: str,
    texto_html: str,
    url_afiliado: str,
    texto_botao: str = "🔥 Ver Oferta na Shopee",
    dry_run: bool = False,
) -> bool:
    """Envia foto com legenda persuasiva e botão inline para o canal do Telegram."""
    bot_token = CFG.get("TELEGRAM_BOT_TOKEN")
    chat_id = CFG.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID são obrigatórios.")
        
    if dry_run:
        print("[DRY-RUN] Transmissão Telegram simulada:")
        print(f"Chat ID: {chat_id}")
        print(f"Texto:\n{texto_html}")
        print(f"Botão URL: {url_afiliado}")
        return True
        
    endpoint = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    wpp_url = CFG.get("WHATSAPP_CHANNEL_URL", "https://whatsapp.com/channel/0029VbDwlyV1HspxTl5YNi2F")
    reply_markup = {
        "inline_keyboard": [
            [{"text": texto_botao, "url": url_afiliado}],
            [
                {"text": "🚀 Canal Telegram VIP", "url": "https://t.me/radardeprecobaixo"},
                {"text": "🟢 Canal WhatsApp", "url": wpp_url}
            ]
        ]
    }
    
    payload = {
        "chat_id": chat_id,
        "caption": texto_html,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(reply_markup),
    }
    
    if caminho_ou_url_imagem.startswith("http"):
        payload["photo"] = caminho_ou_url_imagem
        resp = requests.post(endpoint, data=payload, timeout=15)
    else:
        with open(caminho_ou_url_imagem, "rb") as photo_file:
            resp = requests.post(
                endpoint,
                data=payload,
                files={"photo": photo_file},
                timeout=15
            )
            
    res = resp.json()
    if not res.get("ok"):
        raise RuntimeError(f"Erro ao enviar post para Telegram: {res}")
        
    print("[SUCESSO] Oferta transmitida com sucesso para o canal Telegram VIP!")
    return True

# ------------------------------------------------------------------------------
# 6.2. CANAL DE OFERTAS NO WHATSAPP (CANAL OFICIAL RADAR DE PREÇO BAIXO)
# ------------------------------------------------------------------------------
def formatar_copy_whatsapp(
    titulo: str,
    preco: str,
    desconto: str = "",
    cupom: str = "",
    url_afiliado: str = "",
) -> str:
    """Formata copy persuasiva otimizada para Canal do WhatsApp (sintaxe nativa WhatsApp)."""
    linhas = [
        "🔥 *ACHADO IMPERDÍVEL NA SHOPEE!*",
        "",
        f"⭐ *Produto:* {titulo}",
        f"⚡ *Preço:* {preco}",
    ]
    if desconto:
        linhas.append(f"🏷️ *Desconto:* {desconto}")
    if cupom:
        linhas.append(f"🎟️ *Cupom:* `{cupom}`")

    if url_afiliado:
        linhas.extend([
            "",
            "👉 *Compre com desconto aqui:*",
            f"{url_afiliado}",
        ])

    linhas.extend([
        "",
        "🚚 _Verifique frete grátis e cupons ativos no app da Shopee!_",
        "⚠️ _Estoque promocional limitado._",
    ])
    return "\n".join(linhas)

def publicar_canal_whatsapp(
    caminho_ou_url_imagem: str,
    texto_whatsapp: str,
    url_afiliado: str = "",
    dry_run: bool = False,
) -> bool:
    """Dispara foto com legenda formatada para o Canal/Grupo do WhatsApp via Evolution API ou log estruturado."""
    wpp_channel_url = CFG.get("WHATSAPP_CHANNEL_URL", "https://whatsapp.com/channel/0029VbDwlyV1HspxTl5YNi2F")

    if dry_run:
        print("[DRY-RUN] Transmissão WhatsApp simulada:")
        print(f"Canal: {wpp_channel_url}")
        print(f"Texto:\n{texto_whatsapp}")
        return True

    evo_url = CFG.get("EVOLUTION_API_URL", "http://localhost:8080")
    evo_key = CFG.get("EVOLUTION_API_KEY", "")
    evo_instance = CFG.get("EVOLUTION_INSTANCE", "")
    wpp_jid = CFG.get("WHATSAPP_CHANNEL_JID", "")

    # Se a integração com a Evolution API estiver configurada com JID de canal/grupo:
    if evo_key and evo_instance and wpp_jid:
        try:
            endpoint = f"{evo_url}/message/sendMedia/{evo_instance}"
            media_payload = caminho_ou_url_imagem
            if os.path.isfile(caminho_ou_url_imagem):
                with open(caminho_ou_url_imagem, "rb") as f:
                    media_payload = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "number": wpp_jid,
                "caption": texto_whatsapp,
                "media": media_payload,
                "mediatype": "image",
            }
            resp = requests.post(endpoint, json=payload, headers={"apikey": evo_key}, timeout=20)
            if resp.status_code in [200, 201]:
                print(f"[SUCESSO] Oferta transmitida com sucesso para o WhatsApp ({wpp_jid})!")
                return True
            else:
                print(f"[WHATSAPP] Falha ao enviar via Evolution API ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[WHATSAPP] Erro de conexão com Evolution API: {e}")

    # Fallback determinístico: Grava no log estruturado de postagens do WhatsApp
    wpp_log = DATA_DIR / "whatsapp_posts.log"
    try:
        with open(wpp_log, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n==================== {ts} ====================\n")
            f.write(f"CANAL: {wpp_channel_url}\n")
            f.write(f"IMAGEM: {caminho_ou_url_imagem}\n")
            f.write(f"CONTEÚDO:\n{texto_whatsapp}\n")
        print(f"[WHATSAPP] Oferta registrada no histórico operacional de disparos ({wpp_log.name}).")
        return True
    except Exception as e:
        print(f"[AVISO] Falha ao gravar log do WhatsApp: {e}")
        return False


# ------------------------------------------------------------------------------
# 7. PIPELINE COMPLETO MULTICANAL
# ------------------------------------------------------------------------------
def executar_pipeline_completo(
    url_shopee: str,
    titulo_custom: str | None = None,
    preco_custom: str | None = None,
    desconto_custom: str | None = None,
    cupom_custom: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Executa o ciclo integral de captura, conversão, arte 1080x1920 e publicação."""
    print(f"\n[INÍCIO] Iniciando processamento da oferta Shopee: {url_shopee}")
    
    # 0. Verificação Mandatória da Regra de Cooldown de 14 Dias (2 Semanas)
    item_id_ext, shop_id_ext = extrair_item_id_shopee(url_shopee)
    if item_id_ext and not force and not dry_run:
        is_dup, motivo = verificar_duplicata_em_cooldown(item_id_ext, shop_id_ext, titulo_custom)
        if is_dup:
            raise ValueError(f"BLOQUEIO POR REGRA DE COOLDOWN (14 DIAS): {motivo} Use --force se desejar republicar mesmo assim.")
            
    # 1. Gerar Link de Afiliado Rastreável
    short_link = gerar_link_afiliado_shopee(url_shopee)
    print(f"[SHOPEE] Link de afiliado gerado: {short_link}")
    
    # 2. Consultar Metadados ou Usar Informações Fornecidas
    info = consultar_oferta_shopee(url_shopee) or {}
    titulo = titulo_custom or info.get("productName") or "Oferta Imperdível Shopee"
    preco_val = info.get("priceMin")
    desconto_num = int(info.get("priceDiscountRate") or 0)
    real_shop_id = shop_id_ext or info.get("shopId") or "0"
    real_item_id = item_id_ext or info.get("itemId") or "0"
    
    if preco_custom:
        preco = preco_custom
        preco_orig = None
        try:
            m = re.search(r"(\d+(?:[.,]\d+)?)", preco_custom)
            if m:
                p_custom_val = float(m.group(1).replace(",", "."))
                if 0 < p_custom_val < VALOR_MINIMO_PRODUTO and not force:
                    raise ValueError(
                        f"BLOQUEIO POR REGRA DE PREÇO MÍNIMO (R$ {VALOR_MINIMO_PRODUTO:.2f}): "
                        f"O produto tem valor de R$ {p_custom_val:.2f}. Regra mandatória proíbe postar ofertas abaixo de R$ 100,00. "
                        f"Use --force se desejar abrir exceção manual."
                    )
        except ValueError:
            raise
        except Exception:
            pass
    else:
        try:
            p_val = float(preco_val)
            if 0 < p_val < VALOR_MINIMO_PRODUTO and not force:
                raise ValueError(
                    f"BLOQUEIO POR REGRA DE PREÇO MÍNIMO (R$ {VALOR_MINIMO_PRODUTO:.2f}): "
                    f"O produto tem valor de R$ {p_val:.2f}. Regra mandatória proíbe postar ofertas abaixo de R$ 100,00. "
                    f"Use --force se desejar abrir exceção manual."
                )
            preco = f"R$ {p_val:.2f}".replace('.', ',')
            if 0 < desconto_num < 100:
                p_orig = p_val / (1.0 - (desconto_num / 100.0))
                preco_orig = f"De R$ {p_orig:.2f}".replace('.', ',')
            else:
                preco_orig = None
        except ValueError:
            raise
        except Exception:
            preco = f"R$ {preco_val}" if preco_val else "Confira na Loja"
            preco_orig = None
            
    desconto = desconto_custom or (f"-{desconto_num}% OFF" if desconto_num else None)
    imagem_url = info.get("imageUrl")
    
    if not imagem_url:
        # Imagem padrão Shopee se não conseguir resolver
        imagem_url = "https://cf.shopee.com.br/file/sg-11134201-82590-mt84ny8fg8w851"
        
    # 3. Renderizar Arte Vertical para Instagram Stories (1080x1920)
    story_local_file = renderizar_card_story(
        imagem_produto_url_ou_path=imagem_url,
        titulo=titulo,
        preco=preco,
        desconto=desconto,
        cupom=cupom_custom,
        preco_original=preco_orig,
    )
    print(f"[DESIGN] Story 1080x1920 gerado localmente em: {story_local_file}")
    
    # 4. Upload Temporário para Meta API
    story_public_url = hospedar_imagem_temporaria(story_local_file)
    print(f"[HOSTING] Imagem do Story hospedada para Meta API: {story_public_url}")
    
    # 5. Publicar no Instagram Story
    story_media_id = publicar_story_instagram(story_public_url, dry_run=dry_run)
    
    # 6. Formatar Copywriting e Disparar no Telegram
    linhas_telegram = [
        "🔥 <b>ACHADO IMPERDÍVEL NA SHOPEE!</b>\n",
        f"⭐ <b>Produto:</b> {titulo}",
        f"⚡ <b>Preço:</b> <code>{preco}</code>",
    ]
    if desconto:
        linhas_telegram.append(f"🏷️ <b>Desconto:</b> {desconto}")
    if cupom_custom:
        linhas_telegram.append(f"🎟️ <b>Cupom:</b> <code>{cupom_custom}</code>")
        
    linhas_telegram.append("\n🛒 <i>Aproveite enquanto dura o estoque promocional!</i>")
    copy_telegram = "\n".join(linhas_telegram)
    
    publicar_canal_telegram(
        caminho_ou_url_imagem=story_local_file,
        texto_html=copy_telegram,
        url_afiliado=short_link,
        dry_run=dry_run,
    )
    
    # 6.1. Formatar Copy e Disparar no Canal do WhatsApp
    copy_whatsapp = formatar_copy_whatsapp(
        titulo=titulo,
        preco=preco,
        desconto=desconto,
        cupom=cupom_custom,
        url_afiliado=short_link,
    )
    publicar_canal_whatsapp(
        caminho_ou_url_imagem=story_local_file,
        texto_whatsapp=copy_whatsapp,
        url_afiliado=short_link,
        dry_run=dry_run,
    )
    
    # 7. Registrar no histórico com rastreabilidade completa de produto e vendedor
    if not dry_run:
        registrar_publicacao_historico(
            item_id=real_item_id,
            shop_id=real_shop_id,
            titulo=titulo,
            preco_formatado=preco,
            desconto_taxa=desconto_num,
            short_link=short_link,
            theme="individual",
            story_id=story_media_id,
        )
    
    return {
        "status": "success",
        "short_link": short_link,
        "story_media_id": story_media_id,
        "story_image_url": story_public_url,
        "telegram_posted": True,
        "whatsapp_posted": True,
        "item_id": real_item_id,
        "shop_id": real_shop_id,
    }

def testar_credenciais() -> dict[str, Any]:
    """Testa a integridade e conectividade operacional das APIs Instagram, Shopee e Telegram."""
    resultado: dict[str, Any] = {
        "instagram": {"status": "FAIL", "detalhes": None},
        "shopee": {"status": "FAIL", "detalhes": None},
        "telegram": {"status": "FAIL", "detalhes": None},
        "whatsapp": {"status": "FAIL", "detalhes": None},
    }
    
    # 1. Instagram Graph API
    try:
        ig_token = CFG.get("INSTAGRAM_ACCESS_TOKEN")
        ig_acc = CFG.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        base_url = CFG.get("INSTAGRAM_GRAPH_URL", "https://graph.instagram.com/v21.0")
        if not ig_token or not ig_acc:
            resultado["instagram"]["detalhes"] = "Credenciais ausentes"
        else:
            r_acc = requests.get(f"{base_url}/{ig_acc}?fields=id,username,account_type&access_token={ig_token}", timeout=10).json()
            if "id" in r_acc:
                r_limit = requests.get(f"{base_url}/{ig_acc}/content_publishing_limit?fields=config,quota_usage&access_token={ig_token}", timeout=10).json()
                quota = r_limit.get("data", [{}])[0].get("config", {}).get("quota_total", 100)
                usage = r_limit.get("data", [{}])[0].get("quota_usage", 0)
                resultado["instagram"] = {
                    "status": "OK",
                    "username": r_acc.get("username"),
                    "account_type": r_acc.get("account_type"),
                    "quota_total": quota,
                    "quota_usage": usage,
                }
            else:
                resultado["instagram"]["detalhes"] = r_acc
    except Exception as e:
        resultado["instagram"]["detalhes"] = str(e)

    # 2. Telegram Bot API
    try:
        tg_token = CFG.get("TELEGRAM_BOT_TOKEN")
        chat_id = CFG.get("TELEGRAM_CHAT_ID")
        if not tg_token or not chat_id:
            resultado["telegram"]["detalhes"] = "Credenciais ausentes"
        else:
            r_me = requests.get(f"https://api.telegram.org/bot{tg_token}/getMe", timeout=10).json()
            r_chat = requests.get(f"https://api.telegram.org/bot{tg_token}/getChat?chat_id={chat_id}", timeout=10).json()
            if r_me.get("ok") and r_chat.get("ok"):
                resultado["telegram"] = {
                    "status": "OK",
                    "bot_username": r_me.get("result", {}).get("username"),
                    "channel_title": r_chat.get("result", {}).get("title"),
                    "channel_username": r_chat.get("result", {}).get("username"),
                }
            else:
                resultado["telegram"]["detalhes"] = {"bot": r_me, "chat": r_chat}
    except Exception as e:
        resultado["telegram"]["detalhes"] = str(e)

    # 3. Shopee Affiliate GraphQL
    try:
        app_id = CFG.get("SHOPEE_APP_ID")
        secret = CFG.get("SHOPEE_SECRET_KEY")
        if not app_id or not secret:
            resultado["shopee"]["detalhes"] = "Credenciais ausentes"
        else:
            test_link = gerar_link_afiliado_shopee("https://shopee.com.br/product/933390061/23398164028")
            resultado["shopee"] = {
                "status": "OK",
                "test_short_link": test_link,
                "endpoint": CFG.get("SHOPEE_GRAPHQL_ENDPOINT"),
            }
    except Exception as e:
        resultado["shopee"]["detalhes"] = str(e)

    # 4. WhatsApp Canal
    try:
        wpp_url = CFG.get("WHATSAPP_CHANNEL_URL")
        if wpp_url:
            resultado["whatsapp"] = {
                "status": "OK",
                "channel_url": wpp_url,
                "channel_name": CFG.get("WHATSAPP_CHANNEL_NAME", "Radar de Preço Baixo ⚡ Ofertas & Cupons"),
                "evolution_api": CFG.get("EVOLUTION_API_URL", "http://localhost:8080"),
            }
        else:
            resultado["whatsapp"]["detalhes"] = "WHATSAPP_CHANNEL_URL não configurado"
    except Exception as e:
        resultado["whatsapp"]["detalhes"] = str(e)

    return resultado

# ------------------------------------------------------------------------------
# REGRA MANDATÓRIA DE DEDUPLICAÇÃO E NÃO-REPETIÇÃO (JANELA DE 14 DIAS / 2 SEMANAS)
# ------------------------------------------------------------------------------
COOLDOWN_DIAS = 14
COOLDOWN_SEGUNDOS = COOLDOWN_DIAS * 24 * 3600  # 1.209.600 segundos (336 horas)
VALOR_MINIMO_PRODUTO = float(os.getenv("SHOPEE_MIN_PRICE", "100.0"))  # Regra Mandatória: Piso de R$ 100,00
HISTORICO_POSTS_PATH = DATA_DIR / "historico_posts.json"

def carregar_historico_posts() -> dict[str, Any]:
    """Carrega o histórico de produtos já postados para evitar repetições."""
    if HISTORICO_POSTS_PATH.exists():
        try:
            with open(HISTORICO_POSTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def salvar_historico_posts(historico: dict[str, Any]) -> None:
    """Salva o histórico atualizado em disco."""
    try:
        with open(HISTORICO_POSTS_PATH, "w", encoding="utf-8") as f:
            json.dump(historico, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[AVISO] Falha ao salvar historico de posts: {e}", file=sys.stderr)

def obter_historico_ativo(historico: dict[str, Any] | None = None, janela_segundos: int = COOLDOWN_SEGUNDOS) -> dict[str, Any]:
    """Retorna itens postados dentro da janela de cooldown (padrão: 14 dias / 2 semanas)."""
    if historico is None:
        historico = carregar_historico_posts()
    agora = time.time()
    return {
        str(iid): dados for iid, dados in historico.items()
        if (agora - dados.get("posted_at", 0)) < janela_segundos
    }

STOPWORDS_PRODUTO = {
    "de", "do", "da", "dos", "das", "em", "para", "com", "e", "ou", "o", "a", "os", "as",
    "um", "uma", "uns", "umas", "ao", "aos", "na", "nas", "no", "nos", "por", "sem", "sob",
    "sobre", "p", "c", "kit", "combo", "promocao", "oferta", "frete", "gratis", "envio",
    "imediato", "original", "novo", "nova", "unidades", "pecas", "super", "alta", "qualidade",
    "barato", "imperdivel", "top", "oficial", "brasil", "pronta", "entrega", "conjunto", "set",
    "ate", "brinde", "garantia", "multiuso", "multifuncional"
}

def extrair_tokens_lista(titulo: str) -> list[str]:
    """Extrai lista ordenada de tokens semânticos normalizados do título de um anúncio."""
    if not titulo:
        return []
    t = unicodedata.normalize("NFKD", str(titulo)).encode("ascii", "ignore").decode("utf-8").lower()
    # Remove variações numéricas de voltagem e medidas (ex: 110v, 220v, 2L, 3L, 370ml, etc.)
    t = re.sub(r"\b\d+(?:v|w|l|ml|kg|g|cm|mm|m|gb|tb|mah|hz|fps)\b", " ", t)
    t = re.sub(r"\b\d+/\d+\b", " ", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return [p for p in t.split() if len(p) > 2 and not p.isdigit() and p not in STOPWORDS_PRODUTO]

def extrair_tokens_produto(titulo: str) -> set[str]:
    """Extrai conjunto de tokens semânticos normalizados do título de um anúncio."""
    return set(extrair_tokens_lista(titulo))

def produtos_sao_similares(tit1: str, tit2: str, mesmo_vendedor: bool = False) -> tuple[bool, float, str]:
    """
    Avalia se dois anúncios correspondem essencialmente ao mesmo produto ou linha.
    Funciona tanto para variações do mesmo vendedor quanto cross-seller (vendedores diferentes ofertando produto idêntico).
    """
    if not tit1 or not tit2:
        return False, 0.0, "vazio"
    l1 = extrair_tokens_lista(tit1)
    l2 = extrair_tokens_lista(tit2)
    s1 = set(l1)
    s2 = set(l2)
    if not s1 or not s2:
        return False, 0.0, "sem_tokens"
        
    inter = s1.intersection(s2)
    uniao = s1.union(s2)
    jaccard = len(inter) / len(uniao) if uniao else 0.0
    min_len = min(len(s1), len(s2))
    overlap = len(inter) / min_len if min_len > 0 else 0.0
    
    txt1 = " ".join(sorted(s1))
    txt2 = " ".join(sorted(s2))
    seq_ratio = difflib.SequenceMatcher(None, txt1, txt2).ratio()
    
    # 1. Regra para mesmo vendedor: maior rigor contra variação/clonagem de anúncio
    if mesmo_vendedor:
        if jaccard >= 0.25 or len(inter) >= 3 or overlap >= 0.40 or seq_ratio >= 0.50:
            return True, max(jaccard, overlap, seq_ratio), f"mesmo_vendedor_similar({len(inter)} tokens em comum)"
            
    # 2. Regra para vendedores distintos (cross-seller): produto idêntico ou clone
    # 2.1 Identidade no núcleo inicial (primeiros 4 tokens contêm 3 em comum, ex: 'balança digital precisão')
    head_inter = set(l1[:4]).intersection(set(l2[:4]))
    if len(head_inter) >= 3:
        return True, overlap, f"head_tokens_identicos({len(head_inter)} tokens no inicio: {head_inter})"

    if jaccard >= 0.38:
        return True, jaccard, f"jaccard_alto({jaccard:.2f})"
    if len(inter) >= 5:
        return True, overlap, f"muitos_tokens_iguais({len(inter)} tokens)"
    if len(inter) >= 4 and overlap >= 0.35:
        return True, overlap, f"overlap_tokens({overlap:.2f}, {len(inter)} tokens)"
    if seq_ratio >= 0.65:
        return True, seq_ratio, f"seq_ratio_alto({seq_ratio:.2f})"
        
    return False, max(jaccard, overlap, seq_ratio), "distintos"

def verificar_duplicata_em_cooldown(
    item_id: Any,
    shop_id: Any | None = None,
    titulo: str | None = None,
    historico_ativo: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """
    Verifica se o produto já foi postado dentro da janela de 14 dias (2 semanas).
    Garante:
    1. Bloqueio absoluto por itemId idêntico postado há menos de 14 dias.
    2. Bloqueio por mesmo vendedor (shopId) e mesmo produto (itemId).
    3. Bloqueio por produto idêntico/similar mesmo que de vendedores diferentes (cross-seller duplication block).
    Retorna (is_duplicata, motivo_detalhado).
    """
    if historico_ativo is None:
        historico_ativo = obter_historico_ativo()
        
    iid_str = str(item_id).strip()
    sid_str = str(shop_id).strip() if shop_id else ""
    agora = time.time()

    # 1. Checagem direta por itemId
    if iid_str in historico_ativo:
        dados = historico_ativo[iid_str]
        dias = (agora - dados.get("posted_at", 0)) / 86400
        dias_restantes = max(0.0, COOLDOWN_DIAS - dias)
        return True, f"Produto (itemId={iid_str}) já publicado há {dias:.1f} dias. Cooldown restante: {dias_restantes:.1f} dias."

    # 2. Checagem cruzada por Vendedor + Item ou Similaridade de Produto (inclusive Cross-Seller)
    for k, dados in historico_ativo.items():
        dados_sid = str(dados.get("shop_id") or "").strip()
        dados_iid = str(dados.get("item_id") or k).strip()
        
        # Mesmo vendedor e mesmo itemId
        if sid_str and dados_sid == sid_str and iid_str == dados_iid:
            dias = (agora - dados.get("posted_at", 0)) / 86400
            dias_restantes = max(0.0, COOLDOWN_DIAS - dias)
            return True, f"Mesmo produto do vendedor (shopId={sid_str}, itemId={iid_str}) já publicado há {dias:.1f} dias. Cooldown restante: {dias_restantes:.1f} dias."
            
        # Checagem de similaridade de produto (mesmo vendedor ou cross-seller)
        if titulo and dados.get("title"):
            mesmo_seller = bool(sid_str and dados_sid and sid_str == dados_sid)
            is_sim, score, det = produtos_sao_similares(titulo, dados.get("title", ""), mesmo_vendedor=mesmo_seller)
            if is_sim:
                dias = (agora - dados.get("posted_at", 0)) / 86400
                dias_restantes = max(0.0, COOLDOWN_DIAS - dias)
                origem_seller = "do mesmo vendedor" if mesmo_seller else f"de outro vendedor (shopId={dados_sid})"
                return True, f"Produto idêntico/similar {origem_seller} já publicado há {dias:.1f} dias ('{dados.get('title')[:35]}...'). Cooldown restante: {dias_restantes:.1f} dias."
                
    return False, None

def registrar_publicacao_historico(
    item_id: Any,
    shop_id: Any,
    titulo: str,
    preco_formatado: str,
    desconto_taxa: Any,
    short_link: str,
    theme: str | None = None,
    story_id: str | None = None,
) -> None:
    """Registra uma publicação no histórico garantindo integridade de shop_id e item_id."""
    historico = carregar_historico_posts()
    agora = time.time()
    iid_str = str(item_id).strip()
    sid_str = str(shop_id).strip() if shop_id else ""
    
    historico[iid_str] = {
        "item_id": int(iid_str) if iid_str.isdigit() else iid_str,
        "shop_id": int(sid_str) if sid_str.isdigit() else sid_str,
        "seller_product_key": f"{sid_str}_{iid_str}",
        "title": titulo,
        "price": preco_formatado,
        "discount": desconto_taxa,
        "posted_at": agora,
        "posted_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(agora)),
        "short_link": short_link,
        "theme": theme or "geral",
        "story_id": story_id,
    }
    salvar_historico_posts(historico)

TEMAS_PRESETS: dict[str, dict[str, Any]] = {
    "achados": {
        "nome": "Achados Virais & Praticidade do Dia a Dia",
        "horario_oficial": "08:00",
        "foco_publico": "Despertar, transporte matinal e compras rápidas de impulso",
        "keywords": [
            "aspirador de po portatil sem fio",
            "mini projetor portatil smart wifi",
            "parafusadeira furadeira eletrica sem fio bivolt",
            "ring light grande tripe profissional",
            "caixa som bluetooth potente portatil",
            "maleta ferramentas completa jogo",
            "camera seguranca ip externa wifi prova dagua",
            "mesa digitalizadora desenho usb",
        ],
        "emoji": "🔥",
        "titulo_tg": "🔥 <b>RADAR MATINAL: ACHADOS VIRAIS DO DIA NA SHOPEE!</b>",
    },
    "casa": {
        "nome": "Casa, Cozinha & Praticidade Culinária",
        "horario_oficial": "11:45",
        "foco_publico": "Gatilho do almoço, gastronomia, praticidade doméstica e organização do lar",
        "keywords": [
            "fritadeira eletrica air fryer mondial philco",
            "aspirador de po robo bivolt automatico",
            "jogo de panelas antiaderente ceramica inducao",
            "panela de pressao eletrica digital inox",
            "cafeteira eletrica expresso capsula",
            "purificador de agua refrigerado bancada",
            "ferro passar roupa vapor vertical steamer",
            "mop giratorio lava e seca balde inox",
            "sanduicheira grill eletrica antiaderente",
        ],
        "emoji": "🏠",
        "titulo_tg": "🏠 <b>ACHADOS DE CASA & COZINHA ANTES DO ALMOÇO!</b>",
    },
    "informatica": {
        "nome": "Setup, Gamer & Produtividade Home Office",
        "horario_oficial": "16:30",
        "foco_publico": "Pausa do café da tarde, estudantes, gamers e profissionais em home office",
        "keywords": [
            "teclado mecanico switch hot swap gamer",
            "headset gamer 7.1 surround sem fio",
            "suporte monitor articulado pistao gas",
            "cadeira gamer ergonomica reclinavel",
            "monitor gamer ips full hd",
            "mouse gamer sem fio recarregavel rgb",
            "ssd nvme 1tb pcie high speed",
            "gabinete gamer aquario vidro temperado",
            "mesa gamer escritorio computador",
        ],
        "emoji": "💻",
        "titulo_tg": "💻 <b>SETUP, GAMER & PRODUTIVIDADE NA SHOPEE!</b>",
    },
    "tech": {
        "nome": "Eletrônicos & Smart Gadgets Virais",
        "horario_oficial": "16:30",
        "foco_publico": "Pausa do café da tarde, gadgets e tecnologia",
        "keywords": [
            "smartwatch amoled nfc bluetooth chamada",
            "fone ouvido bluetooth cancelamento ruido ativo anc",
            "caixa de som bluetooth potente subwoofer",
            "mini projetor smart android bivolt",
            "drone com camera 4k gps dobravel",
            "power bank inducao 20000mah carregamento rapido",
            "estabilizador gimbal celular smartphone",
        ],
        "emoji": "⚡",
        "titulo_tg": "⚡ <b>GADGETS VIRAIS & ELETRÔNICOS NA SHOPEE!</b>",
    },
    "feminino": {
        "nome": "Horário Nobre: Moda, Beleza Feminina & Bebês",
        "horario_oficial": "20:30",
        "foco_publico": "Prime time noturno, autocuidado feminino, tendências TikTok e mães",
        "keywords": [
            "escova secadora rotativa alisadora bivolt",
            "modelador de cachos automatico bivolt babyliss",
            "kit mala maternidade completa impermeavel bebe",
            "carrinho de bebe dobravel leve passeio",
            "bebe conforto assento carro veicular",
            "baba eletronica camera sem fio audio visao noturna",
            "mala bordo viagem rodinhas 360 abs",
            "aparelho depilador luz pulsada ipl",
            "bolsa feminina couro legitimo transversal",
        ],
        "emoji": "🌸",
        "titulo_tg": "🌸 <b>HORÁRIO NOBRE: BELEZA, MODA & ACHADOS DE BEBÊ!</b>",
    },
    "beleza_bebe": {
        "nome": "Horário Nobre: Moda, Beleza Feminina & Bebês",
        "horario_oficial": "20:30",
        "foco_publico": "Prime time noturno, autocuidado feminino, tendências TikTok e mães",
        "keywords": [
            "escova secadora rotativa alisadora bivolt",
            "modelador de cachos automatico bivolt babyliss",
            "kit mala maternidade completa impermeavel bebe",
            "carrinho de bebe dobravel leve passeio",
            "bebe conforto assento carro veicular",
            "baba eletronica camera sem fio audio visao noturna",
            "mala bordo viagem rodinhas 360 abs",
            "aparelho depilador luz pulsada ipl",
        ],
        "emoji": "🌸",
        "titulo_tg": "🌸 <b>HORÁRIO NOBRE: BELEZA, MODA & ACHADOS DE BEBÊ!</b>",
    },
}

def obter_tema_por_horario_grade(dt: datetime.datetime | None = None) -> str:
    """Mapeia dinamicamente o horário atual do dia para o tema correspondente da grade oficial de 4 lotes."""
    agora = dt or datetime.datetime.now()
    minutos_dia = agora.hour * 60 + agora.minute
    
    # Nova Grade Estratégica de 4 Lotes:
    # 08:00 (480m)  - Achados Virais & Praticidade: [05:00 às 10:15 / 300m a 615m] -> achados
    # 11:45 (705m)  - Casa, Cozinha & Alimentos:    [10:15 às 14:30 / 615m a 870m] -> casa
    # 16:30 (990m)  - Setup, Gamer & Produtividade: [14:30 às 18:30 / 870m a 1110m] -> informatica
    # 20:30 (1230m) - Moda, Beleza & Bebês:        [18:30 às 04:59 / 1110m a 299m] -> feminino
    if 300 <= minutos_dia < 615:
        return "achados"
    elif 615 <= minutos_dia < 870:
        return "casa"
    elif 870 <= minutos_dia < 1110:
        return "informatica"
    else:
        return "feminino"

def calcular_score_viral(
    sales: int | float | None,
    rating: float | None,
    discount: int | float | None,
    price: float | None,
) -> float:
    """Calcula score de viralidade equilibrando tração real de vendas, prova social e apetite de conversão."""
    vendas = max(0, int(sales or 0))
    nota = max(1.0, min(5.0, float(rating or 4.5)))
    desc = max(0, min(95, int(discount or 0)))
    preco = float(price or 0.0)

    # REGRA MANDATÓRIA: Produtos abaixo do piso mínimo de R$ 100,00 são desqualificados
    if preco < VALOR_MINIMO_PRODUTO:
        return 0.0

    # 1. Base exponencial por volume comprovado de compradores
    base_vendas = math.sqrt(vendas) * 8.0

    # 2. Multiplicador de avaliação estelar (reputação de 4.6+ tem alta conversão em stories)
    fator_nota = (nota / 5.0) ** 3

    # 3. Multiplicador de desconto atrativo real (normalizado até 70% para mitigar anúncios fake)
    desc_efetivo = min(desc, 70)
    fator_desc = 1.0 + (desc_efetivo / 50.0)

    # 4. Ajuste por faixa de preço (Regra Mandatória: Piso mínimo de R$ 100,00)
    if 100.0 <= preco <= 250.0:
        fator_preco = 1.3
    elif 250.0 < preco <= 500.0:
        fator_preco = 1.15
    else:
        fator_preco = 0.95

    return round(base_vendas * fator_nota * fator_desc * fator_preco, 2)

def buscar_melhores_ofertas(
    min_desconto: int = 20,
    limit_fetch: int = 40,
    min_rating: float = 4.0,
    min_sales: int = 15,
    min_preco: float = VALOR_MINIMO_PRODUTO,
    tema: str | None = None,
) -> list:
    """Busca ofertas ativas mais virais na Shopee AMS ordenadas por pontuação de viralidade e prova social."""
    limit_fetch = max(1, min(limit_fetch, 50))  # A API Shopee AMS rejeita rigorosamente limit > 50 (Erro 11001)
    nodes = []
    
    # Se tema não for passado ou for 'auto', seleciona dinamicamente pela grade de horário
    if not tema or tema.lower() == "auto":
        tema_key = obter_tema_por_horario_grade()
    else:
        tema_key = tema.lower()
    
    if tema_key in TEMAS_PRESETS:
        keywords = TEMAS_PRESETS[tema_key]["keywords"]
        for kw in keywords:
            query = f"""
            query {{
              productOfferV2(keyword: "{kw}", page: 1, limit: {limit_fetch}, sortType: 2) {{
                nodes {{
                  itemId
                  shopId
                  productName
                  priceMin
                  priceMax
                  priceDiscountRate
                  imageUrl
                  offerLink
                  sales
                  ratingStar
                }}
              }}
            }}
            """
            try:
                res = shopee_graphql_request(query)
                raw_nodes = res.get("data", {}).get("productOfferV2", {}).get("nodes", [])
                for rn in raw_nodes:
                    rn["_keyword_origem"] = kw
                nodes.extend(raw_nodes)
            except Exception as e:
                print(f"[AVISO] Falha ao buscar produtos para keyword '{kw}': {e}", file=sys.stderr)
    else:
        query = f"""
        query {{
          productOfferV2(page: 1, limit: {limit_fetch}, sortType: 2) {{
            nodes {{
              itemId
              shopId
              productName
              priceMin
              priceMax
              priceDiscountRate
              imageUrl
              offerLink
              sales
              ratingStar
            }}
          }}
        }}
        """
        res = shopee_graphql_request(query)
        nodes = res.get("data", {}).get("productOfferV2", {}).get("nodes", [])
    
    # Deduplicar nós brutos por itemId
    vistos = set()
    unicos = []
    for n in nodes:
        iid = n.get("itemId")
        if iid and iid not in vistos:
            vistos.add(iid)
            unicos.append(n)

    ofertas_filtradas = []
    for item in unicos:
        desconto = int(item.get("priceDiscountRate") or 0)
        if desconto < min_desconto:
            continue
            
        rating = float(item.get("ratingStar") or 0)
        sales = int(item.get("sales") or 0)
        image = item.get("imageUrl")
        price = float(item.get("priceMin") or 0.0)
        if not image or "http" not in image:
            continue
            
        if rating < min_rating and sales < min_sales:
            continue

        # REGRA MANDATÓRIA: Piso mínimo de R$ 100,00 para postagem
        if price < min_preco:
            continue
            
        score_viral = calcular_score_viral(sales, rating, desconto, price)
        if score_viral <= 0:
            continue
        item["_viral_score"] = score_viral
        ofertas_filtradas.append(item)
        
    # Ordenar rigorosamente pelo score de viralidade decrescente
    ofertas_filtradas.sort(key=lambda x: x.get("_viral_score", 0.0), reverse=True)
    return ofertas_filtradas

def executar_lote_autonomo(
    quantidade: int = 3,
    min_desconto: int = 20,
    tema: str | None = None,
    dry_run: bool = False,
    intervalo_segundos: int = 15,
    min_preco: float = VALOR_MINIMO_PRODUTO,
) -> dict[str, Any]:
    """Descobre e publica os produtos mais virais de acordo com a grade de horário e foco de público."""
    if not tema or tema.lower() == "auto":
        tema_efetivo = obter_tema_por_horario_grade()
    else:
        tema_efetivo = tema.lower()

    tema_info = TEMAS_PRESETS.get(tema_efetivo)
    nome_tema = tema_info["nome"] if tema_info else "Geral"
    horario_ref = tema_info.get("horario_oficial", "Horário Geral") if tema_info else "Geral"
    foco_pub = tema_info.get("foco_publico", "Geral") if tema_info else "Geral"

    print(f"\n[AUTONOMIA] Lote Grade [{horario_ref} - {nome_tema}]: {quantidade} produtos mais virais (Foco: {foco_pub} | Piso: R$ {min_preco:.2f})...")
    
    try:
        # 1. Carregar produtos sob regra de Cooldown de 14 Dias (2 Semanas)
        historico_ativo = obter_historico_ativo()
        print(f"[COOLDOWN] {len(historico_ativo)} produtos atualmente protegidos na janela de {COOLDOWN_DIAS} dias.")
        
        ofertas_candidatas = buscar_melhores_ofertas(min_desconto=min_desconto, limit_fetch=40, min_preco=min_preco, tema=tema_efetivo)
        
        # 2. Filtrar itens com DIVERSIDADE TOTAL:
        # - Cooldown de 14 dias (itemId + vendedor + produto idêntico/similar cross-seller)
        # - Piso mínimo de preço (>= R$ 100,00)
        # - Diversidade de Lojistas no lote (nunca repetir loja no mesmo lote)
        # - Diversidade Semântica de Produto no lote (nunca produtos idênticos/similares no mesmo lote)
        # - Diversidade de Nicho/Keyword (cada item de um nicho diferente da categoria)
        def selecionar_itens_diversos(
            candidatos: list,
            alvo_qtd: int,
            itens_atuais: list,
            lojas_atuais: set,
            keywords_atuais: set,
        ) -> tuple[list, set, set]:
            for pass_num in (1, 2):
                for of in candidatos:
                    if len(itens_atuais) >= alvo_qtd:
                        break
                    iid = of.get("itemId")
                    sid = of.get("shopId")
                    tit = of.get("productName")
                    kw_orig = of.get("_keyword_origem")
                    prc = float(of.get("priceMin") or 0.0)

                    # Regra Mandatória: Piso mínimo de R$ 100,00
                    if prc < min_preco:
                        continue

                    if any(sel.get("itemId") == iid for sel in itens_atuais):
                        continue

                    # 1. Cooldown de 14 dias (inclui bloqueio de produto idêntico de outro vendedor)
                    is_dup, motivo = verificar_duplicata_em_cooldown(iid, sid, tit, historico_ativo)
                    if is_dup:
                        if pass_num == 1:
                            print(f"[COOLDOWN 14 DIAS] Ignorando produto: {motivo}")
                        continue

                    # 2. Diversidade de Lojistas no lote (1 produto por loja)
                    if sid and sid in lojas_atuais:
                        if pass_num == 1:
                            print(f"[DIVERSIDADE LOJA] Lojista {sid} já possui produto no lote. Pulando para garantir variedade.")
                        continue

                    # 3. Diversidade Semântica de Produto no lote (evita 2 processadores, 2 bolsas, etc.)
                    conflito_produto = False
                    for ja_sel in itens_atuais:
                        mesmo_v = bool(sid and ja_sel.get("shopId") and sid == ja_sel.get("shopId"))
                        sim, score, det = produtos_sao_similares(tit, ja_sel.get("productName"), mesmo_vendedor=mesmo_v)
                        if sim:
                            conflito_produto = True
                            if pass_num == 1:
                                print(f"[DIVERSIDADE PRODUTO] Produto '{tit[:30]}...' similar a item já no lote ('{ja_sel.get('productName')[:30]}...'). Pulando ({det}).")
                            break
                    if conflito_produto:
                        continue

                    # 4. Diversidade de Nicho/Keyword (Passagem 1 prioriza nichos diferentes)
                    if pass_num == 1 and kw_orig and kw_orig in keywords_atuais:
                        continue

                    # Produto aprovado com diversidade comprovada
                    if sid:
                        lojas_atuais.add(sid)
                    if kw_orig:
                        keywords_atuais.add(kw_orig)
                    itens_atuais.append(of)

                if len(itens_atuais) >= alvo_qtd:
                    break
            return itens_atuais, lojas_atuais, keywords_atuais

        itens_selecionados, lojas_selecionadas, keywords_selecionadas = selecionar_itens_diversos(
            candidatos=ofertas_candidatas,
            alvo_qtd=quantidade,
            itens_atuais=[],
            lojas_atuais=set(),
            keywords_atuais=set(),
        )

        if len(itens_selecionados) < quantidade:
            for fb_desc in [15, 10]:
                print(f"[AUTONOMIA] Tentando fallback para produtos virais com pelo menos {fb_desc}% OFF (Piso: R$ {min_preco:.2f})...")
                ofertas_candidatas_fb = buscar_melhores_ofertas(min_desconto=fb_desc, limit_fetch=40, min_preco=min_preco, tema=tema_efetivo, min_sales=5)
                itens_selecionados, lojas_selecionadas, keywords_selecionadas = selecionar_itens_diversos(
                    candidatos=ofertas_candidatas_fb,
                    alvo_qtd=quantidade,
                    itens_atuais=itens_selecionados,
                    lojas_atuais=lojas_selecionadas,
                    keywords_atuais=keywords_selecionadas,
                )
                if len(itens_selecionados) >= quantidade:
                    print(f"[AUTONOMIA] Fallback bem-sucedido: {len(itens_selecionados)} itens com diversidade garantida a >={fb_desc}% OFF.")
                    break

        if not itens_selecionados:
            msg_aviso = f"Nenhuma nova promoção elegível encontrada para o tema [{nome_tema}]. O lote agendado NÃO foi publicado!"
            print(f"[ALERTA CRÍTICO] {msg_aviso}")
            notificar_alerta_erro_telegram(
                origem=f"executar_lote_autonomo ({nome_tema})",
                erro_msg=msg_aviso,
                tema=tema,
                detalhes=f"Todas as ofertas candidatas foram bloqueadas pela regra de cooldown de 14 dias, piso mínimo de R$ {min_preco:.2f} ou não atingiram o desconto mínimo (mesmo com fallback até 10% OFF)."
            )
            return {"total_publicados": 0, "status": "cooldown_or_no_deals", "resultados": []}

        print(f"[AUTONOMIA] {len(itens_selecionados)} produtos selecionados para postagem.")
        
        resultados_lote = []
        for idx, item in enumerate(itens_selecionados, 1):
            print(f"\n--- Publicando item {idx}/{len(itens_selecionados)}: {item.get('productName')[:40]}... ---")
            
            titulo = item.get("productName")
            preco_val = item.get("priceMin")
            desconto_num = int(item.get("priceDiscountRate") or 0)
            
            try:
                p_val = float(preco_val)
                if p_val < min_preco and not dry_run:
                    print(f"[BLOQUEIO PREÇO MÍNIMO] Item {item.get('itemId')} descartado por violar piso: R$ {p_val:.2f} < R$ {min_preco:.2f}")
                    continue
                preco_formatado = f"R$ {p_val:.2f}".replace('.', ',')
                if 0 < desconto_num < 100:
                    p_orig = p_val / (1.0 - (desconto_num / 100.0))
                    preco_original_str = f"De R$ {p_orig:.2f}".replace('.', ',')
                else:
                    preco_original_str = None
            except Exception:
                if not dry_run:
                    print(f"[BLOQUEIO PREÇO MÍNIMO] Não foi possível validar preço numérico do item {item.get('itemId')}. Pulando.")
                    continue
                preco_formatado = f"R$ {preco_val}" if preco_val else "Confira na Loja"
                preco_original_str = None
                
            desconto_str = f"-{desconto_num}% OFF" if desconto_num else None
            img_url = item.get("imageUrl")
            item_id = str(item.get("itemId"))
            shop_id = str(item.get("shopId") or "0")
            
            try:
                # Link de afiliado garantido com subIds
                product_link = f"https://shopee.com.br/product/{shop_id}/{item_id}"
                short_link = gerar_link_afiliado_shopee(product_link)
                
                # 1. Renderizar card vertical 1080x1920
                story_file = renderizar_card_story(
                    imagem_produto_url_ou_path=img_url,
                    titulo=titulo,
                    preco=preco_formatado,
                    desconto=desconto_str,
                    preco_original=preco_original_str,
                )
                
                # 2. Upload temporário HTTPS
                story_url = hospedar_imagem_temporaria(story_file)
                
                # 3. Publicar Story no Instagram
                story_id = publicar_story_instagram(story_url, dry_run=dry_run)
                
                # 4. Formatar copy e publicar no Telegram
                header_tg = tema_info["titulo_tg"] if tema_info else "🔥 <b>ACHADO IMPERDÍVEL NA SHOPEE!</b>"
                linhas_tg = [
                    f"{header_tg}\n",
                    f"⭐ <b>Produto:</b> {titulo}",
                    f"⚡ <b>Preço:</b> <code>{preco_formatado}</code>",
                    f"🏷️ <b>Desconto:</b> {desconto_str}",
                    "\n🚚 <i>Verifique elegibilidade de Frete Grátis e Cupons no App!</i>",
                    "⚠️ <i>Estoque e cupons promocionais esgotam rapidamente!</i>",
                ]
                copy_tg = "\n".join(linhas_tg)
                
                publicar_canal_telegram(
                    caminho_ou_url_imagem=story_file,
                    texto_html=copy_tg,
                    url_afiliado=short_link,
                    dry_run=dry_run,
                )
                
                # 4.1. Publicar no Canal do WhatsApp
                copy_wpp = formatar_copy_whatsapp(
                    titulo=titulo,
                    preco=preco_formatado,
                    desconto=desconto_str,
                    cupom="",
                    url_afiliado=short_link,
                )
                publicar_canal_whatsapp(
                    caminho_ou_url_imagem=story_file,
                    texto_whatsapp=copy_wpp,
                    url_afiliado=short_link,
                    dry_run=dry_run,
                )
                
                # 5. Gravar no histórico garantindo rastreabilidade do vendedor e produto
                if not dry_run:
                    registrar_publicacao_historico(
                        item_id=item_id,
                        shop_id=shop_id,
                        titulo=titulo,
                        preco_formatado=preco_formatado,
                        desconto_taxa=item.get("priceDiscountRate"),
                        short_link=short_link,
                        theme=tema,
                        story_id=story_id,
                    )
                    # Atualizar cache em memória para o lote atual
                    historico_ativo[item_id] = {
                        "item_id": item_id,
                        "shop_id": shop_id,
                        "title": titulo,
                        "posted_at": time.time(),
                    }
                    
                resultados_lote.append({
                    "item_id": item_id,
                    "shop_id": shop_id,
                    "title": titulo,
                    "price": preco_formatado,
                    "discount": desconto_str,
                    "short_link": short_link,
                    "story_id": story_id,
                    "theme": tema,
                })
            except Exception as item_err:
                erro_item_msg = f"Falha ao processar item {idx}/{len(itens_selecionados)} ('{titulo[:35]}...'): {item_err}"
                print(f"[ERRO ITEM] {erro_item_msg}", file=sys.stderr)
                notificar_alerta_erro_telegram(
                    origem=f"executar_lote_autonomo (item {idx}/{len(itens_selecionados)})",
                    erro_msg=erro_item_msg,
                    tema=tema,
                    detalhes=traceback.format_exc(),
                )
            
            # Espaçamento defensivo entre stories do mesmo lote
            if idx < len(itens_selecionados):
                print(f"[PAUSA] Aguardando {intervalo_segundos}s antes do próximo Story do lote...")
                time.sleep(intervalo_segundos)
                
        return {
            "status": "success",
            "theme": tema,
            "batch_size": len(resultados_lote),
            "posts": resultados_lote,
            "dry_run": dry_run,
        }
    except Exception as fatal_err:
        erro_fatal_msg = f"Falha catastrófica no lote do tema [{nome_tema}]: {fatal_err}"
        print(f"[ERRO FATAL LOTE] {erro_fatal_msg}", file=sys.stderr)
        notificar_alerta_erro_telegram(
            origem=f"executar_lote_autonomo (FATAL - {nome_tema})",
            erro_msg=erro_fatal_msg,
            tema=tema,
            detalhes=traceback.format_exc(),
        )
        raise

# ------------------------------------------------------------------------------
# 8. INTERFACE DE LINHA DE COMANDO (CLI MASTIGADA PARA O HERMES)
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Shopee Hermes Engine CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # Subcomando: link
    p_link = subparsers.add_parser("link", help="Gera link de afiliado encurtado")
    p_link.add_argument("--url", required=True, help="URL original do produto Shopee")
    
    # Subcomando: story
    p_story = subparsers.add_parser("story", help="Publica Story diretamente com URL de imagem pública ou caminho local")
    p_story.add_argument("--image-url", required=True, help="URL pública HTTPS ou caminho local da imagem do story")
    p_story.add_argument("--dry-run", action="store_true", help="Simula sem publicar")

    # Subcomando: feed
    p_feed = subparsers.add_parser("feed", help="Publica post individual no Feed do Instagram com legenda")
    p_feed.add_argument("--image", required=True, help="URL pública HTTPS ou caminho local da imagem")
    p_feed.add_argument("--caption", "--legenda", default="", help="Legenda do post no Feed")
    p_feed.add_argument("--dry-run", action="store_true", help="Simula sem publicar")

    # Subcomando: carousel
    p_car = subparsers.add_parser("carousel", help="Publica Carrossel (2 a 10 imagens) no Feed do Instagram com legenda")
    p_car.add_argument("--images", nargs="+", required=True, help="URLs públicas HTTPS ou caminhos locais das imagens")
    p_car.add_argument("--caption", "--legenda", default="", help="Legenda do post em carrossel")
    p_car.add_argument("--dry-run", action="store_true", help="Simula sem publicar")
    
    # Subcomando: telegram
    p_tg = subparsers.add_parser("telegram", help="Publica oferta no Telegram")
    p_tg.add_argument("--image", required=True, help="Caminho local ou URL da imagem")
    p_tg.add_argument("--text", required=True, help="Texto em HTML defensivo")
    p_tg.add_argument("--url", required=True, help="Link de afiliado Shopee")
    p_tg.add_argument("--dry-run", action="store_true", help="Simula sem postar")
    
    # Subcomando: whatsapp
    p_wpp = subparsers.add_parser("whatsapp", help="Publica oferta no canal/grupo do WhatsApp")
    p_wpp.add_argument("--image", required=True, help="Caminho local da imagem ou URL")
    p_wpp.add_argument("--text", required=True, help="Texto/legenda da oferta")
    p_wpp.add_argument("--url", default="", help="Link de afiliado Shopee")
    p_wpp.add_argument("--dry-run", action="store_true", help="Simula sem postar")
    
    # Subcomando: auto (Ciclo completo por URL específica)
    p_auto = subparsers.add_parser("auto", help="Executa o pipeline completo para 1 produto específico")
    p_auto.add_argument("--url", required=True, help="URL original do produto Shopee")
    p_auto.add_argument("--title", help="Título do produto")
    p_auto.add_argument("--price", help="Preço formatado (ex: R$ 49,90)")
    p_auto.add_argument("--discount", help="Desconto (ex: 35%% OFF)")
    p_auto.add_argument("--coupon", help="Cupom de desconto opcional")
    p_auto.add_argument("--dry-run", action="store_true", help="Simula publicações sem colocar no ar")
    p_auto.add_argument("--force", action="store_true", help="Ignora regra de 14 dias para repostagem forçada")

    # Subcomando: discover (Listar melhores ofertas sem postar)
    p_disc = subparsers.add_parser("discover", help="Descobre promocoes qualificadas na Shopee (>= 20%% OFF e >= R$ 100)")
    p_disc.add_argument("--theme", "--tema", choices=list(TEMAS_PRESETS.keys()) + ["auto"], default="auto", help="Filtrar por tema (ou 'auto' para seguir a grade de horários)")
    p_disc.add_argument("--min-discount", type=int, default=20, help="Desconto minimo em porcentagem (padrao: 20)")
    p_disc.add_argument("--min-price", type=float, default=VALOR_MINIMO_PRODUTO, help=f"Preco minimo em reais (padrao: {VALOR_MINIMO_PRODUTO:.2f})")
    p_disc.add_argument("--limit", type=int, default=10, help="Quantidade de produtos a listar")

    # Subcomando: batch (Ciclo 100% autônomo em lote para o Hermes Agent)
    p_batch = subparsers.add_parser("batch", help="Busca automaticamente promocoes (>=20%% OFF e >= R$ 100) e posta lote no IG Stories e Telegram")
    p_batch.add_argument("--theme", "--tema", choices=list(TEMAS_PRESETS.keys()) + ["auto"], default="auto", help="Tema do lote (ou 'auto' para seguir a grade de horários)")
    p_batch.add_argument("--count", type=int, default=3, help="Quantidade de produtos a postar no lote (padrao: 3)")
    p_batch.add_argument("--min-discount", type=int, default=20, help="Desconto minimo (padrao: 20%%)")
    p_batch.add_argument("--min-price", type=float, default=VALOR_MINIMO_PRODUTO, help=f"Preco minimo em reais (padrao: {VALOR_MINIMO_PRODUTO:.2f})")
    p_batch.add_argument("--dry-run", action="store_true", help="Simula sem postar nas redes")

    # Subcomando: cooldown (Auditoria da Regra de 14 dias)
    subparsers.add_parser("cooldown", help="Audita os produtos bloqueados na janela de cooldown de 14 dias")

    # Subcomando: test-keys (Auditoria e Healthcheck)
    subparsers.add_parser("test-keys", help="Audita e testa a conectividade das APIs configuradas")
    
    # Subcomando: test-alert (Teste do canal de alertas de emergência)
    p_alert = subparsers.add_parser("test-alert", help="Envia um alerta de teste para o Telegram de Bruno (@brncesarms_bot)")
    p_alert.add_argument("--msg", default="Teste de disparo de alerta crítico da esteira de afiliados.", help="Mensagem do alerta")

    args = parser.parse_args()
    
    if args.command == "link":
        short = gerar_link_afiliado_shopee(args.url)
        print(json.dumps({"short_link": short}))
    elif args.command == "story":
        media_id = publicar_story_instagram(args.image_url, dry_run=args.dry_run)
        print(json.dumps({"media_id": media_id}))
    elif args.command == "feed":
        media_id = publicar_feed_instagram(args.image, legenda=args.caption, dry_run=args.dry_run)
        print(json.dumps({"media_id": media_id}))
    elif args.command == "carousel":
        media_id = publicar_carrossel_instagram(args.images, legenda=args.caption, dry_run=args.dry_run)
        print(json.dumps({"media_id": media_id}))
    elif args.command == "telegram":
        ok = publicar_canal_telegram(args.image, args.text, args.url, dry_run=args.dry_run)
        print(json.dumps({"success": ok}))
    elif args.command == "whatsapp":
        ok = publicar_canal_whatsapp(args.image, args.text, args.url, dry_run=args.dry_run)
        print(json.dumps({"success": ok}))
    elif args.command == "auto":
        try:
            res = executar_pipeline_completo(
                url_shopee=args.url,
                titulo_custom=args.title,
                preco_custom=args.price,
                desconto_custom=args.discount,
                cupom_custom=args.coupon,
                dry_run=args.dry_run,
                force=args.force,
            )
            print(json.dumps(res, indent=2))
        except Exception as e:
            notificar_alerta_erro_telegram(
                origem="CLI auto",
                erro_msg=str(e),
                detalhes=traceback.format_exc(),
            )
            sys.exit(1)
    elif args.command == "discover":
        ofertas = buscar_melhores_ofertas(min_desconto=args.min_discount, limit_fetch=args.limit * 3, min_preco=args.min_price, tema=args.theme)
        print(json.dumps(ofertas[:args.limit], indent=2, ensure_ascii=False))
    elif args.command == "batch":
        try:
            res = executar_lote_autonomo(
                quantidade=args.count,
                min_desconto=args.min_discount,
                tema=args.theme,
                dry_run=args.dry_run,
                min_preco=args.min_price,
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
        except Exception as e:
            notificar_alerta_erro_telegram(
                origem=f"CLI batch ({args.theme})",
                erro_msg=str(e),
                tema=args.theme,
                detalhes=traceback.format_exc(),
            )
            sys.exit(1)
    elif args.command == "cooldown":
        ativo = obter_historico_ativo()
        agora = time.time()
        print(f"=== AUDITORIA DE COOLDOWN SHOPEE ({COOLDOWN_DIAS} DIAS / 2 SEMANAS) ===")
        print(f"Total de produtos sob janela de proteção: {len(ativo)}")
        for k, v in ativo.items():
            dias = (agora - v.get("posted_at", 0)) / 86400
            restante = max(0.0, COOLDOWN_DIAS - dias)
            print(f"- [shopId: {v.get('shop_id', 'N/A')}] [itemId: {k}] Postado há {dias:.1f}d | Restam {restante:.1f}d | {v.get('title')[:45]}...")
    elif args.command == "test-keys":
        res = testar_credenciais()
        print(json.dumps(res, indent=2))
    elif args.command == "test-alert":
        ok = notificar_alerta_erro_telegram(
            origem="CLI test-alert / Auditoria",
            erro_msg=args.msg,
            tema="teste",
            detalhes="Disparo de teste de verificação operacional para o bot @brncesarms_bot.",
        )
        print(json.dumps({"alerta_enviado": ok}))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
