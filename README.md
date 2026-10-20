# 🛍️ Hermes E-commerce: Pipeline Autônomo de Afiliados

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Meta Graph API](https://img.shields.io/badge/Meta_Graph_API-v21.0-blueviolet.svg)](https://developers.facebook.com/)

Motor autônomo 24/7 de curadoria de ofertas, geração de cards promocionais em alta resolução, publicação em múltiplos canais (Instagram Stories e Telegram VIP) e auto-responder inteligente no Instagram Direct ("EU QUERO").

---

## 🚀 Funcionalidades Principais

* **Busca e Mineração de Ofertas (Shopee AMS):**
  - Consulta à API GraphQL oficial da Shopee com filtros por desconto mínimo (ex: >= 20%), comissão de afiliado e categoria temática.
  - Encurtamento e rastreamento de URLs comissionadas com parâmetros UTM customizados.

* **Renderização Dinâmica de Cards (Pillow):**
  - Geração automática de artes verticais (1080x1920) prontas para Stories.
  - Tipografia avançada (família Montserrat), logos transparentes, destaque de descontos, preços e CTAs de engajamento (*"Responda QUERO para receber o link"*).

* **Publicação Multi-Canal Autônoma:**
  - **Instagram Stories:** Publicação automática via Meta Graph API v21.0.
  - **Instagram Feed/Carrossel:** Autonomia de agendamento e publicação com legendas geradas via IA.
  - **Telegram VIP:** Postagem formatada com botões interativos inline (*"Comprar com Desconto"*).

* **Auto-Responder no Instagram Direct (DMs):**
  - Monitoramento contínuo da caixa de entrada via polling defensivo.
  - Detecção semântica de intenção de compra (*"quero"*, *"manda o link"*, *"preço"*, *"cupom"*).
  - Reconhecimento automático do Story ao qual o seguidor respondeu, enviando imediatamente o link de afiliado correto daquele produto.

* **Integração com LLM Local (Opcional):**
  - Suporte a modelos locais (ex: Qwen 2.5 32B via OpenAI API compatível) para geração de copywriting persuasivo e atendimento inteligente no Telegram.

---

## 📁 Estrutura do Repositório

```text
hermes-ecommerce/
├── shopee_engine.py          # Motor central de busca Shopee, renderização e publicação
├── instagram_dm_responder.py # Worker autônomo de resposta a DMs ("QUERO")
├── telegram_bot_responder.py # Bot interativo com LLM local para Telegram
├── credentials.env.example   # Template de variáveis de ambiente
├── requirements.txt          # Dependências Python
├── fonts/                    # Fontes Montserrat para renderização Pillow
├── templates/                # Templates gráficos 1080x1920
├── logos/                    # Logos de plataformas parceiras
├── scripts/                  # Scripts de cron para disparo por categoria
│   ├── shopee_achados.sh
│   ├── shopee_casa.sh
│   ├── shopee_feminino.sh
│   ├── shopee_informatica.sh
│   └── shopee_tech.sh
├── systemd/                  # Serviços systemd de segundo plano (24/7)
│   ├── hermes-instagram-dm.service
│   └── hermes-telegram-bot.service
└── docs/                     # Conformidade Meta e Documentação
    ├── PRIVACY_POLICY.md     # Política de Privacidade (Meta App Review)
    ├── TERMS_OF_SERVICE.md   # Termos de Serviço
    ├── DATA_DELETION.md      # Instruções de Exclusão de Dados do Usuário
    └── META_GRAPH_SETUP.md   # Guia de configuração no Meta Developers
```

---

## 🛠️ Instalação e Configuração

### 1. Clonar o Repositório
```bash
git clone https://github.com/brncesarms/hermes-ecommerce.git
cd hermes-ecommerce
```

### 2. Configurar o Ambiente Virtual Python
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurar Credenciais
Copie o template de exemplo e preencha suas chaves:
```bash
cp credentials.env.example credentials.env
chmod 600 credentials.env
nano credentials.env
```

> [!CAUTION]
> **Segurança:** O arquivo `credentials.env` contém segredos sensíveis e está incluído no `.gitignore`. Nunca faça commit ou compartilhe suas chaves.

---

## ⚡ Execução Operacional

### Teste de Validação das Chaves
```bash
python3 shopee_engine.py test-keys
```

### Publicar Lote de Ofertas nos Stories e Telegram
```bash
python3 shopee_engine.py batch --theme informatica --count 3 --min-discount 20
```

### Iniciar o Auto-Responder de Direct
```bash
# Execução direta com polling de 30s
python3 instagram_dm_responder.py --interval 30

# Modo de teste simulado (não envia DMs reais)
python3 instagram_dm_responder.py --once --dry-run
```

---

## ⚙️ Operação Autônoma com Systemd

Para manter o auto-responder de DMs e o bot do Telegram ativos 24/7 no Linux (como no Geekom A7 MAX):

```bash
mkdir -p ~/.config/systemd/user
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload

# Habilitar e iniciar
systemctl --user enable --now hermes-instagram-dm.service
systemctl --user enable --now hermes-telegram-bot.service

# Manter ativo após logout
loginctl enable-linger $USER

# Verificar status
systemctl --user status hermes-instagram-dm.service
```

---

## 📜 Conformidade e Meta App Review

Para submissão ao **Meta for Developers**:
* [Política de Privacidade](docs/PRIVACY_POLICY.md)
* [Termos de Serviço](docs/TERMS_OF_SERVICE.md)
* [Instruções de Exclusão de Dados](docs/DATA_DELETION.md)
* [Guia de Configuração da Graph API](docs/META_GRAPH_SETUP.md)

---

## 📄 Licença
Distribuído sob a licença **MIT**. Veja [LICENSE](LICENSE) para mais informações.
