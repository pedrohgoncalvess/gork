# Criptografia dos dados do Gork

## Padrão de armazenamento

A criptografia é obrigatória para os campos sensíveis e anexos. A leitura exige
um envelope reconhecido e autenticado com a chave da aplicação. Os campos e modos
estão inventariados em `security/schema.py`.

A migração `20261024_01_EncryptedTextColumns` converte para TEXT os campos
criptografados que tinham limites VARCHAR: identificador, telefone e nome do
usuário, nome do grupo e nome da mídia. Ela roda no startup e preserva os valores
existentes, sem truncar nem converter dados antigos para o formato criptografado.
Ainda é necessário revisar constraints e defaults dos demais campos protegidos
antes da implantação e preparar a conversão de bases com dados em texto puro.

## Cobertura

- Mensagens, nomes de contatos e grupos, telefones, descrições e URLs privadas.
- Prompts personalizados, históricos de prompts/respostas, lembretes e observações.
- Termos usados no cache de embeddings; os vetores permanecem pesquisáveis.
- Nomes/descrições dos anexos, imagens de perfil e bytes de todos os uploads MinIO.
- Referências completas e metadados de mídia do WAHA.
- Nomes dos alvos de moderação, telefones/LIDs nas listas de eleitores e votos.
- Configuração de números da aplicação, erros de sincronização, metadados MCP.
- Novas linhas dos logs da aplicação e conteúdo sensível do cache de moderação.
- Chaves Redis que poderiam conter telefones, como locks de conversas privadas.

IDs internos, seriais, UUIDs, datas, relações, flags, contagens, tamanhos, tipos de
mídia e vetores não são criptografados. Identificadores de contato que podem
conter telefones são protegidos mesmo que tecnicamente sejam IDs. Caminhos de
objetos baseados em UUID e identificadores de grupos ficam disponíveis para roteamento.
Hashes de deduplicação e hashes perceptuais continuam sendo metadados de busca.

## Algoritmos e chave

`DATA_ENCRYPTION_KEY` contém 32 bytes aleatórios em Base64. `python -m scripts.setup`
gera o valor quando ausente, preservando os valores existentes. Guarde uma cópia
separada dos backups e restrinja o acesso ao ambiente. Não regenere a chave de uma
base já criptografada. Não existe recuperação sem a chave nem rotação automática.

Os subcampos usam chaves derivadas por HKDF com domínios separados. AES-GCM usa um
nonce aleatório por escrita. AES-SIV é usado onde igualdade indexada, unicidade ou
deduplicação de texto são necessárias: identidades, nomes e observações. Isso
revela repetições dentro do mesmo domínio; não revela o texto sem a chave. O
domínio e a versão são autenticados. A proteção de campos é vinculada ao domínio,
não ao ID de cada linha.

JSON privado é selado integralmente, mantendo a coluna JSONB. JSON de identidades
de moderação tem chaves e valores textuais selados deterministicamente para
preservar os operadores de associação existentes.

Arquivos usam uma chave derivada exclusiva por arquivo, com salt aleatório de
256 bits e blocos AES-GCM de até 1 MiB. O contador é o nonce, e bucket/caminho,
cabeçalho, posição e marcador final são autenticados. O leitor rejeita alteração,
troca de caminho, reordenação, truncamento e bytes após o marcador final. Apenas
blocos autenticados são liberados. O upload multipart mantém memória limitada;
integrações que exigem Base64 ainda materializam o arquivo como antes.

Uma chave ausente, versão desconhecida ou falha de autenticação interrompe a
operação. Toda gravação dos campos protegidos passa pela criptografia.

## Busca e desempenho

Filtros por conversa, período e IDs e a busca vetorial continuam no PostgreSQL.
Igualdade de telefones e identidades continua indexável com AES-SIV. Busca parcial
de nomes e texto ocorre na aplicação depois do filtro de escopo, pois índices de
texto não conseguem consultar ciphertext. Consultas textuais extensas custam mais;
prefira busca semântica em históricos grandes. A busca literal de observações
passa a ser por substring, sem stemming do PostgreSQL.

O endpoint autenticado do painel descriptografa anexos em streaming. URLs diretas
e presigned URLs não servem o conteúdo original; os métodos correspondentes
rejeitam seu uso para evitar a distribuição involuntária de ciphertext.

## Requisitos do esquema

Colunas sensíveis declaradas como VARCHAR precisam de espaço para o envelope
cifrado, preferencialmente com tipo TEXT. O limite da coluna de observações deve
acomodar esse envelope; o limite do conteúdo é validado pela aplicação. Defaults
de campos protegidos devem ser aplicados pela aplicação para passar pela
criptografia. A preparação do esquema deve preservar a busca vetorial e ser
validada com PostgreSQL e MinIO antes da implantação.

## Limites de infraestrutura

A aplicação descriptografa dados para uso e para os provedores de IA selecionados.
Isto protege armazenamento; não implementa E2EE contra o próprio servidor.
Vetores, hashes e metadados podem revelar informações sobre os dados.

O banco/sessão/cache de mídia do WAHA é gerenciado pelo WAHA e não é protegido por
esta camada. Seus volumes, backups, swap e diretórios temporários de FFmpeg e
outros processadores precisam de criptografia do disco/volume, ou temporários em
memória com swap protegido. Configurar TLS entre serviços também é uma etapa de
infraestrutura independente. A alteração não reconfigura esses serviços.

Os logs são envelopes `gork:v1:` por linha. Ferramentas de análise precisam
descriptografar as linhas com o domínio `log`.

## Verificação

`python -m unittest tests.test_data_encryption -v` cobre leitura/escrita real com
SQLAlchemy, busca exata, JSON, adulteração, chave ausente, limites de blocos,
truncamento, reordenação e streaming multipart. A integração com PostgreSQL e
MinIO também deve ser validada antes da implantação.
