from ...ethercat.device import EtherCATSimDevice
from ...cia_402.device import CiA402SimDevice
from ..elmo_gold import ElmoGold420, ElmoGold520
from ..inovance_is620n import InovanceIS620N
from ..inovance_sv660 import InovanceSV660
from ..eve_xcr_e import EVEXCRE
from ..evs_xcr_e import EVSXCRE
from ...tests.interface import DebugInterface


class DevicesForTest(EtherCATSimDevice):
    interface_class = DebugInterface
    category = "devices_for_test"


class ElmoGold420ForTest(DevicesForTest, ElmoGold420, CiA402SimDevice):
    name = "elmo_gold_0x30924_0x10420_test"
    test_category = "elmo_gold_420_test"


class ElmoGold520ForTest(DevicesForTest, ElmoGold520, CiA402SimDevice):
    name = "elmo_gold_0x30925_0x10420_test"
    test_category = "elmo_gold_520_test"


class InovanceIS620NForTest(DevicesForTest, InovanceIS620N, CiA402SimDevice):
    name = "IS620N_ECAT_test"
    test_category = "inovance_sv660n_test"


class InovanceSV660NForTest(DevicesForTest, InovanceSV660, CiA402SimDevice):
    # There's actually a SimInovanceSV660 class, but it's too hard to make an
    # exception in the read_update_write.cases.yaml for the simulated status
    # word bit 15 "home found"
    name = "SV660_ECAT_test"
    test_category = "inovance_is620n_test"


class EVEXCREForTest(DevicesForTest, EVEXCRE, CiA402SimDevice):
    name = "EVE-XCR-E_test"
    test_category = "everest_xcr_e_test"
