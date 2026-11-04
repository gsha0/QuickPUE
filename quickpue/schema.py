"""Versioned input schema (REQ-UI-3, Section 9).  Units are fixed by field-name suffix:
_kw kW, _kwh kWh, _c degC, _k K, _l_s L/s, _pa Pa, _m2 m2, _m m, _pct percent.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


# ---------------------------------------------------------------------------
class PartLoad(_Base):
    """Part-load model for a fan or pump type (Section 11)."""

    method: Optional[Literal["M1", "M2", "M3", "M4", "M5", "M6"]] = Field(
        None, description="PLR method (11.4); default per equipment type (11.6)")
    curve: Any = Field(None, description="FFLP curve id (K-VSM, K-DP(0.3), ...) or user polynomial / table")
    f_min: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum flow fraction for power")
    running: Optional[Literal["R-ALL", "R-STAGE", "R-EPSEQ"]] = Field(None, description="Running-unit rule (11.5)")
    stage_up: float = Field(1.0, gt=0.0, le=1.0, description="R-STAGE stage-up flow fraction")
    design_load_kw: Optional[float] = Field(None, gt=0.0, description="M1 group design load; default from the "
                                            "design pass at installed IT")
    table: Optional[list[tuple[float, float]]] = Field(None, description="M6 table of (IT load fraction, f)")
    server_airflow_l_s_per_kw: Optional[float] = Field(None, gt=0.0, description="M4 server specific airflow")
    bypass_fraction: float = Field(0.0, ge=0.0, description="M4 containment bypass / leakage margin")
    drive: Any = Field(None, description="Optional motor + VFD correction (11.3.2); shaft-power curves only")
    heat_to_stream: float = Field(1.0, ge=0.0, le=1.0, description="Fraction of motor power released to the "
                                  "served stream (REQ-C-4)")


class FanPump(_Base):
    """Design absorbed power per unit x quantity (D3, REQ-DM-2)."""

    power_kw: Optional[float] = Field(None, ge=0.0, description="Design absorbed electrical power per unit "
                                      "(auto-sized from flow if omitted, S-DEF-02 / S-DEF-03)")
    flow_l_s: Optional[float] = Field(None, gt=0.0, description="Design flow per unit")
    quantity: Optional[int] = Field(None, ge=0)
    duty: Optional[int] = Field(None, ge=0)
    standby: int = Field(0, ge=0)
    redundancy: Literal["N+x", "2N_active", "0.5N+0.5N"] = "N+x"
    part_load: PartLoad = Field(default_factory=PartLoad)
    on_ups: bool = Field(False, description="Fed from the mechanical UPS")

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None:
            self.duty = (self.quantity - self.standby) if self.quantity is not None else 1
        if self.quantity is None:
            self.quantity = self.duty + self.standby
        if self.duty + self.standby != self.quantity:
            raise ValueError(f"quantity {self.quantity} != duty {self.duty} + standby {self.standby}")
        return self


# ---------------------------------------------------------------------------
class ProjectInfo(_Base):
    name: str = "Unnamed project"
    location: str = ""
    workflow: str = Field("design-check", description="Default output set (IN-P-3)")
    reference_documents: list[str] = Field(default_factory=list)
    designer_pue: Optional[float] = None
    metering_point: Literal["A", "B"] = Field("A", description="IT metering point (IN-P-5)")
    notes: str = ""


class GHG(_Base):
    electricity_kg_per_kwh: Optional[float] = Field(None, ge=0.0)
    diesel_kg_per_l: Optional[float] = Field(None, ge=0.0)


class Boundary(_Base):
    excluded: list[str] = Field(default_factory=list, description="End-use keys excluded from PUE (IN-P-2)")


class WeatherSpec(_Base):
    epw: str
    distance_km: Optional[float] = None
    site_latitude: Optional[float] = None
    site_longitude: Optional[float] = None
    design_condition: Union[Literal["epw_0.4", "max"], dict] = Field(
        "epw_0.4", description="Design ambient for sizing: EPW 0.4 % cooling DB / MCWB")


class Scenario(_Base):
    name: str
    it_fraction: Optional[float] = Field(None, ge=0.0, le=2.0)
    profile: Optional[str] = Field(None, description="CSV 8,760 h IT profile (UC-6)")
    units: Literal["kW", "fraction"] = "fraction"
    column: Optional[str] = None
    per_hall: bool = False
    repeat: bool = Field(False, description="Repeat a shorter series to 8,760 h")
    liquid_fraction_column: Optional[str] = None

    @model_validator(mode="after")
    def _one(self):
        if (self.it_fraction is None) == (self.profile is None):
            raise ValueError(f"scenario {self.name}: give exactly one of it_fraction or profile")
        return self


class ITMinimum(_Base):
    """Minimum-input mode (8.4): installed IT and liquid fraction for a single hall type."""

    installed_kw: float = Field(..., gt=0.0)
    liquid_fraction: float = Field(0.0, ge=0.0, le=1.0)
    area_m2: Optional[float] = None
    height_m: Optional[float] = None
    halls: int = Field(1, ge=1)


class Hall(_Base):
    name: str
    count: int = Field(1, ge=1)
    it_kw: float = Field(..., ge=0.0, description="Design IT capacity per hall")
    liquid_fraction: float = Field(0.0, ge=0.0, le=1.0, description="Share of IT heat captured by liquid (D11)")
    area_m2: Optional[float] = Field(None, gt=0.0, description="Floor area per hall; default from IT density")
    height_m: float = 4.5
    cold_aisle_c: float = 27.0
    lighting_w_m2: float = Field(5.0, ge=0.0, description="[NKB] data hall lighting 5 W/m2")
    lighting_profile: Any = Field("nkb_dc", description="[NKB] 5 % / 15 % profile")
    occupancy_m2_per_person: Optional[float] = Field(100.0, description="[NKB] 100 m2/person")
    occupancy_profile: Any = "nkb_dc"
    fixed_gain_kw: float = 0.0
    lighting_end_use: str = "lighting_dc"
    losses: dict[str, float] = Field(default_factory=dict, description="Loss element -> fraction released here")


class Reset(_Base):
    type: Literal["fixed", "ambient_linear", "wetbulb_offset", "drybulb_offset"] = "fixed"
    t_amb_low_c: Optional[float] = None
    t_amb_high_c: Optional[float] = None
    supply_low_c: Optional[float] = None
    supply_high_c: Optional[float] = None
    offset_k: float = 3.0
    min_c: float = 12.78
    max_c: float = 23.89


class Loop(_Base):
    name: str
    medium: Literal["water", "pg", "eg"] = "water"
    glycol_pct: float = Field(0.0, ge=0.0, le=60.0)
    supply_c: float
    return_c: float
    reset: Reset = Field(default_factory=Reset)
    connection: Literal["direct", "dedicated", "blended", "hx", "split"] = "direct"
    from_loop: Optional[str] = None
    hx_approach_k: float = Field(2.0, ge=0.0)
    primary_pump: Optional[FanPump] = None
    secondary_pump: Optional[FanPump] = None

    @model_validator(mode="after")
    def _check(self):
        if self.return_c <= self.supply_c:
            raise ValueError(f"loop {self.name}: return must exceed supply")
        if self.connection in ("blended", "hx", "split") and not self.from_loop:
            raise ValueError(f"loop {self.name}: connection {self.connection} needs from_loop")
        return self


class Adiabatic(_Base):
    enabled: bool = True
    activation_c: float = Field(..., description="Pads active when T_db exceeds this value")
    activation_inclusive: bool = Field(False, description="True: T_db >= activation; False: T_db > activation")
    efficiency: float = Field(..., gt=0.0, le=1.0)
    bleed_ratio: float = Field(0.2, ge=0.0, description="Gross / net water - 1 (pad bleed); assumption")


class FreeCooling(_Base):
    enabled: bool = True
    rated_capacity_kw: Optional[float] = Field(None, gt=0.0, description="Free cooling capacity per unit at "
                                               "rated_dt_k, full fan; default 50 % of chiller capacity at 10 K")
    rated_dt_k: float = Field(10.0, gt=0.0, description="Return water minus air temperature at the rating")
    enable_dt_k: float = Field(1.0, ge=0.0, description="Minimum (T_return - T_air) to enable free cooling")
    fan_power_kw: Optional[float] = Field(None, ge=0.0, description="Fan power per unit at full speed; default 2 % "
                                          "of chiller capacity")
    air_to_water_capacity_ratio: float = 1.5
    ua_exponent: float = 0.6
    part_load: PartLoad = Field(default_factory=PartLoad)
    adiabatic_in_free_cooling: bool = False


class ChillerCurveSpec(_Base):
    library: Optional[str] = None
    capft: Optional[list[float]] = None
    eirft: Optional[list[float]] = None
    eirfplr: Optional[list[float]] = None
    table: Optional[list[dict]] = None
    clamp_inputs: bool = True
    normalize: bool = True
    source: Optional[str] = None


class Chiller(_Base):
    name: str
    kind: Literal["air_cooled", "water_cooled"] = "air_cooled"
    quantity: Optional[int] = Field(None, ge=0)
    duty: Optional[int] = Field(None, ge=0)
    standby: int = Field(0, ge=0)
    capacity_kw: Optional[float] = Field(None, gt=0.0, description="Rated capacity per unit (auto-sized if omitted)")
    cop: Optional[float] = Field(None, gt=0.0)
    power_kw: Optional[float] = Field(None, gt=0.0)
    rated_lwt_c: Optional[float] = None
    rated_ect_c: Optional[float] = Field(None, description="Entering condenser air (air cooled) or water temperature")
    curves: ChillerCurveSpec = Field(default_factory=ChillerCurveSpec)
    min_plr: Optional[float] = Field(None, ge=0.0, le=1.0)
    below_min: Literal["cycling", "false_loading"] = "cycling"
    stage_up_plr: float = Field(1.0, gt=0.0, le=1.0)
    standby_on_shortfall: bool = True
    priority: int = 1
    lwt_range_c: Optional[tuple[float, float]] = None
    tcond_range_c: Optional[tuple[float, float]] = None
    integral_pump: Optional[FanPump] = None
    integral_pump_units: Literal["duty", "running"] = Field(
        "duty", description="Integral pumps run on all duty units (R-ALL) or only on running chillers")
    recirculation_k: float = Field(0.0, description="Condenser entering air correction (IN-CH-8)")
    recirculation_order: Literal["after_pads", "before_pads"] = Field(
        "after_pads", description="Recirculation added after (default, TEST_CASES R-1) or before the pads")
    adiabatic: Optional[Adiabatic] = None
    free_cooling: Optional[FreeCooling] = None
    condenser_air_dt_k: float = Field(10.0, gt=0.0, description="Condenser air temperature rise for adiabatic water")
    condenser_flow_l_s: Optional[float] = None
    max_ambient_c: Optional[float] = None

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None:
            self.duty = (self.quantity - self.standby) if self.quantity is not None else None
        if self.quantity is None and self.duty is not None:
            self.quantity = self.duty + self.standby
        return self


class DryCooler(_Base):
    name: str
    quantity: Optional[int] = None
    duty: Optional[int] = None
    standby: int = 0
    rated_capacity_kw: Optional[float] = Field(None, gt=0.0)
    rated_water_in_c: Optional[float] = None
    rated_water_out_c: Optional[float] = None
    rated_air_c: Optional[float] = None
    fan_power_kw: Optional[float] = Field(None, ge=0.0)
    airflow_l_s: Optional[float] = None
    air_to_water_capacity_ratio: float = 1.5
    ua_exponent: float = 0.6
    part_load: PartLoad = Field(default_factory=PartLoad)
    adiabatic: Optional[Adiabatic] = None
    recirculation_k: float = 0.0
    recirculation_order: Literal["after_pads", "before_pads"] = "after_pads"

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None and self.quantity is not None:
            self.duty = self.quantity - self.standby
        if self.quantity is None and self.duty is not None:
            self.quantity = self.duty + self.standby
        return self


class Tower(_Base):
    name: str
    quantity: Optional[int] = None
    duty: Optional[int] = None
    standby: int = 0
    rated_capacity_kw: Optional[float] = Field(None, gt=0.0)
    design_wb_c: Optional[float] = None
    approach_k: float = 4.0
    range_k: float = 5.5
    fan_power_kw: Optional[float] = Field(None, ge=0.0, description="Default 0.0105 W/W of capacity ([EP-IO])")
    airflow_l_s: Optional[float] = None
    part_load: PartLoad = Field(default_factory=PartLoad)
    coc: float = Field(5.0, gt=1.0, description="Cycles of concentration (DCOPTEST)")
    drift_fraction: float = Field(0.0002, ge=0.0, description="Drift as fraction of circulating water (DCOPTEST)")

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None and self.quantity is not None:
            self.duty = self.quantity - self.standby
        if self.quantity is None and self.duty is not None:
            self.quantity = self.duty + self.standby
        return self


class CondenserWater(_Base):
    reset: Reset = Field(default_factory=lambda: Reset(type="wetbulb_offset", offset_k=3.0))
    design_dt_k: float = 5.5
    pump: Optional[FanPump] = None


class WSE(_Base):
    approach_k: float = Field(2.0, ge=0.0)


class Plant(_Base):
    name: str
    type: Literal["CP-1", "CP-2", "CP-3", "CP-4", "CP-5", "CP-6", "CP-7", "CP-8", "CP-9", "CP-10"]
    loop: str
    chillers: list[Chiller] = Field(default_factory=list)
    dry_coolers: list[DryCooler] = Field(default_factory=list)
    towers: list[Tower] = Field(default_factory=list)
    wse: Optional[WSE] = None
    condenser_water: Optional[CondenserWater] = None


class CDU(_Base):
    name: str
    serves: list[str]
    loop: str
    quantity: Optional[int] = None
    active: Optional[int] = None
    capacity_kw: Optional[float] = Field(None, gt=0.0, description="Net capacity per CDU")
    pump: Optional[FanPump] = None
    tcs_supply_c: Optional[float] = None
    approach_k: float = Field(3.0, ge=0.0, description="Approach at rated capacity; assumption (8.4.2)")
    approach_model: Literal["load_scaled", "fixed"] = "load_scaled"
    share: Optional[float] = Field(None, gt=0.0, le=1.0)
    r_th_k_per_kw: Optional[float] = None
    t_junction_max_c: Optional[float] = None
    units_per_hall: Optional[int] = None


class FWU(_Base):
    name: str
    serves: list[str]
    loop: str
    quantity: Optional[int] = None
    duty: Optional[int] = None
    standby: int = 0
    redundancy: Literal["N+x", "2N_active", "0.5N+0.5N"] = "N+x"
    fan_power_kw: Optional[float] = Field(None, ge=0.0)
    airflow_l_s: Optional[float] = None
    static_pa: Optional[float] = None
    coil_capacity_kw: Optional[float] = None
    supply_air_c: Optional[float] = None
    air_dt_k: float = 11.0
    part_load: PartLoad = Field(default_factory=PartLoad)
    on_ups: bool = False
    share: Optional[float] = Field(None, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None and self.quantity is not None:
            self.duty = self.quantity - self.standby
        if self.quantity is None and self.duty is not None:
            self.quantity = self.duty + self.standby
        return self


class Zone(_Base):
    name: str
    category: str = "electrical"
    count: int = Field(1, ge=1)
    area_m2: Optional[float] = Field(None, gt=0.0, description="Area per zone; default 0.02 m2 per kW of "
                                     "installed IT (assumption)")
    height_m: float = 3.5
    setpoint_c: float = 27.0
    rh_max_pct: Optional[float] = None
    external_wall_m2: float = Field(0.0, ge=0.0)
    roof_exposed: bool = False
    u_wall: float = Field(1.1, description="[NKB] concrete 200 mm U 1.1 W/m2K")
    u_roof: float = 1.1
    infiltration_ach: Optional[float] = Field(None, description="Default per [NKB]: 0 pressurised, 0.7 no "
                                              "mechanical OA, 0.35 otherwise")
    pressurised: bool = False
    lighting_w_m2: float = 5.0
    lighting_profile: Any = "nkb_dc"
    occupancy_m2_per_person: Optional[float] = 100.0
    occupancy_profile: Any = "nkb_dc"
    equipment_w_m2: float = 0.0
    equipment_profile: Any = "always"
    fixed_gain_kw: float = 0.0
    losses: dict[str, float] = Field(default_factory=dict, description="Loss element -> fraction released into "
                                     "this zone type (all zones of the type together) (IN-Z-7)")
    boundary: Literal["infrastructure", "excluded"] = "infrastructure"
    lighting_end_use: str = "lighting_non_office"
    equipment_end_use: str = "equipment_other"


class ZoneShare(_Base):
    zone: str
    share: float = Field(1.0, gt=0.0, le=1.0)


class RoomUnit(_Base):
    name: str
    type: Literal["CRAH", "CRAC", "PAC", "VRF", "split", "FCU", "DX_dehumidifier", "OAF", "EAF", "humidifier"]
    serves: list[Union[str, ZoneShare]]
    quantity: Optional[int] = None
    duty: Optional[int] = None
    standby: int = 0
    redundancy: Literal["N+x", "2N_active", "0.5N+0.5N"] = "N+x"
    capacity_kw: Optional[float] = Field(None, gt=0.0, description="Total cooling capacity per unit")
    sensible_capacity_kw: Optional[float] = None
    airflow_l_s: Optional[float] = None
    oa_l_s: float = Field(0.0, ge=0.0, description="Outdoor air per unit")
    off_coil_c: Optional[float] = None
    fan_power_kw: float = Field(0.0, ge=0.0)
    fan_part_load: PartLoad = Field(default_factory=PartLoad)
    cop: float = Field(3.0, gt=0.0, description="[NKB] COP 3.0 assumed where no vendor data")
    cop_ambient_slope_per_k: float = Field(0.0, description="Linear COP change per K of condenser temperature "
                                           "above the rating (negative = worse when hotter)")
    rated_condenser_c: float = 35.0
    eirfplr: Optional[list[float]] = None
    loop: Optional[str] = None
    recirculation_k: float = 0.0
    power_kw: float = Field(0.0, ge=0.0, description="Fixed power per unit (dehumidifier, humidifier, OAF, EAF)")
    activation: Literal["always", "outdoor_dewpoint_above", "outdoor_dewpoint_below", "outdoor_db_above",
                        "outdoor_db_below", "never"] = "always"
    activation_value: Optional[float] = None
    end_use: Optional[str] = None
    on_ups: bool = False

    @model_validator(mode="after")
    def _counts(self):
        if self.duty is None and self.quantity is not None:
            self.duty = self.quantity - self.standby
        if self.quantity is None and self.duty is not None:
            self.quantity = self.duty + self.standby
        if self.type in ("CRAH", "PAC", "FCU") and not self.loop:
            raise ValueError(f"room unit {self.name}: type {self.type} needs a loop")
        return self


class UPS(_Base):
    name: str
    path: Literal["it", "mechanical"] = "it"
    serves: list[str] = Field(default_factory=lambda: ["all"])
    module_kw: Optional[float] = Field(None, gt=0.0)
    modules: int = Field(1, ge=1, description="Modules per system")
    systems: int = Field(1, ge=1)
    active_modules: Optional[int] = Field(None, description="Total active modules (default all)")
    efficiency: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.0, 0.94), (1.0, 0.94)], description="(load fraction, efficiency) table; "
        "default flat 0.94 ([KO26])")
    loss_convention: Optional[Literal["physical", "simplified"]] = None


class Transformer(_Base):
    name: str
    level: Literal["MVLV", "HV"] = "MVLV"
    basis: Literal["facility", "it", "it_path", "mechanical", "infrastructure"] = Field(
        "facility", description="Throughput basis for losses (TEST_CASES R-3)")
    loss_model: Literal["percent", "no_load_load"] = "percent"
    percent: float = Field(1.0, ge=0.0, description="[NKB] MV/LV 1.0 %, HV 0.5 %")
    rating_kva: Optional[float] = None
    quantity: int = 1
    no_load_kw: float = 0.0
    full_load_kw: float = 0.0
    power_factor: float = 0.95


class Distribution(_Base):
    name: str = "Distribution"
    percent: float = Field(1.0, ge=0.0, description="[NKB] 1 % of infrastructure electricity")
    basis: Literal["infrastructure", "it", "facility"] = "infrastructure"


class PDU(_Base):
    loss_fraction: Optional[float] = Field(None, ge=0.0, le=0.2, description="Default 0 at Point A, 0.03 at Point B")


class Electrical(_Base):
    loss_convention: Literal["physical", "simplified"] = Field(
        "physical", description="UPS / PDU loss convention (TEST_CASES R-2)")
    ups: list[UPS] = Field(default_factory=list)
    transformers: list[Transformer] = Field(default_factory=list)
    distribution: Optional[Distribution] = Field(default_factory=Distribution)
    pdu: PDU = Field(default_factory=PDU)
    heat_outdoors: dict[str, float] = Field(default_factory=dict, description="Loss element (or alias) -> "
                                            "fraction released outdoors or outside conditioned zones")


class GeneratorTesting(_Base):
    count: int = Field(0, ge=0)
    rating_kw: Optional[float] = None
    format: Literal["A", "B"] = "A"
    fuel_l_per_h: Optional[float] = None
    hours_per_test: float = 1.0
    tests_per_year: float = 12.0
    annual_litres: Optional[float] = None
    diesel_mwh_per_l: float = Field(0.01076, description="[NKB] 38.6 MJ/L")


class JacketHeaters(_Base):
    kw_per_generator: float = 0.0
    count: Optional[int] = None
    t_on_c: float = 10.0
    t_off_c: float = 32.0
    eflh_hours: Optional[float] = Field(None, description="Override the EFLH computed from the EPW")


class Lift(_Base):
    name: str
    count: int = 1
    trips_per_year: Optional[float] = None
    power_kw: Optional[float] = None
    trip_time_s: Optional[float] = None
    running_factor: float = Field(0.75, description="Assumption reproducing the GBCA method within 0.3 % (S-EQ-22)")
    standby_kw: float = 0.0
    standby_hours: float = 8760.0
    annual_kwh: Optional[float] = None


class FixedLoad(_Base):
    name: str
    end_use: str
    kw: Optional[float] = None
    annual_kwh: Optional[float] = None
    profile: Any = "always"
    heat_to_zone: Optional[str] = None
    boundary: Literal["infrastructure", "excluded"] = "infrastructure"


class PV(_Base):
    annual_kwh: Optional[float] = None
    kw_peak: Optional[float] = None
    specific_yield_kwh_per_kw: Optional[float] = None
    hourly_csv: Optional[str] = None


class Other(_Base):
    generators: Optional[GeneratorTesting] = None
    jacket_heaters: Optional[JacketHeaters] = None
    lifts: list[Lift] = Field(default_factory=list)
    loads: list[FixedLoad] = Field(default_factory=list, description="Ancillary, DHW, office equipment, ...")
    pv: Optional[PV] = None


class Contingency(_Base):
    percent: float = Field(0.0, ge=0.0, description="Percent of infrastructure energy (8.4.2 default 0 %)")
    basis: Literal["gross", "net_of_pv"] = Field(
        "gross", description="gross: before PV credit (reference practice); net_of_pv: after PV")
    note: str = ""


class Settings(_Base):
    max_iterations: int = 20
    tolerance: float = 1e-4
    relaxation: float = Field(1.0, gt=0.0, le=1.0)
    sizing_it_fraction: float = Field(1.0, gt=0.0, le=1.5)
    adiabatic_counterfactual: bool = True
    balance_tolerance: float = 0.005
    annual_items_hourly: Literal["spread", "separate"] = "spread"
    min_speed_warning_share: float = 0.5
    chiller_below_min_warning_share: float = 0.2
    density_kw_per_m2: float = Field(2.5, gt=0.0, description="IT density used when hall area is omitted "
                                     "(assumption)")


class Project(_Base):
    schema_version: str = SCHEMA_VERSION
    preset: Optional[str] = None
    project: ProjectInfo = Field(default_factory=ProjectInfo)
    weather: WeatherSpec
    scenarios: Union[Literal["nabers", "design"], list[Scenario]] = "nabers"
    it: Optional[ITMinimum] = None
    water_system: Optional[Literal["WS-1", "WS-2", "WS-3", "WS-4", "WS-5", "WS-6"]] = None
    halls: list[Hall] = Field(default_factory=list)
    loops: list[Loop] = Field(default_factory=list)
    plants: list[Plant] = Field(default_factory=list)
    cdus: list[CDU] = Field(default_factory=list)
    fwus: list[FWU] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    room_units: list[RoomUnit] = Field(default_factory=list)
    electrical: Electrical = Field(default_factory=Electrical)
    other: Other = Field(default_factory=Other)
    contingency: Contingency = Field(default_factory=Contingency)
    boundary: Boundary = Field(default_factory=Boundary)
    ghg: GHG = Field(default_factory=GHG)
    settings: Settings = Field(default_factory=Settings)

    def scenario_list(self) -> list[Scenario]:
        if self.scenarios == "nabers":
            return [Scenario(name=f"{int(p * 100)}%", it_fraction=p) for p in (0.9, 0.75, 0.5, 0.25)]
        if self.scenarios == "design":
            return [Scenario(name="100%", it_fraction=1.0)]
        return list(self.scenarios)
