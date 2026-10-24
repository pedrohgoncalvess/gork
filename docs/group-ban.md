# Votação de banimento temporário

## Exemplo rápido

```text
!ban @usuário :time 30min :expiration 5
```

Nesse exemplo, a votação fica aberta por até cinco minutos. Se houver quórum e
maioria favorável, o Gork apaga mensagens novas do alvo por trinta minutos.
O participante continua no grupo: a função não o expulsa nem o impede de enviar
mensagens no cliente WhatsApp. O Gork precisa estar ativo e ser administrador
para excluir essas mensagens.

| Etapa | Resultado esperado |
| --- | --- |
| Abertura | Enquete e aviso com menções aos membros |
| Decisão | Mensagem com votos, participação e motivo |
| Ban aprovado | Exclusão de mensagens novas até o prazo |
| Intervenção manual | Cancelar votação ou encerrar ban pelo painel |

Em grupos autorizados, use `!ban @usuário :time 30min`, mencionando exatamente um
membro pelo WhatsApp. Qualquer membro autorizado a usar comandos pode propor a
votação; a conta do Gork precisa ser administradora do grupo.
Também aceita a menção ao bot antes do comando, como `@Gork !ban @usuário :time=5`.
A menção ao Gork é ignorada ao escolher o membro que será votado.

O parâmetro `:time` aceita `3hr`, `30min`, `120` (minutos), `1:30` ou `00:30`
(horas:minutos), com espaço ou `=`. O padrão é 30 minutos. Valores fora do
intervalo de 1 a 180 minutos são rejeitados.

O parâmetro `:expiration` define o prazo da votação em minutos inteiros: mínimo
5, padrão 10 e máximo 20. Aceita espaço ou `=`, por exemplo:
`!ban @usuário :time 30min :expiration=5`. Nesse caso a votação dura até 5 minutos
e o ban, se aprovado, dura 30 minutos. O prazo escolhido é salvo em `closes_at`,
preservado após reinícios e exibido no aviso e no painel.

Cada membro tem um controle separado por grupo. Uma votação aberta ou ban ativo
impede outra votação para o mesmo alvo. Após rejeição, cancelamento ou voto ilegível,
é preciso aguardar 1 hora desde o encerramento real da votação (inclusive antecipado).
Após um ban aprovado, o intervalo de 1 hora começa quando o ban termina; se ele for
encerrado no painel, começa nesse encerramento. Falha no envio da enquete não gera
cooldown. O controle persiste após reinícios e serializa tentativas simultâneas entre
workers, considerando os aliases de telefone e LID.

O Gork envia uma enquete chamada `Banimento {nome}`, com `Sim` e `Não`, permitindo
uma opção por pessoa. Em seguida, envia um aviso curto: `Votação para banimento
de {nome}. Expira em {expiration} minutos.`, seguido das menções individuais aos membros.
Os IDs são enviados explicitamente em `mentions`, acompanhados dos respectivos
`@identificadores` no texto, sem depender da expansão de `@all` pelo provedor.
A votação recebe votos até o prazo escolhido (10 minutos por padrão). A lista de membros
é registrada na abertura, excluindo o próprio Gork. O quórum é **ao menos 1/3 desses
membros, arredondado para cima, e mínimo de 3 votantes**. Com quórum, vence a maioria
dos votos válidos; empate não aprova banimento. Por exemplo, com 10 membros além do
Gork, são necessários 4 votantes: 3 Sim e 1 Não aprovam; 2 Sim e 2 Não não aprovam.

O Gork confere a participação em cada evento. Se todos os membros da lista
tiverem uma escolha válida (Sim ou Não), encerra imediatamente e aplica a maioria,
inclusive quando todos escolhem Sim ou todos escolhem Não. Voto retirado não conta
como participação. Antes do encerramento, alterações substituem a escolha anterior.
Após a decisão, mudanças na enquete do WhatsApp não reabrem a votação nem revertem
o resultado; o Gork comunica a decisão por mensagem no grupo.
A mensagem final informa Sim, Não, participação e o motivo quando o ban não é
aprovado, incluindo falta de quórum. Mesmo sem votos, o prazo encerra e gera aviso.

Telefone e LID são associados ao mesmo eleitor. Mudanças de voto e retirada de
voto substituem a escolha anterior; o timestamp evita que eventos antigos
sobrescrevam votos novos. Votos de fora da lista ou após o prazo são ignorados.
Nos eventos GOWS de grupo, o autor é obtido de `vote.participant` ou dos aliases
do remetente; `vote.from` pode ser o ID do grupo. Timestamps numéricos em texto e
em milissegundos são normalizados. O webhook só confirma após gravar o evento:
falhas devolvem 503 para o WAHA reenviar. Antes de abrir uma enquete, a sessão
confere as assinaturas dos eventos de votação sem reconfigurar ou reiniciar a
conexão durante o comando. O `!ban` não espera a fila do agente de conversa e
tem um limite de 25 segundos para executar; falhas geram uma tentativa de aviso
direto no grupo, sem depender de consulta de resposta citada no banco.
Se um voto não puder ser decifrado (`poll.vote.failed`), a votação é cancelada,
sem aplicar banimento, e o grupo recebe um aviso.

A apuração também roda ao atingir o prazo escolhido, conferido a cada 5 segundos,
usando bloqueios no PostgreSQL para impedir decisões duplicadas entre workers.
Os jobs iniciam com horário UTC explícito, inclusive em servidores cujo fuso
difere do agendador. Após reiniciar com a correção, o primeiro ciclo apura as
votações vencidas ainda abertas e tenta reenviar os avisos pendentes.
A duração do banimento começa na aprovação.
Durante esse período, todas as mensagens novas do membro são excluídas via WAHA antes
do processamento normal: texto, fotos, vídeos, áudios, documentos, figurinhas,
contatos, localização e enquetes, sem filtro por tipo de conteúdo. O membro continua no grupo e pode voltar a falar ao
fim do prazo. Uma mensagem antiga reentregue pelo provedor não é apagada.

O caminho rápido consulta um snapshot compartilhado no Redis, sem SQL antes do
DELETE quando o cache está preenchido. O snapshot inclui o modo de teste e é
invalidado ao aprovar ou encerrar um ban e ao mudar o modo de teste; expira em
5 segundos. Um controle de versão impede publicar um snapshot antigo enquanto
outro worker revoga um ban. Se o Redis falhar, usa a verificação no PostgreSQL.

Depois do DELETE, o evento recebido é salvo em `manager.group_ban_deletion`, com
grupo, remetente, IDs e conteúdo/metadados originais, sem duplicar reentregas.
A referência WAHA também é preservada. Esse registro não baixa nem arquiva os
arquivos binários dos anexos e não executa comandos ou agentes para a mensagem.

Enquetes, votos e períodos aprovados ficam no banco, inclusive após reinício.
No painel, acesse **Acessos → Banimentos** (`/admin#bans`) para buscar por membro
ou grupo e filtrar bans ativos, votações abertas ou histórico. A lista mostra
os votos em Sim/Não e os prazos, com atualização automática a cada 5 segundos.
Durante o cooldown, mostra quando uma nova votação poderá ser aberta.
Use **Cancelar votação** para impedir a apuração (a enquete permanece visível
no WhatsApp) ou **Encerrar ban** para encerrar um período ativo. Se houver mais
de um ban ativo para o mesmo membro no grupo, encerre cada período para liberar
as mensagens. As ações preservam o histórico e exigem autenticação do painel.

Se o serviço estiver desligado no encerramento, a votação é apurada na retomada;
o período começa nessa apuração. Enquanto o serviço está desligado, ele não
consegue excluir mensagens. O modo de teste impede a moderação em grupos.

A inicialização aplica a migração `20261020_03_GroupBan` e a configuração
automática da sessão assina `message.any`, `poll.vote` e `poll.vote.failed`,
mantendo `gows.storage.messageSecrets` habilitado.

Para validar no WhatsApp, use um grupo de teste: verifique a recusa sem admin,
a menção a todos, alterações e retirada de votos, encerramento sem maioria,
aprovação com maioria e exclusão de texto e mídia do alvo. A exclusão de
mensagens de terceiros depende das permissões e do comportamento do WAHA/GOWS;
uma falha da API é registrada como `GroupBan/DeleteMessage`.

## Diagnóstico

Se o comando for recusado, confira grupo autorizado, permissões do Gork, alvo
único, cooldown e modo de teste. Se a enquete abrir mas não receber votos no
backend, confira as assinaturas `poll.vote`/`poll.vote.failed` e o armazenamento
de segredos da sessão. Se um ban aprovado não excluir mensagens, consulte as
falhas WAHA e as permissões de administrador antes de alterar a votação.

O painel mantém histórico de decisões e exclusões; encerrar um ban não apaga
esses registros. Veja [administração](admin-panel.md) para acesso e
[WAHA](waha.md) para diagnóstico do provedor.
