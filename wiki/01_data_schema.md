# Data Schema — `Germany_data_v2_1512.xlsx`

The workbook has 13 sheets. Each sheet feeds specific sets or parameters used in
`new_model_both3.py`. Sheet names are matched by literal string in the code (with one
fallback: the "Production Costs" sheet is actually named `" Prod"` with a leading space, so
the code searches for any sheet name containing `"Prod"` if the expected names aren't found).

## 1. Sets — network nodes

Sheet **"1. Sets"**, columns: `Plants (P)`, `CustomerZones/Market (C)`, `Collection Centers (O)`,
`Refurbish Centers (F)`, `Landfills (L)`, `Suppliers (S)`. Each column lists the IDs for one
node type (ragged — short columns are padded with blanks, dropped via `.dropna()`).

Maps to code sets:
- `P` = Plants (e.g. P1, P2)
- `C` = Customer zones / markets (C1–C3)
- `O` = Collection centers (O1)
- `F` = Refurbishment centers (F1)
- `L` = Landfills (L1)
- `S` = Suppliers (S1–S3)

`K` (module types, e.g. `"Monocrystalline"`) is instead derived from sheet **"7. Module Weights"**,
column `Module_Type_ID`.

## 2. Production Costs — sheet `" Prod"`
| Column | Meaning | Model symbol |
|---|---|---|
| `Plant_ID` | plant | index `p` |
| `Production_Cost_per_KWp (PC_p)` | € per kWp produced | `PC[p]` |

## 3. Operational Costs
| Column | Meaning |
|---|---|
| `Facility_ID` | any of O/F/L facility |
| `Cost_per_Unit (CC_o/FC_f for KWp)` | per-unit handling cost |

Split by facility type in code into `CC` (collection center), `FC` (refurbish center), `DC`
(landfill disposal cost).

## 4. Fixed Costs
| Column | Meaning |
|---|---|
| `Facility_ID` | plant/collection/refurbish facility |
| `Fixed_Operational_Cost (Fix)` | fixed € cost if facility is opened |

Split into `FixO` (collection centers) and `FixF` (refurbish centers) — used with the binary
open/close decisions `W_o`, `W_f`.

## 5. Penalty Costs
| Column | Meaning |
|---|---|
| `Module_Type_ID` | module type |
| `Penalty_Cost_per_KWp (Pen_k)` | € penalty per unit of unmet demand |

→ `Penalty[k]`, applied to shortfall variable `S_ck`.

## 6. Demand & Returns
| Column | Meaning |
|---|---|
| `Customer_Zone_ID` | market zone |
| `Module_Type_ID` | module type |
| `Demand_KWp (DEM_ck)` | forward demand |
| `Returns_KWp (RET_ck)` | end-of-life returns volume |

→ `DEM[(c,k)]`, `RET[(c,k)]`.

## 7. Module Weights
| Column | Meaning |
|---|---|
| `Module_Type_ID` | module type (also used to derive set `K`) |
| `Weight_kg_per_KWp (omega_k)` | kg per kWp, used to convert energy units to mass for
transport cost/emissions and landfill disposal |

→ `omega[k]` (string values with commas as decimal separator are normalized in code).

## 8. Yield Rates
| Column | Meaning |
|---|---|
| `Facility_ID` | facility |
| `Process_Type` | Refurbishing / Reuse / Landfill |
| `Yield_Rate` | baseline yield fraction |

**Not directly read by `new_model_both3.py`** — the script overrides refurbish yield (`alpha`)
per-scenario instead of using this sheet's `Yield_Rate` values. Present for reference /
alternate baseline runs.

## 9. Capacities
| Column | Meaning |
|---|---|
| `Facility_ID` | plant/collection/refurbish facility |
| `Capacity_Value_kWp` | throughput capacity |

→ `CAP[facility]`, enforced on plants unconditionally and on collection/refurbish centers
gated by their open/close binary (`W_o`, `W_f`).

## 10. Revenues
| Column | Meaning |
|---|---|
| `Revenue_Stream` | "Reuse" or "Refurbish" |
| `Item_ID` | module type |
| `Revenue_per_Unit (Rev)_€` | € earned per unit sold back into market |

→ `Rev_reuse[k]`, `Rev_refurb[k]` — subtracted from total cost objective (revenue offsets cost).

## 11. Transportation
| Column | Meaning |
|---|---|
| `Origin_ID`, `Destination_ID` | any two network nodes |
| `Distance_km` | distance between them |
| `Cost_per_kg_km` | global € transport cost rate (same value on every row) |
| `Emission_per_kg_km` | global kg CO2e transport emission rate (same value on every row) |

→ `dist_map[(a,b)]` (default 500 km if a pair is missing — see `DIST()` in code), plus scalar
constants `T_cost`, `T_emit` (taken from the first row only).

## 12. Environmental
| Column | Meaning |
|---|---|
| `Parameter_Name` | `E_p`, `E_o`, `E_f`, `E_l` |
| `Value_kg_CO2e` | emission factor per unit of activity at that node type |

→ `E_p` (production), `E_co`/`E_o` (collection), `E_f` (refurbishment), `E_l` (landfill), with
hardcoded fallback defaults (580, 0.4, 1.2, 0.3) if the sheet is missing a row.

## 13. Supplier_BOM
| Column | Meaning |
|---|---|
| `Supplier_ID` | raw-material supplier |
| `Material_Name` | e.g. Aluminium_Frame, Tempered_Glass, Encapsulant |
| `Qty_per_Module` | units of material per module |
| `Cost_per_Unit`, `Cost_per_kWp` | material cost |
| `Weight_per_module_kg`, `Weight_per_kwp_kg` | material mass |
| `Emission_per_kWp` | embodied emissions per kWp of material |

→ `BOM[s]` (qty/module), `Mat_Cost[s]`, `Em_Supplier[s]` (loaded but not currently referenced
in the objective functions — available for a future extension that costs/emits raw materials
explicitly).

## See also
- [02_optimization_model.md](02_optimization_model.md) for how every symbol above is used in
  constraints and objectives.
