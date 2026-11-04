import json
from typing import get_args

import pytest
from pydantic import ValidationError

from jobpipe.llm.schema import (
    EXTRACTION_JSON_SCHEMA,
    ClearanceValue,
    EmploymentValue,
    ExtractionPayload,
    PeriodValue,
    SalaryField,
    SeniorityValue,
    WorkModeValue,
    WorkRightsValue,
    not_stated_payload,
    strip_keys,
)


def test_json_schema_matches_the_pydantic_models():
    props = EXTRACTION_JSON_SCHEMA["properties"]
    assert set(props) == set(ExtractionPayload.model_fields)
    assert set(EXTRACTION_JSON_SCHEMA["required"]) == set(ExtractionPayload.model_fields)
    for field, values in [("work_rights", WorkRightsValue), ("security_clearance", ClearanceValue),
                          ("work_mode", WorkModeValue), ("seniority", SeniorityValue),
                          ("employment_type", EmploymentValue)]:
        assert props[field]["properties"]["value"]["enum"] == list(get_args(values))
    assert set(props["salary"]["properties"]) == set(SalaryField.model_fields)
    assert props["salary"]["properties"]["period"]["enum"] == list(get_args(PeriodValue))


def test_payload_round_trips_through_json():
    payload = not_stated_payload()
    assert ExtractionPayload.model_validate_json(payload.model_dump_json()) == payload


def test_payload_rejects_unknown_values_and_extra_keys():
    data = not_stated_payload().model_dump()
    data["work_rights"]["value"] = "probably_fine"
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate(data)
    data = not_stated_payload().model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate(data)


def test_strip_keys_removes_additional_properties_everywhere():
    stripped = strip_keys(EXTRACTION_JSON_SCHEMA, {"additionalProperties"})
    assert "additionalProperties" not in json.dumps(stripped)
    assert stripped["properties"]["salary"]["required"] == EXTRACTION_JSON_SCHEMA["properties"]["salary"]["required"]
    assert "additionalProperties" in json.dumps(EXTRACTION_JSON_SCHEMA)
