import pytest

from dendroflow.configuration.workbook.matching import (
    WorkbookMatchError,
    match_workbook,
)
from dendroflow.configuration.workbook.schema import RESOURCE_SHEETS

from .test_configuration_workbook_validation import parsed_export, remove_rows
from .test_configuration_workbook_validation import source as _source


@pytest.fixture
def source():
    return _source.__wrapped__()

@pytest.mark.parametrize('selection',[None,[2]])
def test_unchanged_export_matches(source, selection):
    parsed=parsed_export(source,selection); result=match_workbook(parsed,source)
    assert sum(len(v) for v in result.rows.values()) > 0
    for spec in RESOURCE_SHEETS:
        for row in result.rows[spec.name]: assert row.current is not None

def test_missing_id_blocked(source):
    parsed=parsed_export(source); parsed.frames['sites'].at[0,'site_id']=999
    with pytest.raises(WorkbookMatchError, match='does not exist'): match_workbook(parsed,source)

def test_scope_ownership_blocked(source):
    parsed=parsed_export(source,[2]); parsed.frames['locations'].at[0,'location_id']=61
    with pytest.raises(WorkbookMatchError, match='outside'): match_workbook(parsed,source)

def test_missing_rows_not_deletions(source):
    parsed=parsed_export(source); remove_rows(parsed,'location_labels',[0,1])
    result=match_workbook(parsed,source); assert result.rows['location_labels']==()

def test_new_candidate_has_no_current(source):
    parsed=parsed_export(source,[2]); parsed.frames['sensors'].at[0,'sensor_id']=None
    parsed.frames['sensors'].at[0,'row_role']='edit'
    assert match_workbook(parsed,source).rows['sensors'][0].current is None

def test_differences_retained(source):
    parsed=parsed_export(source); parsed.frames['sites'].at[1,'site_code']='renamed'
    row=match_workbook(parsed,source).rows['sites'][1]
    assert row.current['site_code']=='north' and row.values['site_code']=='renamed'
