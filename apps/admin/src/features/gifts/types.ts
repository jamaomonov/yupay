/** Mirrors the backend `GiftsAdminSettingsOut` (`apps/api/.../gifts/schemas.py`). */
export interface GiftsAdminSettings {
  margin_percent: string;
  enabled: boolean;
  region_default: string;
  regions: string[];
}
