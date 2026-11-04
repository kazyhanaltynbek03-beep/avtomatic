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
    assert len(ai._agent_skills("rick")) == 1
    assert len(ai._agent_skills("rick", "Сколько заработал за прошлый месяц?")) == 2
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
    monkeypatch.setattr(ai, "key", lambda: "test-key")
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


def test_anthropic_tool_history_is_bounded_for_provider_token_limits():
    import json
    from app.ai import _anthropic_messages

    rows = [{"sku": f"SKU-{index}", "name": "Товар" * 1000} for index in range(120)]
    messages = _anthropic_messages([{
        "type": "function_call_output",
        "call_id": "call-1",
        "output": json.dumps({"total": 120, "items": rows}, ensure_ascii=False),
    }])

    tool_result = messages[0]["content"][0]["content"]
    bounded = json.loads(tool_result)
    assert len(tool_result) <= 14000
    assert bounded["total"] == 120
    assert bounded["_ai_context_truncated"] is True
    assert len(bounded["items"]) < 120


def test_anthropic_rate_limit_has_clear_retry_message(monkeypatch):
    from fastapi import HTTPException
    from app import ai

    class Response:
        status_code = 429

        def json(self):
            return {"error": {"type": "rate_limit_error", "message": "too many input tokens"}}

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai, "key", lambda: "test-key")
    monkeypatch.setattr(ai.httpx, "Client", Client)
    try:
        ai.call_response([{"role": "user", "content": "Сколько выручка?"}], "инструкции")
    except HTTPException as error:
        assert error.status_code == 503
        assert "повторите запрос через минуту" in error.detail
    else:
        raise AssertionError("Claude rate limits should be returned as a clear retryable error")

from app.ai import AGENT_TOOLS, _agent_tool_data


def test_agents_have_least_privilege_read_tools():
    assert "get_finance_summary" in AGENT_TOOLS["finance"]
    assert set(AGENT_TOOLS["finance"]) == {"get_finance_summary", "get_marketplace_cost_catalog", "get_data_quality_summary", "query_marketplace_api_data"}
    assert "get_inventory_summary" in AGENT_TOOLS["buyer"]
    assert "get_marketplace_cost_catalog" in AGENT_TOOLS["buyer"]
    assert "get_data_quality_summary" in AGENT_TOOLS["buyer"]
    assert "get_finance_summary" not in AGENT_TOOLS["buyer"]
    assert {"get_marketplace_mapping_catalog", "get_return_inventory_summary"} <= set(AGENT_TOOLS["buyer"])
    assert "get_channel_summary" in AGENT_TOOLS["marketing"]
    assert "get_inventory_summary" not in AGENT_TOOLS["marketing"]
    assert set(AGENT_TOOLS["content"]) == {
        "get_product_summary", "get_data_quality_summary", "query_marketplace_api_data"
    }
    assert set(AGENT_TOOLS["rick"]) == {
        "get_executive_summary", "get_finance_summary", "get_inventory_summary",
        "get_channel_summary", "get_product_summary", "get_marketplace_mapping_catalog",
        "get_return_inventory_summary", "get_marketplace_cost_catalog", "get_data_quality_summary",
        "query_marketplace_api_data"
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


def test_designer_is_disabled_without_an_image_provider():
    import inspect
    from app.ai import designer
    src = inspect.getsource(designer)
    assert "HTTPException(409" in src
    assert "Claude API" in src
    assert "отключены" in src

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
    class FakeSession:
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    def fake_call_response(messages, instructions, *args, **kwargs):
        assert db.rolled_back, "DB transaction must be released before waiting on Claude"
        sent.update({"messages": messages, "instructions": instructions, "args": args, "kwargs": kwargs})
        return {"output": []}

    def forbidden_report(*args, **kwargs):
        raise AssertionError("connection check must not load ERP report")

    monkeypatch.setattr(ai, "require", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "call_response", fake_call_response)
    monkeypatch.setattr(ai, "report", forbidden_report)

    db = FakeSession()
    result = ai.assistant(db, object(), {
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



def test_assistant_recovers_when_claude_tool_turn_has_no_final_text(monkeypatch):
    from app import ai

    monkeypatch.setattr(ai, "require", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "report", lambda *args, **kwargs: {
        "start": "2026-10-01", "end": "2026-10-29", "currency": "KZT",
        "money_unit": "tiyn", "method": "FIFO", "profit_complete": True,
        "pending_cogs_sales": 0, "incomplete_reason": None, "revenue": 12345,
        "gross_profit": 10000, "net_profit": 9000, "margin": 0.7, "units": 2,
        "returns": 0, "advertising": 0, "expenses": 0, "cash": 9000,
        "stock_value": 0, "b2b_debt": 0,
    })
    monkeypatch.setattr(ai, "_cached_executive_snapshot", lambda *args, **kwargs: {
        "start": "2026-10-01", "end": "2026-10-29", "currency": "KZT",
        "money_unit": "tiyn", "method": "FIFO", "profit_complete": True,
        "pending_cogs_sales": 0, "incomplete_reason": None, "revenue": 12345,
        "gross_profit": 10000, "net_profit": 9000, "margin": 0.7, "units": 2,
        "returns": 0, "advertising": 0, "expenses": 0, "cash": 9000,
        "stock_value": 0, "b2b_debt": 0,
    })
    monkeypatch.setattr(ai, "_agent_skills", lambda _agent, _question="": [])

    calls = []

    def fake_call_response(messages, instructions, tools=None, tool_choice=None, **kwargs):
        calls.append({"messages": messages, "instructions": instructions, "tools": tools})
        if len(calls) == 1:
            return {"output": [{"type": "function_call", "name": "get_executive_summary",
                                "arguments": "{}", "call_id": "call-1"}],
                    "raw_content": [], "stop_reason": "tool_use"}
        if len(calls) == 2:
            return {"output": [], "raw_content": [], "stop_reason": "end_turn"}
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Выручка: 123,45 KZT."}]}],
            "raw_content": [{"type": "text", "text": "Выручка: 123,45 KZT."}],
            "stop_reason": "end_turn"}

    monkeypatch.setattr(ai, "call_response", fake_call_response)
    result = ai.assistant(object(), object(), {
        "agent": "rick", "question": "Сколько выручка?", "start": "2026-10-01",
        "end": "2026-10-29", "history": [{"role": "user", "content": "Сколько выручка?"}],
    })

    assert result["answer"] == "Выручка: 123,45 KZT."
    assert result["tools_used"] == ["get_executive_summary"]
    assert calls[0]["tools"] and calls[2]["tools"] is None
    assert "12345" in calls[2]["messages"][0]["content"]



def test_ceo_attaches_only_relevant_claude_skills():
    from app.ai import _agent_skill_keys_for_question

    assert _agent_skill_keys_for_question("rick", "Сколько заработал за прошлый месяц?") == (
        "qor-arman-ceo", "qor-daniyar-finance"
    )
    assert _agent_skill_keys_for_question("rick", "Kaspi и Wildberries") == (
        "qor-arman-ceo", "qor-miras-kaspi", "qor-dias-wildberries"
    )
    broad = _agent_skill_keys_for_question(
        "rick", "Kaspi Wildberries Ozon прибыль товар склад карточка рынок"
    )
    assert len(broad) <= 3



def test_ai_executive_snapshot_uses_warm_cache_without_full_report(monkeypatch):
    from types import SimpleNamespace
    from app import ai

    cached = {"revenue": 123, "start": "2026-10-01", "end": "2026-10-31"}

    class DB:
        def scalar(self, query):
            return None

    monkeypatch.setattr(ai.report_cache, "get", lambda *args: cached)
    monkeypatch.setattr(ai, "report", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full report should not run")))
    result = ai._cached_executive_snapshot(
        DB(), SimpleNamespace(role="Owner"), "2026-10-01", "2026-10-31"
    )
    assert result is not cached
    assert result["revenue"] == cached["revenue"]
    assert result["start"] == cached["start"]
    assert result["end"] == cached["end"]
    assert result["currency"] == "KZT"


def test_ai_executive_snapshot_uses_fast_headline_on_cache_miss(monkeypatch):
    from types import SimpleNamespace
    from app import ai

    expected = {
        "revenue": 456, "gross_profit": 200, "net_profit": 150, "margin": 32.89,
        "units": 3, "returns": 10, "advertising": 0, "expenses": 5,
        "cash": 150, "stock_value": 90, "b2b_debt": 0,
        "profit_complete": True, "pending_cogs_sales": 0,
    }
    captured = {}

    class DB:
        def scalar(self, query):
            return None

    monkeypatch.setattr(ai.report_cache, "get_ai_snapshot", lambda *args: None)
    stored = {}
    monkeypatch.setattr(ai.report_cache, "store_ai_snapshot", lambda *args: stored.update(payload=args[4]))
    monkeypatch.setattr(ai.report_cache, "get", lambda *args: None)
    monkeypatch.setattr(ai.report_cache, "get_pending_source_days", lambda *args, **kwargs: ())

    def headline(db, user, start, end, company_id, active_only, pending_source_days=None):
        captured["active_only"] = active_only
        captured["pending_source_days"] = pending_source_days
        return expected

    monkeypatch.setattr(ai, "report_headline", headline)
    result = ai._cached_executive_snapshot(
        DB(), SimpleNamespace(role="Owner"), "2026-10-01", "2026-10-31"
    )
    assert result["revenue"] == expected["revenue"]
    assert result["start"] == "2026-10-01"
    assert result["end"] == "2026-10-31"
    assert result["currency"] == "KZT"
    assert result["money_unit"] == "tiyn"
    assert ai._agent_tool_data(result, "get_executive_summary")["revenue"] == 456
    assert captured["active_only"] is False
    assert captured["pending_source_days"] == ()
    assert stored["payload"]["start"] == "2026-10-01"


def test_ai_executive_snapshot_cache_hit_avoids_recomputing_report(monkeypatch):
    from types import SimpleNamespace
    from app import ai

    cached = {
        "start": "2026-10-01", "end": "2026-10-31", "currency": "KZT",
        "money_unit": "tiyn", "revenue": 456,
    }
    monkeypatch.setattr(ai.report_cache, "get_ai_snapshot", lambda *args: cached)
    monkeypatch.setattr(ai, "report", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("report should not run")))
    monkeypatch.setattr(ai, "report_headline", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("headline should not run")))

    result = ai._cached_executive_snapshot(
        object(), SimpleNamespace(role="Owner"), "2026-10-01", "2026-10-31"
    )
    assert result is cached
