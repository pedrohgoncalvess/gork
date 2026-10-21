// Browser QA uses isolated API fixtures. It never writes to the real database or WAHA.
// Run with Playwright available in NODE_PATH and ADMIN_BROWSER_EXECUTABLE if needed.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.ADMIN_BROWSER_EXECUTABLE?{executablePath:process.env.ADMIN_BROWSER_EXECUTABLE}:{})});
  const page = await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const output=path.resolve("artifacts/admin");fs.mkdirSync(output,{recursive:true});
  let loggedIn=false,status="NOT_CREATED";
  const users=[{id:1,name:"Ana Costa",src_id:"123456789",phone_number:"5511999999999",allowed:true,is_admin:true,blocked:false},{id:2,name:"Lucas Almeida",src_id:"234567890",phone_number:"5521999999999",allowed:false,is_admin:false,blocked:false}];
  const groups=[{id:1,name:"Equipe de produto",src_id:"120363123456789012",allowed:true,is_admin:false,auto_message:true},{id:2,name:"Conversa de sábado",src_id:"120363123456789013",allowed:false,is_admin:false,auto_message:false}];
  const models=[{id:1,name:"Modelo de conversas",openrouter_id:"provider/chat-model"},{id:2,name:"Modelo alternativo",openrouter_id:"provider/other-model"}];
  const agents=[{id:1,name:"conversation-dm",prompt:"Responda em português.",model_id:1,model_name:models[0].name,openrouter_id:models[0].openrouter_id,model_managed:false,prompt_managed:false},{id:2,name:"conversation-group",prompt:"Participe quando necessário.",model_id:1,model_name:models[0].name,openrouter_id:models[0].openrouter_id,model_managed:false,prompt_managed:false}];
  let blocked=[],rules=[],overrides=[],mcps=[];
  const bans=[{id:1,target_name:'Lucas <script>alert(1)</script>',target_id:'234567890@lid',group_name:'Equipe de produto',chat_id:'120363123456789012@g.us',status:'active',yes_votes:6,no_votes:1,member_count:10,duration_minutes:30,opened_at:new Date().toISOString(),closes_at:new Date().toISOString(),ban_until:new Date(Date.now()+1800000).toISOString()},
    {id:2,target_name:'Ana Costa',target_id:'123456789@lid',group_name:'Conversa de sábado',chat_id:'120363123456789013@g.us',status:'voting',yes_votes:2,no_votes:1,member_count:8,duration_minutes:90,opened_at:new Date().toISOString(),closes_at:new Date(Date.now()+600000).toISOString(),ban_until:null}];
  let testSettings={test_mode:false,test_number:null,phone_number:"5511000000000",lid:"123456"},syncJob=null,syncPayload=null;
  const catalog=[{id:"interaction",description:"Conversas"},{id:"image",description:"Imagens"},{id:"sticker",description:"Figurinhas"},{id:"audio",description:"Áudio"}];
  const staticRoot=path.resolve("api/admin/static");
  await page.route("**/admin",route=>route.fulfill({contentType:"text/html",body:fs.readFileSync(path.join(staticRoot,"index.html"))}));
  await page.route("**/admin/assets/*",route=>{const name=path.basename(new URL(route.request().url()).pathname);return route.fulfill({contentType:name.endsWith(".js")?"application/javascript":name.endsWith(".css")?"text/css":"image/svg+xml",body:fs.readFileSync(path.join(staticRoot,name))});});
  await page.route("**/admin/api/**",async route=>{
    const req=route.request(),url=new URL(req.url()),endpoint=url.pathname.slice("/admin/api".length),method=req.method();
    const data=req.postData()?JSON.parse(req.postData()):{};
    const send=(value,code=200)=>route.fulfill({status:code,contentType:"application/json",body:JSON.stringify(value)});
    if(endpoint==="/login"){if(data.password!=="fixture-password")return send({detail:"Senha incorreta."},401);loggedIn=true;return send({csrf_token:"fixture-csrf"});}
    if(!loggedIn)return send({detail:"Entre no painel para continuar."},401);
    if(endpoint==="/session")return send({csrf_token:"fixture-csrf"});
    if(endpoint.startsWith("/data/"))return send({items:[{id:1,content:'Planejamento da viagem <script>alert(1)</script>',created_at:"2026-10-20T12:00:00Z",user_name:"Ana Costa",group_name:"Equipe de produto",media_id:1,media_name:"foto.png",media_type:"image",media_url:"/admin/api/media/1",description:"Praia e montanhas",size:0.25}],total:1,indexing_remaining:0});
    if(endpoint==="/media/1")return route.fulfill({contentType:"image/png",body:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=","base64")});
    if(endpoint==="/logout"){loggedIn=false;return send({ok:true});}
    if(method!=="GET")assert.equal(req.headers()["x-csrf-token"],"fixture-csrf");
    if(endpoint==='/bans'){const view=url.searchParams.get('view'),q=(url.searchParams.get('q')||'').toLowerCase();const items=bans.filter(item=>(view==='all'||(view==='active'?item.status==='active':view==='voting'?item.status==='voting':['revoked','cancelled'].includes(item.status)))&&JSON.stringify(item).toLowerCase().includes(q));return send({items,total:items.length,offset:0,limit:30});}
    if(/^\/bans\/\d+\/(cancel|revoke)$/.test(endpoint)){bans.find(item=>item.id===Number(endpoint.split('/')[2])).status=endpoint.endsWith('/cancel')?'cancelled':'revoked';return send({ok:true});}
    if(endpoint==="/settings")return send(testSettings);
    if(endpoint==="/settings/test"){testSettings={...testSettings,...data};return send(testSettings);}
    if(endpoint==="/sync"&&method==="GET")return send({job:syncJob});
    if(endpoint==="/sync"){syncPayload=data;syncJob={id:"fixture-job",status:"completed",contacts:2,messages:3,skipped:0};return send({job:syncJob},202);}
    if(endpoint==="/connection")return send({session:"default",status,me:status==="WORKING"?{id:"5511000000000@c.us",name:"Gork"}:null});
    if(endpoint==="/connection/start"){status="SCAN_QR_CODE";return send({status});}
    if(endpoint==="/connection/qr")return route.fulfill({status:200,contentType:"image/png",body:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=","base64")});
    if(endpoint==="/connection/code"){assert.equal(data.phone_number,"5511999999999");return send({code:"ABCD-1234"});}
    if(endpoint.startsWith("/directory/")){let items=endpoint.endsWith("user")?users:groups;const q=(url.searchParams.get("q")||"").toLowerCase();items=items.filter(item=>JSON.stringify(item).toLowerCase().includes(q));return send({items,total:items.length,offset:0,limit:30});}
    if(endpoint.startsWith("/whitelist/")){const [, ,kind,id]=endpoint.split("/");Object.assign((kind==="user"?users:groups).find(item=>item.id===Number(id)),data);return send(data);}
    if(endpoint==="/users"){users.push({id:users.length+1,src_id:data.lid||data.phone_number,...data,allowed:false,is_admin:false});return send({id:users.length},201);}
    if(endpoint==="/groups/sync")return send({imported:2});
    if(endpoint==="/groups"){groups.push({id:groups.length+1,...data,src_id:data.group_jid,allowed:false,is_admin:false,auto_message:false});return send({id:groups.length},201);}
    if(endpoint.startsWith("/groups/")){Object.assign(groups.find(item=>item.id===Number(endpoint.split("/")[2])),data);return send(data);}
    if(endpoint==="/models"&&method==="GET")return send(models);
    if(endpoint==="/models"){models.push({id:models.length+1,...data});return send({id:models.length},201);}
    if(endpoint==="/agents")return send(agents);
    if(endpoint==="/mcps"&&method==="GET")return send(mcps);
    if(endpoint==="/mcps"){mcps.push({id:mcps.length+1,...data,tools:[],checked_at:null,last_error:null});return send({id:mcps.length,needs_sync:true},201);}
    if(/^\/mcps\/\d+\/sync$/.test(endpoint)){const item=mcps.find(item=>item.id===Number(endpoint.split("/")[2]));item.tools=[{name:"search_documents",description:"Busca",inputSchema:{type:"object",properties:{query:{type:"string"}},required:["query"]}}];item.checked_at=new Date().toISOString();return send({tools:item.tools,checked_at:item.checked_at});}
    if(endpoint.startsWith("/mcps/")){const item=mcps.find(item=>item.id===Number(endpoint.split("/")[2]));return send(item);}
    if(endpoint.startsWith("/agents/")){const item=agents.find(item=>item.id===Number(endpoint.split("/")[2]));Object.assign(item,data,{model_managed:true});if(data.model_id){const model=models.find(model=>model.id===data.model_id);item.model_name=model.name;item.openrouter_id=model.openrouter_id;}return send({id:item.id});}
    if(endpoint==="/blacklist"&&method==="GET")return send(blocked);
    if(endpoint==="/blacklist"){blocked=[{...users.find(item=>item.id===data.user_id),...data}];return send(data);}
    if(endpoint.startsWith("/blacklist/")){blocked=[];return send({ok:true});}
    if(endpoint==="/commands"&&method==="GET")return send({catalog,rules});
    if(endpoint==="/commands"){rules.push({id:rules.length+1,...data,user_name:users.find(item=>item.id===data.user_id)?.name,group_name:groups.find(item=>item.id===data.group_id)?.name});return send({id:rules.length},201);}
    if(endpoint.startsWith("/commands/")){rules=rules.filter(item=>item.id!==Number(endpoint.split("/")[2]));return send({ok:true});}
    if(endpoint==="/overrides"&&method==="GET")return send(overrides);
    if(endpoint==="/overrides"){overrides.push({id:overrides.length+1,...data,agent_name:agents.find(item=>item.id===data.agent_id).name,openrouter_id:models.find(item=>item.id===data.model_id).openrouter_id,user_name:users.find(item=>item.id===data.user_id)?.name,group_name:groups.find(item=>item.id===data.group_id)?.name});return send({id:overrides.length});}
    if(endpoint.startsWith("/overrides/")){overrides=[];return send({ok:true});}
    throw new Error(`Unexpected fixture request: ${method} ${endpoint}`);
  });
  const base=process.env.ADMIN_PREVIEW_URL||"http://127.0.0.1:9012/admin";
  try {
    await page.goto(base);await page.locator("#login-screen").waitFor({state:"visible"});
    await page.screenshot({path:path.join(output,"login.png"),fullPage:true});
    await page.locator("#password").fill("wrong");await page.getByRole("button",{name:"Entrar no painel"}).click();await page.getByText("Senha incorreta.").waitFor();
    await page.locator("#password").fill("fixture-password");await page.getByRole("button",{name:"Entrar no painel"}).click();await page.getByText("Não conectado",{exact:true}).waitFor();
    await page.screenshot({path:path.join(output,"connection.png"),fullPage:true});
    await page.getByRole("button",{name:"Conectar com número de telefone"}).click();await page.locator("#phone-number").fill("55 11 99999-9999");assert.equal(await page.getByRole("button",{name:"Gerar código"}).isEnabled(),true);
    await page.getByRole("button",{name:"Iniciar conexão"}).click();await page.getByText("Aguardando conexão",{exact:true}).waitFor();assert.equal(await page.locator("#phone-number").inputValue(),"55 11 99999-9999");await page.getByRole("button",{name:"Gerar código"}).click();await page.getByText("ABCD-1234",{exact:true}).waitFor();
    await page.getByRole("button",{name:"Usar QR code"}).click();await page.getByRole("img",{name:"QR code para conectar o WhatsApp"}).waitFor();
    await page.locator('[data-page="testing"]').click();await page.locator("#test-number").fill("5511999999999");await page.locator("#test-mode").check();await page.getByRole("button",{name:"Salvar configuração",exact:true}).click();await page.getByText("Configuração de teste salva.",{exact:true}).waitFor();assert.equal(testSettings.test_mode,true);
    await page.screenshot({path:path.join(output,"testing.png"),fullPage:true});
    await page.locator('[data-page="sync"]').click();await page.locator("#sync-history").check();assert.equal(await page.locator("#sync-period option").count(),8);await page.locator("#sync-period").selectOption("custom");await page.locator("#sync-start").fill("2026-01-01T10:00");await page.locator("#sync-end").fill("2026-02-01T10:00");await page.getByRole("button",{name:"Iniciar sincronização",exact:true}).click();await page.getByText("Sincronização iniciada.",{exact:true}).waitFor();assert.equal(syncPayload.period,"custom");assert.ok(syncPayload.start.endsWith("Z"));assert.equal(syncPayload.contacts,true);assert.equal(syncPayload.history,true);
    await page.screenshot({path:path.join(output,"sync.png"),fullPage:true});
    await page.locator("summary").filter({hasText:/^Data/}).click();
    await page.locator('[data-page="attachments"]').click();await page.locator(".attachment-preview").waitFor();
    await page.locator("#data-group").selectOption("1");await page.locator("#data-user").selectOption("1");
    await page.locator("#data-period").selectOption("custom");await page.locator("#data-start").fill("2026-10-01T00:00");await page.locator("#data-end").fill("2026-10-20T00:00");await page.locator("#data-query").fill("viagem");
    const filterRequest=page.waitForRequest(req=>req.url().includes("/data/attachments?")&&req.url().includes("q=viagem"));
    await page.getByRole("button",{name:"Aplicar filtros"}).click();const filteredUrl=new URL((await filterRequest).url());assert.equal(filteredUrl.searchParams.get("group_id"),"1");assert.equal(filteredUrl.searchParams.get("user_id"),"1");assert.ok(filteredUrl.searchParams.get("start").endsWith("Z"));
    await page.locator(".attachment-preview").waitFor();await page.screenshot({path:path.join(output,"attachments.png"),fullPage:true});
    await page.getByRole("button",{name:"Limpar",exact:true}).click();await page.locator(".attachment-preview").waitFor();assert.equal(await page.locator("#data-query").inputValue(),"");
    await page.locator('[data-page="messages"]').click();await page.locator(".message-content").first().waitFor();assert.equal(await page.locator(".data-item script").count(),0);
    await page.screenshot({path:path.join(output,"messages.png"),fullPage:true});await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector("#sidebar").getBoundingClientRect().right<=0);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);await page.screenshot({path:path.join(output,"mobile-messages.png"),fullPage:true});await page.setViewportSize({width:1440,height:1000});
    await page.locator('[data-page="bans"]').click();await page.getByRole('button',{name:'Encerrar ban',exact:true}).waitFor();
    assert.equal(await page.locator('#ban-results script').count(),0);
    await page.screenshot({path:path.join(output,'bans.png'),fullPage:true});
    await page.locator('#ban-view').selectOption('voting');await page.getByRole('button',{name:'Cancelar votação',exact:true}).click();await page.locator('#save-editor').click();await page.locator('#editor').waitFor({state:'hidden'});assert.equal(bans[1].status,'cancelled');
    await page.locator('#ban-view').selectOption('active');await page.getByRole('button',{name:'Encerrar ban',exact:true}).click();await page.locator('#save-editor').click();await page.locator('#editor').waitFor({state:'hidden'});assert.equal(bans[0].status,'revoked');
    await page.locator('#ban-view').selectOption('history');await page.getByText('Encerrado no painel',{exact:true}).waitFor();await page.locator('#ban-search').fill('Lucas');await page.waitForFunction(()=>document.querySelectorAll('#ban-results tbody tr').length===1);
    await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('#sidebar').getBoundingClientRect().right<=0);await page.screenshot({path:path.join(output,'mobile-bans.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);await page.setViewportSize({width:1440,height:1000});
    await page.locator('[data-page="users"]').click();await page.getByText("Ana Costa",{exact:true}).waitFor();
    await page.screenshot({path:path.join(output,"users.png"),fullPage:true});
    await page.locator('[data-action="edit-access"][data-id="2"]').click();await page.locator("#allowed").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(users[1].allowed,true);
    await page.locator('[data-page="groups"]').click();await page.getByText("Equipe de produto",{exact:true}).waitFor();await page.locator('[data-action="edit-access"][data-id="2"]').click();await page.locator("#allowed").check();await page.locator("#auto_message").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(groups[1].auto_message,true);
    await page.locator('[data-page="agents"]').click();await page.getByText("Conversas privadas",{exact:true}).waitFor();await page.locator('[data-action="edit-agent"][data-id="1"]').click();await page.locator("#model_id").selectOption("2");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(agents[0].model_id,2);
    await page.screenshot({path:path.join(output,"agents.png"),fullPage:true});
    await page.locator('[data-page="mcps"]').click();await page.getByRole("button",{name:"Adicionar MCP"}).click();
    await page.locator("#name").fill("Documentos internos");await page.locator("#description").fill("Consultar os documentos da equipe quando o usuário perguntar por procedimentos.");await page.locator("#url").fill("http://documents:8000/mcp");
    await page.locator("#headers").fill('{"Authorization":"Bearer fixture-only"}');await page.locator("#params").fill('{"workspace":"equipe"}');await page.locator("#fixed_arguments").fill('{"search_documents":{"tenant_id":"fixed"}}');
    await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(mcps[0].headers.Authorization,"Bearer fixture-only");assert.equal(mcps[0].params.workspace,"equipe");assert.equal(mcps[0].fixed_arguments.search_documents.tenant_id,"fixed");
    await page.getByRole("button",{name:"Testar",exact:true}).click();await page.getByText("Pronto",{exact:true}).waitFor();await page.screenshot({path:path.join(output,"mcps.png"),fullPage:true});
    await page.locator('[data-page="agents"]').click();await page.getByText("Conversas privadas",{exact:true}).waitFor();
    await page.getByRole("button",{name:"Definir por conversa"}).click();await page.locator("#target_id").selectOption("2");await page.locator("#model_id").selectOption("1");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(overrides[0].user_id,2);
    await page.locator('[data-page="blacklist"]').click();await page.getByRole("button",{name:"Bloquear usuário"}).click();await page.locator("#user_id").selectOption("2");await page.locator("#all_features").uncheck();await page.locator("#feature-image").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.deepEqual(blocked[0].features,["image"]);
    await page.locator('[data-page="commands"]').click();await page.getByRole("button",{name:"Nova restrição"}).click();await page.locator("#command").selectOption("sticker");await page.locator("#scope").selectOption("both");await page.locator("#user_id").selectOption("1");await page.locator("#group_id").selectOption("1");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(rules[0].user_id,1);assert.equal(rules[0].group_id,1);
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,"mobile-commands.png"),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,"Mobile viewport should not overflow");
    await page.getByRole("button",{name:"Abrir navegação"}).click();await page.locator('[data-page="connection"]').click();await page.getByRole("button",{name:"Conectar com número de telefone"}).waitFor();
    await page.screenshot({path:path.join(output,"mobile-connection.png"),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log("Browser QA passed: attachment/message galleries, combined data filters, escaped content, mobile layout, login, QR/code, access and settings.");
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
