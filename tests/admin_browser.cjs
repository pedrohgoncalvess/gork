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
  let blocked=[],rules=[],overrides=[];
  const catalog=[{id:"interaction",description:"Conversas"},{id:"image",description:"Imagens"},{id:"sticker",description:"Figurinhas"},{id:"audio",description:"Áudio"}];
  await page.route("**/admin/api/**",async route=>{
    const req=route.request(),url=new URL(req.url()),endpoint=url.pathname.slice("/admin/api".length),method=req.method();
    const data=req.postData()?JSON.parse(req.postData()):{};
    const send=(value,code=200)=>route.fulfill({status:code,contentType:"application/json",body:JSON.stringify(value)});
    if(endpoint==="/login"){if(data.password!=="fixture-password")return send({detail:"Senha incorreta."},401);loggedIn=true;return send({csrf_token:"fixture-csrf"});}
    if(!loggedIn)return send({detail:"Entre no painel para continuar."},401);
    if(endpoint==="/session")return send({csrf_token:"fixture-csrf"});
    if(endpoint==="/logout"){loggedIn=false;return send({ok:true});}
    if(method!=="GET")assert.equal(req.headers()["x-csrf-token"],"fixture-csrf");
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
    await page.getByRole("button",{name:"Iniciar conexão"}).click();await page.getByRole("img",{name:"QR code para conectar o WhatsApp"}).waitFor();
    await page.getByRole("button",{name:"Conectar com número de telefone"}).click();await page.locator("#phone-number").fill("55 11 99999-9999");await page.getByRole("button",{name:"Gerar código"}).click();await page.getByText("ABCD-1234",{exact:true}).waitFor();
    await page.locator('[data-page="users"]').click();await page.getByText("Ana Costa",{exact:true}).waitFor();
    await page.screenshot({path:path.join(output,"users.png"),fullPage:true});
    await page.locator('[data-action="edit-access"][data-id="2"]').click();await page.locator("#allowed").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(users[1].allowed,true);
    await page.locator('[data-page="groups"]').click();await page.getByText("Equipe de produto",{exact:true}).waitFor();await page.locator('[data-action="edit-access"][data-id="2"]').click();await page.locator("#allowed").check();await page.locator("#auto_message").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(groups[1].auto_message,true);
    await page.locator('[data-page="agents"]').click();await page.getByText("Conversas privadas",{exact:true}).waitFor();await page.locator('[data-action="edit-agent"][data-id="1"]').click();await page.locator("#model_id").selectOption("2");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(agents[0].model_id,2);
    await page.screenshot({path:path.join(output,"agents.png"),fullPage:true});
    await page.getByRole("button",{name:"Definir por conversa"}).click();await page.locator("#target_id").selectOption("2");await page.locator("#model_id").selectOption("1");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(overrides[0].user_id,2);
    await page.locator('[data-page="blacklist"]').click();await page.getByRole("button",{name:"Bloquear usuário"}).click();await page.locator("#user_id").selectOption("2");await page.locator("#all_features").uncheck();await page.locator("#feature-image").check();await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.deepEqual(blocked[0].features,["image"]);
    await page.locator('[data-page="commands"]').click();await page.getByRole("button",{name:"Nova restrição"}).click();await page.locator("#command").selectOption("sticker");await page.locator("#scope").selectOption("both");await page.locator("#user_id").selectOption("1");await page.locator("#group_id").selectOption("1");await page.locator("#save-editor").click();await page.locator("#editor").waitFor({state:"hidden"});assert.equal(rules[0].user_id,1);assert.equal(rules[0].group_id,1);
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,"mobile-commands.png"),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,"Mobile viewport should not overflow");
    await page.getByRole("button",{name:"Abrir navegação"}).click();await page.locator('[data-page="connection"]').click();await page.getByRole("button",{name:"Conectar com número de telefone"}).waitFor();
    await page.screenshot({path:path.join(output,"mobile-connection.png"),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log("Browser QA passed: login, QR/code, user/group whitelist, agent model, conversation override, scoped blacklist, scoped commands, mobile layout.");
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
