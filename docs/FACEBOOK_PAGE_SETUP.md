# Guia de Configuração: Página do Facebook (Radar de Preço Baixo)

Este guia orienta a integração da Página do Facebook à esteira de postagens autônoma do Hermes E-commerce.

---

## 📌 Identificação Canônica da Página
- **Nome:** Radar de Preço Baixo
- **URL Pública:** `https://www.facebook.com/radar.de.preco.baixoo/`
- **Page ID:** `61595220492675`

---

## 🚀 Método 1: Disparo Direto via Meta Graph API (Recomendado)

O motor determinístico `shopee_engine.py` já possui suporte completo para postar fotos e legendas persuasivas com links de afiliados diretamente na sua Página do Facebook.

### Passo a Passo para Gerar o Page Access Token:

1. **Acesse o Graph API Explorer da Meta:**
   - [https://developers.facebook.com/tools/explorer/](https://developers.facebook.com/tools/explorer/)
2. **Selecione seu Aplicativo Meta:**
   - No canto superior direito, selecione o seu aplicativo (ex: `openclaw-shopee-ecommerce`).
3. **Selecione as Permissões Necessárias:**
   Em **Permissions** ➔ **Events Groups Pages**, adicione:
   - `pages_manage_posts` (Permite que o bot publique na página)
   - `pages_read_engagement` (Permite ler o status da página)
   - `pages_show_list` (Permite listar suas páginas)
4. **Gerar o Token da Página:**
   - Em **User or Page**, selecione a sua Página: **Radar de Preço Baixo (61595220492675)**.
   - Clique em **Generate Access Token**.
5. **Estender para Token de Longa Duração (60 dias ou Permanente):**
   - Acesse o [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/).
   - Cole o token gerado e clique em **Depurar (Debug)**.
   - No final da página, clique em **Extend Access Token** para gerar o token de longa duração.
6. **Inserir em `credentials.env`:**
   Edite o arquivo `/home/brn/.hermes/ecommerce/credentials.env`:
   ```bash
   FACEBOOK_PAGE_ID="61595220492675"
   FACEBOOK_PAGE_URL="https://www.facebook.com/radar.de.preco.baixoo/"
   FACEBOOK_PAGE_ACCESS_TOKEN="SEU_PAGE_ACCESS_TOKEN_AQUI"
   FACEBOOK_GRAPH_URL="https://graph.facebook.com/v21.0"
   ```
7. **Testar a Conectividade:**
   ```bash
   hermes-radar test
   ```

---

## 🔄 Método 2: Cross-Posting Automático Nativo (Instagram ➔ Facebook)

Você também pode ativar o espelhamento automático nativo da Meta diretamente pelo app do Instagram. Dessa forma, qualquer Story, Post ou Reel publicado no Instagram é automaticamente replicado na Página do Facebook:

1. Abra o aplicativo do **Instagram** no celular logado na conta `@radar.de.preco.baixo`.
2. Vá em **Perfil** ➔ Menu (3 traços) ➔ **Central de Contas (Meta Accounts Center)**.
3. Toque em **Experiências conectadas** ➔ **Compartilhamento entre perfis**.
4. Selecione a conta `@radar.de.preco.baixo` no campo *Compartilhar de*.
5. Selecione a Página **Radar de Preço Baixo** no campo *Compartilhar em*.
6. Ative as opções:
   - ✅ **Seus stories do Instagram**
   - ✅ **Suas publicações do Instagram**
   - ✅ **Seus reels do Instagram**

---

## 🛠️ Comandos de Operação Determinísticos

- **Verificar status dos canais:**
  ```bash
  hermes-radar status
  ```
- **Testar credenciais das APIs:**
  ```bash
  hermes-radar test
  ```
- **Publicar manualmente na Página do Facebook via CLI:**
  ```bash
  python3 /home/brn/.hermes/ecommerce/shopee_engine.py facebook \
    --image /caminho/para/imagem.png \
    --text "🔥 ACHADO IMPERDÍVEL! Confira essa promoção..." \
    --url "https://s.shopee.com.br/exemplo"
  ```
