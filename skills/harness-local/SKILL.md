---
name: harness-local
description: Retoma contexto entre sessões e encaminha tarefas para as skills, agentes e MCPs disponíveis no perfil Harness_Local. Use para escolher um fluxo, continuar um projeto ou guardar uma decisão.
---

# Harness_Local

Leia `references/routes.md`, gerado pela preparação do perfil, e escolha os recursos necessários para o pedido. Use [revisar-escrita](../revisar-escrita/SKILL.md) durante a redação. Consulte `references/commands.md` para descobrir o banco e os launchers deste perfil.

1. Ao retomar um projeto, consulte `harness_local.memory_recall` com termos curtos e até cinco notas. Em um repositório Git, use `git rev-parse --path-format=absolute --git-common-dir` para obter o escopo compartilhado pelas worktrees. Fora do Git, use a raiz absoluta do projeto.
2. Confirme as notas com o estado atual. Ao concluir uma decisão reutilizável ou uma passagem de trabalho, use `memory_save` com chave, escopo, origem e resumo curto. Reserve o escopo pessoal para preferências duráveis pedidas pelo usuário.
3. Escolha a skill mais específica da rota. Quando houver agentes, passe o objetivo, a raiz do projeto, a evidência disponível e o artefato esperado. Use o MCP correspondente para verificar o resultado. Quando faltar uma ferramenta, siga a alternativa da rota.
4. Use `expected_revision` para editar ou esquecer uma nota existente. Registre decisões e resultados verificáveis. Preserve credenciais, dados pessoais sensíveis e transcrições fora da memória.
