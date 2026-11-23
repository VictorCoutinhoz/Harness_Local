---
name: claude-automation-recommender
description: Analisa a estrutura de um projeto e recomenda skills, agentes, hooks, plugins ou MCPs do Claude Code a partir da stack e das tarefas recorrentes.
---

# Sugestões de automação para Claude Code

Comece pelo objetivo do usuário e pela configuração pertinente ao projeto. Consulte manifests, testes, comandos documentados e tarefas recorrentes. Use as integrações já disponíveis como referência para identificar onde existe trabalho repetido ou uma verificação que costuma ser esquecida.

1. Identifique a ação recorrente e a evidência de que ela precisa de automação.
2. Sugira o recurso mais simples que atende ao pedido. Use skills para orientações reutilizáveis, agentes para papéis com entregas claras, hooks para eventos previsíveis e MCPs para integrar uma ferramenta ou fonte de dados.
3. Informe o escopo, os requisitos da integração, os dados necessários e o modo de verificar a ativação. Confirme o comportamento e a revisão na documentação de origem.
4. Entregue uma proposta de poucas opções com a ordem sugerida. Quando o pedido for sobre permissões ou precedência de configurações, use `claude-settings-audit`.

A análise termina na proposta. A configuração de um recurso segue o escopo da mudança solicitada no projeto.

[Claude Code Setup](https://github.com/anthropics/claude-plugins-official/tree/e6143c9807a001832badb63e89d58ffe25d542ec/plugins/claude-code-setup) · [Documentação do Claude Code](https://code.claude.com/docs/en/overview)
