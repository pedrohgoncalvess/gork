import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
import httpx
from mcp.server.mcpserver import MCPServer, Context
from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
import uvicorn

from api.admin.mcp_routes import router, summary, save
from database.models.manager import McpServer
from external.mcp_client import call_tool, check_schema, connection_url, discover
from external.openrouter import _payload_for_log
from services.mcp_config import McpInput, decrypt_settings, encrypt_settings, fixed_merge, public_schema
from services.mcp_runtime import available_bindings, bindings_for, complete_with_mcp, invoke, result_text, scope_filter, tool_alias


SCHEMA={"type":"object","properties":{"query":{"type":"string"},"tenant_id":{"type":"string"}},"required":["query","tenant_id"],"additionalProperties":False}


def server(identifier=1, **changes):
    data=McpInput(name="Documentos",description="Pesquisar documentos internos",url="http://127.0.0.1:8000/mcp",headers={"Authorization":"Bearer test-secret"},params={"workspace":"test-workspace"},fixed_arguments={"search_documents":{"tenant_id":"fixed-tenant"}})
    values=dict(id=identifier,name=data.name,description=data.description,url=data.url,transport="streamable_http",enabled=True,settings_encrypted=encrypt_settings(data),tool_names=[],tools=[{"name":"search_documents","description":"Busca documentos","inputSchema":deepcopy(SCHEMA)}],timeout_seconds=10,user_id=None,group_id=None,last_error=None,deleted_at=None,checked_at=None)
    values.update(changes)
    return SimpleNamespace(**values)


def response(calls=None,content=None):
    return {"choices":[{"message":{"role":"assistant","content":content,"tool_calls":calls or []}}],"usage":{"prompt_tokens":10,"completion_tokens":5,"cost":0.01}}


def tool_call(alias,arguments,identifier="call-1"):
    return {"id":identifier,"type":"function","function":{"name":alias,"arguments":json.dumps(arguments)}}


class KeyMixin:
    def setUp(self):
        self.key=patch.dict(os.environ,{"MCP_ENCRYPTION_KEY":Fernet.generate_key().decode()})
        self.key.start()
        self.addCleanup(self.key.stop)


class McpConfigurationTests(KeyMixin,unittest.TestCase):
    def test_settings_are_encrypted_and_roundtrip_exact_fixed_values(self):
        data=McpInput(name="MCP",description="Consulta",url="http://localhost/mcp",headers={"Authorization":"Bearer protected-secret"},params={"tenant":"1234"},fixed_arguments={"lookup":{"limit":7,"token":" exact "}})
        encrypted=encrypt_settings(data)
        self.assertNotIn("protected-secret",encrypted)
        self.assertNotIn("tenant",encrypted)
        self.assertEqual(decrypt_settings(encrypted)["fixed_arguments"]["lookup"]["token"]," exact ")
        self.assertEqual(decrypt_settings(encrypted)["headers"],data.headers)

    def test_nested_fixed_values_cannot_be_overridden(self):
        arguments={"tenant":"evil","filters":{"tenant":"evil","query":"foo"},"limit":999}
        merged=fixed_merge(arguments,{"tenant":"fixed","filters":{"tenant":"fixed"},"limit":10})
        self.assertEqual(merged,{"tenant":"fixed","filters":{"tenant":"fixed","query":"foo"},"limit":10})
        self.assertEqual(arguments["tenant"],"evil")

    def test_public_schema_hides_fixed_fields_and_required_names(self):
        public=public_schema(SCHEMA,{"tenant_id":"fixed-secret"})
        self.assertEqual(public["required"],["query"])
        self.assertNotIn("tenant_id",public["properties"])
        self.assertNotIn("fixed-secret",json.dumps(public))
        self.assertIn("tenant_id",SCHEMA["properties"])

    def test_parameters_override_url_values_deterministically(self):
        self.assertEqual(connection_url("http://mcp/service?tenant=old&other=x",{"tenant":"new","enabled":True}),"http://mcp/service?tenant=new&other=x&enabled=true")

    def test_untrusted_schema_cannot_fetch_external_references(self):
        with self.assertRaises(ValueError):check_schema({"type":"object","$ref":"http://metadata.internal/schema"})

    def test_invalid_transport_headers_and_scope_are_rejected(self):
        for changes in ({"url":"file:///tmp/mcp"},{"url":"http://user:password@host/mcp"},{"transport":"stdio"},{"headers":{"Host":"elsewhere"}},{"headers":{"Authorization":"bad\r\nInjected: value"}},{"user_id":1,"group_id":2}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):McpInput(name="MCP",description="Consulta",url="http://localhost/mcp",**{k:v for k,v in changes.items() if k!="url"}) if "url" not in changes else McpInput(name="MCP",description="Consulta",**changes)

    def test_aliases_are_stable_and_distinguish_servers_and_tool_names(self):
        self.assertEqual(tool_alias(1,"Name.With/punctuation"),tool_alias(1,"Name.With/punctuation"))
        self.assertNotEqual(tool_alias(1,"search"),tool_alias(2,"search"))
        self.assertRegex(tool_alias(1,"Name.With/punctuation"),r"^mcp_1_[a-f0-9]+$")

    def test_scope_does_not_allow_private_mcp_to_leak_into_groups(self):
        sql=str(scope_filter(12,9).compile(dialect=postgresql.dialect(),compile_kwargs={"literal_binds":True}))
        self.assertIn("group_id = 9",sql)
        self.assertNotIn("user_id = 12",sql)

    def test_logs_omit_tool_results_and_arguments(self):
        logged=_payload_for_log({"messages":[{"role":"tool","content":"private result"},{"role":"assistant","tool_calls":[tool_call("mcp_1",{"token":"private argument"})]}]})
        self.assertNotIn("private result",json.dumps(logged))
        self.assertNotIn("private argument",json.dumps(logged))

    def test_admin_list_does_not_return_encrypted_or_plain_credentials(self):
        item=server()
        data=summary(item)
        self.assertNotIn("settings_encrypted",data)
        self.assertNotIn("headers",data)
        self.assertNotIn("test-secret",json.dumps(data))


class McpInvocationTests(KeyMixin,unittest.IsolatedAsyncioTestCase):
    async def test_real_native_loop_routes_to_two_mcps_and_records_each_model_turn(self):
        first,second=server(1),server(2)
        bindings=bindings_for([first,second])
        aliases=list(bindings)
        final=json.dumps({"reasoning":"done","queries":[],"actions":[{"action":"message","content":"Resultado combinado"}]})
        responses=[response([tool_call(aliases[0],{"query":"A","tenant_id":"evil"})]),response([tool_call(aliases[1],{"query":"B"},"call-2")]),response(content=final)]
        seen=[]
        async def completion(payload):seen.append(deepcopy(payload));return responses.pop(0)
        db=SimpleNamespace(scalar=AsyncMock(side_effect=[first,second]),execute=AsyncMock(),commit=AsyncMock())
        record=AsyncMock()
        result=CallToolResult(content=[TextContent(type="text",text="dados encontrados")])
        with (patch("services.mcp_runtime.available_bindings",new=AsyncMock(return_value=(bindings,[]))),patch("services.mcp_runtime.call_tool",new=AsyncMock(return_value=result)) as call):
            answer=await complete_with_mcp({"model":"provider/model","messages":[{"role":"system","content":"prompt"},{"role":"user","content":"consulta"}]},db,user_id=4,group_id=7,message_id=9,completion=completion,record_response=record)
        self.assertEqual(answer["choices"][0]["message"]["content"],final)
        self.assertEqual(call.await_count,2)
        self.assertEqual(call.await_args_list[0].args[3],{"query":"A","tenant_id":"fixed-tenant"})
        self.assertEqual(call.await_args_list[1].args[0].id,2)
        self.assertEqual(record.await_count,3)
        self.assertEqual(db.commit.await_count,2)
        self.assertEqual(seen[0]["tools"][0]["type"],"function")
        self.assertNotIn("test-secret",json.dumps(seen))
        self.assertNotIn("fixed-tenant",json.dumps(seen[0]))
        self.assertEqual(sum(item["role"]=="tool" for item in seen[-1]["messages"]),2)

    async def test_unknown_alias_does_not_contact_any_server(self):
        bindings=bindings_for([server()])
        completion=AsyncMock(side_effect=[response([tool_call("invented_tool",{"query":"A"})]),response(content="final")])
        with (patch("services.mcp_runtime.available_bindings",new=AsyncMock(return_value=(bindings,[]))),patch("services.mcp_runtime.invoke",new=AsyncMock()) as call):
            await complete_with_mcp({"messages":[]},Mock(),user_id=1,group_id=None,message_id=1,completion=completion,record_response=AsyncMock())
        call.assert_not_awaited()

    async def test_identical_calls_are_not_reexecuted(self):
        bindings=bindings_for([server()]);alias=next(iter(bindings))
        completion=AsyncMock(side_effect=[response([tool_call(alias,{"query":"A"}),tool_call(alias,{"query":"A"},"call-2")]),response(content="final")])
        with (patch("services.mcp_runtime.available_bindings",new=AsyncMock(return_value=(bindings,[]))),patch("services.mcp_runtime.invoke",new=AsyncMock(return_value="result")) as invoke_mock):
            await complete_with_mcp({"messages":[]},Mock(),user_id=1,group_id=None,message_id=1,completion=completion,record_response=AsyncMock())
        self.assertEqual(invoke_mock.await_count,1)

    async def test_disabled_server_is_rechecked_before_call(self):
        binding=next(iter(bindings_for([server()]).values()))
        db=SimpleNamespace(scalar=AsyncMock(return_value=None))
        with patch("services.mcp_runtime.call_tool",new=AsyncMock()) as call:
            result=await invoke(db,binding,{"query":"A"},user_id=1,group_id=None,message_id=1)
        call.assert_not_awaited()
        self.assertTrue(json.loads(result)["is_error"])

    async def test_invalid_arguments_do_not_invoke_provider(self):
        item=server();binding=next(iter(bindings_for([item]).values()))
        db=SimpleNamespace(scalar=AsyncMock(return_value=item),execute=AsyncMock(),commit=AsyncMock())
        with patch("services.mcp_runtime.call_tool",new=AsyncMock()) as call:
            result=await invoke(db,binding,{"query":99},user_id=1,group_id=None,message_id=1)
        call.assert_not_awaited();self.assertTrue(json.loads(result)["is_error"])

    async def test_blocked_mcp_feature_never_advertises_tools(self):
        result=Mock();result.scalars.return_value.all.return_value=[server()]
        db=SimpleNamespace(execute=AsyncMock(return_value=result))
        with patch("services.black_list.is_feature_blocked",new=AsyncMock(return_value=True)):
            bindings,unavailable=await available_bindings(db,1,None)
        self.assertEqual(bindings,{})

    async def test_no_mcp_keeps_response_contract_and_offers_local_knowledge(self):
        payload={"messages":[{"role":"user","content":"olá"}],"response_format":{"type":"json_object"}}
        completion=AsyncMock(return_value=response(content="final"))
        with patch("services.mcp_runtime.available_bindings",new=AsyncMock(return_value=({},[]))):
            await complete_with_mcp(payload,Mock(),user_id=1,group_id=None,message_id=1,completion=completion,record_response=AsyncMock())
        request=completion.await_args.args[0]
        self.assertEqual(request["response_format"],payload["response_format"])
        self.assertEqual(request["messages"][0],payload["messages"][0])
        self.assertEqual([tool["function"]["name"] for tool in request["tools"]],["consult_gork_knowledge"])
        self.assertNotIn("tools",payload)

    async def test_tool_loop_is_bounded_even_when_model_ignores_stop(self):
        bindings=bindings_for([server()]);alias=next(iter(bindings))
        completion=AsyncMock(side_effect=lambda payload:response([tool_call(alias,{"query":"A"})]))
        with (patch("services.mcp_runtime.available_bindings",new=AsyncMock(return_value=(bindings,[]))),patch("services.mcp_runtime.invoke",new=AsyncMock(return_value="result"))):
            result=await complete_with_mcp({"messages":[]},Mock(),user_id=1,group_id=None,message_id=1,completion=completion,record_response=AsyncMock())
        self.assertEqual(completion.await_count,7)
        self.assertIn("Não consegui concluir",json.loads(result["choices"][0]["message"]["content"])["actions"][0]["content"])

    async def test_mcp_api_requires_admin(self):
        app=FastAPI();app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            self.assertEqual((await client.get("/admin/api/mcps")).status_code,401)


@asynccontextmanager
async def serve(app):
    sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    instance=uvicorn.Server(uvicorn.Config(app,log_level="error",lifespan="on"))
    task=asyncio.create_task(instance.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not instance.started:
                if task.done():await task
                await asyncio.sleep(.01)
        yield port
    finally:
        instance.should_exit=True
        await asyncio.wait_for(task,10)
        sock.close()


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_sdk_over_real_http_and_legacy_sse(self):
        for transport in ("streamable_http","sse"):
            with self.subTest(transport=transport):
                mcp=MCPServer("gork-test",log_level="ERROR")
                calls=[];requests=[]
                @mcp.tool()
                def search_documents(tenant_id:str,query:str)->dict:
                    calls.append((tenant_id,query));return {"found":query,"tenant":tenant_id}
                app=mcp.streamable_http_app(json_response=True,stateless_http=True) if transport=="streamable_http" else mcp.sse_app()
                async def wrapped(scope,receive,send):
                    if scope["type"]=="http":requests.append((dict(scope["headers"]),scope["query_string"]))
                    await app(scope,receive,send)
                async with serve(wrapped) as port:
                    item=SimpleNamespace(url=f"http://127.0.0.1:{port}/"+("mcp" if transport=="streamable_http" else "sse"),timeout_seconds=10,transport=transport)
                    settings={"headers":{"Authorization":"Bearer fixture-key"},"params":{"workspace":"fixture"}}
                    tools=await discover(item,settings)
                    self.assertEqual(tools[0]["name"],"search_documents")
                    self.assertEqual(calls,[],"Discovery must not invoke business tools")
                    result=await call_tool(item,settings,"search_documents",{"tenant_id":"fixed","query":"teste"})
                self.assertFalse(result.is_error)
                self.assertEqual(calls,[("fixed","teste")])
                self.assertTrue(requests)
                self.assertTrue(all(headers.get(b"authorization")==b"Bearer fixture-key" for headers,_ in requests))
                self.assertTrue(all(b"workspace=fixture" in query for _,query in requests))


if __name__=="__main__":unittest.main()
