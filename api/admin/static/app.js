"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const paths = {
  phone:'<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4m-3 14h2"/>',
  users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/><circle cx="9" cy="7" r="4"/>',
  group:'<path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2m17 0v-3a4 4 0 0 0-3-3.87"/><circle cx="10" cy="7" r="4"/><path d="M17 3.5a3.5 3.5 0 0 1 0 7"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m9 12 2 2 4-4"/>',
  sliders:'<path d="M4 6h9m4 0h3M4 12h3m4 0h9M4 18h10m4 0h2"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
  layers:'<path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
  terminal:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
  settings:'<path d="m9 3-.5 3-2 .9-2.5-1-2 3 2 2-.1 2-2 2 2 3 2.5-1 2 .9.6 3h4l.5-3 2-.9 2.5 1 2-3-2-2 .1-2 2-2-2-3-2.5 1-2-.9L13 3H9Z"/><circle cx="11" cy="12" r="3"/>',
  logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.55-2.55L20 7M4 17l2.35 2.55A7 7 0 0 0 17.9 17"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', x:'<path d="m6 6 12 12M6 18 18 6"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>', check:'<path d="m5 12 4 4L19 6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  lock:'<rect x="4" y="10" width="16" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>', edit:'<path d="m16 3 5 5-12 12H4v-5L16 3Zm-2 2 5 5"/>',
  trash:'<path d="M3 6h18M5 6l1 15h12l1-15M9 6V3h6v3m-5 4v7m4-7v7"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>', copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.settings}</svg>`;
document.querySelectorAll("[data-icon]").forEach(node => { node.innerHTML = icon(node.dataset.icon); });
const state = {page:"connection", csrf:null, q:"", offset:0, poll:null, qrUrl:null, qrAt:0, connection:null, mode:"qr", code:null, editor:null, data:{}, tab:"defaults", navigation:0};
const titles = {connection:["CONEXÃO","WhatsApp","Vincule seu celular e acompanhe a conexão do Gork."],users:["ACESSOS","Usuários","Defina quem pode conversar com o Gork e acessar seus recursos."],groups:["ACESSOS","Grupos","Gerencie os grupos autorizados e as respostas automáticas."],blacklist:["ACESSOS","Blacklist","Controle bloqueios completos ou restrinja recursos por usuário."],agents:["CONFIGURAÇÃO","Agentes","Ajuste os modelos e as instruções de cada agente."],models:["CONFIGURAÇÃO","Modelos","Modelos disponíveis para os agentes e suas conversas."],commands:["CONFIGURAÇÃO","Permissões de comandos","Defina restrições por comando, usuário ou grupo."]};
const loading = '<div class="loading" role="status"><span class="spinner"></span>Carregando…</div>';
titles.mcps = ["CONFIGURAÇÃO", "Servidores MCP", "Cadastre os serviços que o Gork pode consultar por ferramentas."];
titles.bans = ["ACESSOS", "Banimentos", "Acompanhe votações e gerencie os banimentos temporários dos grupos."];
titles.sync = ["CONEXÃO", "Sincronização", "Importe contatos e o histórico disponível na conta conectada."];
titles.testing = ["CONFIGURAÇÃO", "Número de teste", "Configure o número autorizado para testar o Gork em uma conversa privada."];
titles.attachments = ["DATA", "Anexos", "Explore os anexos salvos nas conversas e busque pelo significado das descrições."];
titles.messages = ["DATA", "Mensagens", "Explore o histórico de mensagens e encontre conversas pelo significado."];
const badge = (text, color="") => `<span class="badge ${color}">${esc(text)}</span>`;
const initials = value => String(value || "?").trim().split(/\s+/).slice(0,2).map(word=>word[0]).join("").toUpperCase();
const person = (name, subline, kind="user") => `<div class="person"><span class="avatar">${kind==="group"?icon("group"):esc(initials(name))}</span><div><strong>${esc(name || "Sem nome")}</strong>${subline?`<span class="subline mono">${esc(subline)}</span>`:""}</div></div>`;
const note = text => `<div class="note">${icon("info")}<span>${text}</span></div>`;
const button = (action, label, glyph, primary=false, extra="") => `<button class="button ${primary?"primary":""}" data-action="${action}" ${extra}>${glyph?icon(glyph):""}${label}</button>`;
function toast(text) { $("#toast").textContent=text; $("#toast").hidden=false; clearTimeout(state.toast);state.toast=setTimeout(()=>$("#toast").hidden=true,4000); }
function message(error) { return error?.message || "Não foi possível concluir a operação."; }
async function api(path, options={}) {
  const headers = {...(options.body?{"Content-Type":"application/json"}:{}), ...(state.csrf?{"X-CSRF-Token":state.csrf}:{}),...options.headers};
  const response = await fetch(`/admin/api${path}`, {...options,headers,cache:"no-store"});
  if (!response.ok) {
    let data; try{data=await response.json();}catch{data={};}
    if(response.status===401 && path!=="/login") showLogin();
    const detail=Array.isArray(data.detail)?"Confira os campos preenchidos e tente novamente.":data.detail;
    throw new Error(detail || "Não foi possível concluir a operação. Tente novamente.");
  }
  return options.binary?response.blob():response.json();
}
function showLogin() { stopPolling();$("#app").hidden=true;$("#boot").hidden=true;$("#login-screen").hidden=false;state.csrf=null;if($("#editor").open)$("#editor").close();$("#password").focus(); }
async function boot() { try {const session=await api("/session");state.csrf=session.csrf_token;showApp();} catch{showLogin();} }
function showApp(){ $("#boot").hidden=true;$("#login-screen").hidden=true;$("#app").hidden=false;navigate(); }
$("#login-form").addEventListener("submit",async event=>{event.preventDefault();const submit=$("button[type=submit]",event.target);submit.disabled=true;$("#login-error").hidden=true;try{const session=await api("/login",{method:"POST",body:JSON.stringify({password:$("#password").value})});state.csrf=session.csrf_token;$("#password").value="";showApp();}catch(error){$("#login-error").textContent=message(error);$("#login-error").hidden=false;}finally{submit.disabled=false;}});
$("#logout").addEventListener("click",async()=>{try{await api("/logout",{method:"POST"});showLogin();}catch(error){toast(message(error));}});
function closeSidebar(){ $("#sidebar").classList.remove("open");$("#sidebar-backdrop").hidden=true;$("#menu-toggle").setAttribute("aria-expanded","false"); }
$("#menu-toggle").addEventListener("click",()=>{const open=$("#sidebar").classList.toggle("open");$("#sidebar-backdrop").hidden=!open;$("#menu-toggle").setAttribute("aria-expanded",String(open));});
$("#sidebar-backdrop").addEventListener("click",closeSidebar);
function stopPolling(){clearInterval(state.poll);state.poll=null;}
function clearQr(){if(state.qrUrl)URL.revokeObjectURL(state.qrUrl);state.qrUrl=null;state.qrAt=0;}
function heading(page){const [section,title,description]=titles[page];let actions="";
 if(page==="connection")actions=button("refresh-connection","Atualizar","refresh")+button("start-connection","Iniciar conexão","plus",true);
 if(page==="users")actions=button("new-user","Adicionar usuário","plus",true);
 if(page==="groups")actions=button("sync-groups","Sincronizar","refresh")+button("new-group","Adicionar grupo","plus",true);
 if(page==="blacklist")actions=button("new-blacklist","Bloquear usuário","plus",true);
 if(page==="agents")actions=button("new-override","Definir por conversa","plus",true);
 if(page==="models")actions=button("new-model","Adicionar modelo","plus",true);
 if(page==="commands")actions=button("new-command","Nova restrição","plus",true);
 if(page==="mcps")actions=button("new-mcp","Adicionar MCP","plus",true);
 if(page==="bans")actions=button("refresh-bans","Atualizar","refresh");
 $("#page-heading").innerHTML=`<div class="heading"><div><span class="eyebrow">${section}</span><h1>${title}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`;
 $("#breadcrumb-current").textContent=title;document.title=`${title} · Gork`;
}
async function navigate(){
 if(!state.csrf)return;stopPolling();closeSidebar();clearQr();state.code=null;state.mode="qr";state.connection=null;
 const page=location.hash.slice(1);state.page=titles[page]?page:"connection";state.offset=0;state.q="";state.data={};state.navigation++;
 document.querySelectorAll("[data-page]").forEach(node=>{const active=node.dataset.page===state.page;node.classList.toggle("active",active);if(active){node.setAttribute("aria-current","page");node.closest("details").open=true;}else node.removeAttribute("aria-current");});
 heading(state.page);$("#page-content").innerHTML=loading;await loadPage();
}
function empty(title, description, glyph="layers", action=""){return `<div class="empty"><div class="icon-box">${icon(glyph)}</div><h3>${title}</h3><p>${description}</p>${action}</div>`;}
function errorState(error){return `<div class="card error-state">${empty("Não foi possível carregar",esc(message(error)),"info",button("retry","Tentar novamente","refresh"))}</div>`;}
async function loadPage(){const nav=state.navigation;try{
 if(["attachments","messages"].includes(state.page)){await renderDataShell();return;}
 if(state.page==="bans"){clearInterval(state.poll);renderBansShell();await loadBans();if(nav===state.navigation)state.poll=setInterval(()=>{if(!document.hidden&&!$("#editor").open)loadBans();},5000);return;}
 if(state.page==="connection"){renderConnection();await refreshConnection();if(nav===state.navigation)state.poll=setInterval(()=>{if(!document.hidden)refreshConnection();},5000);return;}
 if(state.page==="sync"){const data=await api("/sync");if(nav!==state.navigation)return;state.data=data;renderSync();state.poll=setInterval(()=>refreshSync().catch(error=>toast(message(error))),3000);return;}
 if(state.page==="testing"){const data=await api("/settings");if(nav!==state.navigation)return;state.data=data;renderTesting();return;}
 if(state.page==="users"||state.page==="groups"){renderDirectoryShell();await loadDirectory();return;}
 let data;
 if(state.page==="agents"){const [agents,models,overrides]=await Promise.all([api("/agents"),api("/models"),api("/overrides")]);data={agents,models,overrides};}
 if(state.page==="models")data={models:await api("/models")};
 if(state.page==="mcps")data={servers:await api("/mcps")};
 if(state.page==="blacklist"){const [entries,commands]=await Promise.all([api("/blacklist"),api("/commands")]);data={entries,catalog:commands.catalog};}
 if(state.page==="commands")data=await api("/commands");
 if(nav!==state.navigation)return;state.data=data;renderPage();
 }catch(error){if(nav===state.navigation)$("#page-content").innerHTML=errorState(error);}}
function renderPage(){if(state.page==="agents")renderAgents();else if(state.page==="models")renderModels();else if(state.page==="blacklist")renderBlacklist();else if(state.page==="commands")renderCommands();else if(state.page==="mcps")renderMcps();}

const banStatus = {active:["Ativo","red"],voting:["Em votação","amber"],closing:["Em apuração","amber"],preparing:["Preparando","amber"],expired:["Expirado",""],rejected:["Rejeitado",""],cancelled:["Votação cancelada",""],revoked:["Encerrado no painel",""],invalid:["Votos ilegíveis","red"],failed:["Falha no envio","red"]};
function renderBansShell(){
 const views=[{id:"all",name:"Todos"},{id:"active",name:"Bans ativos"},{id:"voting",name:"Votações abertas"},{id:"history",name:"Histórico"}];
 $("#page-content").innerHTML=`<section class="card"><div class="ban-filters">${field(label("Estado","ban-view"),select("ban-view",views,state.banView||"all"))}${field(label("Buscar membro ou grupo","ban-search"),input("ban-search","Nome ou identificador",state.q,'type="search" maxlength="100"'))}</div><div id="ban-results">${loading}</div></section>${note("Atualização automática a cada 5 segundos. Para abrir uma votação, use !ban @usuário no grupo. Encerrar um ban libera as novas mensagens; o histórico é preservado.")}`;
}
async function loadBans(){
 if(state.page!=="bans"||!state.csrf)return;
 const nav=state.navigation,request=state.banRequest=(state.banRequest||0)+1;
 try{
 const result=await api(`/bans?${new URLSearchParams({view:state.banView||"all",q:state.q,offset:state.offset,limit:30})}`);
 if(nav!==state.navigation||request!==state.banRequest)return;
 const date=value=>value?new Date(value).toLocaleString("pt-BR"):"—";
 const rows=result.items.map(item=>{
 const [name,color]=banStatus[item.status]||[item.status,""];
 let action="";
 if(item.status==="active")action=button("revoke-ban","Encerrar ban",null,false,`data-id="${item.id}"`);
 if(["preparing","voting","closing"].includes(item.status))action=button("cancel-ban-poll","Cancelar votação",null,false,`data-id="${item.id}"`);
 if(item.next_vote_at&&new Date(item.next_vote_at)>new Date())action+=`<span class="subline">Nova votação: ${esc(date(item.next_vote_at))}</span>`;
 return `<tr><td>${person(item.target_name,item.target_id)}<span class="subline">Aberta em ${esc(date(item.opened_at))}</span></td><td>${person(item.group_name||"Grupo",item.chat_id,"group")}</td><td>${badge(name,color)}</td><td><strong>${item.yes_votes} Sim · ${item.no_votes} Não</strong><span class="subline">${item.yes_votes+item.no_votes} de ${item.member_count} membros · quórum ${Math.max(3,Math.ceil(item.member_count/3))} · maioria decide</span></td><td>${item.duration_minutes} min<span class="subline">Votação até ${esc(date(item.closes_at))}</span>${item.ban_until?`<span class="subline">Ban até ${esc(date(item.ban_until))}</span>`:""}</td><td>${action}</td></tr>`;
 }).join("");
 $("#ban-results").innerHTML=rows?`<div class="table-scroll"><table><thead><tr><th>Membro</th><th>Grupo</th><th>Estado</th><th>Votos</th><th>Duração e prazos</th><th>Ações</th></tr></thead><tbody>${rows}</tbody></table></div><div class="table-footer"><span>${result.offset+1}–${result.offset+result.items.length} de ${result.total}</span><div class="pagination">${button("bans-prev","Anterior",null,false,result.offset===0?"disabled":"")}${button("bans-next","Próxima",null,false,result.offset+result.items.length>=result.total?"disabled":"")}</div></div>`:empty("Nenhum banimento encontrado","Votações abertas pelo comando !ban aparecerão aqui. Ajuste os filtros para consultar outros registros.","shield");
 }catch(error){if(nav===state.navigation&&request===state.banRequest)$("#ban-results").innerHTML=errorState(error);}
}

async function renderDataShell(){
 const nav=state.navigation;
 const [groups,users]=await Promise.all([api("/directory/group?limit=30"),api("/directory/user?limit=30")]);
 if(nav!==state.navigation)return;
 const picker=(kind,items)=>`<div class="field"><label for="data-${kind}">${kind==="group"?"Grupo":"Contato"}</label><input type="search" class="picker-search" data-picker="data-${kind}" data-kind="${kind}" aria-label="Buscar ${kind==="group"?"grupo":"contato"}" placeholder="Buscar por nome ou identificador">${select(`data-${kind}`,[{id:"",name:"Todos"},...items.map(item=>({id:item.id,name:item.name||item.phone_number||item.src_id||`#${item.id}`}))])}</div>`;
 $("#page-content").innerHTML=`<section class="card"><form id="data-filters" class="data-filters">${picker("group",groups.items)}${picker("user",users.items)}${field(label("Janela de tempo","data-period"),select("data-period",[{id:"all",name:"Todo o histórico"},{id:"1",name:"Últimas 24 horas"},{id:"7",name:"Últimos 7 dias"},{id:"30",name:"Últimos 30 dias"},{id:"custom",name:"Período personalizado"}]))}<div id="data-dates" class="data-dates" hidden>${field(label("Início","data-start"),input("data-start","","",'type="datetime-local"'))}${field(label("Fim (exclusivo)","data-end"),input("data-end","","",'type="datetime-local"'))}<p class="field-hint">Fuso horário do navegador.</p></div><div class="data-query">${field(label("Busca semântica","data-query"),input("data-query","Ex.: planejamento da viagem","",'type="search" maxlength="2000"'),"Ordena por relevância. Deixe vazio para ver os registros mais recentes.")}</div><div class="data-actions"><button class="button primary" type="submit">${icon("search")}Aplicar filtros</button><button class="button" type="reset">Limpar</button></div><p id="data-error" class="form-error" role="alert" hidden></p></form></section><div id="data-results">${loading}</div>${note(state.page==="attachments"?"A busca semântica inclui anexos que já possuem descrição indexada. Cada cartão representa o envio de um anexo em uma conversa.":"A busca semântica indexa até 100 mensagens por vez e usa o modelo de embeddings configurado. A primeira busca pode demorar; continue a indexação para incluir todo o período. Mensagens sem texto aparecem na listagem cronológica.")}`;
 state.dataFilters=new URLSearchParams();state.dataOffset=0;
 await loadData();
}
async function loadData(indexMessages=false){
 const nav=state.navigation,request=(state.dataRequest||0)+1;state.dataRequest=request;
 const params=new URLSearchParams(state.dataFilters);params.set("offset",state.dataOffset);params.set("limit",30);
 if(indexMessages)params.set("index_messages","true");
 $("#data-results").innerHTML=loading;
 try{
 const result=await api(`/data/${state.page}?${params}`);
 if(nav!==state.navigation||request!==state.dataRequest)return;
 state.dataListing=result;
 const cards=result.items.map(item=>{
 const context=`<header><strong>${esc(item.user_name||item.phone_number||"Contato desconhecido")}</strong><span class="subline">${esc(item.group_name||item.contact_name||"Conversa privada")}</span><time datetime="${esc(item.created_at)}">${esc(new Date(item.created_at).toLocaleString("pt-BR"))}</time>${item.similarity!=null?badge(`Relevância ${(item.similarity*100).toFixed(0)}%`):""}</header>`;
 let preview="";
 if(item.media_url){const url=esc(item.media_url),name=esc(item.media_name||"Anexo");
 if(["image","sticker"].includes(item.media_type))preview=`<a href="${url}" target="_blank" rel="noopener"><img class="attachment-preview" src="${url}" alt="${name}" loading="lazy"></a>`;
 else if(item.media_type==="video")preview=`<video class="attachment-preview" controls preload="none" src="${url}" aria-label="${name}"></video>`;
 else if(item.media_type==="audio")preview=`<audio controls preload="none" src="${url}" aria-label="${name}"></audio>`;
 preview+=`<a class="attachment-download" href="${url}?download=true">${icon("layers")}${name}${item.size!=null?` · ${Number(item.size).toFixed(2)} MB`:""} · Baixar</a>`;}
 return `<article class="data-item card">${context}${preview}${item.content?`<p class="message-content">${esc(item.content)}</p>`:""}${item.description?`<details class="attachment-description"><summary>Descrição do anexo</summary><p class="message-content">${esc(item.description)}</p></details>`:""}${!item.content&&!item.media_url?'<p class="muted">Mensagem sem texto.</p>':""}</article>`;
 }).join("");
 $("#data-results").innerHTML=`${result.indexing_remaining?`<div class="note">${icon("info")}<span>Resultados parciais: ${result.indexing_remaining} mensagens ainda precisam ser indexadas.</span>${button("data-index","Continuar indexação","refresh")}</div>`:""}<div class="data-summary">${result.total} ${state.page==="attachments"?"anexos":"mensagens"}${state.dataFilters.get("q")?" com conteúdo indexado · ordem de relevância":" · mais recentes primeiro"}</div>${cards?`<div class="${state.page==="attachments"?"attachment-grid":"message-list"}">${cards}</div>`:`<section class="card">${empty("Nenhum resultado","Ajuste os filtros ou tente outra busca.")}</section>`}<div class="data-pagination">${button("data-prev","Anterior","",false,state.dataOffset===0?"disabled":"")}<span>${result.total?state.dataOffset+1:0}–${Math.min(state.dataOffset+30,result.total)} de ${result.total}</span>${button("data-next","Próxima","",false,state.dataOffset+30>=result.total?"disabled":"")}</div>`;
 }catch(error){if(nav===state.navigation&&request===state.dataRequest){$("#data-results").innerHTML=`<section class="card">${empty("Não foi possível carregar",esc(message(error)),"info",button("data-retry","Tentar novamente","refresh"))}</section>`;}}
}
document.addEventListener("submit",async event=>{
 if(event.target.id!=="data-filters")return;event.preventDefault();
 const errorNode=$("#data-error");errorNode.hidden=true;
 try{
 const params=new URLSearchParams();for(const key of ["group","user"]){const value=$(`#data-${key}`).value;if(value)params.set(`${key}_id`,value);}
 const period=$("#data-period").value;
 if(period==="custom"){const start=$("#data-start").value,end=$("#data-end").value;if(!start||!end||new Date(start)>=new Date(end))throw new Error("Preencha um período com fim posterior ao início.");params.set("start",new Date(start).toISOString());params.set("end",new Date(end).toISOString());}
 else if(period!=="all"){const now=new Date();params.set("start",new Date(now.getTime()-Number(period)*86400000).toISOString());params.set("end",now.toISOString());}
 const q=$("#data-query").value.trim();if(q)params.set("q",q);
 state.dataFilters=params;state.dataOffset=0;await loadData(true);
 }catch(error){errorNode.textContent=message(error);errorNode.hidden=false;}
});
document.addEventListener("reset",event=>{if(event.target.id!=="data-filters")return;setTimeout(()=>{$("#data-dates").hidden=true;$("#data-error").hidden=true;state.dataFilters=new URLSearchParams();state.dataOffset=0;loadData();},0);});

function syncProgress(job){
 if(!job)return note("Nenhuma sincronização iniciada.");
 const names={running:"Em andamento",completed:"Concluída",failed:"Interrompida"};
 const phase={contacts:"Contatos",history:"Histórico"}[job.phase];
 return `<div class="card-head"><div><h3>${esc(names[job.status]||job.status)}${phase?` · ${phase}`:""}</h3><p>${job.contacts} contatos · ${job.messages} mensagens importadas · ${job.skipped} itens ignorados ou já existentes</p>${job.error?`<p role="alert">${esc(job.error)}</p>`:""}</div>${badge(names[job.status]||job.status,job.status==="completed"?"green":"amber")}</div>`;
}
function renderSync(){
 const periods=[{id:"3d",name:"3 dias"},{id:"5d",name:"5 dias"},{id:"1w",name:"1 semana"},{id:"2w",name:"2 semanas"},{id:"1m",name:"1 mês"},{id:"3m",name:"3 meses"},{id:"custom",name:"Janela de tempo específica"},{id:"all",name:"Todo o histórico (all time)"}];
 $("#page-content").innerHTML=`<section class="card"><form id="sync-form" class="dialog-fields">${checkbox("sync-contacts","Sincronizar contatos","Importa nomes, telefones e LIDs sem autorizar novos acessos.",true)}${checkbox("sync-history","Sincronizar histórico","Importa mensagens sem executar comandos nem enviar respostas.")}<div id="history-options" hidden>${field(label("Período do histórico","sync-period"),select("sync-period",periods,"3d"))}<div id="sync-dates" hidden>${field(label("Início","sync-start"),input("sync-start","","",'type="datetime-local"'))}${field(label("Fim","sync-end"),input("sync-end","","",'type="datetime-local"'))}<p class="form-info">As datas usam o fuso horário do seu navegador.</p></div></div><p id="sync-error" class="form-error" role="alert" hidden></p><button id="sync-submit" type="submit" class="button primary" ${state.data.job?.status==="running"?"disabled":""}>${icon("refresh")}Iniciar sincronização</button></form></section><section id="sync-progress" class="card">${syncProgress(state.data.job)}</section>${note("Os períodos se aplicam às mensagens; a agenda de contatos é sincronizada por completo. O histórico depende do que o WhatsApp disponibilizou ao WAHA. Você pode repetir a importação sem duplicar mensagens.")}`;
}
async function refreshSync(){
 if(state.page!=="sync"||document.hidden||state.syncRefreshing)return;
 state.syncRefreshing=true;const nav=state.navigation;
 try{const data=await api("/sync");if(nav!==state.navigation)return;state.data=data;$("#sync-progress").innerHTML=syncProgress(data.job);$("#sync-submit").disabled=data.job?.status==="running";}finally{state.syncRefreshing=false;}
}
function renderTesting(){
 const data=state.data;
 $("#page-content").innerHTML=`<section class="card"><form id="test-settings-form" class="dialog-fields">${field(label("Número de teste","test-number"),input("test-number","5511999999999",data.test_number||"",'type="tel" pattern="\\+?[1-9][0-9]{6,14}"'),"Código do país + DDD + número.")}${checkbox("test-mode","Ativar modo de teste","O Gork responderá somente a esse número em mensagens privadas. Grupos e outros contatos serão ignorados.",data.test_mode)}<p id="test-error" class="form-error" role="alert" hidden></p><button class="button primary" type="submit">Salvar configuração</button></form></section>${note(`Conta principal: <strong>${esc(data.phone_number||"Aguardando conexão do WhatsApp")}</strong>${data.lid?` · LID: ${esc(data.lid)}`:""}. Identificada automaticamente pelo WAHA. As alterações são preservadas após reiniciar.`)}`;
}
document.addEventListener("submit",async event=>{
 if(!["sync-form","test-settings-form"].includes(event.target.id))return;
 event.preventDefault();const form=event.target;const submit=$('button[type="submit"]',form);submit.disabled=true;
 const errorNode=$(form.id==="sync-form"?"#sync-error":"#test-error");errorNode.hidden=true;
 try{
  if(form.id==="sync-form"){
   const payload={contacts:$("#sync-contacts").checked,history:$("#sync-history").checked,period:$("#sync-period").value};
   if(payload.period==="custom"&&payload.history){payload.start=new Date($("#sync-start").value).toISOString();payload.end=new Date($("#sync-end").value).toISOString();}
   if(!payload.history)payload.period="3d";
   state.data=await api("/sync",{method:"POST",body:JSON.stringify(payload)});$("#sync-progress").innerHTML=syncProgress(state.data.job);toast("Sincronização iniciada.");
  }else{
   const payload={test_mode:$("#test-mode").checked,test_number:$("#test-number").value.trim()||null};
   state.data=await api("/settings/test",{method:"PUT",body:JSON.stringify(payload)});toast("Configuração de teste salva.");
  }
 }catch(error){errorNode.textContent=message(error);errorNode.hidden=false;}finally{if(submit.isConnected)submit.disabled=form.id==="sync-form"&&state.data.job?.status==="running";}
});
const statusNames={WORKING:["Conectado","green"],SCAN_QR_CODE:["Aguardando conexão","amber"],STARTING:["Conectando","amber"],STOPPED:["Desconectado",""],FAILED:["Falha na conexão","red"],NOT_CREATED:["Não conectado",""],UNKNOWN:["Estado indisponível",""]};
function renderConnection(){
 const status=state.connection?.status;const [label,color]=statusNames[status]||["Verificando conexão",""];const ready=status==="SCAN_QR_CODE";const working=status==="WORKING";
 let body;
 if(working){body=`<div class="connected-box"><div class="connected-icon">${icon("check")}</div><h2>Seu WhatsApp está conectado.</h2><p>O Gork está pronto para receber e enviar mensagens.</p><span class="mono muted">${esc(state.connection.me?.name || "")} ${esc((state.connection.me?.id||"").split("@")[0])}</span></div>`;}
 else if(state.mode==="code"){
 body=`<div class="code-panel"><h2>Conecte com seu número.</h2><p>Informe o número do celular que será usado pelo Gork, com o código do país e DDD.</p><form id="pairing-form"><label for="phone-number">Número do WhatsApp</label><input type="tel" id="phone-number" name="phone_number" autocomplete="tel" placeholder="55 11 99999-9999" value="${esc(state.phoneNumber||'')}" required ${state.pairingBusy?"disabled":""}><p class="field-hint">${ready?"Um código será exibido para inserir no WhatsApp.":"A conexão será iniciada automaticamente ao gerar o código."}</p><button class="button primary" type="submit" ${state.pairingBusy?"disabled":""}>Gerar código ${icon("arrow")}</button></form><div id="pairing-result">${state.code?codeMarkup():""}</div><p id="pairing-error" class="form-error" role="alert" hidden></p><div class="link-alternative">${button("qr-mode","Usar QR code","phone")}</div></div><div class="connection-instructions"><span class="eyebrow">NO SEU CELULAR</span><h2>Insira o código no WhatsApp.</h2><ol class="steps"><li><span class="step-number">1</span><span>Abra <strong>Aparelhos conectados</strong>.</span></li><li><span class="step-number">2</span><span>Toque em <strong>Conectar um aparelho</strong>.</span></li><li><span class="step-number">3</span><span>Escolha <strong>Conectar com número de telefone</strong> e insira o código.</span></li></ol></div>`;
 }else{
 body=`<div class="qr-column"><div class="qr-frame" id="qr-frame">${state.qrUrl?`<img src="${esc(state.qrUrl)}" alt="QR code para conectar o WhatsApp">`:`<div class="qr-placeholder">${icon("phone")}<p>${ready?"Carregando QR code…":"Inicie a conexão para exibir o QR code."}</p></div>`}</div><div class="qr-caption" id="qr-caption">${qrCaption()}</div></div><div class="connection-instructions"><h2>Conecte seu celular.</h2><p>Leia o QR code ao lado para vincular o WhatsApp ao Gork. Leva só alguns instantes.</p><ol class="steps"><li><span class="step-number">1</span><span>Abra o <strong>WhatsApp</strong> no celular.</span></li><li><span class="step-number">2</span><span>Vá em <strong>Aparelhos conectados</strong>.</span></li><li><span class="step-number">3</span><span>Toque em <strong>Conectar um aparelho</strong> e aponte a câmera.</span></li></ol><div class="link-alternative">${button("code-mode","Conectar com número de telefone","arrow")}</div></div>`;
 }
 $("#page-content").innerHTML=`<div id="connection-error" class="inline-error" role="alert" hidden></div><section class="card"><header class="card-head"><div class="card-title"><span class="icon-box">${icon("phone")}</span><div><h3>Sua conexão</h3><p>WhatsApp · ${esc(state.connection?.session || "Sessão do Gork")}</p></div></div><span id="connection-badge">${badge(label,color)}</span></header><div class="connection-body">${body}</div><div class="connection-foot">${icon("lock")}<span>A conexão fica salva. Você não precisa vincular o celular a cada reinício.</span></div></section><div class="connection-meta"><div class="meta-block">${icon("shield")}<div><strong>Acesso sob controle</strong><p>Autorize usuários e grupos antes de liberar as respostas do Gork.</p></div></div><div class="meta-block">${icon("info")}<div><strong>Seu histórico continua aqui</strong><p>Mensagens, imagens e configurações existentes são preservadas.</p></div></div></div>`;
 const start=$('[data-action="start-connection"]');if(start){start.disabled=working;start.innerHTML=icon(working?"check":"plus")+(working?"Conectado":"Iniciar conexão");}
}
function qrCaption(){return state.qrUrl?`Atualizado às ${new Date(state.qrAt).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})} · ${button("refresh-qr","Renovar","refresh")}`:"O código aparece aqui quando a sessão estiver pronta.";}
function codeMarkup(){return `<div class="code-value" aria-label="Código de conexão">${esc(state.code)}</div><p class="field-hint">Use o código agora. Ele é válido por tempo limitado.</p>${button("copy-code","Copiar código","copy",false)}`;}
async function refreshConnection(){if(state.refreshing||state.page!=="connection")return;state.refreshing=true;const nav=state.navigation;try{const next=await api("/connection");if(nav!==state.navigation||state.page!=="connection")return;const changed=next.status!==state.connection?.status;state.connection=next;if(changed){if(next.status==="WORKING"){clearQr();state.code=null;}renderConnection();}
 const error=$("#connection-error");if(error)error.hidden=true;
 if(next.status==="SCAN_QR_CODE" && state.mode==="qr" && Date.now()-state.qrAt>25000)await fetchQr();
 }catch(error){if(nav!==state.navigation)return;if(!state.connection){state.connection={status:"UNKNOWN"};renderConnection();}const box=$("#connection-error");if(box){box.textContent=message(error);box.hidden=false;}}finally{state.refreshing=false;}}
async function fetchQr(){const nav=state.navigation;const blob=await api("/connection/qr",{binary:true});if(nav!==state.navigation||state.page!=="connection"||state.mode!=="qr")return;clearQr();state.qrUrl=URL.createObjectURL(blob);state.qrAt=Date.now();if($("#qr-frame"))$("#qr-frame").innerHTML=`<img src="${state.qrUrl}" alt="QR code para conectar o WhatsApp">`;if($("#qr-caption"))$("#qr-caption").innerHTML=qrCaption();}
document.addEventListener("input",event=>{if(event.target.id==="phone-number")state.phoneNumber=event.target.value;});
document.addEventListener("submit",async event=>{if(event.target.id!=="pairing-form")return;event.preventDefault();if(state.pairingBusy)return;state.pairingBusy=true;const form=event.target;const submit=$("button[type=submit]",form);submit.disabled=true;$("#pairing-error").hidden=true;try{const phone=$("#phone-number").value.replace(/[^\d+]/g,"");if(!/^\+?[1-9]\d{6,14}$/.test(phone))throw new Error("Informe um número válido, com código do país e DDD.");const result=await api("/connection/code",{method:"POST",body:JSON.stringify({phone_number:phone})});state.code=result.code;if($("#pairing-result"))$("#pairing-result").innerHTML=codeMarkup();}catch(error){if($("#pairing-error")){$("#pairing-error").textContent=message(error);$("#pairing-error").hidden=false;}}finally{state.pairingBusy=false;const liveForm=$("#pairing-form");if(liveForm)liveForm.querySelectorAll("input,button[type=submit]").forEach(node=>node.disabled=false);}});
function renderDirectoryShell(){const kind=state.page==="users"?"user":"group";$("#page-content").innerHTML=`<section class="card"><div class="table-toolbar"><label class="search-field" for="directory-search">${icon("search")}<input id="directory-search" type="search" placeholder="${kind==="user"?"Buscar por nome, telefone ou LID":"Buscar por nome ou identificador"}" autocomplete="off"></label><span class="count-label" id="directory-count"></span></div><div id="directory-results">${loading}</div></section>${note("Estar na whitelist permite usar o Gork. Restrições de comandos e blacklist continuam sendo aplicadas.")}`;}
async function loadDirectory(){const nav=state.navigation;const kind=state.page==="users"?"user":"group";const result=await api(`/directory/${kind}?q=${encodeURIComponent(state.q)}&offset=${state.offset}&limit=30`);if(nav!==state.navigation)return;state.data.directory=result;$("#directory-count").textContent=`${result.total} ${kind==="user"?"usuários":"grupos"}`;
 const headers=kind==="user"?["Usuário","Telefone","Whitelist","Perfil",""]:["Grupo","Whitelist","Respostas automáticas",""];
 const rows=result.items.map(item=>`<tr><td>${person(item.name,null,kind)}</td>${kind==="user"?`<td class="mono">${esc(item.phone_number || "—")}</td>`:""}<td>${badge(item.allowed?"Autorizado":"Fora da lista",item.allowed?"green":"")}${item.blocked?` ${badge("Bloqueado","red")}`:""}</td><td>${kind==="user"?`<span class="role">${item.is_admin?"Administrador":"Padrão"}</span>`:badge(item.auto_message?"Ativadas":"Desativadas",item.auto_message?"green":"")}</td><td>${button("edit-access","Gerenciar",null,false,`data-id="${item.id}"`)}</td></tr>`).join("");
 $("#directory-results").innerHTML=result.items.length?`<div class="table-scroll"><table><thead><tr>${headers.map(text=>`<th>${text}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div><div class="table-footer"><span>${result.offset+1}–${result.offset+result.items.length} de ${result.total}</span><div class="pagination">${button("prev-page","Anterior",null,false,result.offset===0?"disabled":"")}${button("next-page","Próxima",null,false,result.offset+result.items.length>=result.total?"disabled":"")}</div></div>`:empty(state.q?"Nenhum resultado":"Nenhum cadastro por aqui",state.q?"Tente outro nome ou identificador.":"Adicione um cadastro ou aguarde as primeiras mensagens no WhatsApp.",kind==="user"?"users":"group");
}
const agentNames={"conversation-dm":"Conversas privadas","conversation-group":"Conversas em grupo","filter":"Filtro de conversas","audio-generation":"Geração de áudio","describe-image":"Descrição de imagens","resize-image":"Ajuste de imagens","image-generation":"Geração de imagens"};
function agentName(name){return agentNames[name] || name;}
function renderAgents(){const {agents,overrides}=state.data;const scoped=state.tab==="overrides";let rows;
 if(scoped){rows=overrides.map(item=>`<tr><td>${person(item.group_name||item.user_name||"Sem nome",item.group_id?"Grupo":"Usuário",item.group_id?"group":"user")}</td><td>${esc(agentName(item.agent_name))}</td><td class="mono">${esc(item.openrouter_id)}</td><td><div class="row-actions">${button("edit-override","Editar",null,false,`data-id="${item.id}"`)}<button class="icon-button" data-action="delete-override" data-id="${item.id}" aria-label="Restaurar modelo padrão">${icon("trash")}</button></div></td></tr>`).join("");}
 else{rows=agents.map(item=>`<tr><td>${person(agentName(item.name),item.name)}</td><td><strong>${esc(item.model_name)}</strong><span class="subline mono muted">${esc(item.openrouter_id)}</span></td><td>${badge(item.model_managed||item.prompt_managed?"Personalizado":"Padrão",item.model_managed||item.prompt_managed?"green":"")}</td><td><div class="row-actions">${button("edit-agent","Configurar",null,false,`data-id="${item.id}"`)}${item.model_managed||item.prompt_managed?`<button class="icon-button" data-action="reset-agent" data-id="${item.id}" title="Restaurar configuração original" aria-label="Restaurar configuração original">${icon("refresh")}</button>`:""}</div></td></tr>`).join("");}
 const headers=scoped?["Conversa","Agente","Modelo",""]:["Agente","Modelo em uso","Configuração",""];
 $("#page-content").innerHTML=`<div class="tabs"><button class="tab ${!scoped?"active":""}" data-action="agent-tab" data-tab="defaults">Padrões <span class="tab-count">${agents.length}</span></button><button class="tab ${scoped?"active":""}" data-action="agent-tab" data-tab="overrides">Por conversa <span class="tab-count">${overrides.length}</span></button></div><section class="card">${rows?`<div class="table-scroll"><table><thead><tr>${headers.map(value=>`<th>${value}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`:empty(scoped?"Nenhuma exceção definida":"Nenhum agente encontrado",scoped?"Todas as conversas usam os modelos padrão. Defina uma exceção quando precisar.":"Os agentes são cadastrados na inicialização do Gork.","sliders")}</section>${note(scoped?"Uma configuração por conversa tem prioridade sobre o modelo padrão do agente.":"Alterações feitas aqui são preservadas após reiniciar o Gork. Exceções por conversa continuam tendo prioridade.")}`;
}
function renderModels(){const models=state.data.models;$("#page-content").innerHTML=`<section class="card"><div class="card-head"><div><h3>Catálogo de modelos</h3><p>Selecione estes modelos ao configurar seus agentes.</p></div><span class="count-label">${models.length} modelos</span></div>${models.length?`<div class="table-scroll"><table><thead><tr><th>Modelo</th><th>Identificador no OpenRouter</th></tr></thead><tbody>${models.map(item=>`<tr><td>${person(item.name,null)}</td><td class="mono">${esc(item.openrouter_id)}</td></tr>`).join("")}</tbody></table></div>`:empty("Seu catálogo está vazio","Adicione um modelo usando seu identificador no OpenRouter.")}</section>${note("O modelo precisa estar disponível na sua conta e suportar o recurso do agente: texto, imagem, áudio ou embedding.")}`;}
function renderBlacklist(){const entries=state.data.entries;$("#page-content").innerHTML=`<section class="card"><div class="card-head"><div><h3>Usuários com restrições</h3><p>Bloqueios são aplicados em conversas privadas e grupos.</p></div><span class="count-label">${entries.length} registros</span></div>${entries.length?`<div class="table-scroll"><table><thead><tr><th>Usuário</th><th>Recursos bloqueados</th><th></th></tr></thead><tbody>${entries.map(item=>`<tr><td>${person(item.name,item.phone_number||item.src_id)}</td><td>${item.features.length?`<div class="tags">${item.features.map(value=>`<span class="tag">${esc(value)}</span>`).join("")}</div>`:badge("Todos os recursos","red")}</td><td><div class="row-actions">${button("edit-blacklist","Editar",null,false,`data-id="${item.user_id}"`)}${button("delete-blacklist","Desbloquear",null,false,`data-id="${item.user_id}"`)}</div></td></tr>`).join("")}</tbody></table></div>`:empty("Nenhum usuário bloqueado","Os usuários autorizados podem usar os recursos liberados nas permissões.","shield")}</section>`;}
function scopeName(item){if(item.user_id&&item.group_id)return `${item.user_name||"Usuário #"+item.user_id} em ${item.group_name||"Grupo #"+item.group_id}`;return item.group_id?item.group_name||"Grupo #"+item.group_id:item.user_id?item.user_name||"Usuário #"+item.user_id:"Todos os usuários e grupos";}
function formatDate(value){return value?new Intl.DateTimeFormat("pt-BR",{dateStyle:"short",timeStyle:"short"}).format(new Date(value)):"Sem prazo";}
function renderCommands(){const {rules}=state.data;$("#page-content").innerHTML=`<section class="card"><div class="card-head"><div><h3>Restrições de uso</h3><p>Por padrão, os comandos estão liberados para quem está na whitelist.</p></div><span class="count-label">${rules.length} regras</span></div>${rules.length?`<div class="table-scroll"><table><thead><tr><th>Comando</th><th>Aplicar a</th><th>Vigência</th><th></th></tr></thead><tbody>${rules.map(item=>{const expired=item.disabled_until&&new Date(item.disabled_until)<=new Date();return `<tr><td><span class="tag">${esc(item.command==="interaction"?"Conversas":item.command==="mcp"?"Consultas MCP":"!"+item.command)}</span></td><td>${esc(scopeName(item))}</td><td>${badge(expired?"Expirada":"Ativa",expired?"":"amber")} <span class="subline muted">${esc(formatDate(item.disabled_until))}</span></td><td><div class="row-actions">${button("edit-command","Editar",null,false,`data-id="${item.id}"`)}<button class="icon-button" data-action="delete-command" data-id="${item.id}" aria-label="Remover restrição">${icon("trash")}</button></div></td></tr>`;}).join("")}</tbody></table></div>`:empty("Nenhuma restrição de comando","Crie uma regra para suspender um recurso globalmente ou apenas em uma conversa.","terminal")}</section>${note("Restrições com prazo deixam de bloquear automaticamente na data escolhida. Remover uma regra não remove outras restrições ou bloqueios de blacklist.")}`;}
const field = (label,html,hint="")=>`<div class="field">${label}${html}${hint?`<p class="field-hint">${hint}</p>`:""}</div>`;
function renderMcps(){
 const servers=state.data.servers;
 $("#page-content").innerHTML=`<section class="card">${servers.length?`<div class="table-scroll"><table><thead><tr><th>Servidor</th><th>Disponível para</th><th>Ferramentas</th><th>Estado</th><th></th></tr></thead><tbody>${servers.map(item=>{
 const count=item.tool_names.length?item.tools.filter(tool=>item.tool_names.includes(tool.name)).length:item.tools.length;
 const status=!item.enabled?badge("Desativado"):item.last_error?badge("Erro","red"):item.checked_at?badge(count?"Pronto":"Sem ferramentas",count?"green":"amber"):badge("Não testado","amber");
 return `<tr><td><strong>${esc(item.name)}</strong><span class="subline mcp-description">${esc(item.description)}</span></td><td>${esc(item.group_id?"Grupo #"+item.group_id:item.user_id?"Usuário #"+item.user_id:"Todos os autorizados")}</td><td>${count}</td><td>${status}</td><td><div class="row-actions">${button("edit-mcp","Editar",null,false,`data-id="${item.id}"`)}${button("sync-mcp","Testar",null,false,`data-id="${item.id}"`)}<button class="icon-button" data-action="delete-mcp" data-id="${item.id}" aria-label="Remover MCP">${icon("trash")}</button></div></td></tr>`;
 }).join("")}</tbody></table></div>`:empty("Nenhum MCP cadastrado","Adicione um endpoint, salve a configuração e teste para descobrir suas ferramentas.","terminal")}</section>${note("Headers e parâmetros são fixos no servidor. O modelo escolhe as ferramentas por tool call, mas não pode alterar esses valores. Após cadastrar ou mudar a conexão, use Testar.")}`;
}
function jsonField(id,title,value,hint){return field(label(title,id),`<textarea id="${id}" name="${id}" class="json-editor" spellcheck="false">${esc(JSON.stringify(value||{},null,2))}</textarea>`,hint);}
function parseObject(data,key){let value;try{value=JSON.parse(data.get(key)||"{}");}catch{throw new Error(`O campo ${key} precisa conter JSON válido.`);}if(value===null||Array.isArray(value)||typeof value!=="object")throw new Error(`Use um objeto JSON no campo ${key}.`);return value;}
async function mcpEditor(identifier=null){
 const item=identifier?await api(`/mcps/${identifier}`):{name:"",description:"",url:"",transport:"streamable_http",enabled:true,headers:{},params:{},fixed_arguments:{},tool_names:[],tools:[],timeout_seconds:20};
 const scope=item.user_id?"user":item.group_id?"group":"global";
 const picker=scope==="global"?"":await directoryPicker(scope,"target_id",{id:item.user_id||item.group_id,name:scope==="user"?"Usuário #"+item.user_id:"Grupo #"+item.group_id});
 const catalog=item.tools.length?`<details class="mcp-tools"><summary>Ferramentas descobertas (${item.tools.length})</summary>${item.tools.map(tool=>`<p class="mono">${esc(tool.name)}</p><p class="field-hint">${esc(tool.description)}</p><pre>${esc(JSON.stringify(tool.inputSchema,null,2))}</pre>`).join("")}</details>`:"";
 editor(identifier?"Editar MCP":"Adicionar MCP",
 field(label("Nome","name"),input("name","Ex.: Base de documentos",item.name,'required maxlength="100"'))+
 field(label("Descrição para o Gork","description"),`<textarea id="description" name="description" rows="3" required maxlength="3000">${esc(item.description)}</textarea>`,"Explique o que consultar neste serviço e quando usá-lo.")+
 field(label("URL do endpoint MCP","url"),input("url","http://servico:8000/mcp",item.url,'type="url" required maxlength="2000"'))+
 `<div class="field-row">${field(label("Transporte","transport"),select("transport",[{id:"streamable_http",name:"Streamable HTTP"},{id:"sse",name:"SSE (legado)"}],item.transport))}${field(label("Timeout (segundos)","timeout_seconds"),input("timeout_seconds","20",item.timeout_seconds,'type="number" min="3" max="60" required'))}</div>`+
 field(label("Disponível para","scope"),select("scope",[{id:"global",name:"Todos os usuários e grupos autorizados"},{id:"user",name:"Um usuário, somente no privado"},{id:"group",name:"Um grupo"}],scope))+
 `<div id="mcp-targets">${picker}</div>`+
 jsonField("headers","Headers fixos (JSON)",item.headers,'Ex.: {"Authorization": "Bearer sua-chave"}. Não são enviados ao modelo.')+
 jsonField("params","Parâmetros fixos da conexão (JSON)",item.params,'São enviados na query da URL em todas as requisições. Ex.: {"workspace_id": "123"}.')+
 jsonField("fixed_arguments","Argumentos fixos por ferramenta (JSON)",item.fixed_arguments,'Use o nome original da ferramenta. Ex.: {"search_documents": {"tenant_id": "123", "limit": 10}}. Esses valores prevalecem sobre os argumentos do modelo.')+
 field(label("Ferramentas permitidas","tool_names"),`<textarea id="tool_names" name="tool_names" rows="3" placeholder="Uma ferramenta por linha">${esc(item.tool_names.join("\n"))}</textarea>`,"Deixe vazio para disponibilizar todas as ferramentas descobertas. O nome deve ser exatamente o informado pelo MCP.")+
 checkbox("enabled","Habilitar MCP","Disponibiliza as ferramentas ao Gork, após testar a conexão.",item.enabled)+catalog,
 async data=>{
 const scope=data.get("scope");const payload={name:data.get("name"),description:data.get("description"),url:data.get("url"),transport:data.get("transport"),enabled:data.has("enabled"),timeout_seconds:Number(data.get("timeout_seconds")),headers:parseObject(data,"headers"),params:parseObject(data,"params"),fixed_arguments:parseObject(data,"fixed_arguments"),tool_names:String(data.get("tool_names")).split("\n").map(name=>name.trim()).filter(Boolean),user_id:scope==="user"?Number(data.get("target_id")):null,group_id:scope==="group"?Number(data.get("target_id")):null};
 const result=await api(identifier?`/mcps/${identifier}`:"/mcps",{method:identifier?"PUT":"POST",body:JSON.stringify(payload)});
 return result.needs_sync?"MCP salvo. Use Testar para carregar as ferramentas.":"MCP atualizado.";
 });
}
const label = (text,id)=>`<label for="${id}">${text}</label>`;
function input(id,placeholder="",value="",extra=""){return `<input id="${id}" name="${id}" placeholder="${placeholder}" value="${esc(value)}" ${extra}>`;}
function select(id,options,value="",extra=""){return `<select id="${id}" name="${id}" ${extra}>${options.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(value)?"selected":""}>${esc(item.name)}</option>`).join("")}</select>`;}
const checkbox = (id,title,description,checked=false)=>`<div class="check-row"><input id="${id}" name="${id}" type="checkbox" ${checked?"checked":""}><label for="${id}">${title}${description?`<span>${description}</span>`:""}</label></div>`;
function editor(title,html,save,saveLabel="Salvar alterações"){state.editor=save;$("#dialog-title").textContent=title;$("#editor-fields").innerHTML=html;$("#editor-error").hidden=true;$("#save-editor").textContent=saveLabel;$("#save-editor").disabled=false;$("#editor").showModal();}
function closeEditor(){ $("#editor").close();state.editor=null; }
$("#close-editor").addEventListener("click",closeEditor);$("#cancel-editor").addEventListener("click",closeEditor);
$("#editor").addEventListener("close",()=>{state.editor=null;});
$("#editor-form").addEventListener("submit",async event=>{event.preventDefault();const save=state.editor;if(!save)return;$("#save-editor").disabled=true;$("#editor-error").hidden=true;try{const result=await save(new FormData(event.target));closeEditor();toast(typeof result==="string"?result:"Configuração salva.");if(state.page==="users"||state.page==="groups")await loadDirectory();else await loadPage();}catch(error){$("#editor-error").textContent=message(error);$("#editor-error").hidden=false;}finally{$("#save-editor").disabled=false;}});
function confirmAction(title,text,action,saveLabel="Confirmar"){editor(title,`<p class="confirm-text">${esc(text)}</p>`,action,saveLabel);}
async function directoryPicker(kind,id,chosen=null){const result=await api(`/directory/${kind}?limit=30`);return pickerMarkup(kind,id,result.items,chosen);}
function pickerMarkup(kind,id,items,chosen){if(chosen&&!items.some(item=>item.id===chosen.id))items=[chosen,...items];return field(label(kind==="user"?"Usuário":"Grupo",id),`<input type="search" class="picker-search" data-picker="${id}" data-kind="${kind}" placeholder="Buscar por nome ou identificador" aria-label="Buscar ${kind==="user"?"usuário":"grupo"}">${select(id,[{id:"",name:"Selecione…"},...items.map(item=>({id:item.id,name:item.name||`Sem nome · ${item.phone_number||item.src_id||"#"+item.id}`}))],chosen?.id||"",'required')}`);}
async function accessEditor(id){const kind=state.page==="users"?"user":"group";const item=state.data.directory.items.find(row=>row.id===id);editor(`Acesso de ${item.name||"cadastro"}`,`<p class="form-info">${esc(item.phone_number||item.src_id)}</p>${checkbox("allowed","Autorizar na whitelist","Permite que este cadastro use o Gork.",item.allowed)}${checkbox("is_admin","Perfil de administrador","Marca este cadastro como administrador na whitelist.",item.is_admin)}${kind==="group"?checkbox("auto_message","Respostas automáticas","Permite que o Gork participe da conversa sem uma menção direta.",item.auto_message):""}`,async data=>{await api(`/whitelist/${kind}/${id}`,{method:"PUT",body:JSON.stringify({allowed:data.has("allowed"),is_admin:data.has("is_admin")})});if(kind==="group")await api(`/groups/${id}`,{method:"PATCH",body:JSON.stringify({auto_message:data.has("auto_message")})});});}
function userEditor(){editor("Adicionar usuário",field(label("Nome","name"),input("name","Nome do usuário","",'required maxlength="255"'))+field(label("Telefone","phone_number"),input("phone_number","5511999999999","",'type="tel"'),"Código do país + DDD + número, somente dígitos.")+field(label("LID (opcional)","lid"),input("lid","Identificador do WhatsApp"),"Informe o telefone ou LID. A autorização pode ser feita após o cadastro."),async data=>{const phone=String(data.get("phone_number")).replace(/[^\d+]/g,"");await api("/users",{method:"POST",body:JSON.stringify({name:data.get("name"),phone_number:phone||null,lid:data.get("lid")||null})});},"Adicionar usuário");}
function groupEditor(){editor("Adicionar grupo",field(label("Nome do grupo","name"),input("name","Nome do grupo","",'required maxlength="255"'))+field(label("Identificador do grupo","group_jid"),input("group_jid","120363000000000000@g.us","",'required'),"Você também pode sincronizar os grupos da conta conectada."),async data=>{await api("/groups",{method:"POST",body:JSON.stringify(Object.fromEntries(data))});},"Adicionar grupo");}
async function agentEditor(id){const item=state.data.agents.find(row=>row.id===id);const options=state.data.models.map(model=>({id:model.id,name:`${model.name} · ${model.openrouter_id}`}));editor(agentName(item.name),`<p class="form-info">Esta configuração é usada quando a conversa não tem uma exceção própria.</p>`+field(label("Modelo padrão","model_id"),select("model_id",options,item.model_id))+`<details class="prompt-toggle"><summary>Instruções do agente</summary>${field(label("Instruções","prompt"),`<textarea class="prompt-editor" name="prompt" id="prompt" spellcheck="false" maxlength="100000">${esc(item.prompt)}</textarea>`,"As alterações serão preservadas após reiniciar.")}</details>`,async data=>{const payload={};if(Number(data.get("model_id"))!==item.model_id)payload.model_id=Number(data.get("model_id"));if(data.get("prompt")!==item.prompt)payload.prompt=data.get("prompt");if(Object.keys(payload).length)await api(`/agents/${id}`,{method:"PATCH",body:JSON.stringify(payload)});});}
function modelEditor(){editor("Adicionar modelo",field(label("Nome de exibição","name"),input("name","Ex.: Meu modelo de texto","",'required maxlength="255"'))+field(label("Identificador no OpenRouter","openrouter_id"),input("openrouter_id","provedor/nome-do-modelo","",'required maxlength="255"'),"Use o identificador exato do modelo disponível na sua conta."),async data=>{await api("/models",{method:"POST",body:JSON.stringify(Object.fromEntries(data))});},"Adicionar modelo");}
async function overrideEditor(item=null){if(!state.data.agents){const [agents,models]=await Promise.all([api("/agents"),api("/models")]);state.data.agents=agents;state.data.models=models;}
 const kind=item?.group_id?"group":"user";const chosen=item?{id:item.group_id||item.user_id,name:item.group_name||item.user_name}:null;
 const picker=await directoryPicker(kind,"target_id",chosen);
 editor("Modelo por conversa",field(label("Agente","agent_id"),select("agent_id",state.data.agents.map(row=>({id:row.id,name:agentName(row.name)})),item?.agent_id))+field(label("Aplicar a","scope"),select("scope",[{id:"user",name:"Usuário"},{id:"group",name:"Grupo"}],kind))+`<div id="target-picker">${picker}</div>`+field(label("Modelo","model_id"),select("model_id",state.data.models.map(row=>({id:row.id,name:`${row.name} · ${row.openrouter_id}`})),item?.model_id)),async data=>{await api("/overrides",{method:"POST",body:JSON.stringify({agent_id:Number(data.get("agent_id")),model_id:Number(data.get("model_id")),user_id:data.get("scope")==="user"?Number(data.get("target_id")):null,group_id:data.get("scope")==="group"?Number(data.get("target_id")):null})});});
 // Editing changes the same agent/scope; prevent accidentally leaving the old rule active.
 if(item){$("#scope").disabled=true;$("#agent_id").disabled=true;$("#target_id").disabled=true;$(".picker-search",$("#target-picker")).disabled=true;const originalSave=state.editor;state.editor=data=>{data.set("scope",kind);data.set("agent_id",item.agent_id);data.set("target_id",chosen.id);return originalSave(data);};}
}
async function blacklistEditor(item=null){const chosen=item?{id:item.user_id,name:item.name,src_id:item.src_id}:null;const picker=await directoryPicker("user","user_id",chosen);const catalog=state.data.catalog||[];
 editor(item?"Editar bloqueio":"Bloquear usuário",picker+checkbox("all_features","Bloquear todos os recursos","Desmarque para escolher apenas alguns recursos.",!item?.features?.length)+`<div id="feature-options" class="feature-grid" ${!item?.features?.length?"hidden":""}>${catalog.map(command=>`<div class="feature-option"><input type="checkbox" name="features" id="feature-${esc(command.id)}" value="${esc(command.id)}" ${item?.features?.includes(command.id)?"checked":""}><label for="feature-${esc(command.id)}">${esc(command.id==="interaction"?"Conversas":command.id==="mcp"?"Consultas MCP":"!"+command.id)}</label></div>`).join("")}</div>`,async data=>{const features=data.has("all_features")?[]:data.getAll("features");if(!data.has("all_features")&&!features.length)throw new Error("Selecione ao menos um recurso ou marque o bloqueio completo.");await api("/blacklist",{method:"PUT",body:JSON.stringify({user_id:Number(data.get("user_id")),features})});});
 if(item){$("#user_id").disabled=true;$(".picker-search").disabled=true;const save=state.editor;state.editor=data=>{data.set("user_id",item.user_id);return save(data);};}
}
async function commandEditor(item=null){const scope=item?.user_id&&item?.group_id?"both":item?.user_id?"user":item?.group_id?"group":"global";
 const options=state.data.catalog.map(row=>({id:row.id,name:row.id==="interaction"?"Conversas":row.id==="mcp"?"Consultas MCP":"!"+row.id}));
 editor(item?"Editar restrição":"Nova restrição",field(label("Comando","command"),select("command",options,item?.command))+field(label("Aplicar a","scope"),select("scope",[{id:"global",name:"Todos os usuários e grupos"},{id:"user",name:"Um usuário"},{id:"group",name:"Um grupo"},{id:"both",name:"Um usuário em um grupo"}],scope))+`<div id="command-targets">${loading}</div>`+field(label("Bloquear até (opcional)","disabled_until"),input("disabled_until","",item?.disabled_until?localDate(item.disabled_until):"",'type="datetime-local"'),"Sem data, a restrição permanece até ser removida.")+field(label("Mensagem exibida ao usuário","message"),`<textarea id="message" name="message" rows="3" required maxlength="1000">${esc(item?.message||"Este comando está temporariamente desativado.")}</textarea>`),async data=>{const scope=data.get("scope");const until=data.get("disabled_until");await api(item?`/commands/${item.id}`:"/commands",{method:item?"PUT":"POST",body:JSON.stringify({command:data.get("command"),user_id:["user","both"].includes(scope)?Number(data.get("user_id")):null,group_id:["group","both"].includes(scope)?Number(data.get("group_id")):null,message:data.get("message"),disabled_until:until?new Date(until).toISOString():null})});});
 await commandTargets(scope,item);
}
function localDate(value){const date=new Date(value);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);}
async function commandTargets(scope,item=null){let html="";if(["user","both"].includes(scope))html+=await directoryPicker("user","user_id",item?.user_id?{id:item.user_id,name:item.user_name}:null);if(["group","both"].includes(scope))html+=await directoryPicker("group","group_id",item?.group_id?{id:item.group_id,name:item.group_name}:null);if($("#command-targets"))$("#command-targets").innerHTML=html;}
let searchTimer, pickerTimer;
document.addEventListener("input",event=>{
 if(event.target.id==="ban-search"){clearTimeout(searchTimer);state.q=event.target.value;state.offset=0;searchTimer=setTimeout(loadBans,250);}
 if(event.target.id==="directory-search"){clearTimeout(searchTimer);state.q=event.target.value;state.offset=0;searchTimer=setTimeout(()=>loadDirectory().catch(error=>toast(message(error))),250);}
 if(event.target.dataset.picker){const {picker,kind}=event.target.dataset;const query=event.target.value;clearTimeout(pickerTimer);pickerTimer=setTimeout(async()=>{try{const result=await api(`/directory/${kind}?q=${encodeURIComponent(query)}&limit=30`);const target=$("#"+picker);if(!target)return;target.innerHTML=`<option value="">Selecione…</option>`+result.items.map(item=>`<option value="${item.id}">${esc(item.name||"Sem nome")} · ${esc(item.phone_number||item.src_id||"#"+item.id)}</option>`).join("");}catch(error){toast(message(error));}},250);}
});
document.addEventListener("change",async event=>{try{
 if(event.target.id==="ban-view"){state.banView=event.target.value;state.offset=0;await loadBans();}
 if(event.target.id==="data-period")$("#data-dates").hidden=event.target.value!=="custom";
 if(event.target.id==="sync-history"){$("#history-options").hidden=!event.target.checked;}
 if(event.target.id==="sync-period"){$("#sync-dates").hidden=event.target.value!=="custom";}
 if(event.target.id==="all_features")$("#feature-options").hidden=event.target.checked;
 if(event.target.id==="scope"){if($("#command-targets"))await commandTargets(event.target.value);else if($("#mcp-targets"))$("#mcp-targets").innerHTML=event.target.value==="global"?"":await directoryPicker(event.target.value,"target_id");else if($("#target-picker"))$("#target-picker").innerHTML=await directoryPicker(event.target.value,"target_id");}
 }catch(error){toast(message(error));}});
document.addEventListener("click",async event=>{const node=event.target.closest("[data-action]");if(!node||node.disabled)return;const action=node.dataset.action,id=Number(node.dataset.id);node.disabled=true;try{
 switch(action){
 case "refresh-bans":await loadBans();break;
 case "bans-prev":state.offset=Math.max(0,state.offset-30);await loadBans();break;
 case "bans-next":state.offset+=30;await loadBans();break;
 case "cancel-ban-poll":confirmAction("Cancelar votação?","Os votos desta enquete não serão apurados e ela não aplicará um banimento. A enquete continuará visível no WhatsApp.",async()=>{await api(`/bans/${id}/cancel`,{method:"POST"});state.offset=0;},"Cancelar votação");break;
 case "revoke-ban":confirmAction("Encerrar banimento?","Este período de banimento será encerrado. Se houver outros bans ativos para o mesmo membro neste grupo, encerre-os também para liberar as mensagens. As mensagens já excluídas não são recuperadas.",async()=>{await api(`/bans/${id}/revoke`,{method:"POST"});state.offset=0;},"Encerrar ban");break;
 case "data-prev":state.dataOffset=Math.max(0,state.dataOffset-30);await loadData();break;
 case "data-next":state.dataOffset+=30;await loadData();break;
 case "data-index":state.dataOffset=0;await loadData(true);break;
 case "data-retry":await loadData();break;
 case "retry":await loadPage();break;
 case "refresh-connection":await refreshConnection();break;
 case "start-connection":await api("/connection/start",{method:"POST"});await refreshConnection();break;
 case "refresh-qr":await fetchQr();break;
 case "code-mode":state.mode="code";renderConnection();break;
 case "qr-mode":state.mode="qr";renderConnection();await refreshConnection();break;
 case "copy-code":await navigator.clipboard.writeText(state.code);toast("Código copiado.");break;
 case "new-user":userEditor();break;
 case "new-group":groupEditor();break;
 case "sync-groups":{const result=await api("/groups/sync",{method:"POST"});await loadDirectory();toast(`${result.imported} grupos sincronizados.`);break;}
 case "edit-access":await accessEditor(id);break;
 case "prev-page":state.offset=Math.max(0,state.offset-30);await loadDirectory();break;
 case "next-page":state.offset+=30;await loadDirectory();break;
 case "new-model":modelEditor();break;
 case "new-mcp":await mcpEditor();break;
 case "edit-mcp":await mcpEditor(id);break;
 case "sync-mcp":try{const result=await api(`/mcps/${id}/sync`,{method:"POST"});toast(`MCP conectado: ${result.tools.length} ferramentas encontradas.`);}finally{await loadPage();}break;
 case "delete-mcp":confirmAction("Remover MCP?","O Gork deixará de usar este servidor. O histórico de chamadas será mantido.",()=>api(`/mcps/${id}`,{method:"DELETE"}),"Remover MCP");break;
 case "edit-agent":await agentEditor(id);break;
 case "reset-agent":confirmAction("Restaurar configuração original?","O modelo e as instruções deste agente voltarão ao padrão definido no projeto. As exceções por conversa serão mantidas.",()=>api(`/agents/${id}/reset`,{method:"POST"}),"Restaurar padrão");break;
 case "agent-tab":state.tab=node.dataset.tab;renderAgents();break;
 case "new-override":await overrideEditor();break;
 case "edit-override":await overrideEditor(state.data.overrides.find(item=>item.id===id));break;
 case "delete-override":confirmAction("Usar o modelo padrão?","Esta conversa voltará a usar o modelo padrão do agente.",()=>api(`/overrides/${id}`,{method:"DELETE"}),"Usar padrão");break;
 case "new-blacklist":await blacklistEditor();break;
 case "edit-blacklist":await blacklistEditor(state.data.entries.find(item=>item.user_id===id));break;
 case "delete-blacklist":confirmAction("Desbloquear usuário?","O bloqueio de blacklist será removido. As regras de whitelist e de comandos continuam valendo.",()=>api(`/blacklist/${id}`,{method:"DELETE"}),"Desbloquear");break;
 case "new-command":await commandEditor();break;
 case "edit-command":await commandEditor(state.data.rules.find(item=>item.id===id));break;
 case "delete-command":confirmAction("Remover restrição?","Esta regra deixará de bloquear o comando. Outras restrições existentes serão mantidas.",()=>api(`/commands/${id}`,{method:"DELETE"}),"Remover restrição");break;
 }
 }catch(error){toast(message(error));}finally{if(node.isConnected&&!(action==="start-connection"&&state.connection?.status==="WORKING"))node.disabled=false;}});
window.addEventListener("hashchange",navigate);
window.addEventListener("pagehide",()=>{stopPolling();clearQr();});
boot();
