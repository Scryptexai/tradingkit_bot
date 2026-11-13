"""Fail-closed preflight: every mandatory fact must be fresh and affirmative."""
from dataclasses import dataclass
@dataclass(frozen=True)
class GateState:
    worker_online: bool=False
    authentication_valid: bool=False
    capabilities_checked: bool=False
    instrument_available: bool=False
    historical_data_available: bool=False
    user_pressed_start: bool=False

def check(state:GateState)->dict:
    checks={"worker_online":state.worker_online,"authentication_valid":state.authentication_valid,"capabilities_checked":state.capabilities_checked,"instrument_available":state.instrument_available,"historical_data_available":state.historical_data_available,"explicit_start":state.user_pressed_start}
    missing=[k for k,v in checks.items() if not v]
    return {"allowed":not missing,"checks":checks,"missing":missing,"reason":None if not missing else "Execution blocked until all preflight checks are verified."}
