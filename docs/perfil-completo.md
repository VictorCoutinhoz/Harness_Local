# Perfil completo

O perfil completo reúne as 26 skills do catálogo local. O ECC é fornecido pelo cliente quando já estiver presente. As rotas nomeiam apenas os fluxos de trabalho necessários a cada tarefa.

## Diretório de runtimes

Passe a raiz da instalação de ferramentas em `--runtime-root`. Para preparar um diretório novo, execute `python harness.py prepare-runtime $runtime`. O comando copia os launchers de `runtime/windows/` e preserva os existentes. Em seguida, instale os executáveis e os dados dos projetos de origem nos caminhos do catálogo. O comando `doctor --profile completo --strict` verifica o layout. As versões e revisões estão em `catalog.json`.

| Dependência | Layout esperado |
|---|---|
| PowerShell e Node | `runtimes/powershell/pwsh.exe` e `runtimes/node/node.exe` |
| Playwright | `playwright/Invoke-Playwright.ps1`, CLI Node, configuração de descoberta e Chromium local em `playwright/browsers/` |
| ast-grep | `ast-grep/upstream/main.py`, ambiente Python e binário em `ast-grep/bin/` |
| Ferramentas de projeto | Launchers de Agent Browser, Cartographer, Graphify, Impeccable, RepoWise, RTK e SkillSpector nas pastas indicadas pelo catálogo |
| Documentos e design | Ambiente e modelos do Docling, bases de consulta do UI UX Pro Max |
| Biblioteca de skills | CLI Skills Manager e a pasta `skills-manager/library/` |

Para usar Agent Browser em uma instalação nova, indique o Chromium local em `agent-browser/agent-browser.json`. Use a chave `executablePath` com o caminho do navegador, `autoConnect` com valor `false` e `contentBoundaries` com valor `true`.

`--skills-root` aponta para as pastas revisadas fornecidas pelo operador. Para importar uma skill de outra instalação, confirme a licença, a origem e a revisão. Rode o SkillSpector sobre a cópia preparada. O perfil completo reaproveita as dependências instaladas. As etapas de baixar pacotes e modelos do zero dependem dos projetos de origem.

## Playwright

O Planner entrega o projeto Playwright, a seed, o cenário, o resultado esperado e o caminho do teste. O Generator usa esse material para percorrer o fluxo, grava o teste e faz a primeira execução. O Healer parte da falha reproduzida, inspeciona a página, corrige o teste e repete a verificação.

Use o servidor `playwright-test` a partir da raiz do projeto. O launcher respeita a configuração daquele projeto. A rota recorre aos testes e ao navegador disponíveis se o MCP estiver indisponível.

## RepoWise

Indexe um repositório Git selecionado antes de ativar o MCP. Use o launcher do runtime offline e mantenha o índice em `.repowise/`.

```powershell
$repo = 'D:/projetos/exemplo'
& (Join-Path $runtime 'repowise/Invoke-RepoWise.ps1') init $repo --yes --no-prose --no-editor-setup --no-codex --no-save-key --provider mock --embedder mock
python harness.py prepare $repo --profile completo --runtime-root $runtime --skills-root $skills --repowise
```

O perfil anuncia `get_change_risk`, `get_dependency_path` e `get_why` para esse repositório. Confirme as inferências do grafo e do histórico com o código. [RepoWise 0.62.0](https://github.com/repowise-dev/repowise/releases/tag/v0.62.0)
