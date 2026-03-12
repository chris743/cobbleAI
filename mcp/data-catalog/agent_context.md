# DM03 Data Warehouse - Agent Reference

## Overview
This document describes the available views in the DM03 data warehouse.
Use this reference to understand what data is available and how to query it.

## Domains

### Inventory
- **dbo.BININVSNAPSHOTS_EXT** (~10,878 rows)
  - Columns: SnapshotDate, SnapshotTakenAtUtc, Warehouse, Commodity, Grade, ... (+10 more)
- **dbo.VW_BININVENTORY** (~8,034 rows)
  - Columns: source_database, TagNumber, Warehouse, ProductIDx, BlockIDx, ... (+31 more)
- **dbo.VW_BINSRECEIVED** (~5,097 rows)
  - Columns: source_database, InventoryIdx, Tag, CmtyIdx, Commodity, ... (+8 more)
- **dbo.VW_BLOCKS** (~1,097 rows)
  - Columns: GABLOCKIDX, ID, NAME, GROWERNAMEIDX, GrowerName, ... (+9 more)
- **dbo.vw_Portal_BinsReceived_ByBlock** (~1,117 rows)
  - Columns: source_database, GrowerID, GrowerName, GABLOCKIDX, BlockID, ... (+13 more)
- **dbo.vw_Portal_BinsReceived_ByBlock_A** (~1,117 rows)
  - Columns: source_database, GrowerID, GrowerName, GABLOCKIDX, BlockID, ... (+15 more)
- **dbo.vw_Portal_BinsReceived_ByGrower** (~175 rows)
  - Columns: source_database, GrowerID, GrowerName, LastReceivedDate, LastReceivedQty, ... (+3 more)
- **rpt.vw_LaborSummaryDaily_Combined** (~175,801 rows)
  - Columns: Employee Id, Counter Date, Cost Centers(2), Payroll Job Title, Daily Overtime Hours, ... (+29 more)

### Labor
- **rpt.vw_UKG_LaborSummaryDaily** (~39,679 rows)
  - Columns: Employee Id, Counter Date, Cost Centers(2), Payroll Job Title, Daily Overtime Hours, ... (+29 more)

### Other
- **dbo.VW_CF_COMMODITIES** (~11 rows)
  - Columns: source_database, CommodityIDx, InvoiceCommodity, Commodity
- **dbo.VW_LP_COMMODITIES** (~44 rows)
  - Columns: source_database, CommodityIDx, InvoiceCommodity, Commodity

### Packout
- **dbo.VW_14DAYAVGPACKOUT** (~113 rows)
  - Columns: Commodity, CmtyIdx, SizeName, Grade, qnt, ... (+2 more)
- **dbo.VW_14DAYAVGPACKOUT_EXT** (~113 rows)
  - Columns: Commodity, CmtyIdx, SizeName, Grade, qnt, ... (+6 more)

### Products
- **dbo.VW_CF_POOLS** (~103 rows)
  - Columns: POOLIDX, ID, DESCR, ICCLOSEDFLAG, POOLTYPE, ... (+5 more)
- **dbo.VW_LP_LOTS** (~2,894 rows)
  - Columns: GALOTIDX, ID, DESCR, ICCLOSEDFLAG, CLOSEDATE, ... (+2 more)
- **dbo.VW_PRODUCTS** (~38,721 rows)
  - Columns: ProductIdx, source_database, Id, IcType, UPC, ... (+48 more)
- **Ref.vw_CommodityVariety** (~130 rows)
  - Columns: CMTYIDX, CommodityName, CommodityNameInvC, CommodityInactiveFlag, VARIETYIDX, ... (+8 more)

### Receiving
- **dbo.VW_ALLRECEIVINGS** (~11,999 rows)
  - Columns: source_database, InventoryIdx, Tag, Commodity, Style, ... (+6 more)

### Repacking
- **rpt.vw_IC_Repack_Run_Summary** (~914,497 rows)
  - Columns: ICRUNIDX, RUNDATE, GALOTIDX, PRODUCTIDX, warehouseidx, ... (+10 more)
- **rpt.vw_IC_REPACKING_OutputByRun** (~113,914 rows)
  - Columns: ICRUNIDX, RunDate, Output, Output_Equiv, GABLOCKIDX, ... (+5 more)
- **rpt.vw_RepackLabor_CellAreaAllocated** (~39,679 rows)
  - Columns: EmployeeId, CounterDate, CostCenters2, PayrollJobTitle, DefaultCostCenters, ... (+24 more)

### Sales
- **dbo.VW_COBBLESTONESALESORDERS** (~15,244 rows)
  - Columns: SOStatus, SODATETIME, SHIPDATETIME, INVOICEDATE, WAREHOUSEIDX, ... (+20 more)
- **dbo.VW_LPSALESORDERS** (~87,216 rows)
  - Columns: SOStatus, SODATETIME, SHIPDATETIME, INVOICEDATE, WAREHOUSEIDX, ... (+19 more)

### Shipments
- **dbo.VW_E_SHIPMENTS** (~554,169 rows)
  - Columns: Header_SourceDB, ARTRXHDRIDX, SOURCEIDX, SONO, CUSTPOREF, ... (+64 more)
- **dbo.VW_E_SizerEntries** (~214,198 rows)
  - Columns: PKHDRIDX, PKSEQ, POOLIDX, GABLOCKIDX, GALOTIDX, ... (+13 more)
- **rpt.vw_Shipments_RS** (~544,996 rows)
  - Columns: Header_SourceDB, ARTRXHDRIDX, SOURCEIDX, SONO, CUSTPOREF, ... (+65 more)

### Storage
- **rpt.vw_E_StorageCharges** (~207,064 rows)
  - Columns: source_database, Storage, INVCDESCR, Amount, SONO, ... (+1 more)


## Query Guidelines

1. Always use SELECT statements only
2. Use TOP N to limit result sets
3. Date columns are typically datetime or date type
4. Join views using common keys (commodity codes, bin IDs, grower IDs, etc.)

## Common Patterns

```sql
-- Get recent data
SELECT TOP 100 * FROM dbo.VW_BININVENTORY ORDER BY [DateColumn] DESC

-- Aggregate by commodity
SELECT CommodityCode, COUNT(*) as cnt, SUM(Quantity) as total
FROM [ViewName]
GROUP BY CommodityCode
```
