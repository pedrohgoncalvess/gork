# Versionamento e notas de versão

O Gork usa [SemVer](https://semver.org/lang/pt-BR/) com tags Git anotadas no formato `vMAJOR.MINOR.PATCH`. Atualize `project.version` em `pyproject.toml` para a mesma versão, sem o prefixo `v`, antes de criar a tag. Use `PATCH` para correções compatíveis, `MINOR` para novos recursos compatíveis e `MAJOR` para mudanças incompatíveis. Durante `0.x`, sinalize mudanças incompatíveis em destaque nas notas e incremente pelo menos `MINOR`.

## Formato do changelog

Adicione a nova versão no topo de `CHANGELOG.md`, com a data de lançamento em `AAAA-MM-DD`. Use somente os grupos que têm entradas. Escreva uma mudança por item e descreva o efeito para quem usa ou mantém o Gork. Inclua instruções de migração e links para issues ou PRs quando forem relevantes.

```markdown
## [MAJOR.MINOR.PATCH] - AAAA-MM-DD

### Adicionado
- Novos recursos e comandos.

### Alterado
- Mudanças no comportamento ou na configuração.

### Corrigido
- Correções e o comportamento que elas restauram.

### Depreciado
- Recursos com remoção prevista e sua alternativa.

### Removido
- Recursos removidos e passos de migração.

### Segurança
- Correções de segurança e ações necessárias.
```

## Publicação

1. Atualize `pyproject.toml` e as notas da versão em `CHANGELOG.md`. Rode `uv lock --check` para verificar o arquivo de dependências.
2. Passe o commit pela CI em `main` e crie a tag anotada com `git tag -a vMAJOR.MINOR.PATCH -m "Gork MAJOR.MINOR.PATCH"`.
3. Publique a tag em um push separado com `git push origin vMAJOR.MINOR.PATCH`. O workflow valida a versão, roda a suíte e publica a imagem da API no GitHub Container Registry com a tag da versão, por exemplo `ghcr.io/pedrohgoncalvess/gork:v0.1.0`.

Se o GitHub registrar a tag sem iniciar o workflow, publique em `main` um commit com a mensagem exata `CI: publish vMAJOR.MINOR.PATCH`. Use `git commit --allow-empty -m "CI: publish vMAJOR.MINOR.PATCH"` se não houver alterações a registrar. O workflow testa e empacota o código da tag existente.

O Gork lê o `CHANGELOG.md` que acompanha a imagem por meio de `consult_gork_knowledge` com `topic=releases`. A consulta também informa `project_version` de `pyproject.toml`. Versões antigas podem ser consultadas pelas notas preservadas no arquivo.
