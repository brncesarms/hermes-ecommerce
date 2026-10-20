"""Client unificado de inferência para o Hermes E-commerce.
Suporta modelos gratuitos do OpenCode (Zen) em nuvem.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Adicionar caminhos do ecossistema Hermes
HERMES_ROOT = Path("/home/brn/.hermes")
AGENT_DIR = HERMES_ROOT / "hermes-agent"
PLUGIN_OC_DIR = HERMES_ROOT / "plugins" / "oc-free-provider"

for p in (str(AGENT_DIR), str(PLUGIN_OC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("hermes.ecommerce.llm")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "credentials.env"


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
    return cfg


CFG = carregar_configuracoes()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", CFG.get("LLM_PROVIDER", "opencode")).lower()
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", CFG.get("OPENCODE_MODEL", "nemotron-3.5-lightning-free"))


def query_opencode(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.3,
    timeout: float = 25.0,
) -> str | None:
    """Consulta os modelos gratuitos do OpenCode Zen via plugin nativo."""
    target_model = model or OPENCODE_MODEL
    try:
        import hermes_oc_client as oc

        client = oc.OpenCodeClient()
        events, _ = client._direct_events(
            model=target_model,
            messages=messages,
            tools=None,
            tool_choice=None,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=None,
            stop=None,
            extra_body=None,
            extra={},
        )

        content_chunks: list[str] = []
        for ev in events:
            choices = ev.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            c = delta.get("content")
            if c:
                content_chunks.append(c)

        result = "".join(content_chunks).strip()
        if result:
            logger.info("Inferência bem-sucedida via OpenCode Zen (%s).", target_model)
            return result
        logger.warning("OpenCode Zen (%s) retornou conteúdo vazio.", target_model)
    except Exception as exc:
        logger.warning("Falha na inferência OpenCode (%s): %s", target_model, exc)
    return None


def generate_chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.3,
    provider: str | None = None,
) -> str | None:
    """Executa a inferência via OpenCode Free na nuvem."""
    selected_provider = (provider or LLM_PROVIDER).lower()

    if selected_provider == "opencode":
        return query_opencode(messages, model=model, max_tokens=max_tokens, temperature=temperature)

    logger.warning("Provedor não suportado ou descontinuado: %s", selected_provider)
    return None
