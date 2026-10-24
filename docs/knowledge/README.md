# Base de conhecimento do Gork

Os agentes de conversa DM e grupo têm a ferramenta nativa
`consult_gork_knowledge`. Ela é local, somente leitura e disponível mesmo sem
MCP remoto configurado ou quando consultas MCP externas estão bloqueadas.
Os controles normais de acesso à conversa continuam valendo. O modelo de
conversa precisa suportar tool calling.

## Quando consultar

O runtime injeta uma instrução curta para consultar antes de responder perguntas
factuais sobre o próprio Gork: história, autor, recursos/comandos, código,
tecnologias, criptografia, instalação, configuração, deploy e diagnóstico.
A instrução vale também para prompts personalizados preservados pelo painel.
Conversas sem relação com o projeto e execução de ações já compreendidas não
pedem leitura da base. A escolha da chamada continua sendo feita pelo modelo.

## Consultas e respostas

- `{}` ou `{"topic":"index"}`: catálogo com os 18 assuntos e suas fontes.
- `{"topic":"history"}`: história documentada, autoria pública e ressalvas.
- `{"topic":"encryption","query":"AES"}`: trechos do guia de criptografia.
- `{"query":"WAHA"}`: busca lexical em todos os assuntos.
- `{"topic":"development","offset":4,"limit":4}`: continuação de um guia.

Argumentos são validados por JSON Schema. `query` aceita até 300 caracteres,
`offset` de 0 a 10000 e `limit` de 1 a 6 (padrão 4). A busca ignora caixa e
acentos, ordena pelo número de termos encontrados e aceita correspondências
parciais. Não usa embeddings, banco vetorial ou chamada extra de IA. Prefira
palavras específicas em português ou inglês, no idioma do guia. A consulta por
assunto sem query permite ler o documento inteiro, seguindo `next_offset`.

Os resultados incluem assunto, caminho relativo da fonte, seção, parte, texto,
total de trechos, próximo offset e fontes indisponíveis. Cada trecho tem até
2800 caracteres; no máximo seis entram em uma resposta. Trechos longos podem
ser divididos dentro de um parágrafo/bloco; a parte seguinte contém a continuação.
Ausência de resultado não significa ausência da funcionalidade: tente catálogo,
outro termo ou leitura por assunto. Documentação não inspeciona estado real.

## Conteúdo e atualização

`services/gork_knowledge.py` mantém uma lista fixa de documentos permitidos.
Ela combina README e guias existentes com história, arquitetura, tecnologias e
configuração em `docs/knowledge/`. Alterar esses documentos atualiza consultas
seguintes no processo que tiver os arquivos atualizados; não é preciso reindexar.
Preserve paginação consistente evitando mudar arquivos entre páginas de uma consulta.

Para adicionar assunto, escreva/revise o guia e registre título/caminho em TOPICS.
Atualize a descrição da ferramenta se o escopo mudar. Não inclua segredos, logs,
dados de conversas ou arquivos de ambiente. História é curada a partir de Git,
sem executar comandos ou ler o histórico em produção. Revise a cronologia quando
adicionar marcos, e as ressalvas quando uma pendência for resolvida.

Em desenvolvimento, o README e `docs/` precisam estar disponíveis no container;
reconstrua a imagem para atualizar documentos copiados. Em produção, reconstrua
e reinicie após mudanças. Não há nova variável, serviço, migração ou cadastro
MCP para habilitar essa ferramenta.

## Custo de contexto e limites

Somente schema, descrição e orientação curta são enviados em cada chamada do
modelo. Nenhum guia é lido pelo catálogo ou inserido automaticamente no prompt.
O conteúdo retorna apenas depois da tool call e permanece no contexto das rodadas
seguintes daquela execução. Chamadas iguais usam cache no mesmo ciclo. A resposta
final pode naturalmente registrar uma explicação na conversa.

A ferramenta compartilha os limites de execução de `services/mcp_runtime.py`
com ferramentas externas: 6 rodadas, 12 chamadas e 60 segundos acumulados.
Uma vaga do catálogo de 128 ferramentas é reservada para ela. Respostas do modelo
continuam registradas no consumo; a consulta local não gera cobrança de provedor
por busca, mas o texto retornado entra nos tokens da próxima rodada.

## Verificação

`python -m unittest tests.test_gork_knowledge tests.test_mcp -v` verifica
consulta nativa em DM/grupo sem servidor MCP, leitura sob demanda, paginação,
fontes, busca, limites, erros, isolamento de caminhos e regressões do ciclo remoto.
