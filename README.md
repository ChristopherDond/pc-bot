# pc-bot

Agentes de IA controlando o **Windows** — clicando, digitando e navegando da forma mais confiável possível, com um **cursor overlay visível** para o usuário acompanhar cada ação.

## Por quê

O computer use tradicional (ex: cua-driver) depende de uma única árvore de acessibilidade para "ler" a tela. Quando essa árvore está incompleta (browsers modernos, apps Electron, canvas como Google Docs), o clique falha. O pc-bot resolve isso com **camadas**: cada uma tenta ser a mais confiável possível, e o orquestrador cai para a próxima apenas quando necessário.

```
┌──────────────────────────────────────────────┐
│  A · NATIVA (UIA/pywinauto)                  │  ← mais confiável para apps nativos
│    clica por propriedade real do elemento     │
├──────────────────────────────────────────────┤
│  B · BROWSER (CDP/Playwright)                │  ← mais confiável para a web
│    clica por seletor DOM real (ref)           │
├──────────────────────────────────────────────┤
│  C · PIXEL (pyautogui/OpenCV)                │  ← último recurso
│    clica por coordenada / template matching   │
└──────────────────────────────────────────────┘
```

Cada ação reporta o **nível de confiança** usado:
- **A** = clique por elemento (árvore UIA do Windows)
- **B** = clique por DOM (navegador via CDP)
- **C** = clique por pixel (fallback — use com cuidado)

## O cursor overlay

Uma janela transparente em toda a tela (via `UpdateLayeredWindow` + alpha por pixel) desenha um **anel colorido** que desliza até onde o agente vai clicar. Ele **não rouba o foco, não intercepta cliques e fica invisível quando não há ação** — o usuário vê exatamente onde o agente está agindo, mas pode continuar trabalhando em outra janela.

## Instalação

```bash
# requer Python 3.11+
pip install -e .
python -m playwright install chromium   # baixa o Chromium pro CDP (opcional, só p/ web)
```

## Uso

### CLI

```bash
pcbot state                    # lista janelas abertas
pcbot find --name "Editor"     # busca elementos nativos
pcbot click --name "Salvar"    # clica num elemento pelo nome
pcbot click --x 640 --y 400    # clica por coordenada (fallback)
pcbot type "Olá mundo"         # digita na janela ativa
pcbot screenshot               # captura a tela
pcbot demo                     # demo do cursor overlay
```

### Como biblioteca (Python)

```python
from pcbot.agent import AgentDesktop
from pcbot.overlay import CursorOverlay

overlay = CursorOverlay()          # cursorzinho visível
overlay.start()
agent = AgentDesktop(overlay=overlay)

state = agent.get_state()          # janelas abertas
print(state)

result = agent.click(name="Salvar")      # camada A (UIA)
result = agent.click(x=640, y=400)       # camada C (pixel)
print(result["confidence"], result)
```

### Como MCP server (para qualquer agente de IA)

```bash
pcbot-mcp                 # só camadas nativas + pixel
pcbot-mcp --browser       # adiciona a camada browser CDP
```

Depois, configure seu agente (Claude, Hermes, Cursor, etc.) para apontar o MCP:

```json
{
  "mcpServers": {
    "pc-bot": {
      "command": "pcbot-mcp",
      "args": ["--browser"]
    }
  }
}
```

O agente ganha as tools: `screenshot`, `get_state`, `click`, `type_text`, `find`, `browser_goto`, `browser_dom`, `browser_click`, `browser_type`, `browser_text`.

### Plugins

Plugins são módulos Python em `pcbot/plugins/` descobertos automaticamente pelo orquestrador. Exemplo: um plugin pode expor ações de apps específicos (Spotify, Excel, etc.).

## Arquitetura

| Módulo | Papel |
|---|---|
| `pcbot/overlay.py` | Cursor overlay (janela transparente + anel animado) |
| `pcbot/native.py` | Camada A: UIA via pywinauto (inspecionar, clicar, digitar) |
| `pcbot/browser.py` | Camada B: navegador via Playwright/CDP (DOM com refs) |
| `pcbot/pixel.py` | Camada C: screenshot + clique por coordenada + template matching |
| `pcbot/agent.py` | Orquestrador `AgentDesktop` com regra de confiança A/B/C |
| `pcbot/mcp_server.py` | Exposição como MCP (tools para agentes) |
| `pcbot/cli.py` | CLI (`pcbot …`) |
| `pcbot/plugins/` | Plugins auto-descobertos |

## Testes

```bash
python tests/mcp_client_test.py    # conecta um client MCP stdio e chama get_state
```

## Avisos

- **Segurança:** valide o `confidence` em cada resposta antes de agir. Cliques de nível **C** (pixel) devem pedir confirmação ao usuário.
- **Irreversibilidade:** clique errado = ação errada. Para ações sensíveis (apagar, enviar, pagar), o agente deve confirmar antes.
- **Detecção:** cliques sintéticos podem ser detectados por sites que verificam `isTrusted`. Nenhum sistema de automação de desktop escapa disso.

## Roadmap

- [x] Camada nativa UIA (clique/digitação por propriedade)
- [x] Camada browser CDP (DOM com refs, clique real)
- [x] Camada pixel (coordenada + template matching OpenCV)
- [x] Cursor overlay visual (alpha por pixel, sem roubo de foco)
- [x] MCP server (tools para agentes)
- [x] CLI
- [ ] Plugin de OCR (ler texto da tela como fallback de estado)
- [ ] Recording/Playback (gravar trajetórias e repetir)
- [ ] Suporte a múltiplos monitores
- [ ] Modo dry-run (mostrar plano antes de executar)

---

Projeto criado para agentes de IA que precisam de um "par de mãos" confiável no Windows. Feito com ❤️ e commits orgânicos.