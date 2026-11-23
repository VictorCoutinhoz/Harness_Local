---
name: claude-settings-audit
description: Audita configurações e permissões de um projeto no Claude Code. Identifique o escopo dos arquivos e proponha regras de leitura específicas para a stack detectada.
license: Apache-2.0
---

# Auditoria de configurações do Claude Code

Produza um diagnóstico e uma proposta de configuração para o escopo solicitado. Identifique a versão do Claude Code quando ela afetar a sintaxe ou a precedência das regras. Consulte a documentação vigente de [arquivos de configuração](https://code.claude.com/docs/en/settings) e [permissões](https://code.claude.com/docs/en/permissions).

1. Identifique o projeto, o objetivo da auditoria e os escopos de configuração pertinentes. No Windows, use `rg --files --hidden --maxdepth 2` com globs dos arquivos que precisa inspecionar. Procure manifests como `package.json`, `pyproject.toml`, `Cargo.toml` e `go.mod`, arquivos de lock e a configuração de monorepo.
2. Leia a configuração do projeto pertinente à auditoria. `.claude/settings.json` é compartilhado no projeto e `.claude/settings.local.json` é pessoal no projeto. Para auditar regras do usuário ou regras gerenciadas, use o arquivo ou trecho que ele indicar. Para cada ajuste, identifique o escopo, o valor efetivo que conseguiu verificar e os campos que requerem confirmação. Registre apenas os nomes de campos sensíveis.
3. Proponha só os comandos ou acessos que resolvem a tarefa. Prefira operações de leitura da ferramenta e argumentos exatos. Verifique efeitos colaterais de flags e de comandos que carregam configurações ou executam scripts do projeto. Por exemplo, uma proposta pode admitir `Bash(git status --short)` para uma consulta recorrente em um repositório confiável. Preserve as regras existentes na proposta.
4. Entregue observação, impacto e alteração sugerida para cada item. Inclua JSON válido quando o usuário pedir um exemplo aplicável. A auditoria termina na proposta. Faça uma edição apenas a pedido do usuário e no escopo indicado.

Para recomendações de automação, consulte [claude-automation-recommender](../claude-automation-recommender/SKILL.md).
