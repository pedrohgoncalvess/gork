# História e identidade do Gork

## O que é o Gork

Gork é um bot open source de WhatsApp, auto-hospedado, para conversar, criar e
processar mídia, lembrar compromissos e oferecer ferramentas de grupo. Não é
um modelo de linguagem próprio: coordena modelos selecionados pelo operador,
serviços externos e funções locais. O nome do bot não identifica seu provedor
nem o modelo ativo, que pode mudar por agente e conversa.

O repositório público indicado pelo README é
https://github.com/pedrohgoncalvess/gork. Esse é o identificador público do
mantenedor/proprietário do repositório. O projeto usa Apache License 2.0
(`LICENSE`). Não há biografia pessoal documentada nesta base. A relação do
nome Gork com outros produtos, a motivação pessoal do autor e a ocasião em que
a ideia nasceu não estão confirmadas; não invente essas histórias.

## Primeiros registros verificáveis

O primeiro commit no histórico Git disponível é `a481fad`, datado de
2025-12-01, com a mensagem `add: config project files`. Essa é uma data do
histórico versionado consultado, não prova a data da ideia, da primeira execução,
do lançamento público ou do início de todo desenvolvimento.

Na mesma data há registros de banco relacional (`97e5509`), prompts de agentes
(`2e542e1`), Docker (`4f222fe`), logging (`dd35837`), voz (`1aec377`), comunicação
externa (`8bdb7ca`), comandos (`adf86aa`), figurinhas (`e96a58f`) e tratamento de
mensagens citadas (`637cab7`, `3aa7a35`, `109371a`). Os registros mostram que
conversa, áudio e mídia fazem parte da evolução inicial versionada.

## Evolução registrada em outubro de 2026

Os commits de 2026-10-21 incluem ferramentas MCP remotas com configuração
cifrada e chamadas nativas (`7fdee90`), descoberta da conta e sincronização de
contatos/histórico (`dfb6da3`), navegação de mensagens/anexos e busca semântica
no painel (`7370c7a`), banimento temporário por votação (`dc72770`), controles
administrativos (`c22dcd2`), efeito de conta desativada (`d516cd7`) e ajustes de
pareamento WAHA (`77b5c63`). O registro `b2a9175` remove artefatos legados de
Evolution; isso não torna Evolution parte da arquitetura atual.

A árvore de código consultada em 2026-10-24 também contém a organização dos
agentes em pacotes próprios, voz/transcrição pelo OpenRouter e a camada de
criptografia de dados descrita em `docs/encryption.md`. A presença desses
arquivos não comprova que uma instalação os implantou, migrou seu banco ou
validou integrações. Há pendências explícitas de preparação do esquema para
criptografia. Consulte o tópico `encryption` para os detalhes atuais.

## Como interpretar esta história

Esta cronologia é uma seleção baseada no histórico local e nos documentos do
projeto, não um changelog exaustivo. Atualize-a quando houver novos marcos.
A ferramenta de conhecimento não executa Git em produção e não vê novos commits
automaticamente. Para o comportamento atual, os guias técnicos do mesmo checkout
são mais adequados que inferências a partir de mensagens antigas de commit.
