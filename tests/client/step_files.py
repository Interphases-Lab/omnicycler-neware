"""Neware BTS Step Files for the tests, within the subset neware8 compiles (5 V / 10 mA channels)."""

HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<root><config type="Step File" version="17">'
    '<Head_Info><Operate Value="66"/><RateType Value="103"/><Scale Value="1"/><Start_Step Value="1"/></Head_Info>'
    '<Whole_Prt><Protect><Main><Volt><Upper Value="45000"/><Lower Value="0"/></Volt>'
    '<Curr><Upper Value="8"/><Lower Value="-8"/></Curr></Main></Protect>'
    '<Record><Main><Time Value="2000"/></Main></Record></Whole_Prt>'
)


def discharge_cycles() -> bytes:
    """Three 10 s discharges at 1 mA: CC discharge, Cycle x3, End."""
    steps = (
        '<Step_Info Num="3"><Step1 Step_ID="1" Step_Type="2"><Limit><Main><Curr Value="1"/>'
        '<Time Value="10000"/></Main></Limit></Step1>'
        '<Step2 Step_ID="2" Step_Type="5"><Limit><Other><Start_Step Value="1"/><Cycle_Count Value="3"/></Other>'
        '</Limit></Step2><Step3 Step_ID="3" Step_Type="6"/></Step_Info>'
    )
    return (HEAD + steps + "</config></root>").encode()


def long_rest() -> bytes:
    """A rest of about four months."""
    steps = (
        '<Step_Info Num="2"><Step1 Step_ID="1" Step_Type="4"><Limit><Main><Time Value="10000000000"/></Main>'
        '</Limit></Step1><Step2 Step_ID="2" Step_Type="6"/></Step_Info>'
    )
    return (HEAD + steps + "</config></root>").encode()
