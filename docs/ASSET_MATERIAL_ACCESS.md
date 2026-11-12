# Asset and material access boundary

`GET /api/assets/{id}` requires a valid `X-Tenant-Id` and returns only an asset owned by that tenant. Missing or invalid headers return 400; unknown and other-tenant assets return 404. Assets have no public visibility classification and are private by default. `GET /api/materials` requires the same header and includes only that tenant's lots. The static configured material definitions are available without a header at `GET /api/materials/catalog`; it contains no inventory lots.

The tenant header is a scope selector, **not authentication**. This application does not verify that the caller belongs to the named tenant. It must be accessible only through an authenticated, trusted gateway that removes any incoming `X-Tenant-Id`, checks the caller's tenant authorization, and supplies the authorized tenant ID. Direct access by untrusted callers permits impersonation and cross-tenant reads, including on other API routes. Production identity and gateway policy require an owner decision and independent verification before exposure.

Clients loading private assets must send the tenant header (for browser images, fetch the asset with the header and use a blob URL). Legacy `/admin` image links cannot supply this header and require a compatible authenticated delivery mechanism before they work again.
