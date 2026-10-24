from app.schemas import AgentCreate

def test_raw_token_is_not_a_schema_field():
    body = AgentCreate(name="demo", adapter_type="synthetic", authorised=True)
    assert not hasattr(body, "api_key")
