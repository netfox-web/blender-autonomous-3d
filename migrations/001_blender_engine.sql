-- Additive schema for FoxStudio Postgres. Does NOT alter existing tables.
-- Tenant scope follows FS-ADR-006: workspace_id + composite uniqueness.

CREATE TABLE IF NOT EXISTS blender_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  project_id text NOT NULL DEFAULT 'default',
  asset_id uuid,
  recipe_id text,
  priority integer NOT NULL DEFAULT 50,
  job_type text NOT NULL,
  input_assets jsonb NOT NULL DEFAULT '[]'::jsonb,
  scene jsonb NOT NULL DEFAULT '{}'::jsonb,
  camera jsonb NOT NULL DEFAULT '{}'::jsonb,
  lighting jsonb NOT NULL DEFAULT '{}'::jsonb,
  materials jsonb NOT NULL DEFAULT '{}'::jsonb,
  animation jsonb NOT NULL DEFAULT '{}'::jsonb,
  render jsonb NOT NULL DEFAULT '{}'::jsonb,
  output jsonb NOT NULL DEFAULT '{}'::jsonb,
  gpu_requirement jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued',
  progress numeric(5,4) NOT NULL DEFAULT 0,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  assigned_compute_target_key text,
  error text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  started_at timestamptz,
  completed_at timestamptz,
  UNIQUE (workspace_id, id)
);
CREATE INDEX IF NOT EXISTS blender_jobs_ws_status_idx
  ON blender_jobs (workspace_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS product_digital_twins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  sku text NOT NULL,
  version integer NOT NULL DEFAULT 1,
  glb_asset_id uuid,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  content_hash text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workspace_id, id),
  UNIQUE (workspace_id, sku, version)
);

CREATE TABLE IF NOT EXISTS parametric_products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  kind text NOT NULL,
  engineering jsonb NOT NULL,
  engineering_hash text NOT NULL,
  bom jsonb NOT NULL DEFAULT '{}'::jsonb,
  cost jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS blender_script_registry (
  sha256 text PRIMARY KEY,
  name text NOT NULL,
  signature text NOT NULL,
  allow_production boolean NOT NULL DEFAULT false,
  sandbox boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'EXPERIMENTAL',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS blender_render_cache (
  cache_key text PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  output jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS blender_asset_lineage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  job_id uuid,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workspace_id, id)
);

-- Register Blender operations on existing compute capability vocabulary (documentation row).
-- Actual worker operations are declared at heartbeat time; this is an allowlist seed.
INSERT INTO model_profiles (workspace_id, model_key, name, kind, status, metadata)
SELECT w.id, 'fox3d.blender-headless-v1', 'Blender Headless Worker', 'post', 'active',
       '{"capabilities":["BLENDER_RENDER","BLENDER_PREVIEW"],"guiForbidden":true}'::jsonb
FROM workspaces w
ON CONFLICT (workspace_id, model_key) DO NOTHING;
