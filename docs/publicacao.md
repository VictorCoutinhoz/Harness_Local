# Preparação para publicação

O nome do projeto é **Harness_Local**. A raiz Git usa a branch `main`.

Antes do primeiro envio ao GitHub:

1. Defina a licença do código próprio e a visibilidade do repositório.
2. Confira os arquivos do commit com `git diff --cached --stat` e `python tests/check_release.py`. Os bancos, perfis gerados, bibliotecas importadas e binários ficam nas instalações locais.
3. Rode os testes em um checkout novo e prepare o perfil base. Para a edição Windows completa, compare catálogo e serviços com a [verificação nativa](validacao.md).
4. Revise [origens e licenças](../THIRD_PARTY.md) e registre a lista de componentes e versões da primeira release.

Os hooks pedem revisão pelo cliente. A configuração usa permissões, credenciais e modelos selecionados no Codex. A publicação pode começar pelo núcleo e pelo catálogo, com runtimes escolhidos conforme as tarefas do usuário.
