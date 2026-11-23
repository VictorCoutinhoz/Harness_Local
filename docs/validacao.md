# Verificação no Windows

Prepare um perfil de teste separado e execute os testes do projeto.

```powershell
python -m unittest discover -s tests -v
python tests/verify_native.py --codex $codex --runtime-root $runtime --skills-root $skills --label desktop --repowise
python tests/verify_native.py --codex $codexDaExtensao --runtime-root $runtime --skills-root $skills --label vscode
```

Os argumentos `--codex` devem indicar os binários nativos correspondentes. Para o VS Code, execute com o PATH que a extensão recebe do Windows. O teste cria Git, navegador, configuração e banco de memória descartáveis na pasta de verificação local. Ele compara a configuração efetiva do cliente com a gerada pelo projeto.

## Resultado de 23 de novembro de 2026

| Verificação | Codex Desktop | Extensão do VS Code |
|---|---|---|
| Skills do projeto | 26 | 26 |
| Perfis de agentes preparados | 3 | 3 |
| Memória SQLite | Gravação e recuperação pelo MCP | Gravação e recuperação pelo MCP |
| ast-grep | Duas chamadas de código identificadas | Duas chamadas de código identificadas |
| Playwright | 92 ferramentas e um teste de navegador aprovado | 92 ferramentas e um teste de navegador aprovado |
| RepoWise por repositório | Consulta de risco retornada pelo MCP | — |

Os testes do Playwright verificaram a disponibilidade das ferramentas usadas pelos três papéis e executaram um cenário local. Os testes unitários cobrem os hooks com os comandos gerados, a memória entre sessões, a instalação idempotente, a proteção contra arquivos conflitantes e a preparação dos launchers.

## Revisão das skills

O SkillSpector foi executado sobre as 26 cópias preparadas. O catálogo de referências do Taste e as instruções de automação do Claude Code foram reduzidos às tarefas do harness. A segunda análise passou nas quatro skills ajustadas.

Os achados restantes exigiram interpretação do código. Cartographer usa padrões para excluir arquivos sensíveis. O gerador de notebook protege o arquivo de destino e aceita substituição explícita. O fluxo de entrevista resolve dúvidas pela evidência disponível. No UI UX Pro Max, os exemplos de caminhos e artefatos externos ficaram parcialmente resolvidos pela análise estática. Uma consulta de cores no perfil gerado retornou um resultado da base local.
