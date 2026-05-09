from __future__ import annotations

import pytest

from openchronicle.rpa.schemas import (
    ActionStep,
    ActionTrace,
    DeviceInfo,
    ElementLocator,
    StepAssertion,
    StepResult,
    StepSnapshot,
)
from openchronicle.rpa.skill_builder import (
    build_skill_yaml_from_workflow,
    build_workflow_from_trace,
)
from openchronicle.rpa.skill_store import load_skill_yaml, load_workflow, save_skill


def _sample_trace() -> ActionTrace:
    return ActionTrace(
        session_id="phone_demo_20260427_001",
        goal="Search product in Taobao",
        provider="android_adb",
        device=DeviceInfo(provider="android_adb", platform="android"),
        steps=[
            ActionStep(
                step_id="step_001",
                provider="android_adb",
                action="tap",
                target=ElementLocator(
                    text="Taobao",
                    fallback_area=[300, 800, 360, 880],
                    fallback_xy=[326, 842],
                ),
                before=StepSnapshot(screenshot="screens/001_before.png"),
                after=StepSnapshot(screenshot="screens/001_after.png"),
                assertion=StepAssertion(type="text_exists", value="Search"),
                risk_level="L1",
                result=StepResult(ok=True, status="success"),
                params={"x": 326, "y": 842},
            ),
            ActionStep(
                step_id="step_002",
                provider="android_adb",
                action="input_text",
                target=ElementLocator(resource_id="search_box"),
                assertion=StepAssertion(type="text_exists", value="cat food"),
                risk_level="L1",
                result=StepResult(ok=True, status="success"),
                params={"value": "cat food"},
            ),
        ],
    )


def _multi_input_trace() -> ActionTrace:
    trace = _sample_trace()
    trace.steps.append(
        ActionStep(
            step_id="step_003",
            provider="android_adb",
            action="input_text",
            target=ElementLocator(resource_id="quantity_box"),
            assertion=StepAssertion(type="text_exists", value="2"),
            risk_level="L1",
            result=StepResult(ok=True, status="success"),
            params={"value": "2"},
        )
    )
    return trace


def _high_risk_trace() -> ActionTrace:
    trace = _sample_trace()
    trace.steps.append(
        ActionStep(
            step_id="step_003",
            provider="android_adb",
            action="clear_data",
            target=ElementLocator(resource_id="settings"),
            risk_level="L3",
            result=StepResult(ok=True, status="success"),
        )
    )
    return trace


def _simple_yaml_parse(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith(" ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key] = value.strip().strip('"')
    return parsed


def test_trace_can_generate_workflow() -> None:
    workflow = build_workflow_from_trace(_sample_trace())

    assert workflow["schema_version"] == "1.0"
    assert workflow["id"] == "search_product_in_taobao"
    assert workflow["provider"] == "android_adb"
    assert workflow["goal"] == "Search product in Taobao"
    assert workflow["source_trace"] == "phone_demo_20260427_001"
    assert workflow["created_at"]
    assert isinstance(workflow["inputs"], dict)
    assert len(workflow["steps"]) == 2
    assert workflow["steps"][0]["id"] == "step_001"
    assert workflow["steps"][0]["verify"] == {"type": "text_exists", "value": "Search", "message": ""}
    assert workflow["risk_level"] == "L1"


def test_input_text_is_parameterized() -> None:
    workflow = build_workflow_from_trace(_sample_trace())

    assert workflow["inputs"]["keyword"]["default"] == "cat food"
    assert workflow["steps"][1]["params"]["value"] == "{{keyword}}"
    assert workflow["steps"][1]["value"] == "{{keyword}}"


def test_multiple_input_text_parameter_names_do_not_conflict() -> None:
    workflow = build_workflow_from_trace(_multi_input_trace())

    assert list(workflow["inputs"]) == ["keyword", "input_1"]
    assert workflow["steps"][1]["params"]["value"] == "{{keyword}}"
    assert workflow["steps"][2]["params"]["value"] == "{{input_1}}"


def test_verify_value_is_templated_for_input_text() -> None:
    workflow = build_workflow_from_trace(_sample_trace())

    assert workflow["steps"][1]["verify"]["value"] == "{{keyword}}"


def test_l3_risk_promotes_workflow_risk_level() -> None:
    workflow = build_workflow_from_trace(_high_risk_trace())

    assert workflow["risk_level"] == "L3"


def test_fallback_area_is_preserved() -> None:
    workflow = build_workflow_from_trace(_sample_trace())

    target = workflow["steps"][0]["target"]
    assert target["text"] == "Taobao"
    assert target["fallback_area"] == [300, 800, 360, 880]
    assert target["fallback_xy"] == [326, 842]


def test_skill_yaml_can_generate() -> None:
    workflow = build_workflow_from_trace(_sample_trace())
    skill_yaml = build_skill_yaml_from_workflow(workflow)
    parsed = _simple_yaml_parse(skill_yaml)

    assert 'name: "search_product_in_taobao"' in skill_yaml
    assert 'version: "1.0"' in skill_yaml
    assert 'provider: "android_adb"' in skill_yaml
    assert 'risk_level: "L1"' in skill_yaml
    assert 'description: "Search product in Taobao"' in skill_yaml
    assert 'source_trace: "phone_demo_20260427_001"' in skill_yaml
    assert "keyword:" in skill_yaml
    assert 'action: "input_text"' in skill_yaml
    assert parsed["name"] == "search_product_in_taobao"
    assert parsed["version"] == "1.0"


def test_skill_files_can_save_and_read(ac_root) -> None:
    workflow = build_workflow_from_trace(_sample_trace())
    skill_yaml = build_skill_yaml_from_workflow(workflow)

    paths = save_skill(workflow["id"], workflow, skill_yaml)
    loaded_workflow = load_workflow(workflow["id"])
    loaded_yaml = load_skill_yaml(workflow["id"])

    assert paths["workflow"].endswith("workflow.json")
    assert paths["skill_yaml"].endswith("skill.yaml")
    assert loaded_workflow["id"] == workflow["id"]
    assert loaded_yaml == skill_yaml


def test_invalid_skill_name_raises(ac_root) -> None:
    workflow = build_workflow_from_trace(_sample_trace())

    for skill_name in ("../escape", "/absolute", "bad/name", "bad name", "C:\\escape"):
        with pytest.raises(ValueError):
            save_skill(skill_name, {**workflow, "id": skill_name})
