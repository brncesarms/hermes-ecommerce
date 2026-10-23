---
version: alpha
name: Radar de Preco Baixo Design System
description: Especificacao visual oficial para criacao e renderizacao autonoma de cards, stories e posts para o Radar de Preco Baixo (@radar.de.preco.baixo) no ecossistema Hermes.

colors:
  primary: "#D03E1F"
  primary-hover: "#B33216"
  secondary: "#05152C"
  secondary-dark: "#020B18"
  surface-card: "#FFFFFF"
  surface-subtle: "#F8FAFC"
  text-main: "#0F172A"
  text-muted: "#64748B"
  text-strikethrough: "#94A3B8"
  accent-green: "#10B981"
  accent-gold: "#F59E0B"
  telegram-blue: "#229ED9"
  whatsapp-green: "#25D366"

typography:
  headline-display:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 40px
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: -0.5px
  price-current:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 68px
    fontWeight: 800
    lineHeight: 1.0
    letterSpacing: -1px
  price-original:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 30px
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: 0px
  badge-discount:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 34px
    fontWeight: 800
    lineHeight: 1.0
    letterSpacing: 0.5px
  cta-button:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 38px
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: 0px
  body-sm:
    fontFamily: "Montserrat, sans-serif"
    fontSize: 24px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0px

rounded:
  sm: 12px
  md: 24px
  lg: 35px
  full: 9999px

spacing:
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 60px
  safe-top: 250px
  safe-bottom: 280px

components:
  card-container:
    backgroundColor: "{colors.surface-card}"
    rounded: "{rounded.lg}"
    padding: 40px
  canvas-background:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.surface-card}"
  canvas-subtle:
    backgroundColor: "{colors.secondary-dark}"
    textColor: "{colors.surface-subtle}"
  product-title:
    textColor: "{colors.text-main}"
    typography: "{typography.headline-display}"
  product-metadata:
    textColor: "{colors.text-muted}"
    typography: "{typography.body-sm}"
  price-display:
    textColor: "{colors.primary}"
    typography: "{typography.price-current}"
  price-strikethrough:
    textColor: "{colors.text-strikethrough}"
    typography: "{typography.price-original}"
  badge-discount:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface-card}"
    rounded: "{rounded.sm}"
    padding: 14px
  badge-shipping:
    backgroundColor: "{colors.accent-green}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.sm}"
    padding: 12px
  badge-rating:
    backgroundColor: "{colors.accent-gold}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.sm}"
  button-cta:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface-card}"
    rounded: "{rounded.full}"
    height: 105px
  button-cta-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface-card}"
  pill-telegram:
    backgroundColor: "{colors.telegram-blue}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.full}"
  pill-whatsapp:
    backgroundColor: "{colors.whatsapp-green}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.full}"
---

# Radar de Preco Baixo — Design System

Este documento define a identidade visual e as regras de composição gráfica do **Radar de Preco Baixo (@radar.de.preco.baixo)**. Serve como a Fonte Unica da Verdade (SSOT) para os agentes do ecossistema Hermes (Hermes Agent, AGY e OpenCode) durante a geracao e renderizacao de cards de e-commerce (Pillow, HTML Canvas ou imagem vetorial).

---

## Filosofia Visual e Brand Voice

O Radar de Preco Baixo combina **urgencia promocional com confianca e elegancia editorial**:
1. **Clareza Imediata (Eye-Catching):** O usuario de Stories ou Feed deve identificar em menos de 1 segundo o produto, o percentual de desconto e o preco promocional.
2. **Sem Poluicao Visual:** Fundos limpos (canvas Navy profundo com card branco flutuante), tipografia geometrica uniforme (Familia Montserrat) e espacamento generoso.
3. **Credibilidade de Plataforma:** Destaque para logos oficiais (Shopee Oficial, Amazon Prime) para reforcar garantia e seguranca da compra.

---

## Formatos e Safe Zones (Zonas de Seguranca)

### 1. Instagram Stories (1080 x 1920 px — Proporcao 9:16)
O formato principal de divulgacao opera com zonas estritas para nao sofrer sobreposicao dos elementos nativos do app do Instagram:

* **Top Safe Zone (0 a 250 px):** Proibido posicionar textos, titulos, selos ou logos. Esta area e ocupada pela barra de progresso, foto do perfil e botao de fechar.
* **Bottom Safe Zone (1640 a 1920 px):** Proibido posicionar elementos criticos fora do botao de CTA integrado. A barra de resposta ("Enviar mensagem"), o icone de curtir e o de compartilhar cobrem esta regiao.
* **Margens Laterais (X: 0 a 55 px e X: 1025 a 1080 px):** Area de respiro para evitar cortes em telas de smartphones com proporcoes ultra-wide (20:9 ou 21:9).
* **Card Central Utilizavel:** `X: 55px` a `1025px` (largura 970px), `Y: 340px` a `1690px` (altura 1350px). Raio de curvatura de `35px`.

### 2. Instagram Feed / Carrossel (1080 x 1350 px — Proporcao 4:5)
* Utilizado para posts de lotes tematicos e carrosseis informativos.
* Safe zone vertical de 135px no topo e no rodape para manter enquadramento perfeito na grade quadrada (1:1 / 1080x1080) do perfil.

---

## Hierarquia Tipografica e Textos

Toda a comunicacao visual utiliza exclusivamente a **Familia Montserrat** (disponivel em `fonts/`):

1. **Preco Atual ("Por R$"):**
   * Montserrat ExtraBold (68px a 72px) em tom `#D03E1F` (Shopee escuro) ou `#0F172A`.
   * Deve ser o elemento com maior peso visual de toda a peca.
2. **Preco Original Riscado ("De R$"):**
   * Montserrat Medium (28px a 32px) em tom `#94A3B8`, com linha horizontal central riscando o valor.
3. **Selo de Desconto ("-XX% OFF" ou "🔥 -XX%"):**
   * Posicionado no canto superior esquerdo do card (`X: 85px`, `Y: 365px`).
   * Fundo retangular arredondado (`radius: 12px`) com preenchimento `#D03E1F` e texto branco Montserrat ExtraBold (34px).
4. **Titulo do Produto:**
   * Montserrat Bold / SemiBold (34px a 38px) em tom `#0F172A`.
   * Limitado a no maximo 2 linhas legiveis (45 a 55 caracteres), com sufixo reticencias (`...`) caso ultrapasse.
5. **Botao de Acao (CTA):**
   * Retangulo arredondado inferior (`Y: 1730px` a `1835px`) com `radius: 52px` (pill button).
   * Texto: Montserrat Bold (38px) em branco, centralizado: *"EU QUERO"* ou *"RESPONDA 'QUERO' NO DIRECT"*.

---

## Tratamento da Imagem do Produto

* **Dimensoes Maximas no Card:** Caixa delimitadora de `760 x 740 px`, centralizada horizontalmente no Story (`X_center = 540px`).
* **Qualidade de Redimensionamento:** Sempre utilizar reamostragem `LANCZOS` (`Image.Resampling.LANCZOS`).
* **Transparencia e Fundo:**
  - Imagens com fundo transparente (PNG/WebP) devem ser compostas com canal alpha limpo.
  - Imagens com fundo branco integram-se perfeitamente ao corpo branco do card central.

---

## Regras de Execucao (Do's and Don'ts)

### ✅ Do's (Praticas Obrigatorias)
* **Manter o Contraste WCAG:** Todo texto promocional deve atingir pelo menos 4.5:1 de contraste em relacao ao fundo.
* **Respeitar os Limites do Canvas:** Todo o conteudo vital deve permanecer estritamente dentro da area `Y: 250px` a `Y: 1640px`.
* **Utilizar Sempre a Linha de Base Shopee:** Logo oficial transparente em `logos/shopee-logo.webp` redimensionado para maximo `240x90px` no canto superior direito do card.
* **Destaque de Frete Gratis / Cupom:** Quando houver frete gratis ou cupom adicional, utilizar badge auxiliar em tom `#10B981` (Verde).

### ❌ Don'ts (Praticas Proibidas)
* **Nao alterar a proporcao da imagem:** Jamais esticar ou achatar a foto do produto (manter sempre `aspect ratio` original via `thumbnail`).
* **Nao usar fontes genericas:** Nao utilizar Arial, Roboto ou sans-serif do sistema quando os arquivos Montserrat estiverem disponiveis em `fonts/`.
* **Nao cobrir a barra de acao inferior:** Nao colar o preco ou o titulo no rodape do Story.
* **Nao omitir o simbolo "R$":** Valores devem ser formatados no padrao brasileiro (`R$ 199,90`), nunca padrao americano (`$199.90`).
