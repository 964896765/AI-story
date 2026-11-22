import pytest
from pydantic import ValidationError

from app.guardian_ocr import screen_text_findings
from app.story_schemas import ScreenTextContract


def test_screen_text_rules_match_on_the_same_ocr_line_with_evidence():
    contract = ScreenTextContract(language='zh-Hans-CN',required=['灯塔坐标','A9'],forbidden=['旧版权标识'])
    result = screen_text_findings(contract.model_dump(),[
        {'index':0,'lines':['灯塔','坐标','Ａ ９']},
        {'index':2,'lines':['旧版权标识']},
    ])
    assert result==[
        {'code':'required_not_seen','term':'灯塔坐标','evidence_indices':[0,2]},
        {'code':'forbidden_seen','term':'旧版权标识','evidence_indices':[2]},
    ]
    assert screen_text_findings(contract.model_dump(),[{'index':1,'lines':['灯 塔 坐 标','a９']}])==[]


@pytest.mark.parametrize('rules', [
    {'required':[], 'forbidden':[]},
    {'required':['ＡB'], 'forbidden':['ab']},
    {'required':['新版灯塔坐标'], 'forbidden':['灯塔']},
    {'required':['  ']},
])
def test_screen_text_contract_rejects_empty_or_conflicting_terms(rules):
    with pytest.raises(ValidationError):
        ScreenTextContract(language='zh-Hans-CN',**rules)
