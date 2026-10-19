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
 if(state.page==="connection"){renderConnection();await refreshConnection();if(nav===state.navigation)state.poll=setInterval(()=>{if(!document.hidden)refreshConnection();},5000);return;}
 if(state.page==="users"||state.page==="groups"){renderDirectoryShell();await loadDirectory();return;}
 let data;
 if(state.page==="agents"){const [agents,models,overrides]=await Promise.all([api("/agents"),api("/models"),api("/overrides")]);data={agents,models,overrides};}
 if(state.page==="models")data={models:await api("/models")};
 if(state.page==="blacklist"){const [entries,commands]=await Promise.all([api("/blacklist"),api("/commands")]);data={entries,catalog:commands.catalog};}
 if(state.page==="commands")data=await api("/commands");
 if(nav!==state.navigation)return;state.data=data;renderPage();
 }catch(error){if(nav===state.navigation)$("#page-content").innerHTML=errorState(error);}}
function renderPage(){if(state.page==="agents")renderAgents();else if(state.page==="models")renderModels();else if(state.page==="blacklist")renderBlacklist();else if(state.page==="commands")renderCommands();}
const statusNames={WORKING:["Conectado","green"],SCAN_QR_CODE:["Aguardando conexão","amber"],STARTING:["Conectando","amber"],STOPPED:["Desconectado",""],FAILED:["Falha na conexão","red"],NOT_CREATED:["Não conectado",""],UNKNOWN:["Estado indisponível",""]};
function renderConnection(){
 const status=state.connection?.status;const [label,color]=statusNames[status]||["Verificando conexão",""];const ready=status==="SCAN_QR_CODE";const working=status==="WORKING";
 let body;
 if(working){body=`<div class="connected-box"><div class="connected-icon">${icon("check")}</div><h2>Seu WhatsApp está conectado.</h2><p>O Gork está pronto para receber e enviar mensagens.</p><span class="mono muted">${esc(state.connection.me?.name || "")} ${esc((state.connection.me?.id||"").split("@")[0])}</span></div>`;}
 else if(state.mode==="code"){
 body=`<div class="code-panel"><h2>Conecte com seu número.</h2><p>Informe o número do celular que será usado pelo Gork, com o código do país e DDD.</p><form id="pairing-form"><label for="phone-number">Número do WhatsApp</label><input type="tel" id="phone-number" name="phone_number" autocomplete="tel" placeholder="55 11 99999-9999" required ${!ready?"disabled":""}><p class="field-hint">${ready?"Um código será exibido para inserir no WhatsApp.":"Inicie a conexão para solicitar um código."}</p><button class="button primary" type="submit" ${!ready?"disabled":""}>Gerar código ${icon("arrow")}</button></form><div id="pairing-result">${state.code?codeMarkup():""}</div><p id="pairing-error" class="form-error" role="alert" hidden></p><div class="link-alternative">${button("qr-mode","Usar QR code","phone")}</div></div><div class="connection-instructions"><span class="eyebrow">NO SEU CELULAR</span><h2>Insira o código no WhatsApp.</h2><ol class="steps"><li><span class="step-number">1</span><span>Abra <strong>Aparelhos conectados</strong>.</span></li><li><span class="step-number">2</span><span>Toque em <strong>Conectar um aparelho</strong>.</span></li><li><span class="step-number">3</span><span>Escolha <strong>Conectar com número de telefone</strong> e insira o código.</span></li></ol></div>`;
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
document.addEventListener("submit",async event=>{if(event.target.id!=="pairing-form")return;event.preventDefault();const form=event.target;const submit=$("button[type=submit]",form);submit.disabled=true;$("#pairing-error").hidden=true;try{const phone=$("#phone-number").value.replace(/[^\d+]/g,"");if(!/^\+?[1-9]\d{6,14}$/.test(phone))throw new Error("Informe um número válido, com código do país e DDD.");const result=await api("/connection/code",{method:"POST",body:JSON.stringify({phone_number:phone})});state.code=result.code;if($("#pairing-result"))$("#pairing-result").innerHTML=codeMarkup();}catch(error){if($("#pairing-error")){$("#pairing-error").textContent=message(error);$("#pairing-error").hidden=false;}}finally{submit.disabled=false;}});
function renderDirectoryShell(){const kind=state.page==="users"?"user":"group";$("#page-content").innerHTML=`<section class="card"><div class="table-toolbar"><label class="search-field" for="directory-search">${icon("search")}<input id="directory-search" type="search" placeholder="${kind==="user"?"Buscar por nome, telefone ou LID":"Buscar por nome ou identificador"}" autocomplete="off"></label><span class="count-label" id="directory-count"></span></div><div id="directory-results">${loading}</div></section>${note("Estar na whitelist permite usar o Gork. Restrições de comandos e blacklist continuam sendo aplicadas.")}`;}
async function loadDirectory(){const nav=state.navigation;const kind=state.page==="users"?"user":"group";const result=await api(`/directory/${kind}?q=${encodeURIComponent(state.q)}&offset=${state.offset}&limit=30`);if(nav!==state.navigation)return;state.data.directory=result;$("#directory-count").textContent=`${result.total} ${kind==="user"?"usuários":"grupos"}`;
 const headers=kind==="user"?["Usuário","Telefone","Whitelist","Perfil",""]:["Grupo","Whitelist","Respostas automáticas",""];
 const rows=result.items.map(item=>`<tr><td>${person(item.name,item.src_id,kind)}</td>${kind==="user"?`<td class="mono">${esc(item.phone_number || "—")}</td>`:""}<td>${badge(item.allowed?"Autorizado":"Fora da lista",item.allowed?"green":"")}${item.blocked?` ${badge("Bloqueado","red")}`:""}</td><td>${kind==="user"?`<span class="role">${item.is_admin?"Administrador":"Padrão"}</span>`:badge(item.auto_message?"Ativadas":"Desativadas",item.auto_message?"green":"")}</td><td>${button("edit-access","Gerenciar",null,false,`data-id="${item.id}"`)}</td></tr>`).join("");
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
function renderCommands(){const {rules}=state.data;$("#page-content").innerHTML=`<section class="card"><div class="card-head"><div><h3>Restrições de uso</h3><p>Por padrão, os comandos estão liberados para quem está na whitelist.</p></div><span class="count-label">${rules.length} regras</span></div>${rules.length?`<div class="table-scroll"><table><thead><tr><th>Comando</th><th>Aplicar a</th><th>Vigência</th><th></th></tr></thead><tbody>${rules.map(item=>{const expired=item.disabled_until&&new Date(item.disabled_until)<=new Date();return `<tr><td><span class="tag">${esc(item.command==="interaction"?"conversas":"!"+item.command)}</span></td><td>${esc(scopeName(item))}</td><td>${badge(expired?"Expirada":"Ativa",expired?"":"amber")} <span class="subline muted">${esc(formatDate(item.disabled_until))}</span></td><td><div class="row-actions">${button("edit-command","Editar",null,false,`data-id="${item.id}"`)}<button class="icon-button" data-action="delete-command" data-id="${item.id}" aria-label="Remover restrição">${icon("trash")}</button></div></td></tr>`;}).join("")}</tbody></table></div>`:empty("Nenhuma restrição de comando","Crie uma regra para suspender um recurso globalmente ou apenas em uma conversa.","terminal")}</section>${note("Restrições com prazo deixam de bloquear automaticamente na data escolhida. Remover uma regra não remove outras restrições ou bloqueios de blacklist.")}`;}
const field = (label,html,hint="")=>`<div class="field">${label}${html}${hint?`<p class="field-hint">${hint}</p>`:""}</div>`;
const label = (text,id)=>`<label for="${id}">${text}</label>`;
function input(id,placeholder="",value="",extra=""){return `<input id="${id}" name="${id}" placeholder="${placeholder}" value="${esc(value)}" ${extra}>`;}
function select(id,options,value="",extra=""){return `<select id="${id}" name="${id}" ${extra}>${options.map(item=>`<option value="${esc(item.id)}" ${String(item.id)===String(value)?"selected":""}>${esc(item.name)}</option>`).join("")}</select>`;}
const checkbox = (id,title,description,checked=false)=>`<div class="check-row"><input id="${id}" name="${id}" type="checkbox" ${checked?"checked":""}><label for="${id}">${title}${description?`<span>${description}</span>`:""}</label></div>`;
function editor(title,html,save,saveLabel="Salvar alterações"){state.editor=save;$("#dialog-title").textContent=title;$("#editor-fields").innerHTML=html;$("#editor-error").hidden=true;$("#save-editor").textContent=saveLabel;$("#save-editor").disabled=false;$("#editor").showModal();}
function closeEditor(){ $("#editor").close();state.editor=null; }
$("#close-editor").addEventListener("click",closeEditor);$("#cancel-editor").addEventListener("click",closeEditor);
$("#editor").addEventListener("close",()=>{state.editor=null;});
$("#editor-form").addEventListener("submit",async event=>{event.preventDefault();const save=state.editor;if(!save)return;$("#save-editor").disabled=true;$("#editor-error").hidden=true;try{await save(new FormData(event.target));closeEditor();toast("Configuração salva.");if(state.page==="users"||state.page==="groups")await loadDirectory();else await loadPage();}catch(error){$("#editor-error").textContent=message(error);$("#editor-error").hidden=false;}finally{$("#save-editor").disabled=false;}});
function confirmAction(title,text,action,saveLabel="Confirmar"){editor(title,`<p class="confirm-text">${esc(text)}</p>`,action,saveLabel);}
async function directoryPicker(kind,id,chosen=null){const result=await api(`/directory/${kind}?limit=30`);return pickerMarkup(kind,id,result.items,chosen);}
function pickerMarkup(kind,id,items,chosen){if(chosen&&!items.some(item=>item.id===chosen.id))items=[chosen,...items];return field(label(kind==="user"?"Usuário":"Grupo",id),`<input type="search" class="picker-search" data-picker="${id}" data-kind="${kind}" placeholder="Buscar por nome ou identificador" aria-label="Buscar ${kind==="user"?"usuário":"grupo"}">${select(id,[{id:"",name:"Selecione…"},...items.map(item=>({id:item.id,name:`${item.name||"Sem nome"} · ${item.phone_number||item.src_id||"#"+item.id}`}))],chosen?.id||"",'required')}`);}
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
 editor(item?"Editar bloqueio":"Bloquear usuário",picker+checkbox("all_features","Bloquear todos os recursos","Desmarque para escolher apenas alguns recursos.",!item?.features?.length)+`<div id="feature-options" class="feature-grid" ${!item?.features?.length?"hidden":""}>${catalog.map(command=>`<div class="feature-option"><input type="checkbox" name="features" id="feature-${esc(command.id)}" value="${esc(command.id)}" ${item?.features?.includes(command.id)?"checked":""}><label for="feature-${esc(command.id)}">${esc(command.id==="interaction"?"Conversas":"!"+command.id)}</label></div>`).join("")}</div>`,async data=>{const features=data.has("all_features")?[]:data.getAll("features");if(!data.has("all_features")&&!features.length)throw new Error("Selecione ao menos um recurso ou marque o bloqueio completo.");await api("/blacklist",{method:"PUT",body:JSON.stringify({user_id:Number(data.get("user_id")),features})});});
 if(item){$("#user_id").disabled=true;$(".picker-search").disabled=true;const save=state.editor;state.editor=data=>{data.set("user_id",item.user_id);return save(data);};}
}
async function commandEditor(item=null){const scope=item?.user_id&&item?.group_id?"both":item?.user_id?"user":item?.group_id?"group":"global";
 const options=state.data.catalog.map(row=>({id:row.id,name:row.id==="interaction"?"Conversas":"!"+row.id}));
 editor(item?"Editar restrição":"Nova restrição",field(label("Comando","command"),select("command",options,item?.command))+field(label("Aplicar a","scope"),select("scope",[{id:"global",name:"Todos os usuários e grupos"},{id:"user",name:"Um usuário"},{id:"group",name:"Um grupo"},{id:"both",name:"Um usuário em um grupo"}],scope))+`<div id="command-targets">${loading}</div>`+field(label("Bloquear até (opcional)","disabled_until"),input("disabled_until","",item?.disabled_until?localDate(item.disabled_until):"",'type="datetime-local"'),"Sem data, a restrição permanece até ser removida.")+field(label("Mensagem exibida ao usuário","message"),`<textarea id="message" name="message" rows="3" required maxlength="1000">${esc(item?.message||"Este comando está temporariamente desativado.")}</textarea>`),async data=>{const scope=data.get("scope");const until=data.get("disabled_until");await api(item?`/commands/${item.id}`:"/commands",{method:item?"PUT":"POST",body:JSON.stringify({command:data.get("command"),user_id:["user","both"].includes(scope)?Number(data.get("user_id")):null,group_id:["group","both"].includes(scope)?Number(data.get("group_id")):null,message:data.get("message"),disabled_until:until?new Date(until).toISOString():null})});});
 await commandTargets(scope,item);
}
function localDate(value){const date=new Date(value);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);}
async function commandTargets(scope,item=null){let html="";if(["user","both"].includes(scope))html+=await directoryPicker("user","user_id",item?.user_id?{id:item.user_id,name:item.user_name}:null);if(["group","both"].includes(scope))html+=await directoryPicker("group","group_id",item?.group_id?{id:item.group_id,name:item.group_name}:null);if($("#command-targets"))$("#command-targets").innerHTML=html;}
let searchTimer, pickerTimer;
document.addEventListener("input",event=>{
 if(event.target.id==="directory-search"){clearTimeout(searchTimer);state.q=event.target.value;state.offset=0;searchTimer=setTimeout(()=>loadDirectory().catch(error=>toast(message(error))),250);}
 if(event.target.dataset.picker){const {picker,kind}=event.target.dataset;const query=event.target.value;clearTimeout(pickerTimer);pickerTimer=setTimeout(async()=>{try{const result=await api(`/directory/${kind}?q=${encodeURIComponent(query)}&limit=30`);const target=$("#"+picker);if(!target)return;target.innerHTML=`<option value="">Selecione…</option>`+result.items.map(item=>`<option value="${item.id}">${esc(item.name||"Sem nome")} · ${esc(item.phone_number||item.src_id||"#"+item.id)}</option>`).join("");}catch(error){toast(message(error));}},250);}
});
document.addEventListener("change",async event=>{try{
 if(event.target.id==="all_features")$("#feature-options").hidden=event.target.checked;
 if(event.target.id==="scope"){if($("#command-targets"))await commandTargets(event.target.value);else if($("#target-picker"))$("#target-picker").innerHTML=await directoryPicker(event.target.value,"target_id");}
 }catch(error){toast(message(error));}});
document.addEventListener("click",async event=>{const node=event.target.closest("[data-action]");if(!node||node.disabled)return;const action=node.dataset.action,id=Number(node.dataset.id);node.disabled=true;try{
 switch(action){
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
