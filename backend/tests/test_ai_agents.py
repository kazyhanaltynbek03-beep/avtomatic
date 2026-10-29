from app.ai import AI_AGENTS, agent_catalog


def test_ai_team_has_six_unique_agents():
    assert set(AI_AGENTS) == {"rick", "finance", "analyst", "buyer", "marketing", "content"}
    catalog = agent_catalog()
    assert len(catalog) == 6
    assert len({x["name"] for x in catalog}) == 6


def test_ai_agents_have_isolated_role_prompts():
    for key, agent in AI_AGENTS.items():
        assert agent["name"]
        assert agent["title"]
        assert agent["scope"]
        assert len(agent["prompt"]) > 60
    assert "финанс" in AI_AGENTS["finance"]["prompt"].lower()
    assert "остат" in AI_AGENTS["buyer"]["prompt"].lower()


def test_ai_team_matches_qor_skills_roles():
    assert [agent["name"] for agent in agent_catalog()] == [
        "Арман", "Данияр", "Тимур", "Ерлан", "Алия", "Аружан"
    ]


def test_claude_skill_configuration_is_atomic_and_role_scoped(monkeypatch):
    import json
    from app import ai

    monkeypatch.delenv("QOR_CLAUDE_SKILLS_JSON", raising=False)
    assert ai.claude_skills_status() == {"enabled": False, "configured": 0, "required": 11}

    configured = {
        key: {"skill_id": f"skill_{index}", "version": f"skver_{index}"}
        for index, key in enumerate(ai.CLAUDE_SKILL_KEYS)
    }
    monkeypatch.setenv("QOR_CLAUDE_SKILLS_JSON", json.dumps(configured))
    assert ai.claude_skills_status() == {"enabled": True, "configured": 11, "required": 11}
    assert len(ai._agent_skills("rick")) == 11
    assert len(ai._agent_skills("finance")) == 1
    assert len(ai._agent_skills("analyst")) == 5

    duplicate = {key: {"skill_id": "skill_same", "version": "latest"} for key in ai.CLAUDE_SKILL_KEYS}
    monkeypatch.setenv("QOR_CLAUDE_SKILLS_JSON", json.dumps(duplicate))
    assert ai.claude_skills_status() == {"enabled": False, "configured": 0, "required": 11}

    configured.pop("qor-dias-wildberries")
    monkeypatch.setenv("QOR_CLAUDE_SKILLS_JSON", json.dumps(configured))
    assert not ai.claude_skills_status()["enabled"]
    assert ai._agent_skills("rick") == []


def test_anthropic_messages_api_attaches_skills_and_keeps_runtime(monkeypatch):
    from app import ai

    captured = {}

    class Response:
        status_code = 200
        def json(self):
            return {"content": [{"type": "text", "text": "Готово"}],
                    "container": {"id": "container-1"}, "stop_reason": "end_turn"}

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, url, headers, json):
            captured.update(json)
            return Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai.httpx, "Client", Client)
    skill = {"type": "custom", "skill_id": "skill_demo", "version": "skver_demo"}
    result = ai.call_response(
        [{"role": "user", "content": "Отчёт"}], "инструкции",
        tools=[{"name": "get_finance_summary", "description": "report", "parameters": {"type": "object", "properties": {}}}],
        skill_config=[skill], container_id="container-previous",
    )
    assert captured["container"] == {"skills": [skill], "id": "container-previous"}
    assert any(tool.get("name") == "code_execution" and tool.get("type") == "code_execution_20250825" for tool in captured["tools"])
    assert result["container_id"] == "container-1"
    assert result["stop_reason"] == "end_turn"


def test_anthropic_raw_assistant_blocks_survive_tool_roundtrip():
    from app.ai import _anthropic_messages
    raw = [{"type": "server_tool_use", "id": "srv-1", "name": "bash_code_execution", "input": {"command": "true"}}]
    messages = _anthropic_messages([{"type": "anthropic_raw_assistant", "content": raw}])
    assert messages == [{"role": "assistant", "content": raw}]

from app.ai import AGENT_TOOLS, _agent_tool_data


def test_agents_have_least_privilege_read_tools():
    assert "get_finance_summary" in AGENT_TOOLS["finance"]
    assert set(AGENT_TOOLS["finance"]) == {"get_finance_summary", "get_marketplace_cost_catalog", "get_data_quality_summary"}
    assert "get_inventory_summary" in AGENT_TOOLS["buyer"]
    assert "get_marketplace_cost_catalog" in AGENT_TOOLS["buyer"]
    assert "get_data_quality_summary" in AGENT_TOOLS["buyer"]
    assert "get_finance_summary" not in AGENT_TOOLS["buyer"]
    assert {"get_marketplace_mapping_catalog", "get_return_inventory_summary"} <= set(AGENT_TOOLS["buyer"])
    assert "get_channel_summary" in AGENT_TOOLS["marketing"]
    assert "get_inventory_summary" not in AGENT_TOOLS["marketing"]
    assert set(AGENT_TOOLS["content"]) == {"get_product_summary", "get_data_quality_summary"}
    assert set(AGENT_TOOLS["rick"]) == {
        "get_executive_summary", "get_finance_summary", "get_inventory_summary",
        "get_channel_summary", "get_product_summary", "get_marketplace_mapping_catalog",
        "get_return_inventory_summary", "get_marketplace_cost_catalog", "get_data_quality_summary"
    }


def test_finance_tool_does_not_leak_full_snapshot():
    snap = {
        "start":"2026-10-01","end":"2026-10-31","currency":"KZT","money_unit":"tiyn","method":"FIFO",
        "revenue":100,"cogs":50,"gross_profit":50,"net_profit":30,"commission":5,"logistics":5,
        "advertising":5,"expenses":5,"cash":200,"cash_flow":20,"cash_opening":180,"cash_inflow":40,
        "cash_outflow":20,"cash_closing":200,"b2b_debt":10,"refunds_payable":0,"cash_by_category":[],
        "receivables":[],"stock_value":999,"stock":[],"stock_alerts":[],"slow_products":[],"channels":[],
        "channel_summary":[],"b2b":{},"products":[],"secret_unrelated":"must-not-leak"
    }
    data = _agent_tool_data(snap, "get_finance_summary")
    assert data["net_profit"] == 30
    assert "stock" not in data
    assert "secret_unrelated" not in data


def test_designer_uses_source_image_edit_flow():
    import inspect
    from app.ai import designer
    src=inspect.getsource(designer)
    assert "document_id" in src
    assert "/images/edits" in src
    assert "source of truth" in src
    assert 'max(1, min(int(payload.get("variants", 1)), 4))' in src

def test_content_can_use_verified_product_fields():
    import inspect
    from app.ai import content
    src=inspect.getsource(content)
    assert "product_id" in src
    assert "specifications" in src
    assert "Нужно уточнить" in src


def test_specialists_have_job_scoped_write_actions_only():
    from app.ai import AGENT_ACTIONS, _action_tools
    assert "post_expense" in AGENT_ACTIONS["finance"]
    assert "set_marketplace_cost" in AGENT_ACTIONS["finance"]
    assert "post_purchase" not in AGENT_ACTIONS["finance"]
    assert set(AGENT_ACTIONS["buyer"]) == {"post_purchase", "post_adjustment", "create_product", "set_marketplace_cost", "link_marketplace_listing", "set_product_min_stock", "set_return_inventory_status"}
    assert "prepare_product_card_publish" in AGENT_ACTIONS["marketing"]
    assert "post_cash" not in AGENT_ACTIONS["marketing"]
    assert set(AGENT_ACTIONS["content"]) == {"create_product_card", "validate_product_card"}
    assert AGENT_ACTIONS["analyst"] == ()
    assert _action_tools("analyst") == []
    assert len(_action_tools("finance")) == 2


def test_install_claude_skills_uploads_all_bundles_without_exposing_key(monkeypatch):
    from app import ai

    calls = {"get": 0, "post": []}

    class Response:
        is_error = False

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 180

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers, params):
            calls["get"] += 1
            assert headers["x-api-key"] == "test-key"
            assert params["source"] == "custom"
            return Response({"data": [], "next_page": None})

        def post(self, url, headers, data, files):
            calls["post"].append((data["display_name"], [item[1][0] for item in files]))
            index = len(calls["post"])
            return Response({"id": f"skill_{index}", "latest_version_id": f"skver_{index}"})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai.httpx, "Client", Client)
    result = ai.install_claude_skills()

    assert calls["get"] == 1
    assert len(calls["post"]) == 11
    assert len(result) == 11
    assert len({item["skill_id"] for item in result.values()}) == 11
    assert all(any(name.endswith("/SKILL.md") for name in paths) for _, paths in calls["post"])



def test_claude_connection_check_does_not_load_or_send_erp_data(monkeypatch):
    from app import ai

    sent = {}

    def fake_call_response(messages, instructions, *args, **kwargs):
        sent.update({"messages": messages, "instructions": instructions, "args": args, "kwargs": kwargs})
        return {"output": []}

    def forbidden_report(*args, **kwargs):
        raise AssertionError("connection check must not load ERP report")

    monkeypatch.setattr(ai, "require", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "call_response", fake_call_response)
    monkeypatch.setattr(ai, "report", forbidden_report)

    result = ai.assistant(object(), object(), {
        "agent": "rick",
        "question": "Техническая проверка соединения Claude. Ответь строго: CLAUDE_OK. Не анализируй ERP.",
        "history": [{"role": "assistant", "content": "confidential prior ERP context"}],
        "document_ids": [123],
    })

    assert result["answer"] == "CLAUDE_OK"
    assert result["tools_used"] == []
    assert result["period"] is None
    assert sent["messages"] == [{"role": "user", "content": "Reply exactly: CLAUDE_OK"}]
    assert not sent["args"] and not sent["kwargs"]
    assert "confidential" not in str(sent)
