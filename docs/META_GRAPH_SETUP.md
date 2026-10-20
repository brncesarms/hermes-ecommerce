# Guia de Configuração: Meta for Developers & Instagram Graph API

Este guia detalha o passo a passo para configurar o aplicativo no **Meta for Developers** e conectar a esteira autônoma do Hermes E-commerce.

---

## 1. Ativação Obrigatória no App do Celular (Instagram)
Para que a Graph API consiga enxergar qualquer mensagem na caixa de Direct, a conta profissional precisa autorizar ferramentas conectadas:

1. Abra o app do **Instagram** logado na conta profissional (ex.: `@radar.de.preco.baixo`).
2. Acesse seu **Perfil** ➔ Menu (3 traços) ➔ **Configurações e privacidade**.
3. Em *Como outros podem interagir com você*, toque em **Mensagens e respostas ao story**.
4. Toque em **Ferramentas conectadas**.
5. Ative a chave: **Permitir acesso a mensagens** (*Allow access to messages*).

---

## 2. Configurações Básicas no Meta for Developers
Acesse [developers.facebook.com](https://developers.facebook.com/) ➔ Seu App ➔ **Configurações do aplicativo** ➔ **Básicas**:

* **URL da Política de Privacidade:**  
  `https://github.com/brncesarms/hermes-ecommerce/blob/main/docs/PRIVACY_POLICY.md`
* **URL dos Termos de Serviço:**  
  `https://github.com/brncesarms/hermes-ecommerce/blob/main/docs/TERMS_OF_SERVICE.md`
* **Exclusão de Dados do Usuário:**  
  Selecione *URL das instruções de exclusão de dados* e informe:  
  `https://github.com/brncesarms/hermes-ecommerce/blob/main/docs/DATA_DELETION.md`
* **Categoria do Aplicativo:** Negócios e Páginas (*Business*)
* **Ícone do Aplicativo:** Imagem 1024x1024 pixels

---

## 3. Modo de Desenvolvimento vs. Modo Ativo (Live)

### Modo de Desenvolvimento (Para Testes Imediatos)
No modo de desenvolvimento, a Meta só permite que pessoas registradas como **Testadores** recebam mensagens automatizadas:
1. Vá em **Funções do aplicativo** ➔ **Funções**.
2. Em **Testadores do Instagram**, adicione o `@usuario` da sua conta pessoal de teste.
3. No app do Instagram do testador, vá em **Configurações ➔ Apps e sites ➔ Convites de testador** e clique em **Aceitar**.

### Modo Ativo (Para qualquer seguidor receber links)
1. Preencha todos os campos da Seção 2 acima.
2. Alterne a chave no topo do painel de **Em desenvolvimento** para **Ativo**.
3. Se solicitado, conclua a Verificação de Uso de Dados (*Data Use Checkup*).
4. Submeta a permissão `instagram_manage_messages` para análise caso seu app utilize o tipo Empresarial (*Business App*).
