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

from app.ai import AGENT_TOOLS, _agent_tool_data


def test_agents_have_least_privilege_read_tools():
    assert "get_finance_summary" in AGENT_TOOLS["finance"]
    assert set(AGENT_TOOLS["finance"]) == {"get_finance_summary", "get_marketplace_cost_catalog", "get_data_quality_summary"}
    assert "get_inventory_summary" in AGENT_TOOLS["buyer"]
    assert "get_marketplace_cost_catalog" in AGENT_TOOLS["buyer"]
    assert "get_data_quality_summary" in AGENT_TOOLS["buyer"]
    assert "get_finance_summary" not in AGENT_TOOLS["buyer"]
    assert "get_channel_summary" in AGENT_TOOLS["marketing"]
    assert "get_inventory_summary" not in AGENT_TOOLS["marketing"]
    assert set(AGENT_TOOLS["content"]) == {"get_product_summary", "get_data_quality_summary"}
    assert set(AGENT_TOOLS["rick"]) == {
        "get_executive_summary", "get_finance_summary", "get_inventory_summary",
        "get_channel_summary", "get_product_summary", "get_marketplace_cost_catalog", "get_data_quality_summary"
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
    assert set(AGENT_ACTIONS["buyer"]) == {"post_purchase", "post_adjustment", "create_product", "set_marketplace_cost"}
    assert "prepare_product_card_publish" in AGENT_ACTIONS["marketing"]
    assert "post_cash" not in AGENT_ACTIONS["marketing"]
    assert set(AGENT_ACTIONS["content"]) == {"create_product_card", "validate_product_card"}
    assert AGENT_ACTIONS["analyst"] == ()
    assert _action_tools("analyst") == []
    assert len(_action_tools("finance")) == 2
