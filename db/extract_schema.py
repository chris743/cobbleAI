"""
Schema Extraction Script for DM03 Data Warehouse
Extracts schema information from SQL Server and generates YAML documentation templates.

Usage:
    python extract_schema.py

Output:
    - /data-catalog/domains/{domain}/*.yaml files for each view
    - /data-catalog/agent_context.md summary file
"""

import pyodbc
import yaml
import os
from pathlib import Path
from collections import defaultdict

# Connection settings
SERVER = 'RDGW-CF'
DATABASE = 'DM03'
# Using Windows Authentication - adjust if you need SQL auth
CONNECTION_STRING = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;'

# Alternatively, for SQL Server authentication:
# USERNAME = 'your_username'
# PASSWORD = 'your_password'
# CONNECTION_STRING = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}'

# All views to document (from your screenshot)
VIEWS = [
    # Inventory / Bins
    'dbo.BININVSNAPSHOTS_EXT',
    'dbo.VW_BININVENTORY',
    'dbo.VW_BINSRECEIVED',
    'dbo.VW_BLOCKS',
    
    # Packout
    'dbo.VW_14DAYAVGPACKOUT',
    'dbo.VW_14DAYAVGPACKOUT_EXT',
    
    # Receiving
    'dbo.VW_ALLRECEIVINGS',
    
    # Commodities & Products
    'dbo.VW_CF_COMMODITIES',
    'dbo.VW_CF_POOLS',
    'dbo.VW_LP_COMMODITIES',
    'dbo.VW_LP_LOTS',
    'dbo.VW_PRODUCTS',
    'Ref.vw_CommodityVariety',
    
    # Sales & Orders
    'dbo.VW_COBBLESTONESALESORDERS',
    'dbo.VW_LPSALESORDERS',
    
    # Shipments
    'dbo.VW_E_SHIPMENTS',
    'dbo.VW_E_SizerEntries',
    'rpt.vw_Shipments_RS',
    
    # Portal / Grower Views
    'dbo.vw_Portal_BinsReceived_ByBlock',
    'dbo.vw_Portal_BinsReceived_ByBlock_A',
    'dbo.vw_Portal_BinsReceived_ByGrower',
    
    # Storage
    'rpt.vw_E_StorageCharges',
    
    # Repacking
    'rpt.vw_IC_Repack_Run_Summary',
    'rpt.vw_IC_REPACKING_OutputByRun',
    'rpt.vw_RepackLabor_CellAreaAllocated',
    
    # Labor
    'rpt.vw_LaborSummaryDaily_Combined',
    'rpt.vw_UKG_LaborSummaryDaily',
]

# Domain classification based on view names
def classify_domain(view_name: str) -> str:
    """Classify a view into a business domain based on naming patterns."""
    name_upper = view_name.upper()
    
    if any(x in name_upper for x in ['BIN', 'INVENTORY', 'BLOCK']):
        return 'inventory'
    elif any(x in name_upper for x in ['PACKOUT']):
        return 'packout'
    elif any(x in name_upper for x in ['RECEIVING']):
        return 'receiving'
    elif any(x in name_upper for x in ['COMMODITY', 'PRODUCT', 'POOL', 'LOT', 'VARIETY']):
        return 'products'
    elif any(x in name_upper for x in ['SALES', 'ORDER']):
        return 'sales'
    elif any(x in name_upper for x in ['SHIPMENT', 'SIZER']):
        return 'shipments'
    elif any(x in name_upper for x in ['PORTAL', 'GROWER']):
        return 'grower-portal'
    elif any(x in name_upper for x in ['STORAGE']):
        return 'storage'
    elif any(x in name_upper for x in ['REPACK']):
        return 'repacking'
    elif any(x in name_upper for x in ['LABOR', 'UKG']):
        return 'labor'
    else:
        return 'other'


def get_view_columns(cursor, schema: str, view_name: str) -> list:
    """Extract column information for a view."""
    cursor.execute("""
        SELECT 
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.NUMERIC_PRECISION,
            c.NUMERIC_SCALE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = ?
          AND c.TABLE_NAME = ?
        ORDER BY c.ORDINAL_POSITION
    """, schema, view_name)
    
    columns = []
    for row in cursor.fetchall():
        col_type = row.DATA_TYPE
        
        # Format type with length/precision
        if row.CHARACTER_MAXIMUM_LENGTH:
            if row.CHARACTER_MAXIMUM_LENGTH == -1:
                col_type += '(MAX)'
            else:
                col_type += f'({row.CHARACTER_MAXIMUM_LENGTH})'
        elif row.NUMERIC_PRECISION and row.DATA_TYPE in ('decimal', 'numeric'):
            col_type += f'({row.NUMERIC_PRECISION},{row.NUMERIC_SCALE})'
        
        columns.append({
            'name': row.COLUMN_NAME,
            'type': col_type,
            'nullable': row.IS_NULLABLE == 'YES',
            'description': '',  # To be filled in manually
        })
    
    return columns


def get_sample_data(cursor, full_view_name: str, n: int = 3) -> list:
    """Get sample rows to help with documentation."""
    try:
        cursor.execute(f"SELECT TOP {n} * FROM {full_view_name}")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        samples = []
        for row in rows:
            sample = {}
            for i, col in enumerate(columns):
                val = row[i]
                # Convert to string representation for YAML
                if val is not None:
                    sample[col] = str(val)[:50]  # Truncate long values
            samples.append(sample)
        return samples
    except Exception as e:
        print(f"  Warning: Could not get sample data: {e}")
        return []


def get_row_count(cursor, full_view_name: str) -> int:
    """Get approximate row count."""
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {full_view_name}")
        return cursor.fetchone()[0]
    except:
        return -1


def extract_schema():
    """Main extraction function."""
    print(f"Connecting to {SERVER}/{DATABASE}...")
    
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
    except Exception as e:
        print(f"Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure ODBC Driver 17 for SQL Server is installed")
        print("2. Check server name and database name")
        print("3. Verify you have access permissions")
        print("4. If using SQL auth, update USERNAME and PASSWORD in script")
        return
    
    cursor = conn.cursor()
    print("Connected successfully!\n")
    
    # Create output directory
    base_path = Path('./data-catalog')
    base_path.mkdir(exist_ok=True)
    (base_path / 'domains').mkdir(exist_ok=True)
    
    # Track views by domain
    domains = defaultdict(list)
    all_views_info = []
    
    for full_view_name in VIEWS:
        print(f"Processing {full_view_name}...")
        
        # Parse schema and view name
        if '.' in full_view_name:
            parts = full_view_name.split('.')
            schema = parts[0]
            view_name = parts[1]
        else:
            schema = 'dbo'
            view_name = full_view_name
        
        # Classify into domain
        domain = classify_domain(view_name)
        
        # Create domain directory
        domain_path = base_path / 'domains' / domain
        domain_path.mkdir(exist_ok=True)
        
        # Extract column info
        columns = get_view_columns(cursor, schema, view_name)
        
        if not columns:
            print(f"  Warning: No columns found for {full_view_name}")
            continue
        
        # Get row count
        row_count = get_row_count(cursor, full_view_name)
        
        # Get sample data
        samples = get_sample_data(cursor, full_view_name)
        
        # Build documentation structure
        doc = {
            'name': full_view_name,
            'short_name': view_name,
            'schema': schema,
            'domain': domain,
            'description': '',  # TO BE FILLED IN
            'business_purpose': '',  # TO BE FILLED IN
            'row_count_approx': row_count,
            'refresh_frequency': '',  # TO BE FILLED IN (daily, hourly, real-time)
            'columns': columns,
            'relationships': [],  # TO BE FILLED IN
            'common_filters': [],  # TO BE FILLED IN
            'sample_queries': [],  # TO BE FILLED IN
            'notes': '',  # TO BE FILLED IN
        }
        
        # Add sample data as comments
        if samples:
            doc['_sample_data'] = samples
        
        # Write YAML file
        yaml_filename = view_name.lower().replace('vw_', '').replace('vw-', '') + '.yaml'
        yaml_path = domain_path / yaml_filename
        
        with open(yaml_path, 'w') as f:
            f.write(f"# Schema documentation for {full_view_name}\n")
            f.write(f"# Generated automatically - FILL IN descriptions and relationships\n\n")
            yaml.dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        
        print(f"  → {yaml_path}")
        
        # Track for summary
        domains[domain].append(full_view_name)
        all_views_info.append({
            'name': full_view_name,
            'domain': domain,
            'columns': [c['name'] for c in columns],
            'row_count': row_count
        })
    
    # Create domain summary files
    for domain, views in domains.items():
        domain_file = base_path / 'domains' / domain / '_domain.yaml'
        domain_doc = {
            'domain': domain,
            'description': '',  # TO BE FILLED IN
            'views': views,
            'key_concepts': [],  # TO BE FILLED IN
            'common_joins': [],  # TO BE FILLED IN
        }
        with open(domain_file, 'w') as f:
            yaml.dump(domain_doc, f, default_flow_style=False, sort_keys=False)
    
    # Create agent context summary
    create_agent_context(base_path, domains, all_views_info)
    
    # Create glossary template
    create_glossary(base_path)
    
    print(f"\n✓ Extraction complete!")
    print(f"  Output directory: {base_path}")
    print(f"  Views documented: {len(all_views_info)}")
    print(f"  Domains: {list(domains.keys())}")
    print(f"\nNext steps:")
    print("  1. Fill in 'description' fields in each YAML file")
    print("  2. Add 'relationships' (joins) between views")
    print("  3. Add 'sample_queries' for common questions")
    print("  4. Complete the glossary.yaml with business terms")
    
    conn.close()


def create_agent_context(base_path: Path, domains: dict, views_info: list):
    """Create a markdown summary for agent consumption."""
    
    md_content = """# DM03 Data Warehouse - Agent Reference

## Overview
This document describes the available views in the DM03 data warehouse.
Use this reference to understand what data is available and how to query it.

## Domains

"""
    
    for domain, views in sorted(domains.items()):
        md_content += f"### {domain.title()}\n"
        for view in views:
            view_data = next((v for v in views_info if v['name'] == view), None)
            if view_data:
                cols_preview = ', '.join(view_data['columns'][:5])
                if len(view_data['columns']) > 5:
                    cols_preview += f", ... (+{len(view_data['columns'])-5} more)"
                md_content += f"- **{view}** (~{view_data['row_count']:,} rows)\n"
                md_content += f"  - Columns: {cols_preview}\n"
        md_content += "\n"
    
    md_content += """
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
"""
    
    with open(base_path / 'agent_context.md', 'w') as f:
        f.write(md_content)


def create_glossary(base_path: Path):
    """Create a glossary template."""
    
    glossary = {
        'terms': [
            {
                'term': 'Bin',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['dbo.VW_BININVENTORY', 'dbo.VW_BINSRECEIVED']
            },
            {
                'term': 'Commodity',
                'definition': '',  # TO BE FILLED IN  
                'related_views': ['dbo.VW_CF_COMMODITIES', 'dbo.VW_LP_COMMODITIES']
            },
            {
                'term': 'Grower',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['dbo.vw_Portal_BinsReceived_ByGrower']
            },
            {
                'term': 'Pool',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['dbo.VW_CF_POOLS']
            },
            {
                'term': 'Lot',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['dbo.VW_LP_LOTS']
            },
            {
                'term': 'Packout',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['dbo.VW_14DAYAVGPACKOUT']
            },
            {
                'term': 'Repack',
                'definition': '',  # TO BE FILLED IN
                'related_views': ['rpt.vw_IC_Repack_Run_Summary']
            },
            {
                'term': 'UKG',
                'definition': '',  # TO BE FILLED IN (likely UKG/Kronos workforce management)
                'related_views': ['rpt.vw_UKG_LaborSummaryDaily']
            },
        ]
    }
    
    with open(base_path / 'glossary.yaml', 'w') as f:
        f.write("# Business Glossary\n")
        f.write("# Fill in definitions for domain-specific terms\n\n")
        yaml.dump(glossary, f, default_flow_style=False, sort_keys=False)


if __name__ == '__main__':
    extract_schema()