# Harvest Planner API - Complete Context for AI Agent Integration

## Overview

This is an ASP.NET Core REST API for managing harvest planning operations (grower blocks, harvest plans, production runs, contractors, etc.). It uses SQL Server with Entity Framework Core.

## Connection Details

- **Base URL:** `https://<host>/api/v1/` (all endpoints use versioned routes: `api/v1/{controller}`)
- **Content-Type:** `application/json`
- **CORS Allowed Origins:** `http://localhost:3000`, `http://localhost:3001`

---

## Authentication

### JWT Bearer Token

Most endpoints require a JWT Bearer token. Include it in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Zoho Session (Alternative)

For Zoho embedded contexts, pass a session key via header:

```
x-session-key: <zoho_session_key>
```

### Login Flow

1. **POST** `/api/v1/auth/login` with `{ "username": "...", "password": "..." }`
2. Receive `accessToken` and `refreshToken`
3. Use `accessToken` in Authorization header for subsequent requests
4. When access token expires (~30 min), call **POST** `/api/v1/auth/refresh` with `{ "refreshToken": "..." }`
5. Account locks for 15 minutes after 5 failed login attempts

---

## Endpoints Reference

### 1. Auth (`/api/v1/auth`)

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| POST | `/login` | No | Login and get tokens |
| POST | `/logout` | No | Invalidate refresh token |
| POST | `/refresh` | No | Refresh access token |
| GET | `/verify` | Yes | Verify current session |
| POST | `/zoho/session` | No | Create Zoho embedded session |

**POST /login**
```json
// Request
{ "username": "string", "password": "string" }

// Response 200
{
  "accessToken": "string",
  "accessTokenExpiresAt": "2026-01-01T00:00:00Z",
  "refreshToken": "string",
  "refreshTokenExpiresAt": "2026-01-08T00:00:00Z"
}
// 401 = bad credentials, 423 = account locked
```

**POST /logout**
```json
// Request
{ "refreshToken": "string" }
// Response 200
```

**POST /refresh**
```json
// Request
{ "refreshToken": "string" }
// Response 200 (same shape as login response)
```

**GET /verify**
```json
// Response 200
{ "userId": "string", "username": "string", "role": "string", "sessionType": "JWT" }
```

**POST /zoho/session**
```json
// Request
{ "sessionKey": "string", "userId": 1 }
// Response 200
{ "message": "string", "sessionId": 123, "userId": 1, "username": "string" }
```

---

### 2. Users (`/api/v1/users`)

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/` | Yes | List users (paginated) |
| GET | `/{id}` | Yes | Get user by ID |
| POST | `/` | Yes | Create user |
| PUT | `/{id}` | Yes | Update user |
| DELETE | `/{id}` | Yes | Soft-delete (deactivate) user |
| POST | `/{id}/reset-password` | Yes | Admin reset password |
| POST | `/change-password` | Yes | User changes own password |

**GET /?skip=0&take=100**
```json
// Response 200
[{
  "id": 1,
  "username": "string",
  "email": "string|null",
  "fullName": "string|null",
  "role": "admin|manager|user|readonly",
  "isActive": true,
  "createdAt": "2026-01-01T00:00:00Z",
  "lastLogin": "2026-01-01T00:00:00Z|null"
}]
```

**POST /**
```json
// Request
{
  "username": "string",       // required, unique
  "password": "string",       // required
  "email": "string|null",     // optional, unique
  "fullName": "string|null",  // optional
  "role": "string",           // required: admin|manager|user|readonly
  "isActive": true            // required
}
// Response 201 (UserDto)
```

**PUT /{id}**
```json
// Request (all optional)
{
  "email": "string|null",
  "fullName": "string|null",
  "role": "string|null",
  "isActive": true
}
// Response 204
```

**POST /{id}/reset-password**
```json
// Request body: raw string (the new password)
"newPassword123"
// Response 204
```

**POST /change-password**
```json
// Request
{ "currentPassword": "string", "newPassword": "string" }
// Response 204
```

---

### 3. Blocks (`/api/v1/blocks`) - Read Only

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/` | No | List all blocks (max 5000) |

**GET /**
```json
// Response 200
[{
  "source_database": "string",
  "gablockidx": 123,          // primary key
  "id": "string|null",        // block ID code
  "name": "string|null",      // block name
  "blocktype": "string|null",
  "growernameidx": 123,
  "growerlocationseq": 123,
  "growerName": "string|null",
  "growerID": "string|null",
  "gaclassidx": 123,
  "cmtyidx": 123,             // commodity index (FK to commodities)
  "varietyidx": 123,
  "acres": 12.5,
  "estimatedbins": 100.00,
  "district": "string|null",
  "cropyeardescr": "string|null",
  "latitude": 36.7,
  "longitude": -119.8,
  "inactiveflag": "Y|N|null",
  "syncDateTime": "2026-01-01T00:00:00Z|null",
  "syncStatus": "string|null"
}]
```

---

### 4. Commodities (`/api/v1/commodities`) - Read Only

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/` | No | List all commodities (max 1000) |

**GET /**
```json
// Response 200
[{
  "source_database": "string",
  "commodityIDx": 123,           // primary key
  "invoiceCommodity": "string|null",
  "commodity": "string|null",    // commodity name
  "syncDateTime": "2026-01-01T00:00:00Z|null",
  "syncStatus": "string|null"
}]
```

---

### 5. Pools (`/api/v1/pools`) - Read Only

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/?skip=0&take=100` | No | List pools (paginated) |
| GET | `/{id}` | No | Get pool by POOLIDX |

**GET /**
```json
// Response 200
[{
  "poolidx": 123,              // primary key
  "id": "string|null",         // pool ID code
  "descr": "string|null",      // description
  "gaclassidx": 123,
  "icclosedflag": "Y|N|null",
  "pooltype": "string|null",
  "cmtyidx": 123,
  "varietyidx": 123,
  "icdatefrom": "2026-01-01T00:00:00Z|null",
  "icdatethru": "2026-12-31T00:00:00Z|null",
  "source_database": "string",
  "syncDateTime": "2026-01-01T00:00:00Z|null",
  "syncStatus": "string|null"
}]
```

---

### 6. Harvest Plans (`/api/v1/harvestplans`) - Auth Required

This is a core entity. Harvest plans link grower blocks (or placeholder growers) to contractors, rates, and scheduling.

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/?skip=0&take=100` | Yes | List harvest plans (enriched with block, commodity, user, pool info) |
| GET | `/{id}` | Yes | Get harvest plan by GUID |
| POST | `/` | Yes | Create harvest plan |
| PUT | `/{id}` | Yes | Update harvest plan |
| DELETE | `/{id}` | Yes | Delete harvest plan |

**GET /** - Returns enriched DTOs with joined block, commodity, field rep, and pool data.
```json
// Response 200
[{
  "id": "guid-string",
  "grower_block_source_database": "string|null",
  "grower_block_id": 123,                    // FK to blocks.GABLOCKIDX
  "placeholder_grower_id": "guid|null",       // FK to placeholder_growers
  "field_representative_id": 123,             // FK to users
  "planned_bins": 100,
  "contractor_id": 456,                       // FK to harvest_contractors
  "harvesting_rate": 12.5000,
  "hauler_id": 789,                           // FK to harvest_contractors
  "hauling_rate": 8.0000,
  "forklift_contractor_id": 101,              // FK to harvest_contractors
  "forklift_rate": 5.0000,
  "pool_id": 123,                             // FK to pools.POOLIDX
  "notes_general": "string|null",
  "deliver_to": "string|null",
  "packed_by": "string|null",
  "date": "2026-03-15",
  "bins": 50,
  // Enriched data:
  "block": {
    "id": "string|null",
    "name": "string|null",
    "blocktype": "string|null",
    "growerName": "string|null",
    "growerID": "string|null",
    "acres": 12.5,
    "district": "string|null",
    "cropyeardescr": "string|null",
    "latitude": 36.7,
    "longitude": -119.8
  },
  "commodity": {
    "invoiceCommodity": "string|null",
    "commodity": "string|null"
  },
  "fieldRepresentative": {
    "id": 1,
    "username": "string",
    "fullName": "string|null",
    "email": "string|null",
    "role": "string",
    "isActive": true
  },
  "pool": {
    "poolidx": 123,
    "id": "string|null",
    "descr": "string|null",
    "icclosedflag": "string|null",
    "pooltype": "string|null",
    "cmtyidx": 123,
    "varietyidx": 123,
    "icdatefrom": "2026-01-01T00:00:00Z|null",
    "icdatethru": "2026-12-31T00:00:00Z|null",
    "source_database": "string"
  }
}]
```

**POST /**
```json
// Request (all fields optional)
{
  "grower_block_source_database": "string|null",
  "grower_block_id": 123,
  "placeholder_grower_id": "guid|null",
  "field_representative_id": 123,
  "planned_bins": 100,
  "contractor_id": 456,
  "harvesting_rate": 12.50,
  "hauler_id": 789,
  "hauling_rate": 8.00,
  "forklift_contractor_id": 101,
  "forklift_rate": 5.00,
  "pool_id": 123,
  "notes_general": "string|null",
  "deliver_to": "string|null",
  "packed_by": "string|null",
  "date": "2026-03-15",
  "bins": 50
}
// Response 201 (HarvestPlanDto - same shape as GET response)
```

**PUT /{id}** - Same request body as POST (all fields optional). Response: 204.

---

### 7. Harvest Contractors (`/api/v1/harvestcontractors`)

Contractors can provide picking, trucking/hauling, and forklift services. Referenced by harvest plans.

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/?search=&skip=0&take=50` | No | List contractors (searchable, paginated) |
| GET | `/{id}` | No | Get contractor by ID |
| POST | `/` | No | Create contractor |
| PUT | `/{id}` | No | Update contractor |
| DELETE | `/{id}` | No | Delete contractor |

**GET /?search=Jones&skip=0&take=50** - `search` filters by name or primary_contact_name.
```json
// Response 200
[{
  "id": 123,
  "name": "string",                    // required, max 100
  "primary_contact_name": "string|null", // max 50
  "primary_contact_phone": "string|null", // max 20
  "office_phone": "string|null",        // max 20
  "mailing_address": "string|null",     // max 100
  "provides_trucking": true,
  "provides_picking": true,
  "provides_forklift": false
}]
```

**POST /**
```json
// Request
{
  "name": "string",                      // required
  "primary_contact_name": "string|null",
  "primary_contact_phone": "string|null",
  "office_phone": "string|null",
  "mailing_address": "string|null",
  "provides_trucking": true,
  "provides_picking": true,
  "provides_forklift": false
}
// Response 201 (HarvestContractorDto)
```

---

### 8. Placeholder Growers (`/api/v1/placeholdergrower`) - Auth Required

Placeholder growers are used when a real grower block doesn't exist yet in the system. They can be linked to harvest plans.

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/?skip=0&take=100&isActive=&search=` | Yes | List placeholders (filterable) |
| GET | `/{id}` | Yes | Get placeholder by GUID |
| POST | `/` | Yes | Create placeholder |
| PUT | `/{id}` | Yes | Update placeholder |
| DELETE | `/{id}` | Yes | Delete placeholder |
| PATCH | `/{id}/toggle-active` | Yes | Toggle active status |

**GET /?search=Smith&isActive=true**
```json
// Response 200
[{
  "id": "guid-string",
  "grower_name": "string",
  "commodity_name": "string",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-02T00:00:00Z|null",
  "is_active": true,
  "notes": "string|null"
}]
```

**POST /**
```json
// Request
{
  "grower_name": "string",      // required
  "commodity_name": "string",   // required
  "is_active": true,            // default: true
  "notes": "string|null"
}
// Response 201 (PlaceholderGrowerDto)
```

**PUT /{id}** - All fields optional. Response: 200 with updated DTO.

**PATCH /{id}/toggle-active** - No body. Flips is_active. Response: 200 with updated DTO.

---

### 9. Production Runs (`/api/v1/productionruns`) - Auth Required

Production runs track actual processing/packing of harvested fruit from specific blocks.

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/?skip=0&take=100&source_Database=&gaBlockIdx=` | Yes | List runs (filterable, enriched) |
| GET | `/{id}` | Yes | Get run by GUID |
| POST | `/` | Yes | Create run |
| PUT | `/{id}` | Yes | Update run |
| DELETE | `/{id}` | Yes | Delete run |

**GET /?source_Database=DB1&gaBlockIdx=123** - Returns enriched DTOs with block and commodity info.
```json
// Response 200
[{
  "id": "guid-string",
  "source_database": "string",
  "gablockidx": 123,               // FK to blocks
  "bins": 50,
  "run_date": "2026-03-15|null",
  "pick_date": "2026-03-14|null",
  "location": "string|null",
  "pool": "string|null",
  "notes": "string|null",
  "row_order": 1,
  "run_status": "string|null",
  "batch_id": "string|null",
  "time_started": "2026-03-15T08:00:00Z|null",
  "time_completed": "2026-03-15T16:00:00Z|null",
  // Enriched data:
  "block": {
    "id": "string|null",
    "name": "string|null",
    "blocktype": "string|null",
    "growerName": "string|null",
    "growerID": "string|null",
    "acres": 12.5,
    "district": "string|null",
    "cropyeardescr": "string|null",
    "latitude": 36.7,
    "longitude": -119.8
  },
  "commodity": {
    "invoiceCommodity": "string|null",
    "commodity": "string|null"
  }
}]
```

**POST /**
```json
// Request
{
  "source_database": "string",    // required
  "gablockidx": 123,              // required, must be > 0
  "bins": 50,
  "run_date": "2026-03-15",
  "pick_date": "2026-03-14",
  "location": "string|null",
  "pool": "string|null",
  "notes": "string|null",
  "row_order": 1,
  "run_status": "string|null",
  "batch_id": "string|null",
  "time_started": "2026-03-15T08:00:00Z",
  "time_completed": "2026-03-15T16:00:00Z"
}
// Response 201 (ProductionRunDto)
```

---

### 10. Scout Reports (`/api/v1/scoutreportwithblock`) - Read Only

| Method | Route | Auth Required | Description |
|--------|-------|---------------|-------------|
| GET | `/` | No | Returns all scout report records (database view with 100+ columns) |

This is a read-only database view (`VW_ScoutReportWithBlock`) that joins scout reports with block information. It contains a very large number of columns.

---

## Data Relationships

```
Blocks (read-only, synced from external system)
  |-- GABLOCKIDX (PK)
  |-- CMTYIDX --> Commodities.CommodityIDx
  |
  |-- Referenced by:
      |-- HarvestPlans.grower_block_id
      |-- ProcessProductionRuns.GABLOCKIDX + source_database (composite FK)

Commodities (read-only, synced)
  |-- CommodityIDx (PK)

Pools (read-only, synced)
  |-- POOLIDX (PK)
  |-- Referenced by: HarvestPlans.pool_id

PlaceholderGrowers
  |-- id (GUID PK)
  |-- Referenced by: HarvestPlans.placeholder_grower_id

HarvestContractors
  |-- id (long PK)
  |-- Referenced by HarvestPlans:
      |-- contractor_id (picking)
      |-- hauler_id (trucking/hauling)
      |-- forklift_contractor_id (forklift)

Users (auth database)
  |-- Id (int PK)
  |-- Referenced by: HarvestPlans.field_representative_id

HarvestPlans (core entity)
  |-- id (GUID PK)
  |-- grower_block_id --> Blocks.GABLOCKIDX (OR)
  |-- placeholder_grower_id --> PlaceholderGrowers.id
  |-- field_representative_id --> Users.Id
  |-- contractor_id --> HarvestContractors.id
  |-- hauler_id --> HarvestContractors.id
  |-- forklift_contractor_id --> HarvestContractors.id
  |-- pool_id --> Pools.POOLIDX

ProcessProductionRuns
  |-- id (GUID PK)
  |-- source_database + GABLOCKIDX --> Blocks (composite FK)
```

## Pagination

Most list endpoints support pagination via query parameters:
- `skip` (default: 0) - Number of records to skip
- `take` (default: varies, usually 100) - Number of records to return (clamped to 1-500)

## Error Responses

Standard HTTP status codes:
- `200` - Success
- `201` - Created (POST returns created resource)
- `204` - No Content (successful PUT/DELETE)
- `400` - Bad Request (validation errors)
- `401` - Unauthorized (missing/invalid token)
- `404` - Not Found
- `423` - Locked (account locked after failed login attempts)

Error body format:
```json
{ "message": "Description of what went wrong" }
```

## Common Workflow Examples

### Creating a Harvest Plan (full flow)

1. Login: `POST /api/v1/auth/login`
2. Browse blocks: `GET /api/v1/blocks` (find the grower_block_id / GABLOCKIDX)
3. Browse contractors: `GET /api/v1/harvestcontractors` (find contractor IDs)
4. Browse pools: `GET /api/v1/pools` (find pool_id)
5. Create plan: `POST /api/v1/harvestplans` with the collected IDs and rates

### Using Placeholder Growers

If the real grower block doesn't exist yet:
1. Create placeholder: `POST /api/v1/placeholdergrower` with grower_name and commodity_name
2. Use the returned `id` (GUID) as `placeholder_grower_id` in the harvest plan
3. Leave `grower_block_id` null

### Creating a Production Run

1. Login: `POST /api/v1/auth/login`
2. Find the block: `GET /api/v1/blocks`
3. Create run: `POST /api/v1/productionruns` with `source_database` and `GABLOCKIDX` from the block
