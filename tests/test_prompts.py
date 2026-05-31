# tests/test_prompts.py
"""Tests for the get_prompt() resolver."""
import pytest

from linkedin.prompts import get_prompt


@pytest.mark.django_db
def test_get_prompt_returns_db_row_when_present():
    from linkedin.models import PromptTemplate

    pt = PromptTemplate.objects.get(key="qualification")
    result = get_prompt("qualification")
    assert result == pt.body
    assert len(result) > 50  # non-trivial body from data migration


@pytest.mark.django_db
def test_get_prompt_falls_back_to_j2_when_db_row_missing():
    from linkedin.models import PromptTemplate

    PromptTemplate.objects.filter(key="qualification").delete()
    result = get_prompt("qualification")
    # Fallback loads qualify_lead.j2 — contains known marker text
    assert "{{ product_docs }}" in result
    assert "{{ profile_text }}" in result


@pytest.mark.django_db
def test_get_prompt_falls_back_to_inline_for_profile_fact_extraction():
    from linkedin.models import PromptTemplate

    PromptTemplate.objects.filter(key="profile_fact_extraction").delete()
    result = get_prompt("profile_fact_extraction")
    assert "facts" in result.lower()
    assert len(result) > 100


@pytest.mark.django_db
def test_get_prompt_falls_back_to_inline_for_chat_fact_reconciliation():
    from linkedin.models import PromptTemplate

    PromptTemplate.objects.filter(key="chat_fact_reconciliation").delete()
    result = get_prompt("chat_fact_reconciliation")
    assert "ADD" in result
    assert "DELETE" in result
